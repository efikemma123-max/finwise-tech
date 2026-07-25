from __future__ import annotations

import asyncio
import json
import mimetypes
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd

from ai_worker import _log_trade_history, ai_signal
from candle_engine import Multicandleengine
from trade_engine import BrokerFactory, TradingBot


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "terminal_web"
HOST = "127.0.0.1"
PORT = 8787
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class MarketRuntime:
    def __init__(self) -> None:
        self.engine = Multicandleengine(symbols=DEFAULT_SYMBOLS, interval="1m", limit=750)
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return

            bootstrap = threading.Thread(target=self._bootstrap_engine, daemon=True, name="finwise-market-bootstrap")
            bootstrap.start()
            self._started = True

    def _bootstrap_engine(self) -> None:
        try:
            self.engine.fetch_all_history()
        except Exception:
            pass
        asyncio.run(self.engine.run())

    def get_terminal_payload(self, symbol: str, interval: str) -> dict[str, Any]:
        symbol = self.engine.ensure_symbol(symbol.upper())

        try:
            self.engine.fetch_history(symbol)
            self.engine.refresh_symbol(symbol)
        except Exception:
            pass

        candles = self.engine.get_history(symbol, interval=interval).tail(350).copy()
        snapshot = self.engine.get_market_snapshot(symbol)
        orderbook = self.engine.get_orderbook(symbol, depth=12)

        return {
            "symbol": symbol,
            "interval": interval,
            "server_time": datetime.now(timezone.utc).isoformat(),
            "candles": self._serialize_candles(candles),
            "market": self._serialize_market(snapshot),
            "orderbook": self._serialize_orderbook(orderbook),
        }

    def get_signal_payload(self, symbol: str, interval: str, balance: float) -> dict[str, Any]:
        symbol = self.engine.ensure_symbol(symbol.upper())
        df = self.engine.get_history(symbol, interval=interval)
        result = ai_signal(df.copy(), symbol=symbol, current_balance=balance)
        result["symbol"] = symbol
        result["interval"] = interval
        result["generated_at"] = datetime.now(timezone.utc).isoformat()
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
            "broker_name": broker_name.strip(),
            "account_alias": account_alias.strip() or "Terminal",
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


class FinwiseTerminalHandler(BaseHTTPRequestHandler):
    server_version = "FinwiseTerminal/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self._handle_api(path, parse_qs(parsed.query))
            return

        self._serve_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if not path.startswith("/api/"):
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        self._handle_post_api(path)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if not path.startswith("/api/"):
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        self._handle_delete_api(path)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _handle_api(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            if path == "/api/health":
                self._send_json({"ok": True, "server_time": datetime.now(timezone.utc).isoformat()})
                return

            if path == "/api/market/symbols":
                self._send_json({"symbols": RUNTIME.get_symbols()})
                return

            if path == "/api/market/terminal":
                symbol = (query.get("symbol", ["BTCUSDT"])[0] or "BTCUSDT").upper()
                interval = query.get("interval", ["1m"])[0] or "1m"
                payload = RUNTIME.get_terminal_payload(symbol, interval)
                self._send_json(payload)
                return

            if path == "/api/signal":
                symbol = (query.get("symbol", ["BTCUSDT"])[0] or "BTCUSDT").upper()
                interval = query.get("interval", ["1m"])[0] or "1m"
                balance = _safe_float(query.get("balance", ["1000"])[0], 1000.0)
                payload = RUNTIME.get_signal_payload(symbol, interval, balance)
                self._send_json(payload)
                return

            if path == "/api/broker/status":
                self._send_json(BROKERS.get_status())
                return

            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_post_api(self, path: str) -> None:
        try:
            payload = self._read_json_body()

            if path == "/api/broker/profile":
                status = BROKERS.connect_profile(
                    broker_name=str(payload.get("broker_name", "")),
                    account_alias=str(payload.get("account_alias", "")),
                    balance=_safe_float(payload.get("balance", 0)),
                )
                self._send_json(status)
                return

            if path == "/api/broker/live":
                status = BROKERS.connect_live(
                    broker_name=str(payload.get("broker_name", "")),
                    api_key=str(payload.get("api_key", "")),
                    api_secret=str(payload.get("api_secret", "")),
                )
                self._send_json(status)
                return

            if path == "/api/trade/auto":
                status = BROKERS.get_status()
                if not status["live_api"]["connected"]:
                    self._send_json(
                        {
                            "error": "live_broker_required",
                            "message": "Connect a live API broker before using auto trade.",
                            "broker_status": status,
                        },
                        status=HTTPStatus.CONFLICT,
                    )
                    return

                symbol = str(payload.get("symbol", "BTCUSDT")).upper()
                interval = str(payload.get("interval", "1m"))
                balance = _safe_float(payload.get("balance", 1000), 1000.0)
                signal = RUNTIME.get_signal_payload(symbol, interval, balance)
                execution = BROKERS.execute_auto_trade(signal, symbol, interval)
                self._send_json(
                    {
                        "signal": signal,
                        "execution": execution,
                        "broker_status": BROKERS.get_status(),
                    }
                )
                return

            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_delete_api(self, path: str) -> None:
        try:
            if path == "/api/broker/profile":
                self._send_json(BROKERS.disconnect_profile())
                return
            if path == "/api/broker/live":
                self._send_json(BROKERS.disconnect_live())
                return
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _serve_static(self, path: str) -> None:
        if path in {"/", "/terminal"}:
            target = STATIC_DIR / "index.html"
        else:
            safe_path = path.lstrip("/")
            target = (STATIC_DIR / safe_path).resolve()
            if STATIC_DIR not in target.parents and target != STATIC_DIR:
                self._send_json({"error": "Invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return

        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        content_type, _ = mimetypes.guess_type(str(target))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(target.read_bytes())

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)


def run_server(host: str = HOST, port: int = PORT) -> None:
    RUNTIME.start()
    server = ThreadingHTTPServer((host, port), FinwiseTerminalHandler)
    print(f"[Finwise Terminal] Running on http://{host}:{port}/terminal")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
