import os
import json
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

try:
    from websockets.sync.client import connect as websocket_connect
except ImportError:  # pragma: no cover - dependency is installed in the bundled venv
    websocket_connect = None


DERIV_DEFAULT_APP_ID = "1089"
DERIV_WS_BASE = "wss://ws.derivws.com/websockets/v3"
DERIV_CANDLE_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "turnover"]

DERIV_GRANULARITY_BY_TIMEFRAME = {
    "Ticks": 0,
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
}


@dataclass
class DerivConnectionResult:
    ok: bool
    loginid: str = ""
    currency: str = ""
    balance: float = 0.0
    message: str = ""


@dataclass
class DerivTradeExecutionResult:
    ok: bool
    message: str = ""
    contract_id: str = ""
    transaction_id: str = ""
    longcode: str = ""
    buy_price: float = 0.0
    payout: float = 0.0
    balance_after: float = 0.0
    ask_price: float = 0.0
    spot: float = 0.0
    contract_type: str = ""
    raw: dict[str, Any] | None = None


def deriv_app_id() -> str:
    return str(os.getenv("DERIV_APP_ID", DERIV_DEFAULT_APP_ID) or DERIV_DEFAULT_APP_ID).strip()


def deriv_env_token() -> str:
    return str(os.getenv("DERIV_API_TOKEN", "") or "").strip()


def deriv_ws_url(app_id: str | None = None) -> str:
    return f"{DERIV_WS_BASE}?app_id={str(app_id or deriv_app_id()).strip()}"


def _empty_candles() -> pd.DataFrame:
    return pd.DataFrame(columns=DERIV_CANDLE_COLUMNS)


class DerivAPIClient:
    def __init__(self, token: str = "", app_id: str | None = None, timeout: int = 15):
        self.token = str(token or "").strip()
        self.app_id = str(app_id or deriv_app_id()).strip()
        self.timeout = int(timeout or 15)
        self._req_id = 0

    def _next_req_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _send_and_wait(self, ws: Any, payload: dict[str, Any]) -> dict[str, Any]:
        request = dict(payload or {})
        request["req_id"] = self._next_req_id()
        ws.send(json.dumps(request))
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            response = json.loads(ws.recv(timeout=max(0.1, deadline - time.time())))
            if response.get("req_id") != request["req_id"]:
                continue
            error = response.get("error")
            if error:
                raise RuntimeError(error.get("message") or "Deriv API request failed.")
            return response
        raise TimeoutError("Deriv API request timed out.")

    def _request(self, payload: dict[str, Any], *, authorize: bool = False) -> dict[str, Any]:
        if websocket_connect is None:
            raise RuntimeError("websockets is not installed.")
        if authorize and not self.token:
            raise RuntimeError("Enter a Deriv API token first.")

        with websocket_connect(
            deriv_ws_url(self.app_id),
            proxy=None,
            open_timeout=self.timeout,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            if authorize:
                self._send_and_wait(ws, {"authorize": self.token})
            return self._send_and_wait(ws, payload)

    def authorize(self) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("Enter a Deriv API token first.")
        response = self._request({"authorize": self.token})
        return response.get("authorize", {}) or {}

    def balance(self) -> dict[str, Any]:
        response = self._request({"balance": 1, "subscribe": 0}, authorize=True)
        return response.get("balance", {}) or {}

    def test_connection(self) -> DerivConnectionResult:
        try:
            auth = self.authorize()
            balance = self.balance()
            amount = balance.get("balance", auth.get("balance", 0.0))
            try:
                amount = float(amount or 0.0)
            except (TypeError, ValueError):
                amount = 0.0
            return DerivConnectionResult(
                ok=True,
                loginid=str(auth.get("loginid") or balance.get("loginid") or ""),
                currency=str(balance.get("currency") or auth.get("currency") or ""),
                balance=amount,
                message="Deriv API connected.",
            )
        except Exception as exc:
            return DerivConnectionResult(ok=False, message=str(exc))

    def active_symbols(self) -> list[dict[str, Any]]:
        response = self._request({"active_symbols": "brief", "product_type": "basic"})
        return list(response.get("active_symbols", []) or [])

    def latest_tick(self, symbol: str) -> dict[str, Any]:
        api_symbol = str(symbol or "").strip()
        if not api_symbol:
            raise ValueError("Deriv symbol is missing.")

        response = self._request({"ticks": api_symbol})
        tick = response.get("tick") or {}
        if not tick:
            raise RuntimeError("Deriv did not return a live tick.")

        try:
            quote = float(tick.get("quote"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Deriv live tick did not include a numeric quote.") from exc

        epoch = tick.get("epoch")
        timestamp = ""
        try:
            timestamp = pd.to_datetime(int(epoch), unit="s", utc=True).tz_localize(None)
        except (TypeError, ValueError, OverflowError):
            timestamp = ""

        try:
            pip_size = int(tick.get("pip_size") or 0)
        except (TypeError, ValueError):
            pip_size = 0

        return {
            "symbol": str(tick.get("symbol") or api_symbol),
            "quote": quote,
            "timestamp": timestamp,
            "epoch": int(epoch or 0) if str(epoch or "").isdigit() else 0,
            "pip_size": pip_size,
            "raw": tick,
        }

    def _multiplier_contract_type(self, side: str) -> str:
        normalized = str(side or "").strip().upper()
        if normalized == "BUY":
            return "MULTUP"
        if normalized == "SELL":
            return "MULTDOWN"
        raise ValueError("Choose Buy or Sell before executing a Deriv trade.")

    def build_multiplier_proposal(
        self,
        symbol: str,
        side: str,
        stake: float,
        multiplier: int,
        target_profit: float,
        max_loss: float,
        currency: str = "USD",
    ) -> dict[str, Any]:
        amount = round(float(stake or 0), 2)
        if amount <= 0:
            raise ValueError("Stake must be greater than zero.")

        multiplier = int(multiplier or 0)
        if multiplier <= 0:
            raise ValueError("Multiplier must be greater than zero.")

        proposal: dict[str, Any] = {
            "proposal": 1,
            "amount": amount,
            "basis": "stake",
            "contract_type": self._multiplier_contract_type(side),
            "currency": str(currency or "USD").strip().upper(),
            "symbol": str(symbol or "").strip(),
            "multiplier": multiplier,
        }

        limit_order = {}
        take_profit = round(float(target_profit or 0), 2)
        stop_loss = round(float(max_loss or 0), 2)
        if take_profit > 0:
            limit_order["take_profit"] = take_profit
        if stop_loss > 0:
            limit_order["stop_loss"] = stop_loss
        if limit_order:
            proposal["limit_order"] = limit_order

        return proposal

    def execute_multiplier_trade(
        self,
        symbol: str,
        side: str,
        stake: float,
        multiplier: int,
        target_profit: float,
        max_loss: float,
        currency: str = "USD",
    ) -> DerivTradeExecutionResult:
        if websocket_connect is None:
            return DerivTradeExecutionResult(ok=False, message="websockets is not installed.")
        if not self.token:
            return DerivTradeExecutionResult(ok=False, message="Enter a Deriv API token first.")

        proposal_payload = self.build_multiplier_proposal(
            symbol=symbol,
            side=side,
            stake=stake,
            multiplier=multiplier,
            target_profit=target_profit,
            max_loss=max_loss,
            currency=currency,
        )

        try:
            with websocket_connect(
                deriv_ws_url(self.app_id),
                proxy=None,
                open_timeout=self.timeout,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
            ) as ws:
                self._send_and_wait(ws, {"authorize": self.token})
                proposal_response = self._send_and_wait(ws, proposal_payload)
                proposal = proposal_response.get("proposal", {}) or {}
                proposal_id = str(proposal.get("id") or "").strip()
                if not proposal_id:
                    raise RuntimeError("Deriv did not return a proposal ID.")

                ask_price = float(proposal.get("ask_price") or stake or 0)
                buy_response = self._send_and_wait(ws, {"buy": proposal_id, "price": ask_price})
                buy = buy_response.get("buy", {}) or {}

                balance_after = buy.get("balance_after")
                if balance_after is None:
                    try:
                        balance_response = self._send_and_wait(ws, {"balance": 1, "subscribe": 0})
                        balance_after = (balance_response.get("balance", {}) or {}).get("balance", 0)
                    except Exception:
                        balance_after = 0

                return DerivTradeExecutionResult(
                    ok=True,
                    message="Deriv trade executed.",
                    contract_id=str(buy.get("contract_id") or ""),
                    transaction_id=str(buy.get("transaction_id") or ""),
                    longcode=str(buy.get("longcode") or proposal.get("longcode") or ""),
                    buy_price=float(buy.get("buy_price") or ask_price or 0),
                    payout=float(buy.get("payout") or proposal.get("payout") or 0),
                    balance_after=float(balance_after or 0),
                    ask_price=ask_price,
                    spot=float(proposal.get("spot") or buy.get("start_spot") or 0),
                    contract_type=str(proposal_payload.get("contract_type") or ""),
                    raw={"proposal": proposal, "buy": buy},
                )
        except Exception as exc:
            return DerivTradeExecutionResult(ok=False, message=str(exc), contract_type=str(proposal_payload.get("contract_type") or ""))

    def fetch_candles(self, symbol: str, timeframe: str = "1m", count: int = 240) -> pd.DataFrame:
        api_symbol = str(symbol or "").strip()
        timeframe = str(timeframe or "1m")
        try:
            count = max(10, min(int(count or 240), 5000))
        except (TypeError, ValueError):
            count = 240

        granularity = DERIV_GRANULARITY_BY_TIMEFRAME.get(timeframe, 60)
        if granularity <= 0:
            return self.fetch_ticks_as_candles(api_symbol, count=count)

        response = self._request(
            {
                "ticks_history": api_symbol,
                "end": "latest",
                "count": count,
                "style": "candles",
                "granularity": granularity,
                "adjust_start_time": 1,
            }
        )
        candles = response.get("candles") or []
        if not candles:
            return _empty_candles()

        rows = []
        for candle in candles:
            try:
                rows.append(
                    {
                        "timestamp": pd.to_datetime(int(candle.get("epoch")), unit="s", utc=True).tz_localize(None),
                        "open": float(candle.get("open")),
                        "high": float(candle.get("high")),
                        "low": float(candle.get("low")),
                        "close": float(candle.get("close")),
                        "volume": 0.0,
                        "turnover": 0.0,
                    }
                )
            except (TypeError, ValueError):
                continue
        if not rows:
            return _empty_candles()
        return pd.DataFrame(rows, columns=DERIV_CANDLE_COLUMNS).sort_values("timestamp").reset_index(drop=True)

    def fetch_ticks_as_candles(self, symbol: str, count: int = 400) -> pd.DataFrame:
        response = self._request(
            {
                "ticks_history": str(symbol or "").strip(),
                "end": "latest",
                "count": max(10, min(int(count or 400), 5000)),
                "style": "ticks",
                "adjust_start_time": 1,
            }
        )
        history = response.get("history") or {}
        prices = list(history.get("prices") or [])
        times = list(history.get("times") or [])
        rows = []
        for epoch, price in zip(times, prices):
            try:
                value = float(price)
                rows.append(
                    {
                        "timestamp": pd.to_datetime(int(epoch), unit="s", utc=True).tz_localize(None),
                        "open": value,
                        "high": value,
                        "low": value,
                        "close": value,
                        "volume": 0.0,
                        "turnover": 0.0,
                    }
                )
            except (TypeError, ValueError):
                continue
        if not rows:
            return _empty_candles()
        return pd.DataFrame(rows, columns=DERIV_CANDLE_COLUMNS).sort_values("timestamp").reset_index(drop=True)


def test_deriv_connection(token: str = "", app_id: str | None = None) -> DerivConnectionResult:
    return DerivAPIClient(token=token or deriv_env_token(), app_id=app_id).test_connection()


def fetch_deriv_candles(symbol: str, timeframe: str = "1m", count: int = 240, token: str = "", app_id: str | None = None) -> pd.DataFrame:
    return DerivAPIClient(token=token or deriv_env_token(), app_id=app_id).fetch_candles(symbol, timeframe=timeframe, count=count)


def fetch_deriv_latest_tick(symbol: str, token: str = "", app_id: str | None = None, timeout: int = 8) -> dict[str, Any]:
    return DerivAPIClient(token=token or deriv_env_token(), app_id=app_id, timeout=timeout).latest_tick(symbol)


def execute_deriv_multiplier_trade(
    symbol: str,
    side: str,
    stake: float,
    multiplier: int,
    target_profit: float,
    max_loss: float,
    currency: str = "USD",
    token: str = "",
    app_id: str | None = None,
) -> DerivTradeExecutionResult:
    return DerivAPIClient(token=token or deriv_env_token(), app_id=app_id).execute_multiplier_trade(
        symbol=symbol,
        side=side,
        stake=stake,
        multiplier=multiplier,
        target_profit=target_profit,
        max_loss=max_loss,
        currency=currency,
    )
