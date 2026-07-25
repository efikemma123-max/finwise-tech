from __future__ import annotations

import asyncio
import json
import mimetypes
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from ai_worker import _log_trade_history, ai_signal
from candle_engine import Multicandleengine
from trade_engine import BrokerFactory, TradingBot


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "terminal_web"
DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "ADAUSDT",
    "AVAXUSDT",
]

app = FastAPI(title="Finwise Desktop API")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MarketRuntime:
    def __init__(self) -> None:
        self.engine = Multicandleengine(symbols=DEFAULT_SYMBOLS, interval="1m", limit=750)
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return

            bootstrap = threading.Thread(
                target=self._bootstrap_engine,
                daemon=True,
                name="finwise-market-runtime",
            )
            bootstrap.start()
            self._started = True

    def _bootstrap_engine(self) -> None:
        try:
            self.engine.fetch_all_history()
        except Exception:
            pass

        try:
            asyncio.run(self.engine.run())
        except RuntimeError:
            pass

    def get_terminal_payload(self, symbol: str, interval: str) -> dict[str, Any]:
        symbol = self.engine.ensure_symbol(str(symbol or "BTCUSDT").upper())
        interval = str(interval or "1m")

        try:
            self.engine.fetch_history(symbol, interval=interval)
            self.engine.refresh_symbol(symbol)
        except Exception:
            pass

        candles = self.engine.get_history(symbol, interval=interval).tail(350).copy()
        snapshot = self.engine.get_market_snapshot(symbol)
        orderbook = self.engine.get_orderbook(symbol, depth=12)

        return {
            "symbol": symbol,
            "interval": interval,
            "server_time": _utc_now(),
            "candles": self._serialize_candles(candles),
            "market": self._serialize_market(snapshot),
            "orderbook": self._serialize_orderbook(orderbook),
        }

    def get_signal_payload(self, symbol: str, interval: str, balance: float) -> dict[str, Any]:
        symbol = self.engine.ensure_symbol(str(symbol or "BTCUSDT").upper())
        interval = str(interval or "1m")

        try:
            self.engine.fetch_history(symbol, interval=interval)
        except Exception:
            pass

        df = self.engine.get_history(symbol, interval=interval)
        result = ai_signal(
            df.copy(),
            symbol=symbol,
            current_balance=_safe_float(balance, 1000.0),
            timeframe=interval,
        )
        result["symbol"] = symbol
        result["interval"] = interval
        result["generated_at"] = _utc_now()
        return result

    def get_symbols(self) -> list[str]:
        return self.engine.get_available_symbols(max_symbols=120)

    @staticmethod
    def _serialize_candles(df: pd.DataFrame) -> list[dict[str, Any]]:
        if df.empty:
            return []

        rows = []
        for _, row in df.iterrows():
            ts = pd.to_datetime(row["timestamp"], errors="coerce")
            if pd.isna(ts):
                continue
            rows.append(
                {
                    "time": int(ts.timestamp()),
                    "open": _safe_float(row.get("open")),
                    "high": _safe_float(row.get("high")),
                    "low": _safe_float(row.get("low")),
                    "close": _safe_float(row.get("close")),
                    "volume": _safe_float(row.get("volume")),
                }
            )
        return rows

    @staticmethod
    def _serialize_market(snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "last_price": _safe_float(snapshot.get("last_price"), 0.0),
            "mark_price": _safe_float(snapshot.get("mark_price"), 0.0),
            "index_price": _safe_float(snapshot.get("index_price"), 0.0),
            "open_interest": _safe_float(snapshot.get("open_interest"), 0.0),
            "volume_24h": _safe_float(snapshot.get("volume_24h"), 0.0),
            "turnover_24h": _safe_float(snapshot.get("turnover_24h"), 0.0),
            "funding_rate": _safe_float(snapshot.get("funding_rate"), 0.0),
            "price_24h_pcnt": _safe_float(snapshot.get("price_24h_pcnt"), 0.0),
            "high_24h": _safe_float(snapshot.get("high_24h"), 0.0),
            "low_24h": _safe_float(snapshot.get("low_24h"), 0.0),
            "candle_open": _safe_float(snapshot.get("candle_open"), 0.0),
            "candle_high": _safe_float(snapshot.get("candle_high"), 0.0),
            "candle_low": _safe_float(snapshot.get("candle_low"), 0.0),
            "candle_volume": _safe_float(snapshot.get("candle_volume"), 0.0),
            "candle_change": _safe_float(snapshot.get("candle_change"), 0.0),
            "candle_change_pct": _safe_float(snapshot.get("candle_change_pct"), 0.0),
            "updated_at": snapshot.get("updated_at"),
        }

    @staticmethod
    def _serialize_orderbook(orderbook: dict[str, Any]) -> dict[str, Any]:
        bids = [
            {"price": _safe_float(level.get("price")), "size": _safe_float(level.get("size"))}
            for level in orderbook.get("bids", [])
        ]
        asks = [
            {"price": _safe_float(level.get("price")), "size": _safe_float(level.get("size"))}
            for level in orderbook.get("asks", [])
        ]
        return {
            "bids": bids,
            "asks": asks,
            "updated_at": orderbook.get("updated_at"),
        }


class BrokerRuntime:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.manual_profile: dict[str, Any] | None = None
        self.live_broker = None
        self.live_bot: TradingBot | None = None

    def connect_profile(self, broker_name: str, account_alias: str, balance: float) -> dict[str, Any]:
        profile = {
            "broker_name": str(broker_name or "").strip(),
            "account_alias": str(account_alias or "").strip() or "Terminal",
            "balance": max(_safe_float(balance, 0.0), 0.0),
        }
        if not profile["broker_name"]:
            raise ValueError("Broker name is required")

        with self._lock:
            self.manual_profile = profile
        return self.get_status()

    def disconnect_profile(self) -> dict[str, Any]:
        with self._lock:
            self.manual_profile = None
        return self.get_status()

    def connect_live(self, broker_name: str, api_key: str, api_secret: str) -> dict[str, Any]:
        broker_name = str(broker_name or "").strip()
        api_key = str(api_key or "").strip()
        api_secret = str(api_secret or "").strip()
        if not broker_name or not api_key or not api_secret:
            raise ValueError("Broker name, API key, and API secret are required")

        broker = BrokerFactory.create_broker(broker_name, api_key, api_secret)
        if broker is None:
            raise RuntimeError(f"Could not connect to {broker_name}. Check the adapter and your credentials.")

        bot = TradingBot(broker)
        with self._lock:
            self._disconnect_live_locked()
            self.live_broker = broker
            self.live_bot = bot
        return self.get_status()

    def disconnect_live(self) -> dict[str, Any]:
        with self._lock:
            self._disconnect_live_locked()
        return self.get_status()

    def _disconnect_live_locked(self) -> None:
        broker = self.live_broker
        self.live_broker = None
        self.live_bot = None
        if broker is not None:
            try:
                broker.disconnect()
            except Exception:
                pass

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            profile = dict(self.manual_profile) if self.manual_profile else None
            live_broker = self.live_broker
            live_bot = self.live_bot

        live_payload = {
            "connected": live_broker is not None and live_bot is not None,
            "broker_name": None,
            "balance": None,
            "performance": None,
        }
        if live_broker is not None and live_bot is not None:
            live_payload["broker_name"] = live_broker.name
            try:
                live_payload["balance"] = round(float(live_broker.get_balance("USDT")), 2)
            except Exception:
                live_payload["balance"] = None
            live_payload["performance"] = live_bot.get_performance()

        return {
            "manual_profile": {
                "connected": profile is not None,
                "profile": profile,
            },
            "live_api": live_payload,
            "available_brokers": BrokerFactory.get_available_brokers(),
        }

    def execute_auto_trade(self, signal: dict[str, Any], symbol: str, timeframe: str) -> dict[str, Any]:
        with self._lock:
            live_broker = self.live_broker
            live_bot = self.live_bot
            profile = dict(self.manual_profile) if self.manual_profile else None

        if live_broker is None or live_bot is None:
            raise RuntimeError("Connect a live API broker before using auto trade.")

        execution = live_bot.execute_trade_from_ai_worker(signal, symbol)
        if execution.get("status") == "success":
            trade = execution.get("trade", {})
            _log_trade_history(
                username="terminal",
                broker_name=trade.get("broker", live_broker.name),
                account_alias=(profile or {}).get("account_alias", "Terminal"),
                source="live_api",
                status="executed",
                symbol=trade.get("symbol", symbol),
                timeframe=timeframe,
                side=trade.get("signal", signal.get("signal", "HOLD")),
                confidence=trade.get("confidence", signal.get("confidence", 0)),
                quantity=trade.get("quantity", 0),
                notional_usd=trade.get("notional_usd", 0),
                entry_price=trade.get("entry_price", 0),
                stop_loss=trade.get("stop_loss", 0),
                take_profit=trade.get("take_profit", 0),
                fee_paid=trade.get("fee_paid", 0),
                regime=trade.get("regime", ""),
                setup_quality=trade.get("setup_quality", ""),
                risk_reward_ratio=trade.get("risk_reward_ratio", 0),
                notes=f"Terminal order ID: {trade.get('order_id', '')}",
            )
        return execution


RUNTIME = MarketRuntime()
BROKERS = BrokerRuntime()


@app.on_event("startup")
async def start_runtime() -> None:
    RUNTIME.start()


@app.get("/health")
@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "status": "ok", "service": "finwise-desktop-api", "server_time": _utc_now()}


@app.get("/api/market/symbols")
async def market_symbols() -> dict[str, Any]:
    try:
        return {"symbols": await asyncio.to_thread(RUNTIME.get_symbols)}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/market/terminal")
async def market_terminal(symbol: str = "BTCUSDT", interval: str = "1m"):
    try:
        return await asyncio.to_thread(RUNTIME.get_terminal_payload, symbol, interval)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/signal")
async def signal(symbol: str = "BTCUSDT", interval: str = "1m", balance: float = 1000.0):
    try:
        return await asyncio.to_thread(RUNTIME.get_signal_payload, symbol, interval, balance)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/broker/status")
async def broker_status() -> dict[str, Any]:
    return BROKERS.get_status()


@app.post("/api/broker/profile")
async def broker_profile(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return BROKERS.connect_profile(
            broker_name=payload.get("broker_name", ""),
            account_alias=payload.get("account_alias", ""),
            balance=_safe_float(payload.get("balance", 0)),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.delete("/api/broker/profile")
async def broker_profile_delete() -> dict[str, Any]:
    return BROKERS.disconnect_profile()


@app.post("/api/broker/live")
async def broker_live(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return await asyncio.to_thread(
            BROKERS.connect_live,
            payload.get("broker_name", ""),
            payload.get("api_key", ""),
            payload.get("api_secret", ""),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.delete("/api/broker/live")
async def broker_live_delete() -> dict[str, Any]:
    return BROKERS.disconnect_live()


@app.post("/api/trade/auto")
async def trade_auto(payload: dict[str, Any] = Body(default_factory=dict)):
    status = BROKERS.get_status()
    if not status["live_api"]["connected"]:
        return JSONResponse(
            {
                "error": "live_broker_required",
                "message": "Connect a live API broker before using auto trade.",
                "broker_status": status,
            },
            status_code=409,
        )

    symbol = str(payload.get("symbol", "BTCUSDT") or "BTCUSDT").upper()
    interval = str(payload.get("interval", "1m") or "1m")
    balance = _safe_float(payload.get("balance", 1000), 1000.0)
    try:
        signal_payload = await asyncio.to_thread(RUNTIME.get_signal_payload, symbol, interval, balance)
        execution = await asyncio.to_thread(BROKERS.execute_auto_trade, signal_payload, symbol, interval)
        return {
            "signal": signal_payload,
            "execution": execution,
            "broker_status": BROKERS.get_status(),
        }
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.websocket("/ws/kline")
async def kline_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    symbol = str(websocket.query_params.get("symbol", "BTCUSDT") or "BTCUSDT").upper()
    interval = str(websocket.query_params.get("interval", "1m") or "1m")
    last_signature = ""

    try:
        while True:
            payload = await asyncio.to_thread(RUNTIME.get_terminal_payload, symbol, interval)
            candles = payload.get("candles", [])
            signature = json.dumps(candles[-1:] if candles else [], sort_keys=True)
            if signature != last_signature:
                message_type = "history" if not last_signature else "update"
                data = candles if message_type == "history" else candles[-1] if candles else None
                await websocket.send_text(json.dumps({"type": message_type, "data": data}))
                last_signature = signature
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return


def _static_target(asset_path: str) -> Path:
    if asset_path in {"", "/", "terminal", "terminal/"}:
        return STATIC_DIR / "index.html"

    safe_path = asset_path.lstrip("/")
    target = (STATIC_DIR / safe_path).resolve()
    try:
        target.relative_to(STATIC_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid static path") from exc
    return target


@app.get("/", include_in_schema=False)
@app.get("/terminal", include_in_schema=False)
@app.get("/terminal/", include_in_schema=False)
async def desktop_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/{asset_path:path}", include_in_schema=False)
async def desktop_asset(asset_path: str) -> FileResponse:
    target = _static_target(asset_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    content_type, _ = mimetypes.guess_type(str(target))
    return FileResponse(target, media_type=content_type or "application/octet-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
