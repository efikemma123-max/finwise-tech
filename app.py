import os
import logging
import gc
import http.client
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(dotenv_path=None, override=False, **_kwargs):
        """Small fallback loader so the app can boot without python-dotenv."""
        if not dotenv_path:
            return False

        env_file = Path(dotenv_path)
        if not env_file.exists():
            return False

        loaded_any = False
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue

            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]

            if override or key not in os.environ:
                os.environ[key] = value
                loaded_any = True

        return loaded_any

from backend.auth.security_config import allow_insecure_oauth_transport

# ✅ STEP 1: LOAD .env FIRST
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

if allow_insecure_oauth_transport():
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
else:
    os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)

import streamlit as st
import streamlit.components.v1 as components
from streamlit import config as st_config
import bcrypt
import math
import importlib
import mimetypes
import ipaddress
from datetime import date, datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote_plus, urlparse
import tornado.web
import tornado.routing

from backend.ai.ai_worker import (
    ai_signal_for_user,
    get_trade_style_profile,
    list_trade_style_options,
    normalize_trade_style,
)
from backend.trading.trade_engine import TradingBot, BrokerFactory
from ai_worker import auto_trade_page
import stripe # Kept for future Stripe integration, though not directly used now
import hashlib
import hmac
import smtplib
import json
import base64
from textwrap import dedent
from html import escape
from contextlib import contextmanager
from email.mime.text import MIMEText
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
import random
import time
import secrets
import pandas as pd

from backend.market.candle_engine import (
    FOREX_SYMBOL_FALLBACK,
    Multicandleengine,
    get_market_asset_class,
    is_forex_symbol,
    split_market_symbol,
)
from deriv_api import deriv_env_token, execute_deriv_multiplier_trade, fetch_deriv_candles, fetch_deriv_latest_tick, test_deriv_connection
import asyncio
import threading
from streamlit_lightweight_charts import renderLightweightCharts
from backend.market.indicators import IndicatorPipeline
from backend.auth.broker_oauth import (
    ensure_broker_oauth_tables,
    consume_broker_oauth_state,
    deactivate_broker_connection,
    get_active_broker_connection,
    resolve_broker_oauth_redirect_uri,
    save_broker_connection,
)
from backend.core.db_runtime import connect_database, is_database_locked_error, is_integrity_error
from backend.core.notification_service import (
    build_telegram_connect_url,
    connect_telegram_chat,
    describe_telegram_destination,
    get_whatsapp_sender,
    is_twilio_sandbox_sender,
    normalize_phone_number,
    notification_proxy_warning,
    render_notification_diagnostics_panel,
    send_telegram_message,
    send_whatsapp_message,
)
from backend.auth.security_config import is_production_environment, resolve_redirect_uri
# Note: plotly kept for backward compatibility with unused functions
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:
    go = None
    make_subplots = None

import account_views as _account_views_module
import dashboard_views as _dashboard_views_module
import market_workspace_views as _market_workspace_views_module
from mobile_ui_helpers import (
    build_query_href,
    render_mobile_bottom_nav as render_mobile_bottom_nav_links,
    resolve_query_value,
)

_account_views_module = importlib.reload(_account_views_module)
_dashboard_views_module = importlib.reload(_dashboard_views_module)
_market_workspace_views_module = importlib.reload(_market_workspace_views_module)

_render_account_page_view = _account_views_module.render_account_page
_render_mobile_account_page_view = _account_views_module.render_mobile_account_page
_render_dashboard_page_view = _dashboard_views_module.render_dashboard_page
_render_mobile_dashboard_page_view = _dashboard_views_module.render_mobile_dashboard_page
_render_trade_journal_page_view = _dashboard_views_module.render_trade_journal_page
_render_mobile_trade_journal_page_view = _dashboard_views_module.render_mobile_trade_journal_page
_render_ai_page_view = _market_workspace_views_module.render_ai_page
_render_desktop_trading_desk_page_view = _market_workspace_views_module.render_desktop_trading_desk_page
_render_mobile_market_analysis_page_view = _market_workspace_views_module.render_mobile_market_analysis_page
_render_mobile_trading_desk_page_view = _market_workspace_views_module.render_mobile_trading_desk_page
_render_market_analysis_chart_tools_view = _market_workspace_views_module.render_market_analysis_chart_tools

DEFAULT_TRACKED_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "BTCUSDC",
    "BTCUSD",
    "BNBBTC",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
]
DEFAULT_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h"]
DEFAULT_SIGNAL_TIMEFRAME = "5m"
API_SERVER_PORT = 8787
STREAMLIT_MOBILE_PROXY_PREFIX = "/mobile-api"
BROKER_BALANCE_CACHE_TTL_SECONDS = 20.0
BROKER_RESTORE_COOLDOWN_SECONDS = 45.0
SYMBOL_LOAD_COOLDOWN_SECONDS = 12.0
CHART_MIN_READY_CANDLES = 12
AI_SIGNAL_MIN_READY_CANDLES = 50
CHART_INITIAL_FETCH_CANDLES = 900
CHART_SEED_CANDLES = 720
CHART_POLL_WINDOW_CANDLES = 360
CHART_BACKFILL_BATCH_CANDLES = 500
CHART_BACKFILL_TRIGGER_BARS = 24
APP_LOGO_PATH = Path(__file__).parent / "fin-logo.jpeg"
MOBILE_WEB_ROOT = Path(__file__).parent / "mobile_web"
DEFAULT_TRADE_STYLE = "day_trade"
TRADE_STYLE_OPTIONS = list_trade_style_options()
TRADE_STYLE_LABELS = {option["value"]: option["label"] for option in TRADE_STYLE_OPTIONS}
TRADE_STYLE_DESCRIPTIONS = {option["value"]: option["description"] for option in TRADE_STYLE_OPTIONS}
LIGHTWEIGHT_CHARTS_VENDOR_PATH = (
    Path(__file__).parent
    / "react-terminal"
    / "node_modules"
    / "lightweight-charts"
    / "dist"
    / "lightweight-charts.standalone.production.js"
)


def _current_trade_style() -> str:
    return normalize_trade_style(st.session_state.get("trade_style_preference", DEFAULT_TRADE_STYLE))


def _set_current_trade_style(style: str) -> str:
    normalized = normalize_trade_style(style)
    st.session_state["trade_style_preference"] = normalized
    return normalized


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
APP_LOGGER = logging.getLogger("finwise.app")
SHOW_DEBUG_ERRORS = os.getenv("FINWISE_DEBUG_ERRORS", "").strip().lower() in {"1", "true", "yes", "on"}


def _user_safe_error_message(area: str) -> str:
    return (
        f"{area} hit a temporary problem. Your session is still active, "
        "so try refreshing this section or switching pages and coming back."
    )


def _render_error_boundary(area: str, exc: Exception) -> None:
    error_id = secrets.token_hex(4)
    APP_LOGGER.exception("Unhandled %s error [%s]", area, error_id)
    st.error(_user_safe_error_message(area))
    st.caption(f"Error reference: {error_id}")
    if SHOW_DEBUG_ERRORS or not is_production_environment():
        with st.expander("Developer details", expanded=False):
            st.exception(exc)


def _render_page_safely(area: str, render_fn):
    try:
        return render_fn()
    except Exception as exc:
        _render_error_boundary(area, exc)
        return None


def _show_safe_operation_error(area: str, exc: Exception | None = None) -> None:
    if exc is not None:
        APP_LOGGER.exception("%s failed", area)
    else:
        APP_LOGGER.warning("%s failed", area)
    st.error(f"{area} failed temporarily. Please try again.")


@st.cache_data(show_spinner=False)
def _image_path_to_data_uri(path_value: str) -> str:
    path = Path(path_value)
    try:
        image_bytes = path.read_bytes()
    except Exception:
        return ""
    suffix = path.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
    return f"data:image/{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"


APP_LOGO_DATA_URI = _image_path_to_data_uri(str(APP_LOGO_PATH))


# =============================================================
# ENGINE — created once at module level
# _engine_ready uses threading.Event (thread-safe, avoids writing
# to st.session_state from a background thread)
# =============================================================
@st.cache_resource
def _get_market_runtime():
    return {
        "engine": Multicandleengine(
            symbols=DEFAULT_TRACKED_SYMBOLS,
            interval="1m",
            limit=240,
        ),
        "ready": threading.Event(),
        "status": {"ok": False, "message": "Initializing live market feed..."},
        "feed_started": False,
        "chart_api_started": False,
        "chart_api_server": None,
        "lock": threading.RLock(),
    }


_market_runtime = _get_market_runtime()
engine = _market_runtime["engine"]
_engine_ready = _market_runtime["ready"]
_engine_status = _market_runtime["status"]
_signal_notification_runtime = {"last_signal_by_key": {}}


def _signal_notification_key(username: str, symbol: str, tf_label: str) -> tuple[str, str, str]:
    return (
        str(username or "").strip().lower(),
        str(symbol or "").strip().upper(),
        str(tf_label or "").strip().lower(),
    )


def _build_signal_notification_payload(username: str, symbol: str, tf_label: str, result: dict) -> dict:
    key = _signal_notification_key(username, symbol, tf_label)
    previous_state = _signal_notification_runtime["last_signal_by_key"].get(key)
    preferences = get_user_account_preferences(username)
    send_as_update = bool(previous_state and preferences.get("notify_signal_updates"))

    entry_exit = dict(result.get("entry_exit", {}) or {})
    signal_label = str(result.get("signal", "HOLD") or "HOLD").upper()
    confidence = float(result.get("confidence", 0) or 0.0)
    reason = " ".join(str(result.get("reason", "") or "").split())
    if len(reason) > 96:
        reason = f"{reason[:93].rstrip()}..."
    setup_quality = " ".join(str(((result.get("summary") or {}).get("setup_quality", "") or "")).split())
    setup_quality = setup_quality.title() if setup_quality else "Live"

    if send_as_update:
        prior_label = str(previous_state.get("signal_label", "HOLD") or "HOLD").upper()
        transition = f"{prior_label} -> {signal_label}" if prior_label != signal_label else f"{signal_label} refreshed"
        message = (
            f"Finwise Market Update | {symbol} {tf_label} | {transition} | "
            f"Conf: {confidence:.1f}% | Setup: {setup_quality}"
        )
        if reason:
            message += f" | Market: {reason}"
    else:
        message = (
            f"Finwise AI | {signal_label} {symbol} {tf_label} | "
            f"Entry: {entry_exit.get('actual_entry') or entry_exit.get('entry_price', 0):.4f} | "
            f"TP: {entry_exit.get('take_profit', 0):.4f} | "
            f"SL: {entry_exit.get('stop_loss', 0):.4f} | "
            f"R/R: {entry_exit.get('risk_reward_ratio', 0):.2f}x | "
            f"Conf: {confidence:.1f}% | Setup: {setup_quality}"
        )
        if reason:
            message += f" | Market: {reason}"

    _signal_notification_runtime["last_signal_by_key"][key] = {
        "signal_label": signal_label,
        "confidence": confidence,
        "reason": reason,
        "setup_quality": setup_quality,
    }

    return {
        "message": message,
        "signal_type": signal_label,
        "confidence": confidence,
        "is_update": send_as_update,
    }

# ✅ Define functions BEFORE calling them
def _boot_engine():
    """Warm the feed and unlock the UI as soon as the first symbol is usable."""
    try:
        booted_any = False
        for symbol in engine.symbols:
            try:
                history = engine.fetch_history(symbol)
                engine.refresh_symbol(symbol)
                if history is not None and not history.empty and not booted_any:
                    booted_any = True
                    _engine_status["ok"] = True
                    _engine_status["message"] = "Live market feed ready."
                    _engine_ready.set()
            except Exception as symbol_error:
                print(f"[ENGINE BOOT WARNING] {symbol}: {symbol_error}")

        if not booted_any:
            _engine_status["ok"] = False
            _engine_status["message"] = "Live market feed is warming up."
    except Exception as e:
        _engine_status["ok"] = False
        _engine_status["message"] = "Live market feed is temporarily unavailable."
        print(f"[ENGINE BOOT ERROR] {e}")
    finally:
        _engine_ready.set()  # thread-safe, no session_state write from thread

def _start_ws_loop():
    """Run WebSocket candle stream in its own event loop."""
    asyncio.run(engine.run(60))


def _set_session_state_safe(key: str, value):
    try:
        st.session_state[key] = value
    except Exception:
        return


def _start_market_feed(force_refresh: bool = False):
    with _market_runtime["lock"]:
        should_start_ws = not _market_runtime["feed_started"]
        if _market_runtime["feed_started"] and not force_refresh:
            _set_session_state_safe("engine_started", True)
            return

        _engine_status["ok"] = False
        _engine_status["message"] = "Initializing live market feed..."
        _engine_ready.clear()
        threading.Thread(target=_boot_engine, daemon=True, name="finwise-feed-boot").start()
        if should_start_ws:
            threading.Thread(target=_start_ws_loop, daemon=True, name="finwise-feed-ws").start()
            _market_runtime["feed_started"] = True
        _set_session_state_safe("engine_started", True)


def _ensure_symbol_loaded(symbol: str) -> bool:
    try:
        history = engine.fetch_history(symbol)
        engine.refresh_symbol(symbol)
        if history is not None and not history.empty:
            _engine_status["ok"] = True
            _engine_status["message"] = "Live market feed ready."
            _engine_ready.set()
            return True
    except Exception as exc:
        print(f"[ENGINE SYMBOL LOAD WARNING] {symbol}: {exc}")

    _engine_status["ok"] = False
    _engine_status["message"] = "Live market feed is temporarily unavailable."
    return False


def _load_symbol_if_stale(symbol: str, cooldown: float = SYMBOL_LOAD_COOLDOWN_SECONDS, force: bool = False) -> bool:
    cache = st.session_state.get("symbol_load_state", {})
    cache_key = str(symbol or "").upper()
    now = time.time()
    entry = cache.get(cache_key, {})
    last_attempt = float(entry.get("checked_at", 0.0) or 0.0)
    if not force and last_attempt and (now - last_attempt) < cooldown:
        return bool(entry.get("ok"))

    ok = _ensure_symbol_loaded(symbol)
    cache[cache_key] = {"checked_at": now, "ok": ok}
    st.session_state.symbol_load_state = cache
    return ok


def _broker_balance_cache_key(broker, asset: str = "USDT") -> str:
    session_scope = st.session_state.get("auth_session_id") or st.session_state.get("username") or "guest"
    broker_name = getattr(broker, "name", "broker")
    return f"{session_scope}:{broker_name}:{asset.upper()}"


def _get_cached_broker_balance(broker, asset: str = "USDT", ttl: float = BROKER_BALANCE_CACHE_TTL_SECONDS, force: bool = False) -> tuple[float, bool]:
    cache = st.session_state.get("broker_balance_cache", {})
    cache_key = _broker_balance_cache_key(broker, asset)
    now = time.time()
    entry = cache.get(cache_key, {})
    last_sync = float(entry.get("synced_at", 0.0) or 0.0)
    if not force and last_sync and (now - last_sync) < ttl:
        return float(entry.get("value", 0.0) or 0.0), True

    value = float(broker.get_balance(asset))
    cache[cache_key] = {"value": value, "synced_at": now}
    st.session_state.broker_balance_cache = cache
    return value, False


def _get_pair_universe(refresh: bool = False) -> list:
    cache_key = "available_trading_pairs"
    if refresh or cache_key not in st.session_state:
        try:
            st.session_state[cache_key] = engine.get_available_symbols(refresh=refresh)
        except Exception:
            st.session_state[cache_key] = list(dict.fromkeys(list(DEFAULT_TRACKED_SYMBOLS) + list(FOREX_SYMBOL_FALLBACK)))

    symbols = st.session_state.get(cache_key) or list(DEFAULT_TRACKED_SYMBOLS)
    return list(symbols)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bounded_reward_multiple(value, default: float = 4.0, *, minimum: float = 1.5, maximum: float = 4.0) -> float:
    reward_multiple = _safe_float(value, default)
    if not math.isfinite(reward_multiple):
        reward_multiple = default
    return max(float(minimum), min(float(maximum), reward_multiple))


def _validate_instant_price_levels(
    side: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    *,
    atr_value: float = 0.0,
    requested_rr: float = 4.0,
    min_stop_pct: float = 0.0012,
) -> tuple[list[str], dict]:
    side = str(side or "").upper()
    entry_price = _safe_float(entry_price)
    stop_loss = _safe_float(stop_loss)
    take_profit = _safe_float(take_profit)
    atr_value = _safe_float(atr_value)
    requested_rr = _bounded_reward_multiple(requested_rr)
    failures: list[str] = []

    values_are_valid = all(
        math.isfinite(value) and value > 0
        for value in [entry_price, stop_loss, take_profit]
    )
    if side not in {"BUY", "SELL"}:
        failures.append("direction is not Buy or Sell")
    if not values_are_valid:
        failures.append("entry, SL, and TP prices must all be positive numbers")
        return failures, {
            "risk_distance": 0.0,
            "reward_distance": 0.0,
            "risk_distance_pct": 0.0,
            "target_distance_pct": 0.0,
            "actual_rr": 0.0,
            "minimum_stop_distance": 0.0,
        }

    if side == "BUY":
        if not (stop_loss < entry_price < take_profit):
            failures.append("Buy levels must have SL below entry and TP above entry")
        risk_distance = entry_price - stop_loss
        reward_distance = take_profit - entry_price
    else:
        if not (take_profit < entry_price < stop_loss):
            failures.append("Sell levels must have TP below entry and SL above entry")
        risk_distance = stop_loss - entry_price
        reward_distance = entry_price - take_profit

    risk_distance = max(_safe_float(risk_distance), 0.0)
    reward_distance = max(_safe_float(reward_distance), 0.0)
    risk_distance_pct = (risk_distance / max(entry_price, 1e-9)) * 100
    target_distance_pct = (reward_distance / max(entry_price, 1e-9)) * 100
    atr_floor = atr_value * 0.65 if atr_value > 0 else 0.0
    minimum_stop_distance = max(entry_price * float(min_stop_pct or 0.0012), atr_floor, 1e-6)
    actual_rr = reward_distance / risk_distance if risk_distance > 1e-12 else 0.0

    if risk_distance < minimum_stop_distance:
        failures.append(
            f"SL is too close to entry ({risk_distance:.4f}); minimum is {minimum_stop_distance:.4f}"
        )
    if actual_rr < max(1.5, requested_rr * 0.95):
        failures.append(f"reward/risk is {actual_rr:.2f}R, below the {requested_rr:.2f}R gate")
    if actual_rr > 4.25:
        failures.append(f"reward/risk is distorted at {actual_rr:.2f}R; rebuild the chart levels")
    if risk_distance_pct < (float(min_stop_pct or 0.0012) * 100):
        failures.append(f"SL distance is only {risk_distance_pct:.3f}% from entry")

    return failures, {
        "risk_distance": risk_distance,
        "reward_distance": reward_distance,
        "risk_distance_pct": risk_distance_pct,
        "target_distance_pct": target_distance_pct,
        "actual_rr": actual_rr,
        "minimum_stop_distance": minimum_stop_distance,
    }


def _serialize_terminal_candles(df: pd.DataFrame, limit: int = 350) -> list[dict]:
    if df is None or df.empty:
        return []

    rows = []
    for _, row in df.tail(limit).iterrows():
        ts = pd.to_datetime(row.get("timestamp"), errors="coerce")
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


def _serialize_terminal_market(snapshot: dict) -> dict:
    snapshot = snapshot or {}
    return {
        "asset_class": snapshot.get("asset_class"),
        "feed_source": snapshot.get("feed_source"),
        "last_price": _safe_float(snapshot.get("last_price"), None),
        "mark_price": _safe_float(snapshot.get("mark_price"), None),
        "index_price": _safe_float(snapshot.get("index_price"), None),
        "open_interest": _safe_float(snapshot.get("open_interest"), None),
        "volume_24h": _safe_float(snapshot.get("volume_24h"), None),
        "turnover_24h": _safe_float(snapshot.get("turnover_24h"), None),
        "funding_rate": _safe_float(snapshot.get("funding_rate"), None),
        "price_24h_pcnt": _safe_float(snapshot.get("price_24h_pcnt"), None),
        "high_24h": _safe_float(snapshot.get("high_24h"), None),
        "low_24h": _safe_float(snapshot.get("low_24h"), None),
        "candle_open": _safe_float(snapshot.get("candle_open"), None),
        "candle_high": _safe_float(snapshot.get("candle_high"), None),
        "candle_low": _safe_float(snapshot.get("candle_low"), None),
        "candle_volume": _safe_float(snapshot.get("candle_volume"), None),
        "candle_change": _safe_float(snapshot.get("candle_change"), None),
        "candle_change_pct": _safe_float(snapshot.get("candle_change_pct"), None),
        "updated_at": snapshot.get("updated_at"),
    }


def _serialize_terminal_orderbook(snapshot: dict, depth: int = 10) -> dict:
    if not isinstance(snapshot, dict):
        snapshot = {}

    def _rows(items):
        rows = []
        for item in list(items or [])[:depth]:
            rows.append(
                {
                    "price": _safe_float((item or {}).get("price"), None),
                    "size": _safe_float((item or {}).get("size"), None),
                }
            )
        return rows

    bids = _rows(snapshot.get("bids", []))
    asks = _rows(snapshot.get("asks", []))
    best_bid = bids[0]["price"] if bids else None
    best_ask = asks[0]["price"] if asks else None
    spread = (best_ask - best_bid) if best_bid is not None and best_ask is not None else None
    mid_price = ((best_bid + best_ask) / 2) if best_bid is not None and best_ask is not None else None
    bid_total = sum(float(item.get("size") or 0.0) for item in bids)
    ask_total = sum(float(item.get("size") or 0.0) for item in asks)
    total_depth = bid_total + ask_total
    imbalance = ((bid_total - ask_total) / total_depth * 100.0) if total_depth else 0.0
    return {
        "bids": bids,
        "asks": asks,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "mid_price": mid_price,
        "bid_total": bid_total,
        "ask_total": ask_total,
        "imbalance": imbalance,
    }


def _mobile_db_connect():
    db_conn = connect_database("finwise.db")
    return db_conn


def _mobile_close_db(db_conn, db_cursor=None):
    try:
        if db_cursor is not None:
            db_cursor.close()
    except Exception:
        pass
    try:
        if db_conn is not None:
            db_conn.close()
    except Exception:
        pass


def _mobile_json_value(value):
    if isinstance(value, dict):
        return {str(key): _mobile_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_mobile_json_value(item) for item in value]
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    try:
        if value is None or pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _mobile_header_value(headers, *names: str) -> str:
    if headers is None:
        return ""
    for name in names:
        try:
            value = headers.get(name, "")
        except Exception:
            value = ""
        if isinstance(value, (list, tuple)):
            value = " ".join(str(item) for item in value if item is not None)
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    try:
        items = list(headers.items())
    except Exception:
        items = []
    for name in names:
        lowered = str(name or "").lower()
        for key, value in items:
            if str(key or "").lower() != lowered:
                continue
            if isinstance(value, (list, tuple)):
                value = " ".join(str(item) for item in value if item is not None)
            normalized = str(value or "").strip()
            if normalized:
                return normalized
    return ""


def _mobile_request_uses_https(headers) -> bool:
    if "https" in _mobile_header_value(headers, "X-Forwarded-Proto").lower():
        return True
    if "https" in _mobile_header_value(headers, "X-Forwarded-Scheme").lower():
        return True
    if "proto=https" in _mobile_header_value(headers, "Forwarded").lower():
        return True
    if _mobile_header_value(headers, "Origin").lower().startswith("https://"):
        return True
    if _mobile_header_value(headers, "Referer").lower().startswith("https://"):
        return True
    return is_production_environment()


def _mobile_cookie_header(value: str = "", *, expires_at: float = 0, clear: bool = False, secure: bool = False) -> str:
    cookie = f"{SESSION_COOKIE_NAME}={value or ''}; Path=/; SameSite=Lax;"
    if secure:
        cookie += " Secure;"
    if clear:
        cookie += " Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0;"
    elif expires_at:
        expires_text = datetime.utcfromtimestamp(float(expires_at)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        cookie += f" Expires={expires_text};"
    return cookie


def _cleanup_expired_sessions_db(db_conn, now: float = None):
    now = time.time() if now is None else now
    db_cursor = db_conn.cursor()
    try:
        db_cursor.execute(
            "DELETE FROM user_sessions WHERE expires_at < ? OR (revoked_at > 0 AND revoked_at < ?)",
            (now, now - 86400),
        )
        db_conn.commit()
        return True
    except Exception as exc:
        try:
            db_conn.rollback()
        except Exception:
            pass
        if is_database_locked_error(exc):
            return False
        raise


def _cleanup_auth_records_db(db_conn, now: float = None):
    now = time.time() if now is None else now
    db_cursor = db_conn.cursor()
    try:
        db_cursor.execute("DELETE FROM otp_table WHERE expiry < ?", (now,))
        db_cursor.execute("DELETE FROM pending_users WHERE expires_at < ?", (now,))
        db_cursor.execute("DELETE FROM gmail_oauth_state WHERE expires_at < ?", (now,))
        db_cursor.execute(
            "DELETE FROM login_attempts WHERE COALESCE(locked_until, 0) < ? AND updated_at < ?",
            (now, now - 86400),
        )
        db_conn.commit()
        return True
    except Exception as exc:
        try:
            db_conn.rollback()
        except Exception:
            pass
        if is_database_locked_error(exc):
            return False
        raise


def _session_create_record(
    username: str,
    *,
    remember_me: bool = True,
    user_agent: str = "",
    ip_address: str = "",
    db_conn=None,
) -> dict:
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        _cleanup_expired_sessions_db(db_conn)
        now = time.time()
        session_id = secrets.token_urlsafe(18)
        session_key = secrets.token_urlsafe(24)
        token = _build_session_token(session_id, session_key)
        expires_at = now + _session_expiry_seconds(remember_me)
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            """
            INSERT INTO user_sessions (
                session_id, username, session_secret_hash, created_at, last_seen_at,
                expires_at, remember_me, user_agent, ip_address, revoked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                session_id,
                username,
                _session_key_hash(session_key),
                now,
                now,
                expires_at,
                1 if remember_me else 0,
                str(user_agent or "")[:512],
                str(ip_address or "")[:128],
            ),
        )
        db_conn.commit()
        return {
            "session_id": session_id,
            "session_token": token,
            "expires_at": expires_at,
            "remember_me": bool(remember_me),
        }
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _session_lookup_from_token(token: str, *, touch: bool = True, db_conn=None):
    parsed = _parse_session_token(token)
    if not parsed:
        return None
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        _cleanup_expired_sessions_db(db_conn)
        session_id, session_key = parsed
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            """
            SELECT username, session_secret_hash, last_seen_at, expires_at, revoked_at, remember_me
            FROM user_sessions
            WHERE session_id = ?
            LIMIT 1
            """,
            (session_id,),
        )
        row = db_cursor.fetchone()
        if not row:
            return None
        username, secret_hash, last_seen_at, expires_at, revoked_at, remember_me = row
        if float(revoked_at or 0) > 0 or float(expires_at or 0) < time.time():
            return None
        if not hmac.compare_digest(str(secret_hash or ""), _session_key_hash(session_key)):
            return None
        now = time.time()
        if touch and abs(now - float(last_seen_at or 0)) >= SESSION_TOUCH_INTERVAL_SECONDS:
            db_cursor.execute(
                "UPDATE user_sessions SET last_seen_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            db_conn.commit()
        return {
            "username": str(username or ""),
            "session_id": session_id,
            "session_token": token,
            "remember_me": bool(remember_me),
            "expires_at": float(expires_at or 0),
        }
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _revoke_session_record(session_id: str, *, db_conn=None):
    if not session_id:
        return
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            "UPDATE user_sessions SET revoked_at = ? WHERE session_id = ?",
            (time.time(), session_id),
        )
        db_conn.commit()
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _load_registered_user_db(username: str, email: str = "", *, db_conn=None):
    normalized_username = str(username or "").strip()
    normalized_email = str(email or "").strip()
    if not normalized_username:
        return None
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        db_cursor = db_conn.cursor()
        if normalized_email:
            db_cursor.execute(
                """
                SELECT username, password, email, phone, COALESCE(premium, 0)
                FROM users
                WHERE LOWER(username) = LOWER(?)
                  AND LOWER(COALESCE(email, '')) = LOWER(?)
                LIMIT 1
                """,
                (normalized_username, normalized_email),
            )
        else:
            db_cursor.execute(
                """
                SELECT username, password, email, phone, COALESCE(premium, 0)
                FROM users
                WHERE LOWER(username) = LOWER(?)
                LIMIT 1
                """,
                (normalized_username,),
            )
        row = db_cursor.fetchone()
        if not row:
            return None
        return {
            "username": row[0],
            "password": row[1],
            "email": row[2] or "",
            "phone": row[3] or "",
            "premium": int(row[4] or 0),
        }
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _get_login_lock_message_db(username: str, *, db_conn=None) -> str:
    if not username:
        return ""
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        _cleanup_auth_records_db(db_conn)
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            "SELECT failed_count, locked_until FROM login_attempts WHERE username = ? LIMIT 1",
            (username,),
        )
        row = db_cursor.fetchone()
        if not row:
            return ""
        locked_until = float(row[1] or 0)
        if locked_until <= time.time():
            return ""
        remaining_minutes = max(1, math.ceil((locked_until - time.time()) / 60))
        return f"Too many login attempts. Try again in about {remaining_minutes} minute(s)."
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _record_login_failure_db(username: str, *, db_conn=None):
    if not username:
        return
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        now = time.time()
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            "SELECT failed_count, locked_until FROM login_attempts WHERE username = ? LIMIT 1",
            (username,),
        )
        row = db_cursor.fetchone()
        failed_count = int((row[0] if row else 0) or 0) + 1
        locked_until = float((row[1] if row else 0) or 0)
        if failed_count >= MAX_LOGIN_ATTEMPTS:
            locked_until = now + (LOGIN_LOCK_MINUTES * 60)
        db_cursor.execute(
            """
            INSERT INTO login_attempts (username, failed_count, locked_until, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                failed_count=excluded.failed_count,
                locked_until=excluded.locked_until,
                updated_at=excluded.updated_at
            """,
            (username, failed_count, locked_until, now),
        )
        db_conn.commit()
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _clear_login_failures_db(username: str, *, db_conn=None):
    if not username:
        return
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        db_cursor = db_conn.cursor()
        db_cursor.execute("DELETE FROM login_attempts WHERE username = ?", (username,))
        db_conn.commit()
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _save_pending_user_db(username: str, password_hash: str, email: str, phone: str = "", *, db_conn=None):
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        _cleanup_auth_records_db(db_conn)
        if isinstance(password_hash, bytes):
            password_hash = password_hash.decode()
        now = time.time()
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            """
            INSERT INTO pending_users (
                username, password, email, phone, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                password=excluded.password,
                email=excluded.email,
                phone=excluded.phone,
                created_at=excluded.created_at,
                expires_at=excluded.expires_at
            """,
            (username, password_hash, email, phone, now, now + PENDING_USER_TTL_SECONDS),
        )
        db_conn.commit()
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _load_pending_user_db(username: str, *, db_conn=None):
    normalized_username = str(username or "").strip()
    if not normalized_username:
        return None
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        _cleanup_auth_records_db(db_conn)
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            """
            SELECT username, password, email, phone
            FROM pending_users
            WHERE username = ? AND expires_at >= ?
            LIMIT 1
            """,
            (normalized_username, time.time()),
        )
        row = db_cursor.fetchone()
        if not row:
            return None
        return {
            "username": row[0],
            "password": row[1],
            "email": row[2] or "",
            "phone": row[3] or "",
        }
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _clear_pending_user_db(username: str, *, db_conn=None):
    if not username:
        return
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        db_cursor = db_conn.cursor()
        db_cursor.execute("DELETE FROM pending_users WHERE username = ?", (username,))
        db_conn.commit()
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _generate_otp_db(username: str, *, db_conn=None) -> str:
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        _cleanup_auth_records_db(db_conn)
        otp = str(random.randint(100000, 999999))
        expiry = time.time() + OTP_TTL_SECONDS
        db_cursor = db_conn.cursor()
        db_cursor.execute("DELETE FROM otp_table WHERE username = ?", (username,))
        db_cursor.execute(
            "INSERT INTO otp_table (username, code, expiry) VALUES (?, ?, ?)",
            (username, otp, expiry),
        )
        db_conn.commit()
        return otp
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _verify_otp_db(username: str, otp: str, *, db_conn=None) -> bool:
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        _cleanup_auth_records_db(db_conn)
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            "SELECT code, expiry FROM otp_table WHERE username = ? ORDER BY expiry DESC LIMIT 1",
            (username,),
        )
        row = db_cursor.fetchone()
        if not row:
            return False
        stored_code, expiry = row
        if time.time() > float(expiry or 0):
            db_cursor.execute("DELETE FROM otp_table WHERE username = ?", (username,))
            db_conn.commit()
            return False
        if str(stored_code) != str(otp):
            return False
        db_cursor.execute("DELETE FROM otp_table WHERE username = ?", (username,))
        db_conn.commit()
        return True
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _create_registered_user_db(username: str, password_hash: str, email: str, phone: str = "", *, db_conn=None):
    normalized_username = str(username or "").strip()
    normalized_password = str(password_hash or "").strip()
    normalized_email = str(email or "").strip()
    normalized_phone = str(phone or "").strip()
    if not normalized_username:
        raise ValueError("Username is required.")
    if not normalized_password:
        raise ValueError("Password hash is required.")
    if not normalized_email:
        raise ValueError("Email is required.")
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            "INSERT INTO users (username, password, email, phone) VALUES (?, ?, ?, ?)",
            (normalized_username, normalized_password, normalized_email, normalized_phone),
        )
        db_conn.commit()
        return {
            "username": normalized_username,
            "email": normalized_email,
            "phone": normalized_phone,
        }
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _update_user_password_db(username: str, new_password: str, *, db_conn=None):
    password_hash = hash_password(new_password)
    if isinstance(password_hash, bytes):
        password_hash = password_hash.decode()
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            "UPDATE users SET password = ? WHERE username = ?",
            (password_hash, username),
        )
        db_conn.commit()
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _save_user_notification_settings_db(
    username: str,
    phone: str,
    telegram_chat_id: str,
    whatsapp_enabled: bool,
    telegram_enabled: bool,
    *,
    db_conn=None,
):
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        normalized_phone = normalize_phone_number(phone)
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            """
            UPDATE users
            SET phone = ?,
                telegram_chat_id = ?,
                notification_whatsapp = ?,
                notification_telegram = ?
            WHERE username = ?
            """,
            (
                normalized_phone,
                str(telegram_chat_id or "").strip(),
                int(bool(whatsapp_enabled)),
                int(bool(telegram_enabled)),
                username,
            ),
        )
        db_conn.commit()
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _save_user_account_preferences_db(
    username: str,
    *,
    notify_buy_signals: bool,
    notify_sell_signals: bool,
    notify_signal_updates: bool,
    notify_high_confidence_only: bool,
    notify_market_digest: bool,
    security_authenticator_2fa: bool,
    security_sms_verification: bool,
    security_login_alerts: bool,
    db_conn=None,
):
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            """
            UPDATE users
            SET notify_buy_signals = ?,
                notify_sell_signals = ?,
                notify_signal_updates = ?,
                notify_high_confidence_only = ?,
                notify_market_digest = ?,
                security_authenticator_2fa = ?,
                security_sms_verification = ?,
                security_login_alerts = ?
            WHERE username = ?
            """,
            (
                int(bool(notify_buy_signals)),
                int(bool(notify_sell_signals)),
                int(bool(notify_signal_updates)),
                int(bool(notify_high_confidence_only)),
                int(bool(notify_market_digest)),
                int(bool(security_authenticator_2fa)),
                int(bool(security_sms_verification)),
                int(bool(security_login_alerts)),
                username,
            ),
        )
        db_conn.commit()
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _change_user_password_db(username: str, current_password: str, new_password: str, *, db_conn=None) -> tuple[bool, str]:
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        db_cursor = db_conn.cursor()
        db_cursor.execute("SELECT password FROM users WHERE username = ?", (username,))
        row = db_cursor.fetchone()
        if not row:
            return False, "Account could not be found."
        stored_hash = row[0]
        if not verify_password(current_password, stored_hash):
            return False, "Current password is incorrect."
        password_ok, password_error = password_meets_policy(new_password)
        if not password_ok:
            return False, password_error
        if verify_password(new_password, stored_hash):
            return False, "New password must be different from your current password."
        _update_user_password_db(username, new_password, db_conn=db_conn)
        _clear_login_failures_db(username, db_conn=db_conn)
        return True, "Password updated successfully."
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _load_app_token_payload_db(token_name: str, *, db_conn=None):
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            "SELECT token_payload FROM app_runtime_tokens WHERE token_name = ? LIMIT 1",
            (token_name,),
        )
        row = db_cursor.fetchone()
        if row and row[0]:
            try:
                return json.loads(row[0])
            except Exception:
                return None
        return None
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _save_app_token_payload_db(token_name: str, payload: dict, *, db_conn=None):
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            """
            INSERT INTO app_runtime_tokens (token_name, token_payload, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(token_name) DO UPDATE SET
                token_payload=excluded.token_payload,
                updated_at=excluded.updated_at
            """,
            (token_name, json.dumps(payload or {}), time.time()),
        )
        db_conn.commit()
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


@contextmanager
def _gmail_direct_network_env():
    """Bypass broken local proxy env vars for Google OAuth token refresh."""
    proxy_keys = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    )
    keep_proxy = str(os.getenv("FINWISE_GMAIL_USE_SYSTEM_PROXY", "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    previous_values = {key: os.environ.get(key) for key in proxy_keys}
    try:
        if not keep_proxy:
            for key in proxy_keys:
                os.environ.pop(key, None)
        yield
    finally:
        for key, value in previous_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _allow_local_email_fallback() -> bool:
    if is_production_environment():
        return False
    return str(os.getenv("FINWISE_ALLOW_LOCAL_EMAIL_FALLBACK", "1") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _local_email_otp_message(email: str, otp: str, *, purpose: str) -> str:
    normalized_purpose = str(purpose or "verification").strip().lower()
    if normalized_purpose == "password_reset":
        label = "Password reset"
    elif normalized_purpose == "password_change":
        label = "Password change"
    else:
        label = "Verification"
    return f"{label} code prepared locally for {email}. Use this code: {otp}"


def _load_credentials_headless(token_path: str, *, db_conn=None):
    info = _load_app_token_payload_db(token_path, db_conn=db_conn)
    if info is None and os.path.exists(token_path):
        try:
            with open(token_path, encoding="utf-8") as token_file:
                info = json.load(token_file)
        except Exception as exc:
            APP_LOGGER.warning("Token file fallback failed: %s", exc)
            info = None
    if not info:
        return None
    try:
        creds = Credentials.from_authorized_user_info(info, SCOPES)
        if creds and creds.refresh_token and (creds.expired or not getattr(creds, "expiry", None)):
            with _gmail_direct_network_env():
                creds.refresh(Request())
            _save_app_token_payload_db(
                token_path,
                {
                    "token": creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_uri": creds.token_uri,
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes": list(creds.scopes) if creds.scopes else [],
                    "expiry": creds.expiry.isoformat() if getattr(creds, "expiry", None) else None,
                },
                db_conn=db_conn,
            )
        return creds if (creds and creds.valid) else None
    except Exception as exc:
        APP_LOGGER.warning("load_credentials_headless failed: %s", exc)
        return None


def _mobile_email_auth_status() -> dict:
    credentials_path = os.getenv("GOOGLE_OAUTH_CREDENTIALS_FILE", "credentials.json")
    token_path = os.getenv("GOOGLE_OAUTH_TOKEN_FILE", "token.json")
    gmail_address = str(os.getenv("GMAIL_ADDRESS", "") or "").strip()
    if not gmail_address:
        if _allow_local_email_fallback():
            return {
                "enabled": True,
                "message": "Email verification is using local demo mode because Gmail OAuth is not configured on this server.",
            }
        return {"enabled": False, "message": "Email verification is not configured on this server."}
    if not os.path.exists(credentials_path):
        if _allow_local_email_fallback():
            return {
                "enabled": True,
                "message": "Email verification is using local demo mode because the Gmail credentials file is missing.",
            }
        return {"enabled": False, "message": "Google OAuth credentials file is missing on this server."}
    if not os.path.exists(token_path):
        if _allow_local_email_fallback():
            return {
                "enabled": True,
                "message": "Email verification is using local demo mode because the Gmail OAuth token is missing.",
            }
        return {"enabled": False, "message": "Gmail OAuth token is missing on this server. Complete desktop Gmail authorization first."}
    creds = _load_credentials_headless(token_path)
    if not creds or not creds.valid:
        if _allow_local_email_fallback():
            return {
                "enabled": True,
                "message": "Email verification is using local demo mode because Gmail OAuth is not ready.",
            }
        return {
            "enabled": False,
            "message": "Email verification needs Gmail OAuth to be completed from desktop first.",
        }
    return {"enabled": True, "message": "Email verification is ready."}


def _send_email_otp_headless(email: str, username: str, *, purpose: str = "verification") -> tuple[bool, str]:
    credentials_path = os.getenv("GOOGLE_OAUTH_CREDENTIALS_FILE", "credentials.json")
    token_path = os.getenv("GOOGLE_OAUTH_TOKEN_FILE", "token.json")
    gmail_address = str(os.getenv("GMAIL_ADDRESS", "") or "").strip()
    local_fallback = _allow_local_email_fallback()
    if not gmail_address:
        if local_fallback:
            otp = _generate_otp_db(username)
            return True, _local_email_otp_message(email, otp, purpose=purpose)
        return False, "Email verification is not configured on this server."
    if not os.path.exists(credentials_path):
        if local_fallback:
            otp = _generate_otp_db(username)
            return True, _local_email_otp_message(email, otp, purpose=purpose)
        return False, "Google OAuth credentials file is missing on this server."
    if not os.path.exists(token_path):
        if local_fallback:
            otp = _generate_otp_db(username)
            return True, _local_email_otp_message(email, otp, purpose=purpose)
        return False, "Gmail OAuth token is missing on this server. Complete desktop Gmail authorization first."
    creds = _load_credentials_headless(token_path)
    if not creds or not creds.valid:
        if local_fallback:
            otp = _generate_otp_db(username)
            return True, _local_email_otp_message(email, otp, purpose=purpose)
        return False, "Email verification needs Gmail OAuth from desktop before mobile auth can send codes."

    normalized_purpose = str(purpose or "verification").strip().lower()
    if normalized_purpose not in {"verification", "password_reset", "password_change"}:
        normalized_purpose = "verification"

    otp = _generate_otp_db(username)
    if normalized_purpose == "password_reset":
        msg = MIMEText(f"Your Finwise AI password reset code is: {otp}\n\nValid for 5 minutes.")
        msg["Subject"] = "Finwise AI - Password Reset Code"
        success_message = f"Password reset code sent to {email}."
    elif normalized_purpose == "password_change":
        msg = MIMEText(f"Your Finwise AI password change verification code is: {otp}\n\nValid for 5 minutes.")
        msg["Subject"] = "Finwise AI - Password Change Verification Code"
        success_message = f"Password change code sent to {email}."
    else:
        msg = MIMEText(f"Your Finwise AI OTP is: {otp}\n\nValid for 5 minutes.")
        msg["Subject"] = "Finwise AI - Verification Code"
        success_message = f"Verification code sent to {email}."
    msg["From"] = gmail_address
    msg["To"] = email

    server = None
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=20)
        server.ehlo()
        server.starttls()
        server.ehlo()
        auth_string = build_xoauth2_string(gmail_address, creds.token)
        code, _ = server.docmd("AUTH", f"XOAUTH2 {auth_string}")
        if code != 235:
            raise RuntimeError(f"XOAUTH2 auth failed with code {code}")
        server.send_message(msg)
        return True, success_message
    except Exception as exc:
        APP_LOGGER.exception("Mobile OTP delivery failed")
        return False, f"Email delivery failed: {exc}"
    finally:
        try:
            if server:
                server.quit()
        except Exception:
            pass


def _mobile_user_snapshot_db(username: str, *, db_conn=None):
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            """
            SELECT
                username,
                COALESCE(email, ''),
                COALESCE(phone, ''),
                COALESCE(premium, 0),
                COALESCE(notification_whatsapp, 0),
                COALESCE(notification_telegram, 0),
                COALESCE(telegram_chat_id, ''),
                COALESCE(notify_buy_signals, 1),
                COALESCE(notify_sell_signals, 1),
                COALESCE(notify_signal_updates, 0),
                COALESCE(notify_high_confidence_only, 0),
                COALESCE(notify_market_digest, 1),
                COALESCE(security_authenticator_2fa, 0),
                COALESCE(security_sms_verification, 1),
                COALESCE(security_login_alerts, 1)
            FROM users
            WHERE username = ?
            LIMIT 1
            """,
            (username,),
        )
        row = db_cursor.fetchone()
        if not row:
            return None
        return {
            "username": row[0],
            "email": row[1],
            "phone": row[2],
            "premium": int(row[3] or 0),
            "notification_whatsapp": int(row[4] or 0),
            "notification_telegram": int(row[5] or 0),
            "telegram_chat_id": row[6] or "",
            "notify_buy_signals": int(row[7] or 0),
            "notify_sell_signals": int(row[8] or 0),
            "notify_signal_updates": int(row[9] or 0),
            "notify_high_confidence_only": int(row[10] or 0),
            "notify_market_digest": int(row[11] or 0),
            "security_authenticator_2fa": int(row[12] or 0),
            "security_sms_verification": int(row[13] or 0),
            "security_login_alerts": int(row[14] or 0),
        }
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _mobile_signal_usage_snapshot(username: str, *, db_conn=None) -> dict:
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        db_cursor = db_conn.cursor()
        db_cursor.execute("SELECT COALESCE(premium, 0) FROM users WHERE username = ? LIMIT 1", (username,))
        row = db_cursor.fetchone()
        premium = int((row[0] if row else 0) or 0)
        today = str(date.today())
        db_cursor.execute("SELECT used FROM usage WHERE username = ? AND day = ? LIMIT 1", (username, today))
        usage_row = db_cursor.fetchone()
        used = int((usage_row[0] if usage_row else 0) or 0)
        limit = 999999 if premium else 5
        unlimited = bool(premium)
        signals_left = None if unlimited else max(limit - used, 0)
        return {
            "premium": premium,
            "used": used,
            "limit": limit,
            "is_unlimited": unlimited,
            "signals_left": signals_left,
        }
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _consume_signal_usage_db(username: str, *, db_conn=None) -> dict:
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        usage = _mobile_signal_usage_snapshot(username, db_conn=db_conn)
        if not usage["is_unlimited"] and int(usage["used"] or 0) >= int(usage["limit"] or 0):
            return usage
        today = str(date.today())
        db_cursor = db_conn.cursor()
        next_used = int(usage["used"] or 0) + 1
        if int(usage["used"] or 0) == 0:
            db_cursor.execute("INSERT INTO usage VALUES (?, ?, ?)", (username, today, next_used))
        else:
            db_cursor.execute(
                "UPDATE usage SET used = ? WHERE username = ? AND day = ?",
                (next_used, username, today),
            )
        db_conn.commit()
        usage["used"] = next_used
        if not usage["is_unlimited"]:
            usage["signals_left"] = max(int(usage["limit"] or 0) - next_used, 0)
        return usage
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


_TRADE_HISTORY_COLUMNS = [
    "id", "broker_name", "account_alias", "source", "status", "symbol", "timeframe", "side", "confidence",
    "quantity", "notional_usd", "entry_price", "exit_price", "stop_loss", "take_profit", "fee_paid",
    "pnl_usd", "pnl_pct", "regime", "setup_quality", "risk_reward_ratio", "notes", "opened_at", "closed_at", "created_at",
]


def _trade_rows_df_db(username: str, status: str = None, *, limit: int = None, db_conn=None) -> pd.DataFrame:
    own_conn = db_conn is None
    db_conn = db_conn or _mobile_db_connect()
    try:
        db_cursor = db_conn.cursor()
        params = [username]
        query = """
            SELECT id, broker_name, account_alias, source, status, symbol, timeframe, side, confidence,
                   quantity, notional_usd, entry_price, exit_price, stop_loss, take_profit, fee_paid,
                   pnl_usd, pnl_pct, regime, setup_quality, risk_reward_ratio, notes, opened_at, closed_at, created_at
            FROM trade_history
            WHERE username = ?
        """
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY COALESCE(closed_at, opened_at, created_at) DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
        db_cursor.execute(query, tuple(params))
        rows = db_cursor.fetchall()
        return pd.DataFrame(rows, columns=_TRADE_HISTORY_COLUMNS)
    finally:
        if own_conn:
            _mobile_close_db(db_conn)


def _trade_metrics_from_df(df: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    if df.empty:
        return {
            "today_trades": 0,
            "today_net": 0.0,
            "today_profit": 0.0,
            "today_loss": 0.0,
            "lifetime_trades": 0,
            "lifetime_net": 0.0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
        }, df
    closed_df = df[df["status"] == "closed"].copy()
    today = str(date.today())
    if not closed_df.empty:
        closed_df["closed_day"] = closed_df["closed_at"].fillna("").astype(str).str.slice(0, 10)
    today_df = closed_df[closed_df["closed_day"] == today].copy() if not closed_df.empty else closed_df
    wins = closed_df[closed_df["pnl_usd"] > 0]
    losses = closed_df[closed_df["pnl_usd"] < 0]
    metrics = {
        "today_trades": int(len(today_df)),
        "today_net": float(today_df["pnl_usd"].sum()) if not today_df.empty else 0.0,
        "today_profit": float(today_df[today_df["pnl_usd"] > 0]["pnl_usd"].sum()) if not today_df.empty else 0.0,
        "today_loss": float(today_df[today_df["pnl_usd"] < 0]["pnl_usd"].sum()) if not today_df.empty else 0.0,
        "lifetime_trades": int(len(closed_df)),
        "lifetime_net": float(closed_df["pnl_usd"].sum()) if not closed_df.empty else 0.0,
        "win_rate": float((len(wins) / len(closed_df)) * 100) if len(closed_df) else 0.0,
        "avg_win": float(wins["pnl_usd"].mean()) if not wins.empty else 0.0,
        "avg_loss": float(losses["pnl_usd"].mean()) if not losses.empty else 0.0,
    }
    return metrics, closed_df


def _trade_rows_payload(df: pd.DataFrame, *, limit: int = None) -> list[dict]:
    if df.empty:
        return []
    working = df.head(limit) if limit is not None else df
    rows = []
    for row in working.to_dict(orient="records"):
        rows.append(_mobile_json_value(row))
    return rows


def _mobile_broker_summary(username: str) -> dict:
    connection = get_active_broker_connection(username)
    if not connection:
        return {
            "connected": False,
            "broker_name": "Not connected",
            "status": "No broker connected",
            "method": "none",
            "reconnect_required": False,
            "credentials_persisted": False,
            "updated_at": None,
        }
    metadata = dict(connection.get("metadata") or {})
    reconnect_required = bool(metadata.get("reconnect_required"))
    return {
        "connected": True,
        "broker_name": str(connection.get("broker_name") or "Broker").title(),
        "status": "Reconnect required" if reconnect_required else "Connected",
        "method": str(connection.get("auth_method") or "saved"),
        "reconnect_required": reconnect_required,
        "credentials_persisted": bool(metadata.get("credentials_persisted", False)),
        "updated_at": connection.get("updated_at"),
    }


def _mobile_notification_payload(username: str, user: dict | None = None, *, include_connect: bool = True) -> dict:
    user = user or _mobile_user_snapshot_db(username) or {}
    telegram_chat_id = user.get("telegram_chat_id", "")
    telegram_bot_username = ""
    telegram_connect_url = ""
    if include_connect:
        telegram_connect_url = build_telegram_connect_url(username)
        if telegram_connect_url.startswith("https://t.me/"):
            telegram_bot_username = telegram_connect_url.split("https://t.me/", 1)[1].split("?", 1)[0]
    return {
        "whatsapp_enabled": bool(user.get("notification_whatsapp")),
        "telegram_enabled": bool(user.get("notification_telegram")),
        "telegram_chat_id": telegram_chat_id,
        "telegram_connected": bool(str(telegram_chat_id or "").strip()),
        "telegram_destination_label": describe_telegram_destination(telegram_chat_id) if telegram_chat_id else "",
        "telegram_bot_username": telegram_bot_username,
        "telegram_connect_url": telegram_connect_url,
    }


def _mobile_bootstrap_payload(username: str) -> dict:
    db_conn = _mobile_db_connect()
    try:
        user = _mobile_user_snapshot_db(username, db_conn=db_conn) or {"username": username, "premium": 0}
        usage = _mobile_signal_usage_snapshot(username, db_conn=db_conn)
        return {
            "authenticated": True,
            "user": {
                "username": user.get("username", username),
                "email": user.get("email", ""),
                "phone": user.get("phone", ""),
                "premium": bool(user.get("premium")),
            },
            "usage": usage,
            "broker": _mobile_broker_summary(username),
            "notifications": _mobile_notification_payload(username, user, include_connect=False),
            "symbols": list(DEFAULT_TRACKED_SYMBOLS),
            "timeframes": list(DEFAULT_TIMEFRAMES),
            "defaults": {
                "symbol": DEFAULT_TRACKED_SYMBOLS[0],
                "interval": DEFAULT_SIGNAL_TIMEFRAME,
            },
            "email_auth": _mobile_email_auth_status(),
        }
    finally:
        _mobile_close_db(db_conn)


def _mobile_dashboard_payload(username: str) -> dict:
    db_conn = _mobile_db_connect()
    try:
        user = _mobile_user_snapshot_db(username, db_conn=db_conn) or {"username": username, "premium": 0}
        usage = _mobile_signal_usage_snapshot(username, db_conn=db_conn)
        trades_df = _trade_rows_df_db(username, db_conn=db_conn)
        metrics, _ = _trade_metrics_from_df(trades_df)
        recent_trades = _trade_rows_payload(trades_df, limit=6)
        return {
            "user": {
                "username": user.get("username", username),
                "premium": bool(user.get("premium")),
            },
            "usage": usage,
            "metrics": metrics,
            "recent_trades": recent_trades,
            "broker": _mobile_broker_summary(username),
        }
    finally:
        _mobile_close_db(db_conn)


def _mobile_settings_payload(username: str) -> dict:
    user = _mobile_user_snapshot_db(username)
    user = user or {"username": username, "premium": 0}
    return {
        "account": {
            "username": user.get("username", username),
            "email": user.get("email", ""),
            "phone": user.get("phone", ""),
            "premium": bool(user.get("premium")),
        },
        "notifications": _mobile_notification_payload(username, user),
        "preferences": {
            "notify_buy_signals": bool(user.get("notify_buy_signals")),
            "notify_sell_signals": bool(user.get("notify_sell_signals")),
            "notify_signal_updates": bool(user.get("notify_signal_updates")),
            "notify_high_confidence_only": bool(user.get("notify_high_confidence_only")),
            "notify_market_digest": bool(user.get("notify_market_digest")),
        },
        "security": {
            "authenticator_2fa": bool(user.get("security_authenticator_2fa")),
            "sms_verification": bool(user.get("security_sms_verification")),
            "login_alerts": bool(user.get("security_login_alerts")),
        },
        "broker": _mobile_broker_summary(username),
    }


def _mobile_market_payload(
    symbol: str,
    interval: str,
    *,
    candle_limit: int = CHART_POLL_WINDOW_CANDLES,
    before_time: int | None = None,
) -> dict:
    normalized_symbol = str(symbol or DEFAULT_TRACKED_SYMBOLS[0]).strip().upper() or DEFAULT_TRACKED_SYMBOLS[0]
    normalized_interval = str(interval or DEFAULT_SIGNAL_TIMEFRAME).strip() or DEFAULT_SIGNAL_TIMEFRAME
    if normalized_interval not in DEFAULT_TIMEFRAMES:
        normalized_interval = DEFAULT_SIGNAL_TIMEFRAME
    try:
        candle_limit = int(candle_limit or CHART_POLL_WINDOW_CANDLES)
    except Exception:
        candle_limit = CHART_POLL_WINDOW_CANDLES
    candle_limit = max(1, min(candle_limit, 1000))
    _start_market_feed()
    if before_time is not None:
        history = engine.load_older_history(
            normalized_symbol,
            normalized_interval,
            before_time=before_time,
            limit=candle_limit,
        )
    else:
        history = engine.get_history(normalized_symbol, normalized_interval, limit=candle_limit)
    if history is None or history.empty:
        _ensure_symbol_loaded(normalized_symbol)
        if before_time is not None:
            history = engine.load_older_history(
                normalized_symbol,
                normalized_interval,
                before_time=before_time,
                limit=candle_limit,
            )
        else:
            history = engine.get_history(normalized_symbol, normalized_interval, limit=candle_limit)
    snapshot = engine.get_market_snapshot(normalized_symbol)
    orderbook = engine.get_orderbook(normalized_symbol, depth=10)
    return {
        "symbol": normalized_symbol,
        "interval": normalized_interval,
        "candles": _serialize_terminal_candles(history, limit=candle_limit),
        "market": _serialize_terminal_market(snapshot),
        "orderbook": _serialize_terminal_orderbook(orderbook, depth=8),
        "engine_status": {
            "ok": bool(_engine_status.get("ok")),
            "message": str(_engine_status.get("message") or ""),
            "ready": _engine_ready.is_set(),
        },
    }


def _mobile_desk_payload(username: str, symbol: str, interval: str, trade_style: str = "") -> dict:
    market_payload = _mobile_market_payload(symbol, interval)
    usage = _mobile_signal_usage_snapshot(username)
    normalized_trade_style = normalize_trade_style(trade_style or DEFAULT_TRADE_STYLE)
    style_profile = get_trade_style_profile(normalized_trade_style)
    return {
        "usage": usage,
        "broker": _mobile_broker_summary(username),
        "trade_style": {
            "selected": normalized_trade_style,
            "label": style_profile.get("label", TRADE_STYLE_LABELS.get(normalized_trade_style, "Day Trade")),
            "description": style_profile.get("description", TRADE_STYLE_DESCRIPTIONS.get(normalized_trade_style, "")),
            "options": TRADE_STYLE_OPTIONS,
        },
        "market": {
            "symbol": market_payload.get("symbol"),
            "interval": market_payload.get("interval"),
            "snapshot": market_payload.get("market"),
            "engine_status": market_payload.get("engine_status"),
        },
    }


def _mobile_journal_payload(username: str, *, status: str = "", limit: int = 40) -> dict:
    normalized_status = str(status or "").strip().lower() or None
    db_conn = _mobile_db_connect()
    try:
        trades_df = _trade_rows_df_db(username, normalized_status, limit=limit, db_conn=db_conn)
        metrics, _ = _trade_metrics_from_df(_trade_rows_df_db(username, db_conn=db_conn))
        return {
            "status": normalized_status or "all",
            "metrics": metrics,
            "trades": _trade_rows_payload(trades_df),
        }
    finally:
        _mobile_close_db(db_conn)


def _normalize_mobile_proxy_route(path_value: str) -> str:
    normalized = str(path_value or "").strip() or "/"
    proxy_prefix = STREAMLIT_MOBILE_PROXY_PREFIX.rstrip("/")
    if proxy_prefix and (normalized == proxy_prefix or normalized.startswith(f"{proxy_prefix}/")):
        suffix = normalized[len(proxy_prefix):] or ""
        normalized = f"/api/mobile{suffix}" if suffix else "/api/mobile"
    return normalized


class _TerminalMarketHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A003 - BaseHTTPRequestHandler signature
        return

    def _send_bytes(
        self,
        body: bytes,
        *,
        status: HTTPStatus = HTTPStatus.OK,
        content_type: str = "text/plain; charset=utf-8",
        headers: dict | None = None,
        allow_cross_origin: bool = False,
    ):
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if allow_cross_origin:
            self.send_header("Access-Control-Allow-Origin", "*")
        for header_name, header_value in (headers or {}).items():
            self.send_header(str(header_name), str(header_value))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(
        self,
        payload: dict,
        status: HTTPStatus = HTTPStatus.OK,
        *,
        headers: dict | None = None,
        allow_cross_origin: bool = False,
    ):
        body = json.dumps(_mobile_json_value(payload), allow_nan=False).encode("utf-8")
        self._send_bytes(
            body,
            status=status,
            content_type="application/json; charset=utf-8",
            headers=headers,
            allow_cross_origin=allow_cross_origin,
        )

    def _send_redirect(self, location: str, status: HTTPStatus = HTTPStatus.FOUND):
        self.send_response(int(status))
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _request_json(self) -> dict:
        try:
            content_length = int(self.headers.get("Content-Length", "0") or 0)
        except Exception:
            content_length = 0
        if content_length <= 0:
            return {}
        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}
        try:
            return json.loads(raw_body.decode("utf-8"))
        except Exception:
            raise ValueError("Request body must be valid JSON.")

    def _cookie_token(self) -> str:
        try:
            raw_cookie = self.headers.get("Cookie", "")
        except Exception:
            raw_cookie = ""
        if not raw_cookie:
            return ""
        cookie = SimpleCookie()
        try:
            cookie.load(raw_cookie)
        except Exception:
            return ""
        morsel = cookie.get(SESSION_COOKIE_NAME)
        return str(morsel.value or "").strip() if morsel else ""

    def _auth_context(self) -> dict:
        cached = getattr(self, "_cached_auth_context", None)
        if cached is not None:
            return cached
        token = self._cookie_token()
        session = _session_lookup_from_token(token) if token else None
        cached = {
            "token": token,
            "session": session,
            "clear_cookie": bool(token and session is None),
        }
        self._cached_auth_context = cached
        return cached

    def _auth_headers(self) -> dict:
        auth_context = self._auth_context()
        if not auth_context.get("clear_cookie"):
            return {}
        return {
            "Set-Cookie": _mobile_cookie_header(
                clear=True,
                secure=_mobile_request_uses_https(self.headers),
            )
        }

    def _require_auth(self):
        auth_context = self._auth_context()
        session = auth_context.get("session")
        if session:
            return session
        self._send_json(
            {
                "authenticated": False,
                "error": "Sign in required.",
                "email_auth": _mobile_email_auth_status(),
            },
            HTTPStatus.UNAUTHORIZED,
            headers=self._auth_headers(),
        )
        return None

    def _client_ip(self) -> str:
        forwarded_for = _mobile_header_value(self.headers, "X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return str((self.client_address or ("",))[0] or "")

    def _client_user_agent(self) -> str:
        return _mobile_header_value(
            self.headers,
            "user-agent",
            "x-original-user-agent",
            "x-device-user-agent",
        )

    def _serve_mobile_asset(self, route_path: str):
        asset_map = {
            "/mobile/": MOBILE_WEB_ROOT / "index.html",
            "/mobile/index.html": MOBILE_WEB_ROOT / "index.html",
            "/mobile/styles.css": MOBILE_WEB_ROOT / "styles.css",
            "/mobile/app.js": MOBILE_WEB_ROOT / "app.js",
            "/mobile/vendor/lightweight-charts.js": LIGHTWEIGHT_CHARTS_VENDOR_PATH,
        }
        asset_path = asset_map.get(route_path)
        if asset_path is None or not asset_path.exists() or not asset_path.is_file():
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        content_type, _ = mimetypes.guess_type(str(asset_path))
        body = asset_path.read_bytes()
        self._send_bytes(
            body,
            status=HTTPStatus.OK,
            content_type=content_type or "application/octet-stream",
        )

    def do_GET(self):
        parsed = urlparse(self.path)
        route_path = _normalize_mobile_proxy_route(parsed.path)

        if route_path == "/mobile":
            self._send_redirect("/mobile/")
            return
        if route_path.startswith("/mobile/"):
            self._serve_mobile_asset(route_path)
            return
        if route_path == "/healthz":
            self._send_json({"ok": True, "service": "finwise-mobile-api"})
            return

        if route_path == "/api/mobile/session" or route_path == "/api/mobile/bootstrap":
            session = self._auth_context().get("session")
            if not session:
                self._send_json(
                    {
                        "authenticated": False,
                        "symbols": list(DEFAULT_TRACKED_SYMBOLS),
                        "timeframes": list(DEFAULT_TIMEFRAMES),
                        "defaults": {
                            "symbol": DEFAULT_TRACKED_SYMBOLS[0],
                            "interval": DEFAULT_SIGNAL_TIMEFRAME,
                        },
                        "email_auth": _mobile_email_auth_status(),
                    },
                    headers=self._auth_headers(),
                )
                return
            self._send_json(_mobile_bootstrap_payload(session["username"]), headers=self._auth_headers())
            return

        if route_path == "/api/mobile/dashboard":
            session = self._require_auth()
            if session is None:
                return
            self._send_json(_mobile_dashboard_payload(session["username"]), headers=self._auth_headers())
            return

        if route_path == "/api/mobile/market":
            session = self._require_auth()
            if session is None:
                return
            params = parse_qs(parsed.query)
            symbol = str(params.get("symbol", [DEFAULT_TRACKED_SYMBOLS[0]])[0] or DEFAULT_TRACKED_SYMBOLS[0]).upper()
            interval = str(params.get("interval", [DEFAULT_SIGNAL_TIMEFRAME])[0] or DEFAULT_SIGNAL_TIMEFRAME)
            try:
                payload = _mobile_market_payload(symbol, interval)
                payload["symbols"] = list(DEFAULT_TRACKED_SYMBOLS)
                payload["timeframes"] = list(DEFAULT_TIMEFRAMES)
                self._send_json(payload, headers=self._auth_headers())
            except Exception as exc:
                self._send_json(
                    {"error": str(exc), "symbol": symbol, "interval": interval},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    headers=self._auth_headers(),
                )
            return

        if route_path == "/api/mobile/desk":
            session = self._require_auth()
            if session is None:
                return
            params = parse_qs(parsed.query)
            symbol = str(params.get("symbol", [DEFAULT_TRACKED_SYMBOLS[0]])[0] or DEFAULT_TRACKED_SYMBOLS[0]).upper()
            interval = str(params.get("interval", [DEFAULT_SIGNAL_TIMEFRAME])[0] or DEFAULT_SIGNAL_TIMEFRAME)
            trade_style = str(params.get("trade_style", [DEFAULT_TRADE_STYLE])[0] or DEFAULT_TRADE_STYLE)
            try:
                self._send_json(
                    _mobile_desk_payload(session["username"], symbol, interval, trade_style),
                    headers=self._auth_headers(),
                )
            except Exception as exc:
                self._send_json(
                    {"error": str(exc), "symbol": symbol, "interval": interval},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    headers=self._auth_headers(),
                )
            return

        if route_path == "/api/mobile/journal":
            session = self._require_auth()
            if session is None:
                return
            params = parse_qs(parsed.query)
            status = str(params.get("status", [""])[0] or "")
            try:
                limit = max(1, min(100, int(params.get("limit", ["40"])[0] or 40)))
            except Exception:
                limit = 40
            self._send_json(
                _mobile_journal_payload(session["username"], status=status, limit=limit),
                headers=self._auth_headers(),
            )
            return

        if route_path == "/api/mobile/settings":
            session = self._require_auth()
            if session is None:
                return
            self._send_json(_mobile_settings_payload(session["username"]), headers=self._auth_headers())
            return

        if route_path != "/api/market/terminal":
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        params = parse_qs(parsed.query)
        symbol = str(params.get("symbol", [DEFAULT_TRACKED_SYMBOLS[0]])[0] or DEFAULT_TRACKED_SYMBOLS[0]).upper()
        interval = str(params.get("interval", [DEFAULT_SIGNAL_TIMEFRAME])[0] or DEFAULT_SIGNAL_TIMEFRAME)
        try:
            candle_limit = max(1, min(1000, int(params.get("limit", [str(CHART_POLL_WINDOW_CANDLES)])[0] or CHART_POLL_WINDOW_CANDLES)))
        except Exception:
            candle_limit = CHART_POLL_WINDOW_CANDLES
        before_value = params.get("before", [None])[0]
        try:
            before_time = int(before_value) if before_value not in (None, "") else None
        except Exception:
            before_time = None
        try:
            self._send_json(
                _mobile_market_payload(symbol, interval, candle_limit=candle_limit, before_time=before_time),
                allow_cross_origin=True,
            )
        except Exception as exc:
            self._send_json(
                {
                    "error": str(exc),
                    "symbol": symbol,
                    "interval": interval,
                },
                HTTPStatus.INTERNAL_SERVER_ERROR,
                allow_cross_origin=True,
            )

    def do_POST(self):
        parsed = urlparse(self.path)
        route_path = _normalize_mobile_proxy_route(parsed.path)
        try:
            payload = self._request_json()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if route_path == "/api/mobile/auth/login":
            username = str(payload.get("username", "") or "").strip()
            password = str(payload.get("password", "") or "")
            remember_me = bool(payload.get("remember_me", True))
            if not username or not password:
                self._send_json({"error": "Please enter your username and password."}, HTTPStatus.BAD_REQUEST)
                return
            db_conn = _mobile_db_connect()
            try:
                lock_message = _get_login_lock_message_db(username, db_conn=db_conn)
                if lock_message:
                    self._send_json({"error": lock_message}, HTTPStatus.TOO_MANY_REQUESTS)
                    return
                account = _load_registered_user_db(username, db_conn=db_conn)
                if account and verify_password(password, account["password"]):
                    _clear_login_failures_db(username, db_conn=db_conn)
                    _clear_login_failures_db(account["username"], db_conn=db_conn)
                    session_data = _session_create_record(
                        account["username"],
                        remember_me=remember_me,
                        user_agent=self._client_user_agent(),
                        ip_address=self._client_ip(),
                        db_conn=db_conn,
                    )
                    response_headers = {
                        "Set-Cookie": _mobile_cookie_header(
                            session_data["session_token"],
                            expires_at=session_data["expires_at"],
                            secure=_mobile_request_uses_https(self.headers),
                        )
                    }
                    auth_payload = _mobile_bootstrap_payload(account["username"])
                    auth_payload["message"] = f"Signed in as {account['username']}."
                    self._send_json(auth_payload, headers=response_headers)
                    return
                _record_login_failure_db(username, db_conn=db_conn)
                self._send_json(
                    {"error": _get_login_lock_message_db(username, db_conn=db_conn) or "Invalid username or password."},
                    HTTPStatus.UNAUTHORIZED,
                )
                return
            finally:
                _mobile_close_db(db_conn)

        if route_path == "/api/mobile/auth/logout":
            auth_context = self._auth_context()
            session = auth_context.get("session")
            if session:
                _revoke_session_record(session.get("session_id", ""))
            self._send_json(
                {
                    "ok": True,
                    "authenticated": False,
                    "message": "Signed out.",
                    "email_auth": _mobile_email_auth_status(),
                },
                headers={
                    "Set-Cookie": _mobile_cookie_header(
                        clear=True,
                        secure=_mobile_request_uses_https(self.headers),
                    )
                },
            )
            return

        if route_path == "/api/mobile/auth/register/start":
            username = str(payload.get("username", "") or "").strip()
            password = str(payload.get("password", "") or "")
            email = str(payload.get("email", "") or "").strip()
            phone = str(payload.get("phone", "") or "").strip()
            email_auth = _mobile_email_auth_status()
            if not email_auth.get("enabled"):
                self._send_json({"error": email_auth.get("message", "Email verification is unavailable.")}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            if not username or not password or not email:
                self._send_json({"error": "Username, password, and email are required."}, HTTPStatus.BAD_REQUEST)
                return
            password_ok, password_error = password_meets_policy(password)
            if not password_ok:
                self._send_json({"error": password_error}, HTTPStatus.BAD_REQUEST)
                return
            db_conn = _mobile_db_connect()
            try:
                if _load_registered_user_db(username, db_conn=db_conn):
                    self._send_json({"error": "Username already exists. Please choose another."}, HTTPStatus.CONFLICT)
                    return
                password_hash = hash_password(password)
                if isinstance(password_hash, bytes):
                    password_hash = password_hash.decode()
                _save_pending_user_db(username, password_hash, email, phone, db_conn=db_conn)
            finally:
                _mobile_close_db(db_conn)
            ok, message = _send_email_otp_headless(email, username, purpose="verification")
            if not ok:
                self._send_json({"error": message}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self._send_json({"ok": True, "message": message})
            return

        if route_path == "/api/mobile/auth/register/complete":
            username = str(payload.get("username", "") or "").strip()
            otp = str(payload.get("otp", "") or "").strip()
            remember_me = bool(payload.get("remember_me", True))
            if not username or not otp:
                self._send_json({"error": "Username and OTP are required."}, HTTPStatus.BAD_REQUEST)
                return
            db_conn = _mobile_db_connect()
            try:
                pending_user = _load_pending_user_db(username, db_conn=db_conn)
                if not pending_user:
                    self._send_json({"error": "Registration session expired. Please start again."}, HTTPStatus.BAD_REQUEST)
                    return
                if not _verify_otp_db(pending_user["username"], otp, db_conn=db_conn):
                    self._send_json({"error": "Invalid or expired verification code."}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    _create_registered_user_db(
                        pending_user["username"],
                        pending_user["password"],
                        pending_user["email"],
                        pending_user.get("phone", ""),
                        db_conn=db_conn,
                    )
                except Exception as exc:
                    if is_integrity_error(exc):
                        self._send_json({"error": "Username already exists. Please sign in instead."}, HTTPStatus.CONFLICT)
                        return
                    raise
                _clear_pending_user_db(pending_user["username"], db_conn=db_conn)
                _clear_login_failures_db(pending_user["username"], db_conn=db_conn)
                session_data = _session_create_record(
                    pending_user["username"],
                    remember_me=remember_me,
                    user_agent=self._client_user_agent(),
                    ip_address=self._client_ip(),
                    db_conn=db_conn,
                )
                response_headers = {
                    "Set-Cookie": _mobile_cookie_header(
                        session_data["session_token"],
                        expires_at=session_data["expires_at"],
                        secure=_mobile_request_uses_https(self.headers),
                    )
                }
                auth_payload = _mobile_bootstrap_payload(pending_user["username"])
                auth_payload["message"] = f"Workspace created for {pending_user['username']}."
                self._send_json(auth_payload, HTTPStatus.CREATED, headers=response_headers)
                return
            finally:
                _mobile_close_db(db_conn)

        if route_path == "/api/mobile/auth/password/request":
            username = str(payload.get("username", "") or "").strip()
            email = str(payload.get("email", "") or "").strip()
            email_auth = _mobile_email_auth_status()
            if not email_auth.get("enabled"):
                self._send_json({"error": email_auth.get("message", "Email verification is unavailable.")}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            if not username or not email:
                self._send_json({"error": "Username and email are required."}, HTTPStatus.BAD_REQUEST)
                return
            user = _load_registered_user_db(username, email)
            if not user:
                self._send_json({"error": "We could not match that username and email."}, HTTPStatus.NOT_FOUND)
                return
            ok, message = _send_email_otp_headless(user["email"], user["username"], purpose="password_reset")
            if not ok:
                self._send_json({"error": message}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self._send_json({"ok": True, "message": message})
            return

        if route_path == "/api/mobile/auth/password/reset":
            username = str(payload.get("username", "") or "").strip()
            email = str(payload.get("email", "") or "").strip()
            otp = str(payload.get("otp", "") or "").strip()
            new_password = str(payload.get("new_password", "") or "")
            remember_me = bool(payload.get("remember_me", True))
            if not username or not email or not otp or not new_password:
                self._send_json({"error": "Username, email, OTP, and new password are required."}, HTTPStatus.BAD_REQUEST)
                return
            password_ok, password_error = password_meets_policy(new_password)
            if not password_ok:
                self._send_json({"error": password_error}, HTTPStatus.BAD_REQUEST)
                return
            db_conn = _mobile_db_connect()
            try:
                user = _load_registered_user_db(username, email, db_conn=db_conn)
                if not user:
                    self._send_json({"error": "We could not match that username and email."}, HTTPStatus.NOT_FOUND)
                    return
                if not _verify_otp_db(user["username"], otp, db_conn=db_conn):
                    self._send_json({"error": "Invalid or expired reset code."}, HTTPStatus.BAD_REQUEST)
                    return
                _update_user_password_db(user["username"], new_password, db_conn=db_conn)
                _clear_login_failures_db(user["username"], db_conn=db_conn)
                session_data = _session_create_record(
                    user["username"],
                    remember_me=remember_me,
                    user_agent=self._client_user_agent(),
                    ip_address=self._client_ip(),
                    db_conn=db_conn,
                )
                response_headers = {
                    "Set-Cookie": _mobile_cookie_header(
                        session_data["session_token"],
                        expires_at=session_data["expires_at"],
                        secure=_mobile_request_uses_https(self.headers),
                    )
                }
                auth_payload = _mobile_bootstrap_payload(user["username"])
                auth_payload["message"] = "Password updated. You are signed in."
                self._send_json(auth_payload, headers=response_headers)
                return
            finally:
                _mobile_close_db(db_conn)

        if route_path == "/api/mobile/settings/notifications":
            session = self._require_auth()
            if session is None:
                return
            db_conn = _mobile_db_connect()
            try:
                current_settings = _mobile_user_snapshot_db(session["username"], db_conn=db_conn) or {}
                raw_phone = str(payload.get("phone", current_settings.get("phone", "")) or "").strip()
                normalized_phone = normalize_phone_number(raw_phone)
                telegram_chat_id = str(payload.get("telegram_chat_id", current_settings.get("telegram_chat_id", "")) or "").strip()
                whatsapp_enabled = bool(payload.get("whatsapp_enabled", False))
                telegram_enabled = bool(payload.get("telegram_enabled", False))

                if raw_phone and not normalized_phone:
                    self._send_json(
                        {"error": "Use a valid WhatsApp number like +2348012345678 before saving."},
                        HTTPStatus.BAD_REQUEST,
                        headers=self._auth_headers(),
                    )
                    return
                if whatsapp_enabled and not normalized_phone:
                    self._send_json(
                        {"error": "Add a valid WhatsApp number before turning on WhatsApp alerts."},
                        HTTPStatus.BAD_REQUEST,
                        headers=self._auth_headers(),
                    )
                    return
                if telegram_enabled and not telegram_chat_id:
                    self._send_json(
                        {"error": "Finish the Telegram connect step before turning on Telegram alerts."},
                        HTTPStatus.BAD_REQUEST,
                        headers=self._auth_headers(),
                    )
                    return

                _save_user_notification_settings_db(
                    session["username"],
                    raw_phone,
                    telegram_chat_id,
                    whatsapp_enabled,
                    telegram_enabled,
                    db_conn=db_conn,
                )
            finally:
                _mobile_close_db(db_conn)
            settings_payload = _mobile_settings_payload(session["username"])
            settings_payload["message"] = "Notification routes saved."
            self._send_json(settings_payload, headers=self._auth_headers())
            return

        if route_path == "/api/mobile/settings/telegram/connect":
            session = self._require_auth()
            if session is None:
                return
            linked, result = connect_telegram_chat(session["username"])
            if not linked:
                self._send_json({"error": str(result)}, HTTPStatus.BAD_REQUEST, headers=self._auth_headers())
                return

            connection_payload = result if isinstance(result, dict) else {}
            chat_id = str(connection_payload.get("chat_id") or "").strip()
            if not chat_id:
                self._send_json(
                    {"error": "Telegram did not return a chat destination yet. Tap Start in the bot and try again."},
                    HTTPStatus.BAD_REQUEST,
                    headers=self._auth_headers(),
                )
                return

            db_conn = _mobile_db_connect()
            try:
                current_settings = _mobile_user_snapshot_db(session["username"], db_conn=db_conn) or {}
                _save_user_notification_settings_db(
                    session["username"],
                    str(current_settings.get("phone", "") or "").strip(),
                    chat_id,
                    bool(current_settings.get("notification_whatsapp", 0)),
                    True,
                    db_conn=db_conn,
                )
            finally:
                _mobile_close_db(db_conn)

            settings_payload = _mobile_settings_payload(session["username"])
            destination_label = connection_payload.get("label") or describe_telegram_destination(
                chat_id,
                chat_data=connection_payload.get("chat") if isinstance(connection_payload.get("chat"), dict) else None,
            )
            settings_payload["message"] = f"Telegram connected to {destination_label}."
            self._send_json(settings_payload, headers=self._auth_headers())
            return

        if route_path == "/api/mobile/settings/preferences":
            session = self._require_auth()
            if session is None:
                return
            db_conn = _mobile_db_connect()
            try:
                _save_user_account_preferences_db(
                    session["username"],
                    notify_buy_signals=bool(payload.get("notify_buy_signals", False)),
                    notify_sell_signals=bool(payload.get("notify_sell_signals", False)),
                    notify_signal_updates=bool(payload.get("notify_signal_updates", False)),
                    notify_high_confidence_only=bool(payload.get("notify_high_confidence_only", False)),
                    notify_market_digest=bool(payload.get("notify_market_digest", False)),
                    security_authenticator_2fa=bool(payload.get("security_authenticator_2fa", False)),
                    security_sms_verification=bool(payload.get("security_sms_verification", False)),
                    security_login_alerts=bool(payload.get("security_login_alerts", False)),
                    db_conn=db_conn,
                )
            finally:
                _mobile_close_db(db_conn)
            settings_payload = _mobile_settings_payload(session["username"])
            settings_payload["message"] = "Preferences saved."
            self._send_json(settings_payload, headers=self._auth_headers())
            return

        if route_path == "/api/mobile/settings/password":
            session = self._require_auth()
            if session is None:
                return
            current_password = str(payload.get("current_password", "") or "")
            new_password = str(payload.get("new_password", "") or "")
            if not current_password or not new_password:
                self._send_json({"error": "Current password and new password are required."}, HTTPStatus.BAD_REQUEST, headers=self._auth_headers())
                return
            db_conn = _mobile_db_connect()
            try:
                ok, message = _change_user_password_db(
                    session["username"],
                    current_password,
                    new_password,
                    db_conn=db_conn,
                )
            finally:
                _mobile_close_db(db_conn)
            if not ok:
                self._send_json({"error": message}, HTTPStatus.BAD_REQUEST, headers=self._auth_headers())
                return
            self._send_json({"ok": True, "message": message}, headers=self._auth_headers())
            return

        if route_path == "/api/mobile/signal":
            session = self._require_auth()
            if session is None:
                return
            symbol = str(payload.get("symbol", DEFAULT_TRACKED_SYMBOLS[0]) or DEFAULT_TRACKED_SYMBOLS[0]).strip().upper()
            interval = str(payload.get("interval", DEFAULT_SIGNAL_TIMEFRAME) or DEFAULT_SIGNAL_TIMEFRAME).strip()
            trade_style = normalize_trade_style(payload.get("trade_style", DEFAULT_TRADE_STYLE))
            balance_basis = _safe_float(payload.get("balance_basis"), 10000.0)
            if balance_basis <= 0:
                balance_basis = 10000.0
            usage = _mobile_signal_usage_snapshot(session["username"])
            if not usage["is_unlimited"] and int(usage["used"] or 0) >= int(usage["limit"] or 0):
                self._send_json(
                    {
                        "error": "Daily signal limit reached for your current plan.",
                        "usage": usage,
                    },
                    HTTPStatus.FORBIDDEN,
                    headers=self._auth_headers(),
                )
                return
            try:
                market_payload = _mobile_market_payload(symbol, interval)
                history = engine.get_history(symbol, interval)
                result = ai_signal_for_user(
                    session["username"],
                    history if history is not None else pd.DataFrame(),
                    symbol=symbol,
                    current_balance=balance_basis,
                    timeframe=interval,
                    trade_style=trade_style,
                )
                instant_signal, instant_error = _build_hidden_crypto_instant_signal(
                    username=session["username"],
                    symbol=symbol,
                    tf_label=interval,
                    df=history if history is not None else pd.DataFrame(),
                    snapshot=engine.get_market_snapshot(symbol) or {},
                    orderbook=engine.get_orderbook(symbol, depth=10) or {},
                    min_confidence=48.0,
                    min_rr=1.5,
                    risk_percent=1.0,
                    trade_style=trade_style,
                    balance_basis=balance_basis,
                )
                usage = _consume_signal_usage_db(session["username"])
                notification_payload = _build_signal_notification_payload(
                    session["username"],
                    symbol,
                    interval,
                    result,
                )
                try:
                    notify_premium_user(
                        notification_payload["message"],
                        session["username"],
                        signal_type=notification_payload["signal_type"],
                        confidence=notification_payload["confidence"],
                        is_update=notification_payload["is_update"],
                    )
                except Exception as notify_error:
                    APP_LOGGER.warning("Mobile signal notification failed: %s", notify_error)
                self._send_json(
                    {
                        "ok": True,
                        "symbol": symbol,
                        "interval": interval,
                        "trade_style": trade_style,
                        "usage": usage,
                        "signal": result,
                        "instant_signal": instant_signal,
                        "instant_signal_error": instant_error,
                        "broker": _mobile_broker_summary(session["username"]),
                        "market": {
                            "snapshot": market_payload.get("market"),
                            "engine_status": market_payload.get("engine_status"),
                        },
                    },
                    headers=self._auth_headers(),
                )
            except Exception as exc:
                self._send_json(
                    {"error": str(exc), "symbol": symbol, "interval": interval},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    headers=self._auth_headers(),
                )
            return

        self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)


def _streamlit_base_url_prefix() -> str:
    raw_base = str(st_config.get_option("server.baseUrlPath") or "").strip().strip("/")
    return f"/{raw_base}" if raw_base else ""


def _mobile_proxy_target_path(request_path: str, request_query: str = "") -> str:
    normalized_path = str(request_path or "").strip() or "/"
    base_prefix = _streamlit_base_url_prefix()
    if base_prefix and (normalized_path == base_prefix or normalized_path.startswith(f"{base_prefix}/")):
        normalized_path = normalized_path[len(base_prefix):] or "/"
    normalized_path = _normalize_mobile_proxy_route(normalized_path)
    if request_query:
        return f"{normalized_path}?{request_query}"
    return normalized_path


class _StreamlitMobileProxyHandler(tornado.web.RequestHandler):
    SUPPORTED_METHODS = ("GET", "POST", "OPTIONS")

    def options(self, *args, **kwargs):  # noqa: ARG002
        self.set_status(int(HTTPStatus.NO_CONTENT))
        self.finish()

    async def get(self, *args, **kwargs):  # noqa: ARG002
        self._proxy_request()

    async def post(self, *args, **kwargs):  # noqa: ARG002
        self._proxy_request()

    def _proxy_request(self) -> None:
        _start_terminal_chart_api()
        _start_market_feed()
        target_path = _mobile_proxy_target_path(self.request.path, self.request.query)
        outbound_headers: dict[str, str] = {
            "X-Forwarded-Proto": "https" if self.request.protocol == "https" else "http",
        }

        for header_name, header_value in self.request.headers.get_all():
            lowered = str(header_name or "").strip().lower()
            if lowered in {
                "host",
                "connection",
                "content-length",
                "transfer-encoding",
                "accept-encoding",
            }:
                continue
            outbound_headers[str(header_name)] = str(header_value)

        request_body = self.request.body if self.request.method in {"POST", "PUT", "PATCH"} else None
        connection = http.client.HTTPConnection("127.0.0.1", API_SERVER_PORT, timeout=30)
        try:
            connection.request(self.request.method, target_path, body=request_body, headers=outbound_headers)
            response = connection.getresponse()
            payload = response.read()
        except Exception as exc:
            APP_LOGGER.warning("Mobile same-host proxy failed for %s: %s", target_path, exc)
            self.set_status(int(HTTPStatus.BAD_GATEWAY))
            self.set_header("Content-Type", "application/json; charset=utf-8")
            self.finish(json.dumps({"error": "Mobile service is temporarily unavailable."}))
            return
        finally:
            connection.close()

        hop_by_hop = {
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailer",
            "transfer-encoding",
            "upgrade",
            "content-length",
        }
        self.set_status(response.status, reason=response.reason)
        for header_name, header_value in response.getheaders():
            lowered = str(header_name or "").strip().lower()
            if lowered in hop_by_hop:
                continue
            if lowered == "set-cookie":
                self.add_header(header_name, header_value)
            else:
                self.set_header(header_name, header_value)
        self.finish(payload)


def _find_streamlit_tornado_app():
    for obj in gc.get_objects():
        try:
            if isinstance(obj, tornado.web.Application) and hasattr(obj, "add_handlers"):
                return obj
        except Exception:
            continue
    return None


def _mobile_proxy_route_specs() -> list[tuple[str, type[tornado.web.RequestHandler]]]:
    base_prefix = _streamlit_base_url_prefix().strip("/")
    def _pattern(route_suffix: str) -> str:
        return rf"^/{'/'.join(part for part in [base_prefix, route_suffix] if part)}$"

    return [
        (_pattern(r"mobile(?:/.*)?"), _StreamlitMobileProxyHandler),
        (_pattern(r"mobile-api(?:/.*)?"), _StreamlitMobileProxyHandler),
        (_pattern(r"api/market/terminal(?:/.*)?"), _StreamlitMobileProxyHandler),
    ]


def _mobile_proxy_route_rules() -> list[tornado.routing.Rule]:
    return [
        tornado.routing.Rule(
            tornado.routing.PathMatches(pattern),
            handler,
            name=f"finwise_mobile_proxy_{index}",
        )
        for index, (pattern, handler) in enumerate(_mobile_proxy_route_specs())
    ]


def _ensure_streamlit_mobile_proxy_routes() -> bool:
    app = _find_streamlit_tornado_app()
    if app is None:
        return False
    if getattr(app, "_finwise_mobile_proxy_registered", False):
        return True
    try:
        inserted = False
        seen_targets: set[int] = set()
        default_rules = list(getattr(getattr(app, "default_router", None), "rules", []) or [])
        for host_rule in default_rules:
            target = getattr(host_rule, "target", None)
            nested_rules = getattr(target, "rules", None)
            if not isinstance(nested_rules, list) or id(target) in seen_targets:
                continue
            seen_targets.add(id(target))
            existing_names = {getattr(rule, "name", None) for rule in nested_rules}
            for route_rule in reversed(_mobile_proxy_route_rules()):
                if route_rule.name in existing_names:
                    continue
                nested_rules.insert(0, route_rule)
                inserted = True
        if not inserted:
            app.add_handlers(r".*$", _mobile_proxy_route_specs())
        app._finwise_mobile_proxy_registered = True
        return True
    except Exception as exc:
        APP_LOGGER.warning("Unable to register same-host mobile proxy routes: %s", exc)
        return False


def _start_terminal_chart_api():
    with _market_runtime["lock"]:
        if _market_runtime["chart_api_started"]:
            _set_session_state_safe("terminal_chart_api_started", True)
            return

        try:
            server = ThreadingHTTPServer(("0.0.0.0", API_SERVER_PORT), _TerminalMarketHandler)
        except OSError as exc:
            print(f"[CHART API WARNING] {exc}")
            _market_runtime["chart_api_started"] = True
            _set_session_state_safe("terminal_chart_api_started", True)
            return

        def _serve():
            try:
                server.serve_forever()
            except Exception as server_error:
                print(f"[CHART API ERROR] {server_error}")

        _market_runtime["chart_api_server"] = server
        threading.Thread(target=_serve, daemon=True, name="finwise-chart-api").start()
        _market_runtime["chart_api_started"] = True
        _set_session_state_safe("terminal_chart_api_started", True)


def _page_requires_market_feed(choice: str) -> bool:
    return choice in {"Market Analysis", "Trading Desk"}


def _page_requires_chart_api(choice: str) -> bool:
    return choice in {"Market Analysis", "Trading Desk"}


def _page_requires_broker_restore(choice: str) -> bool:
    return choice in {"Trading Desk", "Signal Result"}


def _ensure_page_runtime_services(choice: str):
    if _page_requires_market_feed(choice):
        _start_market_feed()
    if _page_requires_chart_api(choice):
        _start_terminal_chart_api()


def _normalize_nav_choice(choice: str) -> str:
    normalized = str(choice or "Dashboard").strip() or "Dashboard"
    if normalized in {"AI Signals", "Auto Trade"}:
        return "Trading Desk"
    if normalized in {"Synthetic", "Synthetic Indices", "Syythethis Trade", "Syythethis"}:
        return "Synthetic Trade"
    if normalized == "Settings":
        return "Account"
    return normalized


def _open_trading_desk_signal_workspace(
    symbol: str,
    tf_label: str,
    *,
    trade_style: str = "",
    mobile_layout: bool = False,
) -> None:
    st.session_state["market_analysis_pair_select"] = symbol
    st.session_state["market_analysis_tf_control"] = tf_label
    st.session_state["market_analysis_tf_radio"] = tf_label
    if trade_style:
        _set_current_trade_style(trade_style)
    st.session_state["trading_desk_view"] = "Signal Workspace"
    st.session_state["nav_choice"] = "Trading Desk"
    st.query_params["mdeskmode"] = "Signal Workspace"
    st.query_params["mtf"] = tf_label
    if mobile_layout:
        st.session_state["mobile_trading_desk_panel"] = "Signal"
        st.query_params["mdeskpanel"] = "Signal"
    st.rerun()


# ✅ LIVE CANDLE BUILDING FUNCTIONS
def _update_live_candle(symbol: str, timeframe: str, price: float, volume: float = 0):
    """Update the current candle being built with latest tick data."""
    if symbol not in st.session_state.live_candles:
        st.session_state.live_candles[symbol] = {}
    
    candle_key = timeframe
    now = time.time()
    
    # If no candle yet, initialize it
    if candle_key not in st.session_state.live_candles[symbol]:
        st.session_state.live_candles[symbol][candle_key] = {
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": volume,
            "last_update": now,
        }
    else:
        # Update existing candle
        candle = st.session_state.live_candles[symbol][candle_key]
        candle["high"] = max(candle["high"], price)
        candle["low"] = min(candle["low"], price)
        candle["close"] = price
        candle["volume"] += volume
        candle["last_update"] = now
        st.session_state.chart_stream_key += 1


def _get_live_candle(symbol: str, timeframe: str) -> dict:
    """Get the current candle being built."""
    if symbol in st.session_state.live_candles:
        if timeframe in st.session_state.live_candles[symbol]:
            return st.session_state.live_candles[symbol][timeframe]
    return None


def _feed_engine_to_live_candle(symbol: str, timeframe: str):
    """
    ✅ NEW: Feed real-time data from the market engine into live candle tracking.
    This creates the Binance-style candle building effect.
    """
    try:
        # Get latest tick price from engine
        tick = engine.get_latest_tick(symbol)
        last_price = tick.get("last_price")
        
        if last_price is not None and last_price > 0:
            # Update live candle with real price
            _update_live_candle(symbol, timeframe, float(last_price), volume=0)
    except Exception as e:
        pass  # Silent fail - don't disrupt the UI


def _merge_live_candle_with_history(df: pd.DataFrame, symbol: str, timeframe: str) -> pd.DataFrame:
    """Merge the live candle with historical data for smooth rendering."""
    df = df.copy()
    live_candle = _get_live_candle(symbol, timeframe)
    
    if live_candle is not None and not df.empty:
        # Update the last row with live data
        df_copy = df.copy()
        df_copy.iloc[-1, df_copy.columns.get_loc("open")] = live_candle["open"]
        df_copy.iloc[-1, df_copy.columns.get_loc("high")] = live_candle["high"]
        df_copy.iloc[-1, df_copy.columns.get_loc("low")] = live_candle["low"]
        df_copy.iloc[-1, df_copy.columns.get_loc("close")] = live_candle["close"]
        df_copy.iloc[-1, df_copy.columns.get_loc("volume")] = live_candle["volume"]
        return df_copy
    
    return df


def _searchable_pair_picker(label: str, key_prefix: str, default_symbol: str = None, *, show_caption: bool = True) -> str:
    pair_universe = _get_pair_universe()
    default_symbol = (default_symbol or DEFAULT_TRACKED_SYMBOLS[0]).upper()
    if default_symbol not in pair_universe:
        pair_universe = [default_symbol] + [symbol for symbol in pair_universe if symbol != default_symbol]

    search_key = f"{key_prefix}_pair_search"
    select_key = f"{key_prefix}_pair_select"
    search_query = st.text_input(
        "Search pair",
        value=st.session_state.get(search_key, ""),
        placeholder="BTC, EURUSD, USDJPY...",
        key=search_key,
    ).strip().upper()

    filtered_pairs = [symbol for symbol in pair_universe if search_query in symbol] if search_query else pair_universe
    if not filtered_pairs:
        filtered_pairs = pair_universe

    visible_pairs = filtered_pairs[:120]
    current_symbol = st.session_state.get(select_key, default_symbol)
    if current_symbol not in visible_pairs:
        current_symbol = visible_pairs[0]

    symbol = st.selectbox(
        label,
        visible_pairs,
        index=visible_pairs.index(current_symbol),
        key=select_key,
        help=f"Showing {len(visible_pairs)} of {len(filtered_pairs)} matches.",
    )
    if show_caption:
        st.caption(f"{len(filtered_pairs)} searchable pairs available.")
    return symbol

# ✅ STEP 2: SESSION STATE — must come before any st.* calls
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "otp_sent" not in st.session_state:
    st.session_state.otp_sent = False
if "temp_user" not in st.session_state:
    st.session_state.temp_user = {}
if "oauth_state" not in st.session_state:
    st.session_state.oauth_state = ""
if "awaiting_oauth" not in st.session_state:
    st.session_state.awaiting_oauth = False
if "oauth_returned" not in st.session_state:
    st.session_state.oauth_returned = False
if "pending_email" not in st.session_state:
    st.session_state.pending_email = ""
if "pending_username" not in st.session_state:
    st.session_state.pending_username = ""
if "password_reset_sent" not in st.session_state:
    st.session_state.password_reset_sent = False
if "password_reset_verified" not in st.session_state:
    st.session_state.password_reset_verified = False
if "password_reset_request" not in st.session_state:
    st.session_state.password_reset_request = {}
if "password_change_sent" not in st.session_state:
    st.session_state.password_change_sent = False
if "password_change_verified" not in st.session_state:
    st.session_state.password_change_verified = False
if "password_change_request" not in st.session_state:
    st.session_state.password_change_request = {}
if "auth_otp_context" not in st.session_state:
    st.session_state.auth_otp_context = ""
if "auth_notice" not in st.session_state:
    st.session_state.auth_notice = ""
if "otp_store" not in st.session_state:
    st.session_state.otp_store = {}
if "oauth_code" not in st.session_state:
    st.session_state.oauth_code = ""
if "oauth_code_state" not in st.session_state:
    st.session_state.oauth_code_state = ""
if "oauth_return_auth_view" not in st.session_state:
    st.session_state.oauth_return_auth_view = ""
if "broker_oauth_code" not in st.session_state:
    st.session_state.broker_oauth_code = ""
if "broker_oauth_state" not in st.session_state:
    st.session_state.broker_oauth_state = ""
if "broker_oauth_returned" not in st.session_state:
    st.session_state.broker_oauth_returned = False
if "pending_deriv_oauth_connection" not in st.session_state:
    st.session_state.pending_deriv_oauth_connection = {}
if "deriv_oauth_status_message" not in st.session_state:
    st.session_state.deriv_oauth_status_message = ""
if "deriv_oauth_status_tone" not in st.session_state:
    st.session_state.deriv_oauth_status_tone = "info"
if "auth_session_id" not in st.session_state:
    st.session_state.auth_session_id = ""
if "auth_session_token" not in st.session_state:
    st.session_state.auth_session_token = ""
if "auth_cookie_action" not in st.session_state:
    st.session_state.auth_cookie_action = {}
if "pending_signed_session" not in st.session_state:
    st.session_state.pending_signed_session = {}
if "_auth_entry_landing_seen" not in st.session_state:
    st.session_state._auth_entry_landing_seen = False
if "trading_desk_view" not in st.session_state:
    st.session_state.trading_desk_view = "Signal Workspace"
if "engine_started" not in st.session_state:
    st.session_state.engine_started = False
if "terminal_chart_api_started" not in st.session_state:
    st.session_state.terminal_chart_api_started = False
if "broker_balance_cache" not in st.session_state:
    st.session_state.broker_balance_cache = {}
if "broker_restore_state" not in st.session_state:
    st.session_state.broker_restore_state = {}
if "symbol_load_state" not in st.session_state:
    st.session_state.symbol_load_state = {}

# ✅ LIVE CANDLE TRACKING — for real-time candle building (Binance-style)
if "live_candles" not in st.session_state:
    st.session_state.live_candles = {}  # {symbol: {timeframe: {...current_candle_data...}}}
if "last_tick_time" not in st.session_state:
    st.session_state.last_tick_time = {}  # Track tick timestamps
if "chart_stream_key" not in st.session_state:
    st.session_state.chart_stream_key = 0  # Force chart rerender when data updates

# ✅ CHART DATA CACHING (prevent refresh flashing)
if "chart_cache" not in st.session_state:
    st.session_state.chart_cache = {}  # {symbol_tf: {"candles": [...], "last_time": ...}}

if "last_chart_update" not in st.session_state:
    st.session_state.last_chart_update = {}

# ✅ INDICATOR SETTINGS
if "chart_indicators" not in st.session_state:
    st.session_state.chart_indicators = {
        "moving_averages": {
            "enabled": True,
            "ema": [20, 50],
            "sma": []
        },
        "rsi": {"enabled": False, "period": 14},
        "macd": {"enabled": False, "fast": 12, "slow": 26, "signal": 9},
        "bollinger_bands": {"enabled": False, "period": 20, "std_dev": 2}
    }
else:
    st.session_state.chart_indicators.setdefault("moving_averages", {"enabled": True, "ema": [20, 50], "sma": []})
    st.session_state.chart_indicators.setdefault("rsi", {"enabled": False, "period": 14})
    st.session_state.chart_indicators.setdefault("macd", {"enabled": False, "fast": 12, "slow": 26, "signal": 9})
    st.session_state.chart_indicators.setdefault("bollinger_bands", {"enabled": False, "period": 20, "std_dev": 2})
    st.session_state.chart_indicators["moving_averages"].setdefault("enabled", True)
    st.session_state.chart_indicators["moving_averages"].setdefault("ema", [20, 50])
    st.session_state.chart_indicators["moving_averages"].setdefault("sma", [])
    st.session_state.chart_indicators["rsi"].setdefault("enabled", False)
    st.session_state.chart_indicators["rsi"].setdefault("period", 14)
    st.session_state.chart_indicators["macd"].setdefault("enabled", False)
    st.session_state.chart_indicators["macd"].setdefault("fast", 12)
    st.session_state.chart_indicators["macd"].setdefault("slow", 26)
    st.session_state.chart_indicators["macd"].setdefault("signal", 9)
    st.session_state.chart_indicators["bollinger_bands"].setdefault("enabled", False)
    st.session_state.chart_indicators["bollinger_bands"].setdefault("period", 20)
    st.session_state.chart_indicators["bollinger_bands"].setdefault("std_dev", 2)

# ✅ STEP 4: HANDLE GOOGLE REDIRECT
query_params = dict(st.query_params)


def _query_param_value(params: dict, name: str) -> str:
    value = params.get(name, "")
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value or "").strip()


def _clear_query_params(names: set[str]) -> None:
    try:
        params = dict(st.query_params)
    except Exception:
        return
    changed = False
    for name in names:
        if name in params:
            params.pop(name, None)
            changed = True
    if not changed:
        return
    try:
        st.query_params.clear()
        for key, value in params.items():
            st.query_params[key] = value
    except Exception:
        pass


deriv_oauth_token = _query_param_value(query_params, "deriv_oauth_token")
if deriv_oauth_token:
    deriv_oauth_account = _query_param_value(query_params, "deriv_oauth_account")
    deriv_oauth_currency = _query_param_value(query_params, "deriv_oauth_currency").upper()
    st.session_state.pending_deriv_oauth_connection = {
        "token": deriv_oauth_token,
        "account": deriv_oauth_account,
        "currency": deriv_oauth_currency,
        "state": _query_param_value(query_params, "deriv_oauth_state"),
        "source": "efikemma_deriv_callback",
        "attempted": False,
    }
    st.session_state.deriv_api_token = deriv_oauth_token
    st.session_state.synthetic_deriv_token_input = deriv_oauth_token
    st.session_state.nav_choice = "Synthetic Trade"
    st.session_state.trading_desk_view = "Synthetic Trade"
    st.session_state.deriv_oauth_status_tone = "info"
    st.session_state.deriv_oauth_status_message = (
        f"Deriv returned {deriv_oauth_account or 'an account'}"
        f"{f' in {deriv_oauth_currency}' if deriv_oauth_currency else ''}. Auto-connecting now..."
    )
    _clear_query_params(
        {
            "deriv_oauth_token",
            "deriv_oauth_account",
            "deriv_oauth_currency",
            "deriv_oauth_state",
            "deriv_oauth_auto_connect",
        }
    )

if "code" in query_params and "state" in query_params:
    incoming_state = query_params.get("state", "")
    if str(incoming_state).startswith("broker-oauth:"):
        st.session_state["broker_oauth_code"] = query_params.get("code", "")
        st.session_state["broker_oauth_state"] = incoming_state
        st.session_state["broker_oauth_returned"] = True
    else:
        if not st.session_state.get("oauth_code"):
            st.session_state["oauth_code"]       = query_params.get("code", "")
            st.session_state["oauth_code_state"] = incoming_state
        st.session_state["oauth_returned"] = True
        st.session_state["awaiting_oauth"] = True
    st.query_params.clear()


# -----------------------------------
# THEME — original colours, IDX dashboard layout/structure
# -----------------------------------
st.set_page_config(
    page_title="Finwise AI",
    page_icon=str(APP_LOGO_PATH) if APP_LOGO_PATH.exists() else "F",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* ══ APP SHELL ══ */
.stApp {
    background:
        radial-gradient(circle at top right, rgba(20, 220, 207, 0.08), transparent 24%),
        linear-gradient(180deg, #07121d 0%, #08131f 46%, #09141f 100%);
    color: #e8f4f8;
    overflow-x: hidden;
}
.main .block-container {
    max-width: 100%;
    overflow-x: hidden;
}
div[data-testid="column"] {
    min-width: 0 !important;
}

/* ══ SIDEBAR ══ */
[data-testid="stSidebar"] {
    background:
        radial-gradient(circle at top left, rgba(17, 228, 214, 0.08), transparent 18%),
        linear-gradient(180deg, #0a1724 0%, #0a1927 100%) !important;
    border-right: 1px solid rgba(255,255,255,0.05);
    box-shadow: inset -1px 0 0 rgba(255,255,255,0.02);
}
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span { color: #8ab4c8 !important; }

/* Sidebar logo block */
.sidebar-logo {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 0 22px;
    font-size: 20px; font-weight: 700; color: white;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    margin-bottom: 18px;
}
.sidebar-logo-icon {
    width: 34px; height: 34px; border-radius: 10px;
    background: linear-gradient(180deg, #1be7d6 0%, #0ed4c9 100%);
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; color: #0b1e2d; font-weight: 900;
    box-shadow: 0 10px 24px rgba(12, 198, 190, 0.2);
}
.nav-label { font-size: 14px; font-weight: 600; }

/* Sidebar nav items */
.nav-item {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 14px; border-radius: 10px;
    font-size: 14px; font-weight: 500;
    color: #8ab4c8; margin-bottom: 2px;
    cursor: default;
}
.nav-item.active {
    background: rgba(0,245,212,0.10);
    color: #00f5d4 !important;
    border-left: 3px solid #00f5d4;
    padding-left: 11px;
}
.nav-item .nav-icon { font-size: 16px; width: 20px; text-align:center; }

/* Sidebar bottom user badge */
.sidebar-user {
    margin-top: 24px;
    padding: 12px 14px;
    background: rgba(255,255,255,0.025);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 14px;
    font-size: 13px; color: #8ab4c8;
    display: flex; align-items: center; gap: 10px;
}
.sidebar-avatar {
    width: 32px; height: 32px; border-radius: 50%;
    background: linear-gradient(180deg, #1be7d6 0%, #0ed4c9 100%);
    color: #0b1e2d;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 14px; flex-shrink: 0;
    box-shadow: 0 8px 18px rgba(12, 198, 190, 0.16);
}

/* ══ TOP BAR ══ */
.top-bar {
    display: flex; align-items: center; justify-content: space-between;
    padding-bottom: 20px;
    border-bottom: 1px solid rgba(0,245,212,0.1);
    margin-bottom: 24px;
}
.top-bar-title { font-size: 26px; font-weight: 700; color: white; margin: 0; }
.top-bar-sub { font-size: 13px; color: #8ab4c8; margin-top: 3px; }
.top-bar-right { display: flex; align-items: center; gap: 12px; }
.top-bar-deploy {
    color: #7f9ab0;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.02em;
}
.live-badge {
    display: inline-flex; align-items: center; gap: 7px;
    background: rgba(18, 212, 197, 0.08);
    border: 1px solid rgba(18, 212, 197, 0.22);
    border-radius: 20px; padding: 5px 14px;
    font-size: 12px; color: #7de8db; font-weight: 700;
}
.live-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: #19dfd0; display: inline-block;
    box-shadow: 0 0 12px rgba(25, 223, 208, 0.8);
    animation: blink 1.4s ease-in-out infinite;
}
[data-testid="stStatusWidget"] {
    visibility: hidden;
    display: none;
}
.stPlotlyChart {
    min-height: 450px;
}
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.2} }

/* ══ STAT CARDS ROW ══ */
.stat-row {
    display: grid; grid-template-columns: repeat(3,1fr);
    gap: 14px; margin-bottom: 24px;
}
.stat-card {
    background: #0f2639;
    border: 1px solid rgba(0,245,212,0.12);
    border-radius: 14px; padding: 16px 18px;
    display: flex; align-items: center; gap: 14px;
}
.stat-icon-wrap {
    width: 46px; height: 46px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 20px; flex-shrink: 0;
}
.stat-text-label { font-size: 12px; color: #8ab4c8; margin-bottom: 3px; }
.stat-text-value { font-size: 22px; font-weight: 700; color: white; line-height: 1; }

/* ══ BUTTONS ══ */
.stButton > button,
.stFormSubmitButton > button,
[data-testid="stButton"] > button,
[data-testid="stFormSubmitButton"] > button,
[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-default"],
[data-testid="stLinkButton"] > a {
    background: linear-gradient(180deg, #19dfd0 0%, #09cbc0 100%) !important;
    color: #05202f !important;
    border: 1px solid rgba(25,223,208,0.18) !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    font-size: 14px !important;
    padding: 9px 22px !important;
    box-shadow: 0 12px 24px rgba(0,0,0,0.18) !important;
    transition: opacity 0.2s, transform 0.2s, border-color 0.2s !important;
}
.stButton > button *,
.stFormSubmitButton > button *,
[data-testid="stButton"] > button *,
[data-testid="stFormSubmitButton"] > button *,
[data-testid="stBaseButton-secondary"] *,
[data-testid="stBaseButton-primary"] *,
[data-testid="stBaseButton-default"] *,
[data-testid="stLinkButton"] > a * {
    color: inherit !important;
}
.stButton > button:hover,
.stFormSubmitButton > button:hover,
[data-testid="stButton"] > button:hover,
[data-testid="stFormSubmitButton"] > button:hover,
[data-testid="stBaseButton-secondary"]:hover,
[data-testid="stBaseButton-primary"]:hover,
[data-testid="stBaseButton-default"]:hover,
[data-testid="stLinkButton"] > a:hover {
    opacity: 0.94 !important;
    transform: translateY(-1px);
}
.stButton > button[kind="secondary"],
.stFormSubmitButton > button[kind="secondary"],
[data-testid="stButton"] > button[kind="secondary"],
[data-testid="stFormSubmitButton"] > button[kind="secondary"],
[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-default"] {
    background: rgba(12, 24, 38, 0.92) !important;
    color: #d5eef3 !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    box-shadow: none !important;
}
.stButton > button:disabled,
.stFormSubmitButton > button:disabled,
[data-testid="stButton"] > button:disabled,
[data-testid="stFormSubmitButton"] > button:disabled,
[data-testid="stBaseButton-secondary"]:disabled,
[data-testid="stBaseButton-primary"]:disabled,
[data-testid="stBaseButton-default"]:disabled {
    background: #1a3a52 !important;
    color: #4a7a94 !important;
}
[data-testid="stSidebar"] .stButton {
    margin-bottom: 8px;
}
[data-testid="stSidebar"] .stButton > button {
    justify-content: flex-start !important;
    min-height: 44px;
    background: transparent !important;
    color: #89a8ba !important;
    border: 1px solid rgba(255,255,255,0.05) !important;
    box-shadow: none !important;
}
[data-testid="stSidebar"] .stButton > button svg {
    width: 18px !important;
    height: 18px !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    color: white !important;
    border-color: rgba(25,223,208,0.18) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: linear-gradient(90deg, rgba(15, 192, 178, 0.3), rgba(17, 217, 203, 0.18)) !important;
    color: #ebffff !important;
    border-color: rgba(25,223,208,0.28) !important;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03), 0 10px 24px rgba(0,0,0,0.16) !important;
}

/* ══ SIGNAL CARD (original colours preserved) ══ */
.signal-card {
    background: #0f2639;
    border: 1px solid rgba(0,245,212,0.2);
    border-radius: 14px; padding: 20px; margin-bottom: 16px;
}
.sig-buy  { color: #26a69a; font-size: 28px; font-weight: 700; letter-spacing: 2px; }
.sig-sell { color: #ef5350; font-size: 28px; font-weight: 700; letter-spacing: 2px; }
.sig-hold { color: #ffc107; font-size: 28px; font-weight: 700; letter-spacing: 2px; }
.stat-label { color: #8ab4c8; font-size: 12px; }
.stat-val   { color: #e8f4f8; font-size: 15px; font-weight: 600; font-family: monospace; }

/* ══ FORM ELEMENTS ══ */
.stSelectbox > div > div {
    background: #0f2639 !important;
    border: 1px solid rgba(0,245,212,0.15) !important;
    border-radius: 10px !important; color: white !important;
}
.stTextInput > div > div > input {
    background: rgba(12, 27, 42, 0.92) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 12px !important; color: white !important;
    min-height: 44px !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    padding-left: 14px !important;
}
.stTextInput > div > div > input::placeholder {
    color: #5e7689 !important;
    opacity: 1 !important;
}
.stTextInput [data-baseweb="base-input"] {
    background: #1d2a38 !important;
    border: 1px solid rgba(238,244,248,0.88) !important;
    border-radius: 10px !important;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.02) !important;
}
.stNumberInput > div > div > input {
    background: rgba(12, 27, 42, 0.92) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 12px !important; color: white !important;
    min-height: 44px !important;
}
[data-baseweb="select"] > div {
    background: #0a2c42 !important;
    border: 1px solid rgba(12, 126, 162, 0.58) !important;
    border-radius: 10px !important;
    min-height: 44px !important;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.01) !important;
}
[data-baseweb="select"] span,
[data-baseweb="select"] div {
    color: #effbfd !important;
    font-size: 13px !important;
    font-weight: 700 !important;
}
div[data-baseweb="popover"] [role="listbox"] {
    background: #0d2232 !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    box-shadow: 0 18px 38px rgba(0,0,0,0.34) !important;
}
div[data-baseweb="popover"],
div[data-baseweb="popover"] > div,
div[data-baseweb="popover"] ul,
div[data-baseweb="popover"] li {
    background: #0d2232 !important;
    color: #e7f5fb !important;
}
div[data-baseweb="popover"] [role="option"] {
    color: #e7f5fb !important;
    background: transparent !important;
}
div[data-baseweb="popover"] [role="option"] *,
div[data-baseweb="popover"] li * {
    color: #e7f5fb !important;
}
div[data-baseweb="popover"] [role="option"]:hover,
div[data-baseweb="popover"] [role="option"][aria-selected="true"] {
    background: rgba(25,223,208,0.12) !important;
}
div[data-testid="stSegmentedControl"] {
    background: #0c1825 !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-radius: 10px !important;
    padding: 3px !important;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.02) !important;
}
div[data-testid="stSegmentedControl"] > div {
    gap: 4px !important;
}
div[data-testid="stSegmentedControl"] button {
    background: transparent !important;
    border: 1px solid transparent !important;
    color: #7d8e9b !important;
    border-radius: 6px !important;
    min-height: 28px !important;
    padding: 4px 10px !important;
    font-size: 11px !important;
    font-weight: 800 !important;
    box-shadow: none !important;
}
div[data-testid="stSegmentedControl"] button[aria-pressed="true"] {
    background: rgba(255, 84, 104, 0.08) !important;
    border-color: #ff5367 !important;
    color: #ff5367 !important;
    box-shadow: inset 0 0 0 1px rgba(255, 83, 103, 0.06) !important;
}
div[data-testid="stSegmentedControl"] button:hover {
    color: #c8d6df !important;
}
label[data-testid="stWidgetLabel"] p {
    color: #6f8ca0 !important;
    font-size: 11px !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
div[data-testid="stExpander"] {
    background: rgba(10, 24, 38, 0.72);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 18px;
    overflow: hidden;
    margin: 8px 0 18px;
}
div[data-testid="stExpander"] summary {
    font-weight: 700;
}

/* ══ HIDE DEFAULT STREAMLIT CHROME ══ */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
[data-testid="stHeader"] {
    background: transparent !important;
}
[data-testid="collapsedControl"] {
    display: flex !important;
    visibility: visible !important;
}
.block-container { padding-top: 1.5rem !important; max-width: 100% !important; }

/* ══ DIVIDER ══ */
hr { border-color: rgba(0,245,212,0.1) !important; }
.dashboard-rail {
    display: flex;
    flex-direction: column;
    gap: 16px;
}
.premium-rail-card {
    position: relative;
    overflow: hidden;
    background:
        radial-gradient(circle at top right, rgba(0,245,212,0.14), transparent 34%),
        linear-gradient(180deg, rgba(19,40,59,0.98) 0%, rgba(11,30,45,0.98) 100%);
    border: 1px solid rgba(0,245,212,0.14);
    border-radius: 24px;
    padding: 18px;
    box-shadow: 0 20px 44px rgba(0,0,0,0.26);
}
.premium-rail-card::after {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(145deg, rgba(255,255,255,0.05), transparent 42%);
    pointer-events: none;
}
.premium-rail-card > * {
    position: relative;
    z-index: 1;
}
.rail-kicker {
    color: #4a7a94;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.3px;
    text-transform: uppercase;
}
.rail-title {
    color: white;
    font-size: 21px;
    font-weight: 800;
    margin-top: 8px;
    line-height: 1.1;
}
.rail-copy {
    color: #8ab4c8;
    font-size: 12px;
    line-height: 1.6;
    margin-top: 8px;
}
.coach-stack,
.activity-stack {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-top: 16px;
}
.coach-note,
.activity-item,
.premium-empty-state,
.broker-balance,
.broker-meta-item {
    position: relative;
    z-index: 1;
    background: rgba(6,14,22,0.44);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 18px;
}
.coach-note {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 12px;
    padding: 14px;
}
.coach-note-index {
    min-width: 36px;
    height: 36px;
    border-radius: 12px;
    background: rgba(0,245,212,0.12);
    border: 1px solid rgba(0,245,212,0.18);
    color: #00f5d4;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    font-weight: 800;
}
.coach-note-text {
    color: #d9edf3;
    font-size: 13px;
    line-height: 1.6;
}
.broker-hero {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 14px;
    margin-top: 16px;
}
.broker-balance {
    padding: 16px;
    margin-top: 18px;
}
.broker-balance-value {
    color: white;
    font-size: 31px;
    font-weight: 800;
    line-height: 1;
    margin-top: 8px;
}
.broker-meta-grid {
    position: relative;
    z-index: 1;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
    margin-top: 14px;
}
.broker-meta-item {
    padding: 10px 12px;
}
.rail-label-sm {
    color: #4a7a94;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.85px;
    text-transform: uppercase;
}
.rail-value-md {
    color: white;
    font-size: 14px;
    font-weight: 700;
    margin-top: 6px;
}
.activity-item {
    padding: 14px;
}
.activity-top,
.activity-foot {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
}
.activity-foot {
    align-items: center;
    margin-top: 12px;
}
.activity-symbol {
    color: white;
    font-size: 15px;
    font-weight: 700;
}
.activity-meta {
    color: #8ab4c8;
    font-size: 12px;
    line-height: 1.5;
    margin-top: 4px;
}
.activity-pnl {
    font-size: 16px;
    font-weight: 800;
    text-align: right;
    white-space: nowrap;
}
.activity-status {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 6px 10px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.7px;
    text-transform: uppercase;
}
.activity-time {
    color: #6f93a6;
    font-size: 11px;
}
.premium-empty-state {
    padding: 16px;
}
.premium-empty-title {
    color: white;
    font-size: 15px;
    font-weight: 700;
}
.premium-empty-copy {
    color: #8ab4c8;
    font-size: 12px;
    line-height: 1.6;
    margin-top: 6px;
}
.market-summary-grid,
.market-overview-grid,
.market-live-grid {
    display: grid;
    gap: 12px;
}
.market-summary-grid {
    grid-template-columns: repeat(5, minmax(0, 1fr));
    margin: 10px 0 18px;
}
.market-summary-card,
.market-overview-card,
.market-live-card,
.market-upgrade-banner {
    position: relative;
    overflow: hidden;
    background:
        radial-gradient(circle at top right, rgba(25, 223, 208, 0.08), transparent 28%),
        linear-gradient(180deg, rgba(10, 23, 36, 0.98) 0%, rgba(8, 19, 31, 0.98) 100%);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: {chart_radius}px;
    box-shadow: 0 22px 48px rgba(0,0,0,0.22);
}
.market-summary-card {
    min-height: 108px;
    padding: 16px 18px;
}
.market-summary-card-volume {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 86px;
    gap: 12px;
    align-items: end;
}
.market-summary-kicker,
.market-overview-label,
.market-live-label,
.market-card-kicker {
    color: #5f7f93;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.market-summary-value {
    color: white;
    font-size: 24px;
    font-weight: 800;
    margin-top: 12px;
    letter-spacing: -0.02em;
}
.market-summary-value-small {
    color: white;
    font-size: 19px;
    font-weight: 800;
    margin-top: 12px;
    letter-spacing: -0.01em;
}
.market-summary-meta {
    color: #7f9ab0;
    font-size: 11px;
    margin-top: 5px;
}
.market-summary-delta {
    font-size: 12px;
    font-weight: 800;
    margin-top: 7px;
}
.market-summary-chart {
    width: 100%;
    height: 58px;
    align-self: center;
}
.market-overview-card,
.market-live-card {
    padding: 18px;
    margin-top: 4px;
}
.market-card-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 16px;
}
.market-card-title {
    color: white;
    font-size: 18px;
    font-weight: 800;
}
.market-card-sub {
    color: #7f9ab0;
    font-size: 12px;
    margin-top: 4px;
}
.market-live-hero {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 16px;
}
.market-live-hero-price {
    color: white;
    font-size: 28px;
    font-weight: 800;
    line-height: 1;
    text-align: right;
}
.market-live-hero-delta {
    font-size: 12px;
    font-weight: 800;
    margin-top: 6px;
    text-align: right;
}
.market-overview-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
}
.market-overview-item,
.market-live-item {
    background: rgba(10, 24, 38, 0.86);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 14px;
    padding: 12px 14px;
}
.market-overview-value {
    color: white;
    font-size: 15px;
    font-weight: 700;
    margin-top: 6px;
}
.market-live-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
}
.market-live-value {
    color: white;
    font-size: 17px;
    font-weight: 800;
    margin-top: 5px;
}
.market-live-sub {
    color: #7f9ab0;
    font-size: 11px;
    margin-top: 4px;
}
.market-controls-strip {
    margin: 8px 0 14px;
    padding: 2px 0 0;
}
.market-control-label {
    color: #8ca7b9;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin: 0 0 8px;
}
.market-live-svg {
    width: 100%;
    height: 44px;
    margin-top: 10px;
}
.market-spark-empty {
    color: #58778b;
    font-size: 11px;
    margin-top: 16px;
}
.market-upgrade-banner {
    display: grid;
    grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr);
    gap: 16px;
    align-items: center;
    padding: 20px 22px;
    margin-top: 20px;
}
.market-upgrade-title {
    color: white;
    font-size: 22px;
    font-weight: 800;
}
.market-upgrade-copy {
    color: #8aa5b7;
    font-size: 13px;
    line-height: 1.7;
    margin-top: 8px;
}
.market-upgrade-art {
    min-height: 124px;
    border-radius: 18px;
    border: 1px solid rgba(255,255,255,0.05);
    background:
        radial-gradient(circle at 22% 24%, rgba(25, 223, 208, 0.22), transparent 20%),
        radial-gradient(circle at 74% 30%, rgba(59, 151, 255, 0.18), transparent 18%),
        radial-gradient(circle at 62% 78%, rgba(25, 223, 208, 0.14), transparent 18%),
        linear-gradient(145deg, rgba(8, 24, 37, 0.9), rgba(5, 18, 29, 0.96));
}
.market-ticker-strip {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 10px;
    margin-top: 14px;
}
.market-ticker-item {
    background: rgba(10, 24, 38, 0.92);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 14px;
    padding: 10px 12px;
}
.market-ticker-symbol {
    color: white;
    font-size: 12px;
    font-weight: 800;
}
.market-ticker-price {
    color: #d9eef4;
    font-size: 12px;
    font-weight: 700;
    margin-top: 6px;
}
.market-ticker-change {
    font-size: 11px;
    font-weight: 800;
    margin-top: 4px;
}
@media (max-width: 1280px) {
    .market-summary-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .market-overview-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .market-ticker-strip {
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }
}
@media (max-width: 980px) {
    div[data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
        gap: 0.8rem !important;
    }
    div[data-testid="column"] {
        width: 100% !important;
        flex: 1 1 100% !important;
        min-width: 100% !important;
    }
    .market-live-grid,
    .market-upgrade-banner {
        grid-template-columns: 1fr;
    }
    .market-summary-card-volume,
    .market-live-hero {
        grid-template-columns: 1fr;
        flex-direction: column;
        align-items: flex-start;
    }
    .market-ticker-strip {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}
@media (max-width: 1100px) {
    .broker-hero,
    .activity-top,
    .activity-foot {
        flex-direction: column;
        align-items: flex-start;
    }
    .broker-meta-grid {
        grid-template-columns: 1fr;
    }
    .activity-pnl {
        text-align: left;
    }
}
@media (max-width: 760px) {
    .block-container {
        padding-top: 1rem !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
        padding-bottom: 7.2rem !important;
    }
    [data-testid="stSidebar"] {
        min-width: min(82vw, 320px) !important;
        max-width: min(82vw, 320px) !important;
    }
    .sidebar-logo {
        padding: 4px 0 16px;
        margin-bottom: 14px;
        font-size: 18px;
    }
    .sidebar-logo-icon {
        width: 30px;
        height: 30px;
        border-radius: 9px;
        font-size: 16px;
    }
    .top-bar {
        flex-direction: column;
        align-items: flex-start;
        gap: 12px;
        padding-bottom: 16px;
        margin-bottom: 18px;
    }
    .top-bar-title {
        font-size: 22px;
        line-height: 1.1;
    }
    .top-bar-sub {
        font-size: 12px;
        line-height: 1.5;
        max-width: 100%;
    }
    .top-bar-right {
        width: 100%;
        justify-content: space-between;
        gap: 8px;
        flex-wrap: wrap;
    }
    .top-bar-deploy,
    .live-badge {
        font-size: 11px;
    }
    div[data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
        gap: 0.8rem !important;
    }
    div[data-testid="column"] {
        width: 100% !important;
        flex: 1 1 100% !important;
        min-width: 100% !important;
    }
    div[data-testid="stSegmentedControl"] > div {
        flex-wrap: wrap !important;
    }
    div[data-testid="stSegmentedControl"] button {
        flex: 1 0 calc(25% - 4px) !important;
        min-height: 30px !important;
        font-size: 10px !important;
        padding: 4px 8px !important;
    }
    [data-testid="stTabs"] [role="tablist"] {
        overflow-x: auto;
        scrollbar-width: none;
        gap: 6px;
    }
    [data-testid="stTabs"] [role="tablist"]::-webkit-scrollbar {
        display: none;
    }
    [data-testid="stTabs"] [role="tab"] {
        white-space: nowrap;
        min-width: max-content;
    }
    .market-control-label {
        margin-bottom: 6px;
    }
    div[data-testid="stExpander"] {
        margin: 6px 0 12px;
    }
    .mobile-island-nav {
        position: fixed;
        left: 0;
        right: 0;
        bottom: calc(env(safe-area-inset-bottom) + 0.72rem);
        z-index: 10030;
        display: flex;
        justify-content: center;
        pointer-events: none;
        padding: 0 0.72rem;
    }
    .mobile-island-nav__rail {
        position: relative;
        isolation: isolate;
        overflow: hidden;
        pointer-events: auto;
        width: min(96vw, 31rem);
        display: grid;
        grid-template-columns: repeat(var(--mobile-nav-count, 5), minmax(0, 1fr));
        align-items: center;
        gap: 0.2rem;
        padding: 0.46rem;
        border-radius: 2rem;
        background:
            linear-gradient(180deg, rgba(255,255,255,0.16), rgba(255,255,255,0.03)),
            linear-gradient(135deg, rgba(12, 28, 42, 0.88), rgba(6, 14, 25, 0.76));
        border: 1px solid rgba(206, 255, 250, 0.14);
        box-shadow:
            0 28px 58px rgba(0,0,0,0.46),
            inset 0 1px 0 rgba(255,255,255,0.14),
            inset 0 -1px 0 rgba(255,255,255,0.03),
            0 0 42px rgba(25,223,208,0.10);
        backdrop-filter: blur(26px) saturate(1.45);
        -webkit-backdrop-filter: blur(26px) saturate(1.45);
    }
    .mobile-island-nav__rail::before {
        content: "";
        position: absolute;
        inset: 1px;
        border-radius: inherit;
        background: linear-gradient(180deg, rgba(255,255,255,0.11), rgba(255,255,255,0));
        opacity: 0.82;
        pointer-events: none;
        z-index: -1;
    }
    .mobile-island-nav__rail::after {
        content: "";
        position: absolute;
        left: 12%;
        right: 12%;
        top: -42%;
        height: 88%;
        border-radius: 999px;
        background: radial-gradient(circle, rgba(95,255,239,0.26), rgba(95,255,239,0.02) 64%, transparent 74%);
        filter: blur(18px);
        opacity: 0.92;
        pointer-events: none;
        z-index: -1;
        animation: mobileIslandFloat 8s ease-in-out infinite;
    }
    .mobile-island-nav__item {
        position: relative;
        overflow: hidden;
        min-width: 0;
        min-height: 3.2rem;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 0.22rem;
        border-radius: 1.32rem;
        color: #9cb4c7 !important;
        text-decoration: none !important;
        transition: transform 180ms ease, color 180ms ease, background 180ms ease, box-shadow 180ms ease;
    }
    .mobile-island-nav__item::before {
        content: "";
        position: absolute;
        inset: 1px;
        border-radius: inherit;
        background: linear-gradient(135deg, rgba(255,255,255,0.12), rgba(255,255,255,0.01));
        opacity: 0;
        transition: opacity 180ms ease;
    }
    .mobile-island-nav__item:hover {
        transform: translateY(-1px);
        color: #d8fffb !important;
        background: rgba(255,255,255,0.04);
    }
    .mobile-island-nav__item:hover::before,
    .mobile-island-nav__item.is-active::before {
        opacity: 1;
    }
    .mobile-island-nav__item.is-active {
        color: #eaffff !important;
        background:
            radial-gradient(circle at top, rgba(64,255,237,0.28), transparent 58%),
            linear-gradient(180deg, rgba(25,223,208,0.26), rgba(16,54,67,0.42));
        box-shadow:
            inset 0 0 0 1px rgba(89,249,232,0.26),
            0 10px 26px rgba(0,0,0,0.18),
            0 0 24px rgba(73,248,232,0.14);
    }
    .mobile-island-nav__item.is-active::after {
        content: "";
        position: absolute;
        left: 18%;
        right: 18%;
        bottom: 0;
        height: 2px;
        border-radius: 999px;
        background: linear-gradient(90deg, transparent, rgba(95,255,239,0.95), transparent);
    }
    .mobile-island-nav__icon {
        position: relative;
        width: 1.18rem;
        height: 1.18rem;
        display: inline-flex;
        align-items: center;
        justify-content: center;
    }
    .mobile-island-nav__icon::before {
        content: "";
        position: absolute;
        inset: -0.34rem;
        border-radius: 999px;
        background: radial-gradient(circle, rgba(96,255,241,0.18), transparent 72%);
        opacity: 0;
        transition: opacity 180ms ease;
    }
    .mobile-island-nav__item.is-active .mobile-island-nav__icon::before {
        opacity: 1;
    }
    .mobile-island-nav__icon svg {
        width: 1.12rem;
        height: 1.12rem;
        fill: none;
        stroke: currentColor;
        stroke-width: 1.8;
        stroke-linecap: round;
        stroke-linejoin: round;
    }
    .mobile-island-nav__label {
        max-width: 100%;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: 0.58rem;
        font-weight: 850;
        line-height: 1;
        letter-spacing: 0.01em;
    }
    @keyframes mobileIslandFloat {
        0%, 100% {
            transform: translateX(-3%) translateY(0);
            opacity: 0.88;
        }
        50% {
            transform: translateX(4%) translateY(8%);
            opacity: 1;
        }
    }
}
@media (max-width: 540px) {
    .top-bar-title {
        font-size: 20px;
    }
    .top-bar-right {
        align-items: flex-start;
    }
    div[data-testid="stSegmentedControl"] button {
        flex-basis: calc(33.333% - 4px) !important;
    }
    .mobile-island-nav__rail {
        width: min(96vw, 27rem);
        border-radius: 1.72rem;
        padding: 0.38rem;
        gap: 0.12rem;
    }
    .mobile-island-nav__item {
        min-height: 3.02rem;
        border-radius: 1.16rem;
    }
    .mobile-island-nav__label {
        font-size: 0.53rem;
    }
}
@media (min-width: 761px) {
    .mobile-island-nav {
        display: none !important;
    }
}
</style>
""", unsafe_allow_html=True)

if APP_LOGO_DATA_URI:
    st.markdown(
        f"""
        <style>
        .sidebar-logo-icon img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            border-radius: inherit;
            display: block;
        }}
        .top-bar-right::before {{
            content: "";
            width: 34px;
            height: 34px;
            border-radius: 12px;
            flex: 0 0 auto;
            display: inline-block;
            background:
                linear-gradient(180deg, rgba(27,231,214,0.14) 0%, rgba(14,212,201,0.06) 100%),
                url('{APP_LOGO_DATA_URI}') center / cover no-repeat;
            border: 1px solid rgba(27,231,214,0.18);
            box-shadow: 0 10px 24px rgba(12, 198, 190, 0.14);
        }}
        .brand-watermark {{
            position: fixed;
            right: 18px;
            bottom: 18px;
            width: 54px;
            height: 54px;
            opacity: 0.18;
            pointer-events: none;
            z-index: 998;
            filter: drop-shadow(0 10px 24px rgba(0,0,0,0.32));
        }}
        .brand-watermark img {{
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: block;
        }}
        @media (max-width: 700px) {{
            .top-bar-right::before {{
                width: 30px;
                height: 30px;
                border-radius: 10px;
            }}
            .brand-watermark {{
                width: 42px;
                height: 42px;
                right: 12px;
                bottom: 12px;
            }}
        }}
        </style>
        <div class="brand-watermark"><img src="{APP_LOGO_DATA_URI}" alt="Finwise logo" /></div>
        """,
        unsafe_allow_html=True,
    )

# -----------------------------------
# DATABASE
# -----------------------------------
conn   = connect_database("finwise.db")
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, email TEXT, phone TEXT, referrals INTEGER DEFAULT 0, premium INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS usage (username TEXT, day TEXT, used INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS expenses (username TEXT, amount REAL, category TEXT, day TEXT)")
cursor.execute("""
CREATE TABLE IF NOT EXISTS otp_table (
    username TEXT,
    code TEXT,
    expiry REAL
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS pending_users (
    username TEXT PRIMARY KEY,
    password TEXT,
    email TEXT,
    phone TEXT,
    created_at REAL,
    expires_at REAL
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS gmail_oauth_state (
    state TEXT PRIMARY KEY,
    pending_username TEXT,
    code_verifier TEXT,
    created_at REAL,
    expires_at REAL
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS app_runtime_tokens (
    token_name TEXT PRIMARY KEY,
    token_payload TEXT,
    updated_at REAL
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS login_attempts (
    username TEXT PRIMARY KEY,
    failed_count INTEGER DEFAULT 0,
    locked_until REAL DEFAULT 0,
    updated_at REAL
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_sessions (
    session_id TEXT PRIMARY KEY,
    username TEXT,
    session_secret_hash TEXT,
    created_at REAL,
    last_seen_at REAL,
    expires_at REAL,
    remember_me INTEGER DEFAULT 1,
    user_agent TEXT,
    ip_address TEXT,
    revoked_at REAL DEFAULT 0
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS trade_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    broker_name TEXT,
    account_alias TEXT,
    source TEXT,
    status TEXT,
    symbol TEXT,
    timeframe TEXT,
    side TEXT,
    confidence REAL DEFAULT 0,
    quantity REAL DEFAULT 0,
    notional_usd REAL DEFAULT 0,
    entry_price REAL DEFAULT 0,
    exit_price REAL DEFAULT 0,
    stop_loss REAL DEFAULT 0,
    take_profit REAL DEFAULT 0,
    fee_paid REAL DEFAULT 0,
    pnl_usd REAL DEFAULT 0,
    pnl_pct REAL DEFAULT 0,
    regime TEXT,
    setup_quality TEXT,
    risk_reward_ratio REAL DEFAULT 0,
    notes TEXT,
    opened_at TEXT,
    closed_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

def _ensure_users_table_columns():
    cursor.execute("PRAGMA table_info(users)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    required_columns = {
        "notification_whatsapp": "INTEGER DEFAULT 0",
        "notification_telegram": "INTEGER DEFAULT 0",
        "telegram_chat_id": "TEXT DEFAULT ''",
        "notify_buy_signals": "INTEGER DEFAULT 1",
        "notify_sell_signals": "INTEGER DEFAULT 1",
        "notify_signal_updates": "INTEGER DEFAULT 0",
        "notify_high_confidence_only": "INTEGER DEFAULT 0",
        "notify_market_digest": "INTEGER DEFAULT 1",
        "security_authenticator_2fa": "INTEGER DEFAULT 0",
        "security_sms_verification": "INTEGER DEFAULT 1",
        "security_login_alerts": "INTEGER DEFAULT 1",
    }
    for column_name, definition in required_columns.items():
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} {definition}")

_ensure_users_table_columns()
conn.commit()
ensure_broker_oauth_tables()

# -----------------------------------
# STRIPE
# -----------------------------------
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

def create_checkout_session():
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "Premium Subscription"},
                "unit_amount": 800,
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=os.getenv("SUCCESS_URL", "YOUR_SUCCESS_URL"),
        cancel_url=os.getenv("CANCEL_URL",   "YOUR_CANCEL_URL"),
    )
    return session.url

# -----------------------------------
# SECURITY
# -----------------------------------
def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())

def verify_password(password, hashed):
    try:
        if isinstance(hashed, str):
            hashed = hashed.encode()
        # Guard: bcrypt hashes always start with $2b$ or $2a$
        if not (hashed.startswith(b"$2b$") or hashed.startswith(b"$2a$")):
            return False
        return bcrypt.checkpw(password.encode(), hashed)
    except ValueError:
        return False
    except Exception:
        return False

# OTP
# -----------------------------------
SCOPES = ["https://mail.google.com/"]
OTP_TTL_SECONDS = max(60, int(os.getenv("FINWISE_OTP_TTL_SECONDS", "600") or 600))
PENDING_USER_TTL_SECONDS = max(300, int(os.getenv("FINWISE_PENDING_USER_TTL_SECONDS", "1800") or 1800))
GMAIL_OAUTH_STATE_TTL_SECONDS = max(300, int(os.getenv("FINWISE_GMAIL_OAUTH_STATE_TTL_SECONDS", "900") or 900))
MAX_LOGIN_ATTEMPTS = max(1, int(os.getenv("FINWISE_MAX_LOGIN_ATTEMPTS", "5") or 5))
LOGIN_LOCK_MINUTES = max(1, int(os.getenv("FINWISE_LOGIN_LOCK_MINUTES", "15") or 15))


def _cleanup_auth_records(now: float = None):
    now = time.time() if now is None else now
    try:
        cursor.execute("DELETE FROM otp_table WHERE expiry < ?", (now,))
        cursor.execute("DELETE FROM pending_users WHERE expires_at < ?", (now,))
        cursor.execute("DELETE FROM gmail_oauth_state WHERE expires_at < ?", (now,))
        cursor.execute(
            "DELETE FROM login_attempts WHERE COALESCE(locked_until, 0) < ? AND updated_at < ?",
            (now, now - 86400),
        )
        conn.commit()
        return True
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        if is_database_locked_error(exc):
            return False
        raise


def password_meets_policy(password: str):
    if len(password or "") < 8:
        return False, "Password must be at least 8 characters long."
    if not any(ch.isalpha() for ch in password):
        return False, "Password must include at least one letter."
    if not any(ch.isdigit() for ch in password):
        return False, "Password must include at least one number."
    return True, ""


def generate_otp(username):
    _cleanup_auth_records()
    otp = str(random.randint(100000, 999999))
    expiry = time.time() + OTP_TTL_SECONDS
    cursor.execute("DELETE FROM otp_table WHERE username = ?", (username,))
    cursor.execute(
        "INSERT INTO otp_table (username, code, expiry) VALUES (?, ?, ?)",
        (username, otp, expiry),
    )
    conn.commit()
    return otp


def verify_otp(username, otp):
    _cleanup_auth_records()
    cursor.execute(
        "SELECT code, expiry FROM otp_table WHERE username = ? ORDER BY expiry DESC LIMIT 1",
        (username,),
    )
    row = cursor.fetchone()
    if not row:
        return False
    stored_code, expiry = row
    if time.time() > float(expiry or 0):
        cursor.execute("DELETE FROM otp_table WHERE username = ?", (username,))
        conn.commit()
        return False
    if str(stored_code) == str(otp):
        cursor.execute("DELETE FROM otp_table WHERE username = ?", (username,))
        conn.commit()
        return True
    return False


def save_pending_user(username, pw_hash, email, phone):
    _cleanup_auth_records()
    if isinstance(pw_hash, bytes):
        pw_hash = pw_hash.decode()
    now = time.time()
    cursor.execute(
        """
        INSERT INTO pending_users (
            username, password, email, phone, created_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            password=excluded.password,
            email=excluded.email,
            phone=excluded.phone,
            created_at=excluded.created_at,
            expires_at=excluded.expires_at
        """,
        (username, pw_hash, email, phone, now, now + PENDING_USER_TTL_SECONDS),
    )
    conn.commit()


def load_pending_user(username: str = "", oauth_state: str = ""):
    _cleanup_auth_records()
    now = time.time()
    if oauth_state:
        cursor.execute(
            """
            SELECT p.username, p.password, p.email, p.phone
            FROM pending_users p
            JOIN gmail_oauth_state g ON g.pending_username = p.username
            WHERE g.state = ? AND p.expires_at >= ? AND g.expires_at >= ?
            LIMIT 1
            """,
            (oauth_state, now, now),
        )
        row = cursor.fetchone()
        if row:
            return {"username": row[0], "password": row[1], "email": row[2], "phone": row[3]}
    if not username:
        return None
    cursor.execute(
        "SELECT username, password, email, phone FROM pending_users WHERE username = ? AND expires_at >= ?",
        (username, now),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {"username": row[0], "password": row[1], "email": row[2], "phone": row[3]}


def clear_pending_user(username: str = "", oauth_state: str = ""):
    if oauth_state and not username:
        pending = load_pending_user(oauth_state=oauth_state)
        username = (pending or {}).get("username", "")
    if username:
        cursor.execute("DELETE FROM pending_users WHERE username = ?", (username,))
        conn.commit()


def save_gmail_oauth_state(state: str, code_verifier: str, pending_username: str = ""):
    _cleanup_auth_records()
    now = time.time()
    cursor.execute(
        """
        INSERT INTO gmail_oauth_state (
            state, pending_username, code_verifier, created_at, expires_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(state) DO UPDATE SET
            pending_username=excluded.pending_username,
            code_verifier=excluded.code_verifier,
            created_at=excluded.created_at,
            expires_at=excluded.expires_at
        """,
        (state, pending_username, code_verifier, now, now + GMAIL_OAUTH_STATE_TTL_SECONDS),
    )
    conn.commit()


def load_gmail_oauth_state(state: str):
    _cleanup_auth_records()
    if not state:
        return None
    cursor.execute(
        """
        SELECT state, pending_username, code_verifier, created_at, expires_at
        FROM gmail_oauth_state
        WHERE state = ?
        LIMIT 1
        """,
        (state,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "state": row[0],
        "pending_username": row[1],
        "code_verifier": row[2],
        "created_at": row[3],
        "expires_at": row[4],
    }


def clear_gmail_oauth_state(state: str):
    if not state:
        return
    cursor.execute("DELETE FROM gmail_oauth_state WHERE state = ?", (state,))
    conn.commit()


def save_app_token_payload(token_name: str, payload: dict):
    cursor.execute(
        """
        INSERT INTO app_runtime_tokens (token_name, token_payload, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(token_name) DO UPDATE SET
            token_payload=excluded.token_payload,
            updated_at=excluded.updated_at
        """,
        (token_name, json.dumps(payload or {}), time.time()),
    )
    conn.commit()


def load_app_token_payload(token_name: str):
    cursor.execute(
        "SELECT token_payload FROM app_runtime_tokens WHERE token_name = ? LIMIT 1",
        (token_name,),
    )
    row = cursor.fetchone()
    if row and row[0]:
        try:
            return json.loads(row[0])
        except Exception:
            return None
    return None


def get_login_lock_message(username: str):
    if not username:
        return ""
    _cleanup_auth_records()
    cursor.execute(
        "SELECT failed_count, locked_until FROM login_attempts WHERE username = ? LIMIT 1",
        (username,),
    )
    row = cursor.fetchone()
    if not row:
        return ""
    locked_until = float(row[1] or 0)
    if locked_until <= time.time():
        return ""
    remaining_minutes = max(1, math.ceil((locked_until - time.time()) / 60))
    return f"Too many login attempts. Try again in about {remaining_minutes} minute(s)."


def record_login_failure(username: str):
    if not username:
        return
    now = time.time()
    cursor.execute(
        "SELECT failed_count, locked_until FROM login_attempts WHERE username = ? LIMIT 1",
        (username,),
    )
    row = cursor.fetchone()
    failed_count = int((row[0] if row else 0) or 0) + 1
    locked_until = float((row[1] if row else 0) or 0)
    if failed_count >= MAX_LOGIN_ATTEMPTS:
        locked_until = now + (LOGIN_LOCK_MINUTES * 60)
    cursor.execute(
        """
        INSERT INTO login_attempts (username, failed_count, locked_until, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            failed_count=excluded.failed_count,
            locked_until=excluded.locked_until,
            updated_at=excluded.updated_at
        """,
        (username, failed_count, locked_until, now),
    )
    conn.commit()


def clear_login_failures(username: str):
    if not username:
        return
    cursor.execute("DELETE FROM login_attempts WHERE username = ?", (username,))
    conn.commit()


def load_registered_user(username: str, email: str = ""):
    normalized_username = str(username or "").strip()
    normalized_email = str(email or "").strip()
    if not normalized_username:
        return None
    if normalized_email:
        cursor.execute(
            """
            SELECT username, password, email, phone
            FROM users
            WHERE LOWER(username) = LOWER(?)
              AND LOWER(COALESCE(email, '')) = LOWER(?)
            LIMIT 1
            """,
            (normalized_username, normalized_email),
        )
    else:
        cursor.execute(
            """
            SELECT username, password, email, phone
            FROM users
            WHERE LOWER(username) = LOWER(?)
            LIMIT 1
            """,
            (normalized_username,),
        )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "username": row[0],
        "password": row[1],
        "email": row[2] or "",
        "phone": row[3] or "",
    }


def authenticate_registered_user(username: str, password: str):
    account = load_registered_user(username)
    if not account:
        return None
    if not verify_password(password, account["password"]):
        return None
    return account


def create_registered_user(username: str, password_hash: str, email: str, phone: str = ""):
    normalized_username = str(username or "").strip()
    normalized_password = str(password_hash or "").strip()
    normalized_email = str(email or "").strip()
    normalized_phone = str(phone or "").strip()

    if not normalized_username:
        raise ValueError("Username is required.")
    if not normalized_password:
        raise ValueError("Password hash is required.")
    if not normalized_email:
        raise ValueError("Email is required.")

    cursor.execute(
        "INSERT INTO users (username, password, email, phone) VALUES (?, ?, ?, ?)",
        (normalized_username, normalized_password, normalized_email, normalized_phone),
    )
    conn.commit()
    return {
        "username": normalized_username,
        "password": normalized_password,
        "email": normalized_email,
        "phone": normalized_phone,
    }


def update_user_password(username: str, new_password: str):
    password_hash = hash_password(new_password)
    if isinstance(password_hash, bytes):
        password_hash = password_hash.decode()
    cursor.execute(
        "UPDATE users SET password = ? WHERE username = ?",
        (password_hash, username),
    )
    conn.commit()


def clear_password_reset_state():
    st.session_state.password_reset_sent = False
    st.session_state.password_reset_verified = False
    st.session_state.password_reset_request = {}
    if st.session_state.get("auth_otp_context") == "password_reset":
        st.session_state.auth_otp_context = ""
        st.session_state.pending_username = ""
        st.session_state.pending_email = ""


def clear_password_change_state():
    st.session_state.password_change_sent = False
    st.session_state.password_change_verified = False
    st.session_state.password_change_request = {}
    if st.session_state.get("auth_otp_context") == "password_change":
        st.session_state.auth_otp_context = ""
        st.session_state.pending_username = ""
        st.session_state.pending_email = ""


# -----------------------------------
# SIGNED SESSIONS
# -----------------------------------
SESSION_COOKIE_NAME = str(os.getenv("FINWISE_SESSION_COOKIE_NAME", "finwise_session")).strip() or "finwise_session"
SHORT_SESSION_HOURS = max(1, int(os.getenv("FINWISE_SHORT_SESSION_HOURS", "12") or 12))
REMEMBER_SESSION_DAYS = max(1, int(os.getenv("FINWISE_REMEMBER_SESSION_DAYS", "14") or 14))
SESSION_TOUCH_INTERVAL_SECONDS = max(60, int(os.getenv("FINWISE_SESSION_TOUCH_INTERVAL_SECONDS", "300") or 300))


def _session_secret() -> str:
    secret = str(
        os.getenv("FINWISE_SESSION_SECRET")
        or os.getenv("SESSION_SECRET")
        or ""
    ).strip()
    if secret:
        return secret
    if is_production_environment():
        raise RuntimeError("FINWISE_SESSION_SECRET must be configured in production.")
    return hashlib.sha256(str(Path(__file__).resolve()).encode()).hexdigest()


def _session_key_hash(session_key: str) -> str:
    return hashlib.sha256(session_key.encode()).hexdigest()


def _session_signature(session_id: str, session_key: str) -> str:
    message = f"{session_id}.{session_key}".encode()
    return hmac.new(_session_secret().encode(), message, hashlib.sha256).hexdigest()


def _build_session_token(session_id: str, session_key: str) -> str:
    return f"{session_id}.{session_key}.{_session_signature(session_id, session_key)}"


def _parse_session_token(token: str):
    if not token:
        return None
    parts = str(token).strip().split(".")
    if len(parts) != 3:
        return None
    session_id, session_key, signature = parts
    expected = _session_signature(session_id, session_key)
    if not hmac.compare_digest(signature, expected):
        return None
    return session_id, session_key


def _queue_auth_cookie(value: str = "", expires_at: float = 0, clear: bool = False):
    st.session_state.auth_cookie_action = {
        "name": SESSION_COOKIE_NAME,
        "value": value or "",
        "expires_at": float(expires_at or 0),
        "clear": bool(clear),
    }


def _clear_auth_identity():
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.auth_session_id = ""
    st.session_state.auth_session_token = ""
    st.session_state.pending_signed_session = {}
    st.session_state.auth_view = "landing"
    st.session_state._auth_entry_landing_seen = False


def _get_pending_signed_session() -> dict[str, str]:
    pending = st.session_state.get("pending_signed_session") or {}
    username = str(pending.get("username", "") or "").strip()
    session_id = str(pending.get("session_id", "") or "").strip()
    session_token = str(pending.get("session_token", "") or "").strip()
    if not username or not session_id or not session_token:
        return {}
    return {
        "username": username,
        "session_id": session_id,
        "session_token": session_token,
    }


def _resume_pending_signed_session(*, nav_choice: str = "Dashboard") -> bool:
    pending = _get_pending_signed_session()
    if not pending:
        return False
    st.session_state.logged_in = True
    st.session_state.username = pending["username"]
    st.session_state.auth_session_id = pending["session_id"]
    st.session_state.auth_session_token = pending["session_token"]
    if not str(st.session_state.get("nav_choice", "") or "").strip():
        st.session_state.nav_choice = nav_choice
    st.session_state.login_notice = f"Signed in as {pending['username']}"
    st.session_state.pending_signed_session = {}
    st.session_state.auth_view = "landing"
    st.session_state._auth_entry_landing_seen = True
    return True


def _render_saved_session_prompt(*, button_key: str):
    pending = _get_pending_signed_session()
    if not pending:
        return
    username = pending["username"]
    st.markdown(
        f"""
        <div style="
            margin:0 0 0.9rem;
            padding:0.92rem 1rem;
            border-radius:18px;
            border:1px solid rgba(24, 223, 207, 0.16);
            background:rgba(8, 18, 33, 0.76);
            box-shadow:0 16px 34px rgba(0, 0, 0, 0.22);
            color:rgba(236, 244, 255, 0.94);
        ">
            <div style="font-weight:700; font-size:0.98rem; margin-bottom:0.28rem;">Saved session found</div>
            <div style="font-size:0.9rem; line-height:1.5; color:rgba(210, 223, 240, 0.84);">
                Continue as <strong>{escape(username)}</strong> without entering your password again,
                or choose Login/Register to use another account.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button(f"Continue as {username}", key=button_key, use_container_width=True):
        if _resume_pending_signed_session():
            st.rerun()


def _consume_transient_query_param(name: str) -> str:
    try:
        raw_value = str(st.query_params.get(name, "") or "").strip()
    except Exception:
        raw_value = ""
    if not raw_value:
        return ""
    try:
        params = dict(st.query_params)
    except Exception:
        params = {}
    if name in params:
        params.pop(name, None)
        try:
            st.query_params.clear()
            for key, value in params.items():
                st.query_params[key] = value
        except Exception:
            pass
    return raw_value


def _render_mobile_auth_landing(hero_logo: str, *, auth_view: str = "landing") -> None:
    pending = _get_pending_signed_session()
    login_href = build_query_href(viewport="mobile", auth="login")
    register_href = build_query_href(viewport="mobile", auth="register")
    resume_href = build_query_href(viewport="mobile", resume_session="1")
    login_active = " is-active" if auth_view == "login" else ""
    register_active = " is-active" if auth_view == "register" else ""
    shell_muted = " is-auth-open" if auth_view != "landing" else ""
    resume_markup = ""
    if pending:
        resume_markup = f"""
        <div class="fw-mobile-auth-return">
            <div>
                <div class="fw-mobile-auth-return-label">Saved Session</div>
                <div class="fw-mobile-auth-return-copy">Continue as {escape(pending["username"])} without typing your password again.</div>
            </div>
            <a class="fw-mobile-auth-return-btn" href="{escape(resume_href, quote=True)}" target="_self">Continue</a>
        </div>
        """

    st.html(
        dedent(
            f"""
        <style>
        .public-page-label {{
            display: none !important;
        }}
        .fw-mobile-auth-shell {{
            position: relative;
            overflow: hidden;
            max-width: 29rem;
            border-radius: 1.75rem;
            padding: 0.96rem 0.92rem 0.92rem;
            margin: 0.25rem auto 0.55rem;
            border: 1px solid rgba(34,231,202,0.14);
            background:
                radial-gradient(circle at 12% 14%, rgba(34,231,202,0.18), transparent 20%),
                radial-gradient(circle at 84% 8%, rgba(53,214,255,0.14), transparent 26%),
                radial-gradient(circle at 52% 78%, rgba(122,96,255,0.10), transparent 24%),
                linear-gradient(180deg, rgba(11,18,30,0.96) 0%, rgba(8,14,24,0.98) 100%);
            box-shadow: 0 22px 50px rgba(0,0,0,0.32);
            transition: filter 0.18s ease, transform 0.18s ease, opacity 0.18s ease;
        }}
        .fw-mobile-auth-shell.is-auth-open {{
            filter: blur(4px);
            transform: scale(0.985);
            opacity: 0.66;
        }}
        .fw-mobile-auth-shell::before {{
            content: "";
            position: absolute;
            inset: auto -18% -18% auto;
            width: 10rem;
            height: 10rem;
            border-radius: 999px;
            background: radial-gradient(circle, rgba(34,231,202,0.14), transparent 68%);
            filter: blur(10px);
            pointer-events: none;
        }}
        .fw-mobile-auth-shell::after {{
            content: "";
            position: absolute;
            inset: -24% auto auto -34%;
            width: 12rem;
            height: 12rem;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(79, 119, 255, 0.18), transparent 68%);
            filter: blur(18px);
            pointer-events: none;
            animation: fwMobileAuraDrift 8.4s ease-in-out infinite;
        }}
        .fw-mobile-auth-topbar {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.8rem;
        }}
        .fw-mobile-auth-brand {{
            display: flex;
            align-items: center;
            gap: 0.72rem;
            min-width: 0;
        }}
        .fw-mobile-auth-logo {{
            width: 2.5rem;
            height: 2.5rem;
            border-radius: 0.9rem;
            overflow: hidden;
            display: grid;
            place-items: center;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.08);
            box-shadow: 0 14px 28px rgba(0,0,0,0.18);
        }}
        .fw-mobile-auth-logo img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }}
        .fw-mobile-auth-logo span {{
            color: #18dfcf;
            font-size: 1.1rem;
            font-weight: 800;
        }}
        .fw-mobile-auth-brand-name {{
            color: #f5fbff;
            font-size: 1rem;
            font-weight: 800;
            letter-spacing: -0.02em;
        }}
        .fw-mobile-auth-brand-tag {{
            color: #8ca4bc;
            font-size: 0.66rem;
            margin-top: 0.14rem;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }}
        .fw-mobile-auth-live {{
            display: inline-flex;
            align-items: center;
            gap: 0.38rem;
            padding: 0.3rem 0.6rem;
            border-radius: 999px;
            border: 1px solid rgba(34,231,202,0.18);
            background: rgba(34,231,202,0.08);
            color: #dffff8;
            font-size: 0.62rem;
            font-weight: 800;
            white-space: nowrap;
        }}
        .fw-mobile-auth-access-row {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.46rem;
            margin-top: 0.74rem;
        }}
        .fw-mobile-auth-access-link {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 2.55rem;
            padding: 0.2rem 0.4rem;
            border-radius: 0.92rem;
            border: 1px solid rgba(255,255,255,0.08);
            background: rgba(255,255,255,0.03);
            color: #edf8ff !important;
            text-decoration: none !important;
            font-size: 0.74rem;
            font-weight: 850;
            letter-spacing: 0.01em;
        }}
        .fw-mobile-auth-access-link.is-active {{
            border-color: rgba(34,231,202,0.18);
            background: linear-gradient(135deg, rgba(34,231,202,0.14), rgba(53,214,255,0.08));
            color: #e8fffb !important;
        }}
        .fw-mobile-auth-live::before {{
            content: "";
            width: 0.42rem;
            height: 0.42rem;
            border-radius: 999px;
            background: #22e7ca;
            box-shadow: 0 0 12px rgba(34,231,202,0.72);
        }}
        .fw-mobile-auth-kicker {{
            margin-top: 0.8rem;
            color: #7fece0;
            font-size: 0.62rem;
            font-weight: 850;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }}
        .fw-mobile-auth-title {{
            margin-top: 0.38rem;
            color: #ffffff;
            font-size: 1.82rem;
            line-height: 0.94;
            font-weight: 900;
            letter-spacing: -0.05em;
            max-width: 11ch;
            background: linear-gradient(180deg, #ffffff 0%, #d6fff6 72%, #b7e8ff 100%);
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: 0 10px 30px rgba(34, 231, 202, 0.08);
        }}
        .fw-mobile-auth-type-row {{
            display: inline-flex;
            align-items: center;
            margin-top: 0.45rem;
            max-width: 100%;
        }}
        .fw-mobile-auth-type {{
            display: inline-block;
            max-width: 100%;
            overflow: hidden;
            white-space: nowrap;
            color: #cffff8;
            font-size: 0.8rem;
            font-weight: 800;
            letter-spacing: 0.02em;
            border-right: 2px solid rgba(207,255,248,0.8);
            animation: fwMobileTyping 4.2s steps(26, end) infinite alternate, fwMobileCursor 0.85s step-end infinite;
        }}
        .fw-mobile-auth-copy {{
            margin-top: 0.6rem;
            color: #9db5cb;
            font-size: 0.74rem;
            line-height: 1.62;
        }}
        .fw-mobile-auth-chip-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.42rem;
            margin-top: 0.62rem;
        }}
        .fw-mobile-auth-chip {{
            padding: 0.28rem 0.5rem;
            border-radius: 999px;
            border: 1px solid rgba(255,255,255,0.06);
            background: rgba(255,255,255,0.03);
            color: #d8e6f4;
            font-size: 0.58rem;
            font-weight: 800;
            letter-spacing: 0.04em;
        }}
        .fw-mobile-auth-rail {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.55rem;
            margin-top: 0.72rem;
        }}
        .fw-mobile-auth-stat {{
            padding: 0.7rem 0.76rem;
            border-radius: 1rem;
            border: 1px solid rgba(255,255,255,0.05);
            background: rgba(255,255,255,0.03);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.02);
        }}
        .fw-mobile-auth-stat-value {{
            color: #ffffff;
            font-size: 1rem;
            font-weight: 900;
            letter-spacing: -0.03em;
        }}
        .fw-mobile-auth-stat-label {{
            color: #83a0b8;
            font-size: 0.62rem;
            line-height: 1.45;
            margin-top: 0.22rem;
            text-transform: uppercase;
            letter-spacing: 0.09em;
        }}
        .fw-mobile-auth-preview {{
            margin-top: 0.72rem;
            padding: 0.76rem 0.8rem;
            border-radius: 1.08rem;
            border: 1px solid rgba(255,255,255,0.05);
            background: linear-gradient(180deg, rgba(16,24,38,0.92), rgba(10,17,28,0.96));
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.02);
            position: relative;
            overflow: hidden;
            animation: fwMobilePreviewFloat 6.8s ease-in-out infinite;
        }}
        .fw-mobile-auth-preview::before {{
            content: "";
            position: absolute;
            inset: 0;
            background: linear-gradient(115deg, transparent 0%, rgba(255,255,255,0.05) 28%, transparent 50%);
            transform: translateX(-140%);
            animation: fwMobileGlassSweep 5.6s linear infinite;
            pointer-events: none;
        }}
        .fw-mobile-auth-preview-top {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.8rem;
        }}
        .fw-mobile-auth-preview-kicker {{
            color: #7b93ab;
            font-size: 0.58rem;
            font-weight: 850;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }}
        .fw-mobile-auth-preview-title {{
            color: #f6fbff;
            font-size: 0.88rem;
            font-weight: 850;
            margin-top: 0.18rem;
        }}
        .fw-mobile-auth-preview-copy {{
            color: #88a1b8;
            font-size: 0.66rem;
            line-height: 1.52;
            margin-top: 0.18rem;
        }}
        .fw-mobile-auth-preview-badge {{
            padding: 0.24rem 0.48rem;
            border-radius: 999px;
            border: 1px solid rgba(34,231,202,0.16);
            background: rgba(34,231,202,0.08);
            color: #dffff8;
            font-size: 0.56rem;
            font-weight: 800;
            white-space: nowrap;
        }}
        .fw-mobile-auth-mock {{
            margin-top: 0.78rem;
            padding: 0.72rem;
            border-radius: 0.92rem;
            border: 1px solid rgba(255,255,255,0.05);
            background:
                radial-gradient(circle at top right, rgba(34,231,202,0.08), transparent 28%),
                linear-gradient(180deg, rgba(10,18,29,0.98), rgba(7,13,23,0.98));
        }}
        .fw-mobile-auth-mock-head {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.68rem;
        }}
        .fw-mobile-auth-mock-symbol {{
            color: #f5fbff;
            font-size: 0.86rem;
            font-weight: 850;
            letter-spacing: -0.02em;
        }}
        .fw-mobile-auth-mock-meta {{
            color: #7f97af;
            font-size: 0.6rem;
            line-height: 1.45;
            margin-top: 0.16rem;
        }}
        .fw-mobile-auth-mock-live {{
            padding: 0.22rem 0.48rem;
            border-radius: 999px;
            border: 1px solid rgba(34,231,202,0.16);
            background: rgba(34,231,202,0.08);
            color: #dffff8;
            font-size: 0.54rem;
            font-weight: 800;
            white-space: nowrap;
        }}
        .fw-mobile-auth-chart {{
            margin-top: 0.58rem;
            height: 5.8rem;
            border-radius: 0.86rem;
            border: 1px solid rgba(255,255,255,0.04);
            background:
                radial-gradient(circle at 72% 18%, rgba(34,231,202,0.08), transparent 28%),
                #0b1322;
            position: relative;
            overflow: hidden;
        }}
        .fw-mobile-auth-chart::before {{
            content: "";
            position: absolute;
            inset: 0;
            background:
                repeating-linear-gradient(to right, transparent 0 calc(25% - 1px), rgba(255,255,255,0.05) calc(25% - 1px) 25%),
                repeating-linear-gradient(to bottom, transparent 0 calc(25% - 1px), rgba(255,255,255,0.05) calc(25% - 1px) 25%);
            opacity: 0.55;
        }}
        .fw-mobile-auth-candles {{
            position: absolute;
            inset: 0.78rem 3rem 0.92rem 0.62rem;
            display: flex;
            align-items: stretch;
            gap: 0.32rem;
        }}
        .fw-mobile-auth-candle {{
            position: relative;
            flex: 1 1 0;
            min-width: 0;
            height: 100%;
            --candle: #2ef1d3;
        }}
        .fw-mobile-auth-candle.is-down {{
            --candle: #ff6a72;
        }}
        .fw-mobile-auth-candle::before {{
            content: "";
            position: absolute;
            left: 50%;
            top: var(--wick-top);
            height: var(--wick-height);
            width: 1px;
            transform: translateX(-50%);
            background: var(--candle);
            opacity: 0.92;
        }}
        .fw-mobile-auth-candle::after {{
            content: "";
            position: absolute;
            left: 50%;
            top: var(--body-top);
            height: var(--body-height);
            width: 72%;
            min-width: 0.22rem;
            transform: translateX(-50%);
            border-radius: 999px;
            background: var(--candle);
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
        }}
        .fw-mobile-auth-price-tag {{
            position: absolute;
            right: 0.58rem;
            top: 50%;
            transform: translateY(-50%);
            padding: 0.24rem 0.4rem;
            border-radius: 0.66rem;
            background: rgba(46,241,211,0.12);
            border: 1px solid rgba(46,241,211,0.18);
            color: #dffff8;
            font-size: 0.58rem;
            font-weight: 800;
            animation: fwMobilePricePulse 3.6s ease-in-out infinite;
        }}
        .fw-mobile-auth-chart::after {{
            content: "";
            position: absolute;
            top: 0;
            bottom: 0;
            width: 42%;
            left: -42%;
            background: linear-gradient(90deg, transparent, rgba(46,241,211,0.08), transparent);
            animation: fwMobileChartSweep 5.8s linear infinite;
            pointer-events: none;
        }}
        .fw-mobile-auth-preview-tabs {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.28rem;
            margin-top: 0.52rem;
        }}
        .fw-mobile-auth-preview-tab {{
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 1.56rem;
            border-radius: 0.72rem;
            border: 1px solid rgba(255,255,255,0.05);
            background: rgba(255,255,255,0.02);
            color: #7d92ab;
            font-size: 0.58rem;
            font-weight: 800;
            letter-spacing: 0.02em;
            transition: transform 0.18s ease;
        }}
        .fw-mobile-auth-preview-tab.tab-chart {{
            animation: fwMobileTabChart 16s infinite;
        }}
        .fw-mobile-auth-preview-tab.tab-signal {{
            animation: fwMobileTabSignal 16s infinite;
        }}
        .fw-mobile-auth-preview-tab.tab-depth {{
            animation: fwMobileTabDepth 16s infinite;
        }}
        .fw-mobile-auth-preview-tab.tab-route {{
            animation: fwMobileTabRoute 16s infinite;
        }}
        .fw-mobile-auth-demo-shell {{
            position: relative;
            min-height: 4.9rem;
            margin-top: 0.54rem;
            border-radius: 0.82rem;
            border: 1px solid rgba(255,255,255,0.05);
            background: linear-gradient(180deg, rgba(6,13,23,0.92), rgba(8,15,25,0.98));
            overflow: hidden;
        }}
        .fw-mobile-auth-demo-shell::before {{
            content: "";
            position: absolute;
            inset: 0;
            background:
                radial-gradient(circle at top right, rgba(34,231,202,0.08), transparent 34%),
                linear-gradient(180deg, rgba(255,255,255,0.02), transparent 30%);
            pointer-events: none;
        }}
        .fw-mobile-auth-demo-scene {{
            position: absolute;
            inset: 0;
            padding: 0.62rem 0.66rem;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            gap: 0.42rem;
            opacity: 0;
            transform: translateX(8%);
        }}
        .fw-mobile-auth-demo-scene.scene-chart {{
            animation: fwMobileSceneChart 16s infinite;
        }}
        .fw-mobile-auth-demo-scene.scene-signal {{
            animation: fwMobileSceneSignal 16s infinite;
        }}
        .fw-mobile-auth-demo-scene.scene-depth {{
            animation: fwMobileSceneDepth 16s infinite;
        }}
        .fw-mobile-auth-demo-scene.scene-route {{
            animation: fwMobileSceneRoute 16s infinite;
        }}
        .fw-mobile-auth-demo-head {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
        }}
        .fw-mobile-auth-demo-label {{
            color: #7fece0;
            font-size: 0.52rem;
            font-weight: 850;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }}
        .fw-mobile-auth-demo-value {{
            color: #f5fbff;
            font-size: 0.78rem;
            font-weight: 850;
        }}
        .fw-mobile-auth-demo-copy {{
            color: #89a3b9;
            font-size: 0.6rem;
            line-height: 1.45;
        }}
        .fw-mobile-auth-demo-pill {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 1.28rem;
            padding: 0 0.46rem;
            border-radius: 999px;
            border: 1px solid rgba(255,255,255,0.05);
            background: rgba(255,255,255,0.04);
            color: #d5edf4;
            font-size: 0.52rem;
            font-weight: 800;
            white-space: nowrap;
        }}
        .fw-mobile-auth-demo-pill.is-positive {{
            border-color: rgba(34,231,202,0.16);
            background: rgba(34,231,202,0.08);
            color: #e0fffa;
        }}
        .fw-mobile-auth-demo-chip-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.34rem;
        }}
        .fw-mobile-auth-demo-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.42rem;
        }}
        .fw-mobile-auth-demo-stat {{
            padding: 0.42rem 0.48rem;
            border-radius: 0.68rem;
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.04);
        }}
        .fw-mobile-auth-demo-stat-label {{
            color: #7c95ab;
            font-size: 0.5rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}
        .fw-mobile-auth-demo-stat-value {{
            color: #f4fbff;
            font-size: 0.68rem;
            font-weight: 850;
            margin-top: 0.18rem;
        }}
        .fw-mobile-auth-signal-meter {{
            height: 0.34rem;
            border-radius: 999px;
            background: rgba(255,255,255,0.05);
            overflow: hidden;
        }}
        .fw-mobile-auth-signal-meter-fill {{
            height: 100%;
            width: 62%;
            border-radius: 999px;
            background: linear-gradient(90deg, rgba(46,241,211,0.8), rgba(53,214,255,0.9));
            animation: fwMobileMeterPulse 2.2s ease-in-out infinite;
        }}
        .fw-mobile-auth-depth-track {{
            height: 0.34rem;
            border-radius: 999px;
            background: rgba(255,106,114,0.18);
            overflow: hidden;
        }}
        .fw-mobile-auth-depth-fill {{
            height: 100%;
            width: 74%;
            border-radius: 999px;
            background: linear-gradient(90deg, rgba(46,241,211,0.8), rgba(46,241,211,0.35));
            animation: fwMobileDepthShift 2.8s ease-in-out infinite;
        }}
        .fw-mobile-auth-depth-rows {{
            display: grid;
            gap: 0.22rem;
        }}
        .fw-mobile-auth-depth-row {{
            display: grid;
            grid-template-columns: 1fr 0.82fr 0.86fr;
            gap: 0.3rem;
            color: #dcecf7;
            font-size: 0.54rem;
        }}
        .fw-mobile-auth-depth-row span:last-child {{
            text-align: right;
        }}
        .fw-mobile-auth-depth-row .is-bid {{
            color: #82f5df;
        }}
        .fw-mobile-auth-depth-row .is-ask {{
            color: #ff8f98;
        }}
        .fw-mobile-auth-route-rail {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.34rem;
        }}
        .fw-mobile-auth-route-step {{
            padding: 0.38rem 0.4rem;
            border-radius: 0.64rem;
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.04);
            text-align: center;
        }}
        .fw-mobile-auth-route-step strong {{
            display: block;
            color: #f5fbff;
            font-size: 0.6rem;
            font-weight: 850;
        }}
        .fw-mobile-auth-route-step span {{
            display: block;
            margin-top: 0.16rem;
            color: #86a2b8;
            font-size: 0.48rem;
            line-height: 1.35;
        }}
        .fw-mobile-auth-return {{
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 0.7rem;
            align-items: center;
            margin-top: 0.68rem;
            padding: 0.78rem 0.82rem;
            border-radius: 1rem;
            border: 1px solid rgba(34,231,202,0.12);
            background: rgba(11, 22, 35, 0.72);
        }}
        .fw-mobile-auth-return-label {{
            color: #7fece0;
            font-size: 0.56rem;
            font-weight: 850;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }}
        .fw-mobile-auth-return-copy {{
            color: #d9e7f4;
            font-size: 0.7rem;
            line-height: 1.48;
            margin-top: 0.18rem;
        }}
        .fw-mobile-auth-return-btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 2.45rem;
            padding: 0 0.86rem;
            border-radius: 0.9rem;
            text-decoration: none !important;
            color: #06161b !important;
            background: linear-gradient(135deg, #2ef1d3 0%, #35d6ff 100%);
            font-size: 0.74rem;
            font-weight: 850;
            white-space: nowrap;
        }}
        @keyframes fwMobileAuraDrift {{
            0%, 100% {{
                transform: translate3d(0, 0, 0);
                opacity: 0.9;
            }}
            50% {{
                transform: translate3d(1rem, 0.9rem, 0);
                opacity: 0.65;
            }}
        }}
        @keyframes fwMobilePreviewFloat {{
            0%, 100% {{
                transform: translateY(0);
            }}
            50% {{
                transform: translateY(-4px);
            }}
        }}
        @keyframes fwMobileGlassSweep {{
            0% {{
                transform: translateX(-140%);
            }}
            100% {{
                transform: translateX(140%);
            }}
        }}
        @keyframes fwMobileTyping {{
            0% {{
                width: 0;
            }}
            45% {{
                width: 26ch;
            }}
            55% {{
                width: 26ch;
            }}
            100% {{
                width: 12ch;
            }}
        }}
        @keyframes fwMobileCursor {{
            50% {{
                border-color: transparent;
            }}
        }}
        @keyframes fwMobileChartSweep {{
            0% {{
                left: -42%;
            }}
            100% {{
                left: 118%;
            }}
        }}
        @keyframes fwMobilePricePulse {{
            0%, 100% {{
                box-shadow: 0 0 0 rgba(46,241,211,0);
                transform: translateY(-50%) scale(1);
            }}
            50% {{
                box-shadow: 0 0 18px rgba(46,241,211,0.18);
                transform: translateY(-50%) scale(1.04);
            }}
        }}
        @keyframes fwMobileMeterPulse {{
            0%, 100% {{
                width: 62%;
            }}
            50% {{
                width: 68%;
            }}
        }}
        @keyframes fwMobileDepthShift {{
            0%, 100% {{
                width: 74%;
            }}
            50% {{
                width: 81%;
            }}
        }}
        @keyframes fwMobileSceneChart {{
            0%, 22% {{
                opacity: 1;
                transform: translateX(0);
            }}
            27%, 100% {{
                opacity: 0;
                transform: translateX(-6%);
            }}
        }}
        @keyframes fwMobileSceneSignal {{
            0%, 23% {{
                opacity: 0;
                transform: translateX(8%);
            }}
            25%, 47% {{
                opacity: 1;
                transform: translateX(0);
            }}
            52%, 100% {{
                opacity: 0;
                transform: translateX(-6%);
            }}
        }}
        @keyframes fwMobileSceneDepth {{
            0%, 48% {{
                opacity: 0;
                transform: translateX(8%);
            }}
            50%, 72% {{
                opacity: 1;
                transform: translateX(0);
            }}
            77%, 100% {{
                opacity: 0;
                transform: translateX(-6%);
            }}
        }}
        @keyframes fwMobileSceneRoute {{
            0%, 73% {{
                opacity: 0;
                transform: translateX(8%);
            }}
            75%, 97% {{
                opacity: 1;
                transform: translateX(0);
            }}
            100% {{
                opacity: 0;
                transform: translateX(-6%);
            }}
        }}
        @keyframes fwMobileTabChart {{
            0%, 22% {{
                color: #e9fffb;
                border-color: rgba(34,231,202,0.18);
                background: linear-gradient(180deg, rgba(34,231,202,0.14), rgba(53,214,255,0.06));
                transform: translateY(-1px);
            }}
            27%, 100% {{
                color: #7d92ab;
                border-color: rgba(255,255,255,0.05);
                background: rgba(255,255,255,0.02);
                transform: none;
            }}
        }}
        @keyframes fwMobileTabSignal {{
            0%, 23% {{
                color: #7d92ab;
                border-color: rgba(255,255,255,0.05);
                background: rgba(255,255,255,0.02);
                transform: none;
            }}
            25%, 47% {{
                color: #e9fffb;
                border-color: rgba(34,231,202,0.18);
                background: linear-gradient(180deg, rgba(34,231,202,0.14), rgba(53,214,255,0.06));
                transform: translateY(-1px);
            }}
            52%, 100% {{
                color: #7d92ab;
                border-color: rgba(255,255,255,0.05);
                background: rgba(255,255,255,0.02);
                transform: none;
            }}
        }}
        @keyframes fwMobileTabDepth {{
            0%, 48% {{
                color: #7d92ab;
                border-color: rgba(255,255,255,0.05);
                background: rgba(255,255,255,0.02);
                transform: none;
            }}
            50%, 72% {{
                color: #e9fffb;
                border-color: rgba(34,231,202,0.18);
                background: linear-gradient(180deg, rgba(34,231,202,0.14), rgba(53,214,255,0.06));
                transform: translateY(-1px);
            }}
            77%, 100% {{
                color: #7d92ab;
                border-color: rgba(255,255,255,0.05);
                background: rgba(255,255,255,0.02);
                transform: none;
            }}
        }}
        @keyframes fwMobileTabRoute {{
            0%, 73% {{
                color: #7d92ab;
                border-color: rgba(255,255,255,0.05);
                background: rgba(255,255,255,0.02);
                transform: none;
            }}
            75%, 97% {{
                color: #e9fffb;
                border-color: rgba(34,231,202,0.18);
                background: linear-gradient(180deg, rgba(34,231,202,0.14), rgba(53,214,255,0.06));
                transform: translateY(-1px);
            }}
            100% {{
                color: #7d92ab;
                border-color: rgba(255,255,255,0.05);
                background: rgba(255,255,255,0.02);
                transform: none;
            }}
        }}
        </style>
        <section class="fw-mobile-auth-shell{shell_muted}">
            <div class="fw-mobile-auth-topbar">
                <div class="fw-mobile-auth-brand">
                    <div class="fw-mobile-auth-logo">{hero_logo}</div>
                    <div>
                        <div class="fw-mobile-auth-brand-name">Finwise AI</div>
                        <div class="fw-mobile-auth-brand-tag">Mobile Access</div>
                    </div>
                </div>
                <div class="fw-mobile-auth-live">Live Ready</div>
            </div>
            <div class="fw-mobile-auth-access-row">
                <a class="fw-mobile-auth-access-link{login_active}" href="{escape(login_href, quote=True)}" target="_self">Login</a>
                <a class="fw-mobile-auth-access-link{register_active}" href="{escape(register_href, quote=True)}" target="_self">Sign Up</a>
            </div>
            <div class="fw-mobile-auth-kicker">Pocket Trading System</div>
            <div class="fw-mobile-auth-title">Precision markets in one cinematic mobile flow.</div>
            <div class="fw-mobile-auth-type-row">
                <span class="fw-mobile-auth-type">Scan. Sense. Signal. Send.</span>
            </div>
            <div class="fw-mobile-auth-copy">
                A sharper mobile launchpad for live market reads, AI-backed conviction, and a faster path from setup to execution.
            </div>
            <div class="fw-mobile-auth-chip-row">
                <span class="fw-mobile-auth-chip">Live Market Feed</span>
                <span class="fw-mobile-auth-chip">AI Signal Context</span>
                <span class="fw-mobile-auth-chip">Broker Handoff</span>
            </div>
            <div class="fw-mobile-auth-rail">
                <div class="fw-mobile-auth-stat">
                    <div class="fw-mobile-auth-stat-value">24/7</div>
                    <div class="fw-mobile-auth-stat-label">Market monitoring</div>
                </div>
                <div class="fw-mobile-auth-stat">
                    <div class="fw-mobile-auth-stat-value">1 Flow</div>
                    <div class="fw-mobile-auth-stat-label">Analysis to execution</div>
                </div>
            </div>
            <div class="fw-mobile-auth-preview">
                <div class="fw-mobile-auth-preview-top">
                    <div>
                        <div class="fw-mobile-auth-preview-kicker">Landing Preview</div>
                        <div class="fw-mobile-auth-preview-title">A living launchpad for Finwise mobile</div>
                        <div class="fw-mobile-auth-preview-copy">Typography, motion, and signal-first framing work together so the mobile entry feels like the platform, not a placeholder.</div>
                    </div>
                    <div class="fw-mobile-auth-preview-badge">BTCUSDT</div>
                </div>
                <div class="fw-mobile-auth-mock">
                    <div class="fw-mobile-auth-mock-head">
                        <div>
                            <div class="fw-mobile-auth-mock-symbol">BTCUSDT</div>
                            <div class="fw-mobile-auth-mock-meta">Chart, signal, and broker routing shown in one focused mobile flow.</div>
                        </div>
                        <div class="fw-mobile-auth-mock-live">Live</div>
                    </div>
                    <div class="fw-mobile-auth-chart">
                        <div class="fw-mobile-auth-candles" aria-hidden="true">
                            <span class="fw-mobile-auth-candle" style="--wick-top:14%;--wick-height:56%;--body-top:34%;--body-height:18%;"></span>
                            <span class="fw-mobile-auth-candle is-down" style="--wick-top:18%;--wick-height:54%;--body-top:30%;--body-height:24%;"></span>
                            <span class="fw-mobile-auth-candle" style="--wick-top:10%;--wick-height:58%;--body-top:26%;--body-height:18%;"></span>
                            <span class="fw-mobile-auth-candle" style="--wick-top:22%;--wick-height:48%;--body-top:38%;--body-height:14%;"></span>
                            <span class="fw-mobile-auth-candle is-down" style="--wick-top:28%;--wick-height:42%;--body-top:42%;--body-height:16%;"></span>
                            <span class="fw-mobile-auth-candle" style="--wick-top:16%;--wick-height:54%;--body-top:30%;--body-height:20%;"></span>
                            <span class="fw-mobile-auth-candle is-down" style="--wick-top:24%;--wick-height:46%;--body-top:36%;--body-height:18%;"></span>
                            <span class="fw-mobile-auth-candle" style="--wick-top:12%;--wick-height:58%;--body-top:22%;--body-height:24%;"></span>
                            <span class="fw-mobile-auth-candle" style="--wick-top:8%;--wick-height:60%;--body-top:20%;--body-height:20%;"></span>
                            <span class="fw-mobile-auth-candle is-down" style="--wick-top:20%;--wick-height:48%;--body-top:34%;--body-height:18%;"></span>
                            <span class="fw-mobile-auth-candle" style="--wick-top:14%;--wick-height:54%;--body-top:28%;--body-height:18%;"></span>
                            <span class="fw-mobile-auth-candle" style="--wick-top:6%;--wick-height:64%;--body-top:18%;--body-height:22%;"></span>
                        </div>
                        <div class="fw-mobile-auth-price-tag">79,410</div>
                    </div>
                    <div class="fw-mobile-auth-preview-tabs">
                        <span class="fw-mobile-auth-preview-tab tab-chart">Chart</span>
                        <span class="fw-mobile-auth-preview-tab tab-signal">Signal</span>
                        <span class="fw-mobile-auth-preview-tab tab-depth">Depth</span>
                        <span class="fw-mobile-auth-preview-tab tab-route">Route</span>
                    </div>
                    <div class="fw-mobile-auth-demo-shell" aria-hidden="true">
                        <div class="fw-mobile-auth-demo-scene scene-chart">
                            <div class="fw-mobile-auth-demo-head">
                                <div>
                                    <div class="fw-mobile-auth-demo-label">Chart View</div>
                                    <div class="fw-mobile-auth-demo-value">Momentum rebuilding above 79,300</div>
                                </div>
                                <span class="fw-mobile-auth-demo-pill is-positive">3m</span>
                            </div>
                            <div class="fw-mobile-auth-demo-grid">
                                <div class="fw-mobile-auth-demo-stat">
                                    <div class="fw-mobile-auth-demo-stat-label">Bias</div>
                                    <div class="fw-mobile-auth-demo-stat-value">Recovery</div>
                                </div>
                                <div class="fw-mobile-auth-demo-stat">
                                    <div class="fw-mobile-auth-demo-stat-label">Trigger</div>
                                    <div class="fw-mobile-auth-demo-stat-value">79,520 Break</div>
                                </div>
                            </div>
                        </div>
                        <div class="fw-mobile-auth-demo-scene scene-signal">
                            <div class="fw-mobile-auth-demo-head">
                                <div>
                                    <div class="fw-mobile-auth-demo-label">Signal View</div>
                                    <div class="fw-mobile-auth-demo-value">AI confidence updates in context</div>
                                </div>
                                <span class="fw-mobile-auth-demo-pill">62%</span>
                            </div>
                            <div class="fw-mobile-auth-signal-meter">
                                <div class="fw-mobile-auth-signal-meter-fill"></div>
                            </div>
                            <div class="fw-mobile-auth-demo-chip-row">
                                <span class="fw-mobile-auth-demo-pill">Support 79,180</span>
                                <span class="fw-mobile-auth-demo-pill">Resistance 79,640</span>
                            </div>
                        </div>
                        <div class="fw-mobile-auth-demo-scene scene-depth">
                            <div class="fw-mobile-auth-demo-head">
                                <div>
                                    <div class="fw-mobile-auth-demo-label">Depth View</div>
                                    <div class="fw-mobile-auth-demo-value">Order flow stays visible before entry</div>
                                </div>
                                <span class="fw-mobile-auth-demo-pill is-positive">74% Bids</span>
                            </div>
                            <div class="fw-mobile-auth-depth-track">
                                <div class="fw-mobile-auth-depth-fill"></div>
                            </div>
                            <div class="fw-mobile-auth-depth-rows">
                                <div class="fw-mobile-auth-depth-row"><span class="is-bid">79,409.8</span><span>0.82 BTC</span><span>2.41 BTC</span></div>
                                <div class="fw-mobile-auth-depth-row"><span class="is-bid">79,409.4</span><span>0.55 BTC</span><span>1.59 BTC</span></div>
                                <div class="fw-mobile-auth-depth-row"><span class="is-ask">79,410.6</span><span>0.31 BTC</span><span>0.88 BTC</span></div>
                            </div>
                        </div>
                        <div class="fw-mobile-auth-demo-scene scene-route">
                            <div class="fw-mobile-auth-demo-head">
                                <div>
                                    <div class="fw-mobile-auth-demo-label">Route View</div>
                                    <div class="fw-mobile-auth-demo-value">Signal handoff moves straight into execution</div>
                                </div>
                                <span class="fw-mobile-auth-demo-pill is-positive">Broker Ready</span>
                            </div>
                            <div class="fw-mobile-auth-route-rail">
                                <div class="fw-mobile-auth-route-step"><strong>Scan</strong><span>Market context stays loaded</span></div>
                                <div class="fw-mobile-auth-route-step"><strong>Signal</strong><span>Confidence and levels stay pinned</span></div>
                                <div class="fw-mobile-auth-route-step"><strong>Route</strong><span>Send to broker without leaving desk</span></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            {resume_markup}
        </section>
        """
        ).strip()
    )


def _clear_registration_state():
    pending_username = str(
        (st.session_state.get("temp_user") or {}).get("username")
        or st.session_state.get("pending_username", "")
        or ""
    ).strip()
    if pending_username:
        clear_pending_user(pending_username)
    st.session_state.otp_sent = False
    st.session_state.temp_user = {}
    st.session_state.pending_email = ""
    st.session_state.pending_username = ""
    if st.session_state.get("auth_otp_context") == "register":
        st.session_state.auth_otp_context = ""


def _mobile_auth_href(*, auth: str | None = None, action: str | None = None) -> str:
    updates = {"viewport": "mobile"}
    if auth is not None:
        updates["auth"] = auth
    if action is not None:
        updates["auth_action"] = action
    return build_query_href(**updates)


def _handle_mobile_auth_action(action: str) -> None:
    action = str(action or "").strip().lower()
    if not action:
        return

    if action == "to_reset":
        clear_password_reset_state()
        st.session_state.password_reset_username_field = str(
            st.session_state.get("login_username_field", "") or ""
        ).strip()
        st.session_state.auth_view = "reset_password"
        return

    if action == "restart_register":
        _clear_registration_state()
        st.session_state.auth_view = "register"
        return

    if action == "register_to_login":
        pending_username = str(
            (st.session_state.get("temp_user") or {}).get("username")
            or st.session_state.get("pending_username", "")
            or ""
        ).strip()
        if pending_username:
            st.session_state.login_username_field = pending_username
        st.session_state.auth_otp_context = ""
        st.session_state.auth_view = "login"
        return

    if action == "restart_reset":
        clear_password_reset_state()
        st.session_state.auth_view = "reset_password"
        return

    if action == "reset_code_again":
        st.session_state.password_reset_verified = False
        st.session_state.auth_view = "reset_password"
        return

    if action == "reset_to_login":
        reset_request = st.session_state.get("password_reset_request") or {}
        reset_username = str(reset_request.get("username") or "").strip()
        if reset_username:
            st.session_state.login_username_field = reset_username
        clear_password_reset_state()
        st.session_state.auth_view = "login"
        return

    if action == "resend_reset_code":
        reset_request = st.session_state.get("password_reset_request") or {}
        username = str(reset_request.get("username") or "").strip()
        email = str(reset_request.get("email") or "").strip()
        user = load_registered_user(username, email) if username and email else None
        if not user or not user.get("email"):
            clear_password_reset_state()
            st.session_state.auth_view = "reset_password"
            st.session_state.auth_error = "Password reset session expired. Please start again."
            return
        st.session_state.pending_username = user["username"]
        st.session_state.pending_email = user["email"]
        st.session_state.auth_otp_context = "password_reset"
        if send_email_otp(user["email"], user["username"], purpose="password_reset"):
            st.session_state.password_reset_sent = True
            st.session_state.password_reset_verified = False
            st.session_state.auth_view = "reset_password"
            st.session_state.auth_notice = f"A fresh reset code was sent to {user['email']}."
            return
        st.session_state.auth_error = "We could not send the reset code right now. Please try again."


def _render_mobile_auth_stage_shell(*, kicker: str, title: str, copy: str, back_href: str, back_label: str = "Back") -> None:
    st.markdown(
        dedent(
            f"""
            <style>
            .fw-mobile-auth-stage-card {{
                position: relative;
                overflow: hidden;
                max-width: 29rem;
                margin: 0.35rem auto 0.8rem;
                padding: 0.98rem 0.98rem 0.94rem;
                border-radius: 1.45rem;
                border: 1px solid rgba(34,231,202,0.12);
                background:
                    radial-gradient(circle at top right, rgba(34,231,202,0.10), transparent 28%),
                    linear-gradient(180deg, rgba(11,18,30,0.96) 0%, rgba(8,14,24,0.98) 100%);
                box-shadow: 0 20px 44px rgba(0,0,0,0.28);
            }}
            .fw-mobile-auth-stage-top {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 0.75rem;
            }}
            .fw-mobile-auth-stage-back {{
                display: inline-flex;
                align-items: center;
                gap: 0.3rem;
                color: #d9ebf8 !important;
                text-decoration: none !important;
                font-size: 0.68rem;
                font-weight: 800;
                padding: 0.32rem 0.56rem;
                border-radius: 999px;
                border: 1px solid rgba(255,255,255,0.06);
                background: rgba(255,255,255,0.03);
            }}
            .fw-mobile-auth-stage-back::before {{
                content: "‹";
                font-size: 0.9rem;
                line-height: 1;
            }}
            .fw-mobile-auth-stage-badge {{
                padding: 0.26rem 0.5rem;
                border-radius: 999px;
                border: 1px solid rgba(34,231,202,0.16);
                background: rgba(34,231,202,0.08);
                color: #dffff8;
                font-size: 0.56rem;
                font-weight: 800;
                white-space: nowrap;
            }}
            .fw-mobile-auth-stage-kicker {{
                margin-top: 0.88rem;
                color: #7fece0;
                font-size: 0.58rem;
                font-weight: 850;
                letter-spacing: 0.12em;
                text-transform: uppercase;
            }}
            .fw-mobile-auth-stage-title {{
                color: #ffffff;
                font-size: 1.34rem;
                line-height: 1.04;
                font-weight: 900;
                letter-spacing: -0.04em;
                margin-top: 0.36rem;
            }}
            .fw-mobile-auth-stage-copy {{
                color: #93acc3;
                font-size: 0.74rem;
                line-height: 1.62;
                margin-top: 0.42rem;
            }}
            .fw-mobile-auth-stage-shell {{
                max-width: 29rem;
                margin: 0 auto 1rem;
            }}
            .st-key-mobile_auth_form_shell {{
                max-width: 29rem;
                margin: 0 auto 0.95rem;
            }}
            .st-key-mobile_auth_form_shell [data-testid="stForm"] {{
                border: 1px solid rgba(255,255,255,0.06) !important;
                border-radius: 1.25rem !important;
                background: linear-gradient(180deg, rgba(14,22,34,0.94), rgba(9,16,26,0.98)) !important;
                box-shadow: 0 18px 38px rgba(0,0,0,0.2) !important;
                padding: 0.92rem 0.9rem 0.98rem !important;
            }}
            .fw-mobile-auth-field-label {{
                color: #7f95ac;
                font-size: 0.58rem;
                font-weight: 850;
                letter-spacing: 0.12em;
                text-transform: uppercase;
                margin: 0.14rem 0 0.34rem;
            }}
            .st-key-mobile_auth_form_shell .stTextInput > div > div > input,
            .st-key-mobile_auth_form_shell .stNumberInput > div > div > input {{
                min-height: 3rem !important;
                border-radius: 1rem !important;
                border: 1px solid rgba(255,255,255,0.07) !important;
                background: rgba(15, 24, 38, 0.92) !important;
                color: #edf8ff !important;
                font-size: 0.84rem !important;
                font-weight: 700 !important;
                padding-left: 0.9rem !important;
            }}
            .st-key-mobile_auth_form_shell .stTextInput > div > div > input::placeholder,
            .st-key-mobile_auth_form_shell .stNumberInput > div > div > input::placeholder {{
                color: #6f8398 !important;
                opacity: 1 !important;
            }}
            .st-key-mobile_auth_form_shell .stFormSubmitButton > button,
            .st-key-mobile_auth_form_shell [data-testid="stFormSubmitButton"] > button {{
                min-height: 3rem !important;
                border-radius: 1rem !important;
                border: 1px solid rgba(255,255,255,0.02) !important;
                background: linear-gradient(135deg, #2ef1d3 0%, #35d6ff 100%) !important;
                color: #06161b !important;
                font-size: 0.82rem !important;
                font-weight: 850 !important;
                box-shadow: 0 16px 28px rgba(34,231,202,0.16) !important;
            }}
            .st-key-mobile_auth_form_shell [data-testid="stAlert"] {{
                border-radius: 1rem !important;
                border-width: 1px !important;
            }}
            .fw-mobile-auth-status-card {{
                margin: 0 auto 0.72rem;
                max-width: 29rem;
                padding: 0.82rem 0.86rem;
                border-radius: 1rem;
                border: 1px solid rgba(34,231,202,0.12);
                background: rgba(10, 20, 32, 0.78);
                color: #def4ff;
                font-size: 0.72rem;
                line-height: 1.52;
            }}
            .fw-mobile-auth-status-card.is-success {{
                border-color: rgba(34,231,202,0.16);
                background: rgba(9, 24, 30, 0.92);
                color: #defcf7;
            }}
            .fw-mobile-auth-status-card.is-error {{
                border-color: rgba(255,107,129,0.18);
                background: rgba(38, 12, 20, 0.9);
                color: #ffdce4;
            }}
            .fw-mobile-auth-status-card strong {{
                color: #ffffff;
            }}
            .fw-mobile-auth-link-row {{
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.55rem;
                max-width: 29rem;
                margin: 0.72rem auto 0.5rem;
            }}
            .fw-mobile-auth-link {{
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 2.82rem;
                padding: 0.3rem 0.42rem;
                border-radius: 0.96rem;
                border: 1px solid rgba(255,255,255,0.07);
                background: rgba(255,255,255,0.03);
                color: #e8f5ff !important;
                text-decoration: none !important;
                font-size: 0.72rem;
                font-weight: 850;
                text-align: center;
            }}
            .fw-mobile-auth-link.is-muted {{
                color: #a8bfd3 !important;
            }}
            .fw-mobile-auth-link-single {{
                max-width: 29rem;
                margin: 0.72rem auto 0.5rem;
            }}
            .fw-mobile-auth-link-single .fw-mobile-auth-link {{
                min-height: 2.88rem;
            }}
            </style>
            <section class="fw-mobile-auth-stage-card">
                <div class="fw-mobile-auth-stage-top">
                    <a class="fw-mobile-auth-stage-back" href="{escape(back_href, quote=True)}" target="_self">{escape(back_label)}</a>
                    <div class="fw-mobile-auth-stage-badge">Secure Access</div>
                </div>
                <div class="fw-mobile-auth-stage-kicker">{escape(kicker)}</div>
                <div class="fw-mobile-auth-stage-title">{escape(title)}</div>
                <div class="fw-mobile-auth-stage-copy">{escape(copy)}</div>
            </section>
            """
        ),
        unsafe_allow_html=True,
    )


def _render_mobile_auth_feedback(message: str, *, title: str = "", kind: str = "info") -> None:
    message = str(message or "").strip()
    if not message:
        return
    classes = "fw-mobile-auth-status-card"
    if kind == "success":
        classes += " is-success"
    elif kind == "error":
        classes += " is-error"
    title_markup = f"<strong>{escape(title)}</strong><br/>" if title else ""
    message_markup = escape(message).replace("\n", "<br/>")
    st.markdown(
        f'<div class="{classes}">{title_markup}{message_markup}</div>',
        unsafe_allow_html=True,
    )


def _render_mobile_auth_links(links: list[tuple[str, str, bool]], *, single: bool = False) -> None:
    if not links:
        return
    container_class = "fw-mobile-auth-link-single" if single else "fw-mobile-auth-link-row"
    anchors = []
    for label, href, muted in links:
        label_text = str(label or "").strip()
        href_value = str(href or "").strip()
        if not label_text or not href_value:
            continue
        class_name = "fw-mobile-auth-link is-muted" if muted else "fw-mobile-auth-link"
        anchors.append(
            f'<a class="{class_name}" href="{escape(href_value, quote=True)}" target="_self">{escape(label_text)}</a>'
        )
    if not anchors:
        return
    st.markdown(
        f'<div class="{container_class}">{"".join(anchors)}</div>',
        unsafe_allow_html=True,
    )


def _render_mobile_auth_overlay_shell(*, auth_view: str) -> None:
    login_href = _mobile_auth_href(auth="login")
    register_href = _mobile_auth_href(auth="register")
    landing_href = _mobile_auth_href(auth="landing")
    login_active = " is-active" if auth_view == "login" else ""
    register_active = " is-active" if auth_view == "register" else ""
    reset_badge = ""
    if auth_view == "reset_password":
        reset_badge = '<div class="fw-mobile-auth-overlay-badge">Reset Password</div>'
    st.markdown(
        dedent(
            f"""
            <style>
            .st-key-mobile_auth_overlay {{
                position: fixed;
                inset: 0;
                z-index: 9999;
                display: flex;
                align-items: flex-start;
                justify-content: center;
                padding: 0.55rem 0.7rem 0.7rem;
                background: rgba(5, 11, 18, 0.58);
                backdrop-filter: blur(14px);
                overflow: hidden;
            }}
            .st-key-mobile_auth_overlay > div {{
                width: min(29rem, 100%);
                max-height: calc(100vh - 1.25rem);
                overflow: hidden;
                padding: 0.9rem 0.92rem 0.98rem;
                border-radius: 1.45rem;
                border: 1px solid rgba(255,255,255,0.08);
                background:
                    radial-gradient(circle at top right, rgba(34,231,202,0.10), transparent 28%),
                    linear-gradient(180deg, rgba(11,18,30,0.98) 0%, rgba(8,14,24,0.99) 100%);
                box-shadow: 0 24px 60px rgba(0,0,0,0.34);
            }}
            .fw-mobile-auth-overlay-head {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 0.7rem;
                margin-bottom: 0.7rem;
            }}
            .fw-mobile-auth-overlay-close {{
                display: inline-flex;
                align-items: center;
                justify-content: center;
                min-height: 2.3rem;
                padding: 0 0.84rem;
                border-radius: 999px;
                text-decoration: none !important;
                border: 1px solid rgba(255,255,255,0.08);
                background: rgba(255,255,255,0.03);
                color: #e8f4ff !important;
                font-size: 0.7rem;
                font-weight: 850;
            }}
            .fw-mobile-auth-overlay-tabs {{
                display: inline-grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.42rem;
                flex: 1 1 auto;
            }}
            .fw-mobile-auth-overlay-tab {{
                display: inline-flex;
                align-items: center;
                justify-content: center;
                min-height: 2.3rem;
                padding: 0 0.7rem;
                border-radius: 0.9rem;
                text-decoration: none !important;
                border: 1px solid rgba(255,255,255,0.08);
                background: rgba(255,255,255,0.03);
                color: #ddecf9 !important;
                font-size: 0.7rem;
                font-weight: 850;
                text-align: center;
            }}
            .fw-mobile-auth-overlay-tab.is-active {{
                border-color: rgba(34,231,202,0.18);
                background: linear-gradient(135deg, rgba(34,231,202,0.14), rgba(53,214,255,0.08));
                color: #e8fffb !important;
            }}
            .fw-mobile-auth-overlay-badge {{
                margin-bottom: 0.62rem;
                display: inline-flex;
                align-items: center;
                min-height: 1.9rem;
                padding: 0 0.72rem;
                border-radius: 999px;
                border: 1px solid rgba(34,231,202,0.16);
                background: rgba(34,231,202,0.08);
                color: #dffff8;
                font-size: 0.62rem;
                font-weight: 850;
                letter-spacing: 0.06em;
                text-transform: uppercase;
            }}
            .fw-mobile-auth-overlay-headline {{
                margin: 0 0 0.7rem;
            }}
            .fw-mobile-auth-overlay-headline-kicker {{
                color: #7fece0;
                font-size: 0.56rem;
                font-weight: 850;
                letter-spacing: 0.12em;
                text-transform: uppercase;
            }}
            .fw-mobile-auth-overlay-headline-title {{
                color: #ffffff;
                font-size: 1.18rem;
                line-height: 1.04;
                font-weight: 900;
                letter-spacing: -0.04em;
                margin-top: 0.32rem;
            }}
            .fw-mobile-auth-overlay-headline-copy {{
                color: #8fa8bf;
                font-size: 0.7rem;
                line-height: 1.54;
                margin-top: 0.28rem;
            }}
            .st-key-mobile_auth_overlay .stTextInput > div > div > input,
            .st-key-mobile_auth_overlay .stNumberInput > div > div > input {{
                min-height: 2.85rem !important;
                border-radius: 0.98rem !important;
                border: 1px solid rgba(255,255,255,0.07) !important;
                background: rgba(15, 24, 38, 0.92) !important;
                color: #edf8ff !important;
                font-size: 0.82rem !important;
                font-weight: 700 !important;
                padding-left: 0.86rem !important;
            }}
            .st-key-mobile_auth_overlay .stTextInput > div > div > input::placeholder,
            .st-key-mobile_auth_overlay .stNumberInput > div > div > input::placeholder {{
                color: #6f8398 !important;
                opacity: 1 !important;
            }}
            .st-key-mobile_auth_overlay [data-testid="stForm"] {{
                border: none !important;
                background: transparent !important;
                padding: 0 !important;
                box-shadow: none !important;
            }}
            .st-key-mobile_auth_overlay .stFormSubmitButton > button,
            .st-key-mobile_auth_overlay [data-testid="stFormSubmitButton"] > button {{
                min-height: 2.9rem !important;
                border-radius: 1rem !important;
                font-size: 0.78rem !important;
            }}
            .st-key-mobile_auth_overlay [data-testid="stAlert"] {{
                border-radius: 1rem !important;
            }}
            .st-key-mobile_auth_overlay .fw-mobile-auth-status-card,
            .st-key-mobile_auth_overlay .fw-mobile-auth-link-row,
            .st-key-mobile_auth_overlay .fw-mobile-auth-link-single {{
                max-width: none;
                margin-left: 0;
                margin-right: 0;
            }}
            </style>
            <div class="fw-mobile-auth-overlay-head">
                <a class="fw-mobile-auth-overlay-close" href="{escape(landing_href, quote=True)}" target="_self">Close</a>
                <div class="fw-mobile-auth-overlay-tabs">
                    <a class="fw-mobile-auth-overlay-tab{login_active}" href="{escape(login_href, quote=True)}" target="_self">Login</a>
                    <a class="fw-mobile-auth-overlay-tab{register_active}" href="{escape(register_href, quote=True)}" target="_self">Sign Up</a>
                </div>
            </div>
            {reset_badge}
            """
        ),
        unsafe_allow_html=True,
    )


def _client_request_context():
    headers = getattr(st.context, "headers", {}) or {}
    user_agent = ""
    for header_name in ("user-agent", "x-original-user-agent", "x-device-user-agent"):
        try:
            header_value = headers.get(header_name, "")
        except Exception:
            header_value = ""
        if isinstance(header_value, (list, tuple)):
            header_value = " ".join(str(item) for item in header_value if item is not None)
        header_value = str(header_value or "").strip()
        if header_value:
            user_agent = header_value
            break
    ip_address = str(getattr(st.context, "ip_address", "") or "")
    return user_agent, ip_address


def _request_header_value(*names: str) -> str:
    try:
        headers = getattr(st.context, "headers", {}) or {}
    except Exception:
        headers = {}

    def _normalize(value) -> str:
        if isinstance(value, (list, tuple)):
            return " ".join(str(item) for item in value if item is not None).strip()
        return str(value or "").strip()

    for name in names:
        try:
            direct = _normalize(headers.get(name, ""))
        except Exception:
            direct = ""
        if direct:
            return direct

    try:
        items = list(headers.items())
    except Exception:
        items = []

    for name in names:
        lowered = str(name or "").lower()
        for key, value in items:
            if str(key or "").lower() == lowered:
                normalized = _normalize(value)
                if normalized:
                    return normalized
    return ""


def _request_uses_https() -> bool:
    try:
        headers = getattr(st.context, "headers", {}) or {}
    except Exception:
        headers = {}

    def _header(name: str) -> str:
        try:
            value = headers.get(name, "")
        except Exception:
            return ""
        if isinstance(value, (list, tuple)):
            return " ".join(str(item) for item in value if item is not None)
        return str(value or "")

    forwarded_proto = _header("X-Forwarded-Proto").lower()
    if "https" in forwarded_proto:
        return True

    forwarded_scheme = _header("X-Forwarded-Scheme").lower()
    if "https" in forwarded_scheme:
        return True

    forwarded = _header("Forwarded").lower()
    if "proto=https" in forwarded:
        return True

    origin = _header("Origin").lower()
    if origin.startswith("https://"):
        return True

    referer = _header("Referer").lower()
    if referer.startswith("https://"):
        return True

    return is_production_environment()


def _session_expiry_seconds(remember_me: bool) -> int:
    if remember_me:
        return REMEMBER_SESSION_DAYS * 86400
    return SHORT_SESSION_HOURS * 3600


def _cleanup_expired_sessions(now: float = None):
    now = time.time() if now is None else now
    try:
        cursor.execute(
            "DELETE FROM user_sessions WHERE expires_at < ? OR (revoked_at > 0 AND revoked_at < ?)",
            (now, now - 86400),
        )
        conn.commit()
        return True
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        if is_database_locked_error(exc):
            return False
        raise


def create_user_session(username: str, remember_me: bool = True) -> str:
    _cleanup_expired_sessions()
    user_agent, ip_address = _client_request_context()
    now = time.time()
    session_id = secrets.token_urlsafe(18)
    session_key = secrets.token_urlsafe(24)
    token = _build_session_token(session_id, session_key)
    expires_at = now + _session_expiry_seconds(remember_me)
    cursor.execute(
        """
        INSERT INTO user_sessions (
            session_id, username, session_secret_hash, created_at, last_seen_at,
            expires_at, remember_me, user_agent, ip_address, revoked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            session_id,
            username,
            _session_key_hash(session_key),
            now,
            now,
            expires_at,
            1 if remember_me else 0,
            user_agent[:512],
            ip_address[:128],
        ),
    )
    conn.commit()
    st.session_state.auth_session_id = session_id
    st.session_state.auth_session_token = token
    _queue_auth_cookie(token, expires_at=expires_at, clear=False)
    return token


def _finish_password_login(username: str, *, remember_me: bool = True, nav_choice: str = "Dashboard"):
    create_user_session(username, remember_me=remember_me)
    st.session_state.logged_in = True
    st.session_state.username = username
    st.session_state.nav_choice = nav_choice
    st.session_state.login_notice = f"Signed in as {username}"
    st.session_state.auth_view = "landing"


def revoke_user_session(session_id: str = ""):
    target_session_id = session_id or st.session_state.get("auth_session_id", "")
    if not target_session_id:
        return
    cursor.execute(
        "UPDATE user_sessions SET revoked_at = ? WHERE session_id = ?",
        (time.time(), target_session_id),
    )
    conn.commit()


def _logout_active_session():
    revoke_user_session()
    _queue_auth_cookie(clear=True)
    _clear_auth_identity()


def _ensure_signed_session_for_active_login():
    if not st.session_state.get("logged_in"):
        return
    username = str(st.session_state.get("username", "") or "").strip()
    if not username:
        return
    if st.session_state.get("auth_session_token"):
        return
    create_user_session(username, remember_me=True)


def _restore_signed_session_from_request():
    if st.session_state.get("logged_in") and st.session_state.get("username"):
        st.session_state.pending_signed_session = {}
        return
    _cleanup_expired_sessions()
    cookie_token = str((getattr(st.context, "cookies", {}) or {}).get(SESSION_COOKIE_NAME, "") or "").strip()
    if not cookie_token:
        st.session_state.pending_signed_session = {}
        return
    parsed = _parse_session_token(cookie_token)
    if not parsed:
        st.session_state.pending_signed_session = {}
        _queue_auth_cookie(clear=True)
        return
    session_id, session_key = parsed
    cursor.execute(
        """
        SELECT username, session_secret_hash, last_seen_at, expires_at, revoked_at
        FROM user_sessions
        WHERE session_id = ?
        LIMIT 1
        """,
        (session_id,),
    )
    row = cursor.fetchone()
    if not row:
        st.session_state.pending_signed_session = {}
        _queue_auth_cookie(clear=True)
        return
    username, secret_hash, last_seen_at, expires_at, revoked_at = row
    if float(revoked_at or 0) > 0 or float(expires_at or 0) < time.time():
        st.session_state.pending_signed_session = {}
        _queue_auth_cookie(clear=True)
        return
    if not hmac.compare_digest(str(secret_hash or ""), _session_key_hash(session_key)):
        st.session_state.pending_signed_session = {}
        _queue_auth_cookie(clear=True)
        return
    now = time.time()
    if abs(now - float(last_seen_at or 0)) >= SESSION_TOUCH_INTERVAL_SECONDS:
        cursor.execute(
            "UPDATE user_sessions SET last_seen_at = ? WHERE session_id = ?",
            (now, session_id),
        )
        conn.commit()
    restored_username = str(username or "").strip()
    st.session_state.logged_in = True
    st.session_state.username = restored_username
    st.session_state.auth_session_id = session_id
    st.session_state.auth_session_token = cookie_token
    st.session_state.pending_signed_session = {}
    if not str(st.session_state.get("nav_choice", "") or "").strip():
        st.session_state.nav_choice = "Dashboard"
    if not st.session_state.get("otp_sent") and not st.session_state.get("awaiting_oauth"):
        st.session_state.auth_view = "landing"
        st.session_state._auth_entry_landing_seen = True


def _render_auth_cookie_bridge():
    action = st.session_state.get("auth_cookie_action") or {}
    if not action:
        return
    secure_cookie = _request_uses_https()
    cookie_html = dedent(
        f"""
        <!doctype html>
        <html>
        <body style="margin:0;background:transparent;"></body>
        <script>
        (function() {{
          const name = {json.dumps(action.get("name", SESSION_COOKIE_NAME))};
          const value = {json.dumps(action.get("value", ""))};
          const clearCookie = {str(bool(action.get("clear"))).lower()};
          const expiresAt = {json.dumps(float(action.get("expires_at", 0) or 0))};
          let cookie = name + "=" + encodeURIComponent(value) + "; path=/; SameSite=Lax;";
          if ({str(secure_cookie).lower()}) {{
            cookie += " Secure;";
          }}
          if (clearCookie) {{
            cookie += " expires=Thu, 01 Jan 1970 00:00:00 GMT;";
          }} else if (expiresAt > 0) {{
            cookie += " expires=" + new Date(expiresAt * 1000).toUTCString() + ";";
          }}
          document.cookie = cookie;
        }})();
        </script>
        </html>
        """
    ).strip()
    components.html(cookie_html, height=0, width=0)
    st.session_state.auth_cookie_action = {}


_restore_signed_session_from_request()
_ensure_signed_session_for_active_login()
_render_auth_cookie_bridge()
_ensure_streamlit_mobile_proxy_routes()


# -----------------------------------
# GMAIL OAUTH
# -----------------------------------
def generate_pkce_verifier():
    return secrets.token_urlsafe(64)


def generate_pkce_challenge(verifier):
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def get_oauth_config():
    credentials_path = os.getenv("GOOGLE_OAUTH_CREDENTIALS_FILE", "credentials.json")
    token_path = os.getenv("GOOGLE_OAUTH_TOKEN_FILE", "token.json")
    redirect_uri = os.getenv("OAUTH_REDIRECT_URI")
    gmail_address = os.getenv("GMAIL_ADDRESS")
    try:
        actual_port = int(st.get_option("server.port") or 8051)
    except Exception:
        actual_port = 8051
    redirect_uri = resolve_redirect_uri(
        redirect_uri,
        default_port=actual_port,
        service_name="Gmail OAuth",
    )
    return credentials_path, token_path, redirect_uri, gmail_address


def save_credentials(creds, token_path):
    save_app_token_payload(
        token_path,
        {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes) if creds.scopes else [],
            "expiry": creds.expiry.isoformat() if getattr(creds, "expiry", None) else None,
        },
    )


def load_credentials(token_path):
    info = load_app_token_payload(token_path)
    if info is None and os.path.exists(token_path):
        try:
            with open(token_path) as f:
                info = json.load(f)
        except Exception as e:
            print(f"load_credentials file fallback error: {e}")
            info = None
    if not info:
        return None
    try:
        creds = Credentials.from_authorized_user_info(info, SCOPES)
        if creds and creds.refresh_token and (creds.expired or not getattr(creds, "expiry", None)):
            with _gmail_direct_network_env():
                creds.refresh(Request())
            save_credentials(creds, token_path)
        return creds if (creds and creds.valid) else None
    except Exception as e:
        print(f"load_credentials error: {e}")
        return None


def get_gmail_oauth_credentials(credentials_path, token_path, redirect_uri, pending_username="", *, allow_interactive_oauth=True):
    if not os.path.exists(credentials_path):
        return None, f"Missing OAuth credentials file: {credentials_path}"
    creds = load_credentials(token_path)
    if creds and creds.valid:
        return creds, None

    code = st.session_state.get("oauth_code", "")
    state = st.session_state.get("oauth_code_state", "")
    state_record = load_gmail_oauth_state(state)

    if code and state and state_record:
        last_error = None
        code_verifier = state_record.get("code_verifier")
        for attempt in range(3):
            try:
                flow = Flow.from_client_secrets_file(
                    credentials_path, scopes=SCOPES, state=state
                )
                flow.redirect_uri = redirect_uri
                auth_resp = f"{redirect_uri}?code={code}&state={state}"
                with _gmail_direct_network_env():
                    if code_verifier:
                        flow.fetch_token(
                            authorization_response=auth_resp,
                            code_verifier=code_verifier,
                        )
                    else:
                        flow.fetch_token(authorization_response=auth_resp)
                creds = flow.credentials
                save_credentials(creds, token_path)
                clear_gmail_oauth_state(state)
                st.session_state["oauth_code"] = ""
                st.session_state["oauth_code_state"] = ""
                return creds, None
            except Exception as e:
                last_error = e
                print(f"Token exchange attempt {attempt+1} failed: {e}")
                time.sleep(1)
        return None, f"OAuth token exchange failed after 3 attempts: {last_error}"

    if not allow_interactive_oauth:
        return None, "Gmail sender authorization is not ready. Ask the app owner to reconnect the sender account."

    try:
        code_verifier = generate_pkce_verifier()
        code_challenge = generate_pkce_challenge(code_verifier)
        flow = Flow.from_client_secrets_file(credentials_path, scopes=SCOPES)
        flow.redirect_uri = redirect_uri
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            code_challenge=code_challenge,
            code_challenge_method="S256",
        )
        save_gmail_oauth_state(
            state,
            code_verifier,
            pending_username=pending_username or st.session_state.get("pending_username", ""),
        )
        st.session_state.oauth_state = state
        return None, auth_url
    except Exception as e:
        return None, f"OAuth setup failed: {e}"


_cleanup_auth_records()


def build_xoauth2_string(email, access_token):
    auth_string = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
    return base64.b64encode(auth_string.encode()).decode()

def send_email_otp(email, username, *, purpose: str = "verification"):
    try:
        credentials_path, token_path, redirect_uri, gmail_address = get_oauth_config()
    except RuntimeError as exc:
        suffix = " Configure a public HTTPS callback before deploying." if is_production_environment() else ""
        st.error(f"❌ {exc}{suffix}")
        return False
    local_fallback = _allow_local_email_fallback()
    if not gmail_address:
        if local_fallback:
            otp = generate_otp(username)
            st.success(_local_email_otp_message(email, otp, purpose=purpose))
            return True
        st.error("❌ GMAIL_ADDRESS is not configured in .env file.")
        return False
    if not os.path.exists(credentials_path):
        if local_fallback:
            otp = generate_otp(username)
            st.success(_local_email_otp_message(email, otp, purpose=purpose))
            return True
        st.error(f"❌ OAuth credentials file not found: {credentials_path}")
        return False

    normalized_purpose = str(purpose or "").strip().lower()
    if normalized_purpose not in {"verification", "password_reset", "password_change"}:
        normalized_purpose = "verification"
    if normalized_purpose == "password_reset":
        st.session_state.oauth_return_auth_view = ""
        st.session_state.awaiting_oauth = False
        st.session_state.oauth_returned = False
    elif normalized_purpose == "verification":
        st.session_state.oauth_return_auth_view = "register"

    def _do_send(creds):
        otp = generate_otp(username)
        if normalized_purpose == "password_reset":
            msg = MIMEText(f"Your Finwise AI password reset code is: {otp}\n\nValid for 5 minutes.")
            msg["Subject"] = "Finwise AI - Password Reset Code"
            success_copy = f"✅ Password reset code sent to {email}"
        elif normalized_purpose == "password_change":
            msg = MIMEText(f"Your Finwise AI password change verification code is: {otp}\n\nValid for 5 minutes.")
            msg["Subject"] = "Finwise AI - Password Change Verification Code"
            success_copy = f"✅ Password change code sent to {email}"
        else:
            msg = MIMEText(f"Your Finwise AI OTP is: {otp}\n\nValid for 5 minutes.")
            msg["Subject"] = "Finwise AI - Verification Code"
            success_copy = f"✅ OTP sent to {email}"
        msg["From"]    = gmail_address
        msg["To"]      = email
        server = None
        try:
            server = smtplib.SMTP("smtp.gmail.com", 587)
            server.ehlo()
            server.starttls()
            server.ehlo()
            auth_string = build_xoauth2_string(gmail_address, creds.token)
            code, _ = server.docmd("AUTH", f"XOAUTH2 {auth_string}")
            if code != 235:
                raise Exception(f"XOAUTH2 auth failed with code {code}")
            server.send_message(msg)
            st.success(success_copy)
            return True
        except Exception as e:
            if normalized_purpose == "password_reset":
                APP_LOGGER.warning("Password reset email delivery failed: %s", e)
                return False
            _show_safe_operation_error("Email delivery", e)
            return False
        finally:
            try:
                if server:
                    server.quit()
            except Exception:
                pass

    creds, oauth_result = get_gmail_oauth_credentials(
        credentials_path,
        token_path,
        redirect_uri,
        pending_username=username,
        allow_interactive_oauth=normalized_purpose != "password_reset",
    )
    if creds is not None and creds.valid:
        return _do_send(creds)
    if local_fallback:
        otp = generate_otp(username)
        st.success(_local_email_otp_message(email, otp, purpose=purpose))
        return True
    if oauth_result and oauth_result.startswith("http"):
        st.warning("⚠️ Gmail authorization required. Click the link below:")
        st.markdown(f"[🔐 Authorize Gmail Access]({oauth_result})")
        st.info("After authorizing, you will be redirected back here automatically.")
        st.session_state.awaiting_oauth = True
        st.stop()
    if normalized_purpose == "password_reset":
        APP_LOGGER.warning("Password reset email not sent because Gmail sender is unavailable: %s", oauth_result)
        return False
    st.error(f"❌ OAuth Error: {oauth_result}")
    return False


def _complete_auth_otp_after_oauth_return():
    otp_context = str(st.session_state.get("auth_otp_context", "") or "").strip().lower()
    return_auth_view = str(st.session_state.get("oauth_return_auth_view", "") or "").strip()

    if otp_context == "password_change":
        change_request = st.session_state.get("password_change_request") or {}
        username = str(change_request.get("username") or st.session_state.get("pending_username", "") or "").strip()
        email = str(change_request.get("email") or st.session_state.get("pending_email", "") or "").strip()
        user = load_registered_user(username, email)
        if user and user.get("email"):
            st.session_state.password_change_request = {
                "username": user["username"],
                "email": user["email"],
            }
            st.session_state.pending_username = user["username"]
            st.session_state.pending_email = user["email"]
            success = send_email_otp(user["email"], user["username"], purpose="password_change")
            st.session_state.awaiting_oauth = False
            st.session_state.oauth_returned = False
            if success:
                st.session_state.password_change_sent = True
                st.session_state.password_change_verified = False
                st.session_state.nav_choice = "Account"
                st.session_state.account_settings_view = "change_password"
                st.rerun()
            st.warning("⚠️ Password change code sending failed. Please try again.")
            st.rerun()
        else:
            clear_password_change_state()
            st.warning("⚠️ Password change session expired. Please start again.")
            st.session_state.awaiting_oauth = False
            st.session_state.oauth_returned = False
            st.session_state.nav_choice = "Account"
            st.rerun()
        return

    if otp_context == "password_reset":
        st.session_state.auth_view = "reset_password"
        st.session_state._auth_entry_landing_seen = True
        reset_request = st.session_state.get("password_reset_request") or {}
        username = str(reset_request.get("username") or st.session_state.get("pending_username", "") or "").strip()
        email = str(reset_request.get("email") or st.session_state.get("pending_email", "") or "").strip()
        user = load_registered_user(username, email)
        if user:
            st.session_state.password_reset_request = {
                "username": user["username"],
                "email": user["email"],
            }
            st.session_state.pending_username = user["username"]
            st.session_state.pending_email = user["email"]
            success = send_email_otp(user["email"], user["username"], purpose="password_reset")
            st.session_state.awaiting_oauth = False
            st.session_state.oauth_returned = False
            if success:
                st.session_state.password_reset_sent = True
                st.session_state.password_reset_verified = False
                st.session_state.auth_view = "reset_password"
                st.session_state.oauth_return_auth_view = ""
                st.rerun()
            st.warning("⚠️ Reset code sending failed. Please try again.")
            st.rerun()
        else:
            clear_password_reset_state()
            st.warning("⚠️ Password reset session expired. Please start again.")
            st.session_state.awaiting_oauth = False
            st.session_state.oauth_returned = False
            st.session_state.auth_view = "reset_password"
            st.session_state.oauth_return_auth_view = ""
            st.rerun()
        return

    pending = load_pending_user(
        username=st.session_state.get("pending_username", ""),
        oauth_state=st.session_state.get("oauth_code_state", ""),
    )
    if pending:
        st.session_state.temp_user = pending
        st.session_state.pending_email = pending["email"]
        st.session_state.pending_username = pending["username"]
        if return_auth_view:
            st.session_state.auth_view = return_auth_view
            st.session_state._auth_entry_landing_seen = True
        success = send_email_otp(pending["email"], pending["username"])
        st.session_state.awaiting_oauth = False
        st.session_state.oauth_returned = False
        if success:
            st.session_state.otp_sent = True
            st.session_state.oauth_return_auth_view = ""
            st.rerun()
        st.warning("⚠️ OTP sending failed. Please try registering again.")
        st.rerun()

    st.warning("⚠️ Session expired. Please fill in your details and try again.")
    st.session_state.awaiting_oauth = False
    st.session_state.oauth_returned = False
    if return_auth_view:
        st.session_state.auth_view = return_auth_view
        st.session_state._auth_entry_landing_seen = True
        st.session_state.oauth_return_auth_view = ""
    st.rerun()


def _render_password_reset_flow(mobile: bool = False):
    prefix = ""
    reset_request = st.session_state.get("password_reset_request") or {}
    def _field(label: str, key: str, *, password: bool = False, placeholder: str = "") -> str:
        if mobile:
            st.markdown(
                f'<div class="fw-mobile-auth-field-label">{escape(label)}</div>',
                unsafe_allow_html=True,
            )
        return st.text_input(
            label,
            key=key,
            type="password" if password else "default",
            placeholder=placeholder if mobile else None,
            label_visibility="collapsed" if mobile else "visible",
        ).strip()

    if st.session_state.get("password_reset_sent") and not str(reset_request.get("username", "") or "").strip():
        clear_password_reset_state()
        st.warning("⚠️ Password reset session expired. Please start again.")
        st.session_state.auth_view = "reset_password"

    if not st.session_state.get("password_reset_sent"):
        with st.form(f"{prefix}password_reset_request_form"):
            username = _field(
                "Username",
                key=f"{prefix}password_reset_username_field",
                placeholder="Your workspace username",
            )
            email = _field(
                "Email",
                key=f"{prefix}password_reset_email_field",
                placeholder="Email attached to this account",
            )
            send_reset = st.form_submit_button("Send Reset Code", use_container_width=True, type="primary")

        if send_reset:
            if not username or not email:
                st.error("Please enter your username and email.")
                st.stop()
            auth_status = _mobile_email_auth_status()
            if not auth_status.get("enabled"):
                st.error(auth_status.get("message", "Email verification is unavailable."))
                st.stop()
            user = load_registered_user(username, email)
            if not user:
                st.error("We couldn't match that username and email.")
                st.stop()
            if not user.get("email"):
                st.error("This account does not have an email address saved for password reset.")
                st.stop()
            st.session_state.password_reset_request = {
                "username": user["username"],
                "email": user["email"],
            }
            st.session_state.pending_username = user["username"]
            st.session_state.pending_email = user["email"]
            st.session_state.auth_otp_context = "password_reset"
            if send_email_otp(user["email"], user["username"], purpose="password_reset"):
                st.session_state.password_reset_sent = True
                st.session_state.password_reset_verified = False
                st.session_state.auth_view = "reset_password"
                st.rerun()
            st.error("We could not send the reset code right now. Gmail OAuth token may be missing or expired.")
        return

    username = str(reset_request.get("username") or "").strip()
    email = str(reset_request.get("email") or "").strip()

    if not st.session_state.get("password_reset_verified"):
        if mobile:
            _render_mobile_auth_feedback(
                f"We sent a reset code to {email or 'your email'}. The code is valid for about 10 minutes.",
                title="Reset Code Sent",
                kind="success",
            )
        else:
            st.info(f"Reset code sent to {email or 'your email'}. The code is valid for about 10 minutes.")

        with st.form(f"{prefix}password_reset_verify_code_form"):
            otp = _field(
                "Reset Code",
                key=f"{prefix}password_reset_code_field",
                placeholder="Enter the code from your email",
            )
            verify_submit = st.form_submit_button("Verify Code", use_container_width=True, type="primary")

        if verify_submit:
            if not otp:
                st.error("Please enter the reset code.")
                st.stop()
            if verify_otp(username, otp):
                st.session_state.password_reset_verified = True
                st.rerun()
            st.error("Invalid or expired reset code. Please try again.")

        if mobile:
            _render_mobile_auth_links(
                [
                    ("Resend Code", _mobile_auth_href(auth="reset_password", action="resend_reset_code"), False),
                    ("Start Over", _mobile_auth_href(auth="reset_password", action="restart_reset"), True),
                ]
            )
            return

        verify_action_left, verify_action_right = st.columns(2, gap="medium")
        with verify_action_left:
            if st.button("Resend Code", key=f"{prefix}resend_password_reset_code", use_container_width=True):
                user = load_registered_user(username, email)
                if not user or not user.get("email"):
                    clear_password_reset_state()
                    st.warning("âš ï¸ Password reset session expired. Please start again.")
                    st.session_state.auth_view = "reset_password"
                    st.rerun()
                st.session_state.pending_username = user["username"]
                st.session_state.pending_email = user["email"]
                st.session_state.auth_otp_context = "password_reset"
                if send_email_otp(user["email"], user["username"], purpose="password_reset"):
                    st.session_state.password_reset_sent = True
                    st.session_state.password_reset_verified = False
                    st.rerun()
                st.error("We could not send the reset code right now. Gmail OAuth token may be missing or expired.")
        with verify_action_right:
            if st.button("Start Over", key=f"{prefix}restart_password_reset", use_container_width=True):
                clear_password_reset_state()
                st.session_state.auth_view = "reset_password"
                st.rerun()
        return

    if mobile:
        _render_mobile_auth_feedback(
            "Code verified. Choose your new password.",
            title="Verified",
            kind="success",
        )
    else:
        st.success("Code verified. Choose your new password.")
    with st.form(f"{prefix}password_reset_password_form"):
        new_password = _field(
            "New Password",
            key=f"{prefix}password_reset_new_password_field",
            password=True,
            placeholder="Create a new password",
        )
        confirm_password = _field(
            "Confirm New Password",
            key=f"{prefix}password_reset_confirm_password_field",
            password=True,
            placeholder="Confirm the new password",
        )
        reset_submit = st.form_submit_button("Update Password", use_container_width=True, type="primary")

    if reset_submit:
        if not new_password or not confirm_password:
            st.error("Please fill in both password fields.")
            st.stop()
        if new_password != confirm_password:
            st.error("New password and confirmation do not match.")
            st.stop()
        password_ok, password_error = password_meets_policy(new_password)
        if not password_ok:
            st.error(password_error)
            st.stop()
        update_user_password(username, new_password)
        clear_login_failures(username)
        clear_password_reset_state()
        st.session_state.auth_notice = "Password updated. Sign in with your new password."
        st.session_state.auth_view = "login"
        st.session_state.login_username_field = username
        st.session_state.login_password_field = ""
        st.rerun()

    if mobile:
        _render_mobile_auth_links(
            [
                ("Use Another Code", _mobile_auth_href(auth="reset_password", action="reset_code_again"), True),
                ("Back to Login", _mobile_auth_href(auth="login", action="reset_to_login"), False),
            ]
        )
        return

    password_action_left, password_action_right = st.columns(2, gap="medium")
    with password_action_left:
        if st.button("Use Another Code", key=f"{prefix}restart_password_reset_code_step", use_container_width=True):
            st.session_state.password_reset_verified = False
            st.rerun()
    with password_action_right:
        if st.button("Back to Login", key=f"{prefix}back_to_login_from_reset", use_container_width=True):
            clear_password_reset_state()
            st.session_state.auth_view = "login"
            st.rerun()

# -----------------------------------
# LOGIN / REGISTER
# -----------------------------------
def login_page():
    mobile_layout = _resolve_viewport_mode() == "mobile"
    if mobile_layout and _can_use_standalone_mobile():
        try:
            mobile_auth_target = str(st.query_params.get("auth", "") or "").strip().lower()
        except Exception:
            mobile_auth_target = ""
        _render_mobile_web_redirect("Trading Desk", auth_view=mobile_auth_target)
        return
    if not mobile_layout:
        st.markdown('<div class="public-page-label">Finwise AI</div>', unsafe_allow_html=True)

    resume_requested = _consume_transient_query_param("resume_session").lower()
    if resume_requested in {"1", "true", "yes", "on"}:
        if _resume_pending_signed_session():
            st.rerun()

    try:
        auth_override = str(st.query_params.get("auth", "") or "").strip().lower()
    except Exception:
        auth_override = ""
    auth_override_map = {
        "landing": "landing",
        "login": "login",
        "register": "register",
        "reset": "reset_password",
        "reset_password": "reset_password",
    }
    if auth_override in auth_override_map:
        st.session_state.auth_view = auth_override_map[auth_override]

    mobile_auth_action = _consume_transient_query_param("auth_action").lower()
    if mobile_auth_action:
        _handle_mobile_auth_action(mobile_auth_action)

    if st.session_state.get("awaiting_oauth") and st.session_state.get("oauth_returned"):
        st.info("⏳ Completing Gmail authorization, please wait...")
        _complete_auth_otp_after_oauth_return()
        return

    if not st.session_state.get("_auth_entry_landing_seen") and not st.session_state.get("otp_sent"):
        if auth_override not in auth_override_map:
            st.session_state.auth_view = "landing"
        st.session_state._auth_entry_landing_seen = True

    auth_view = st.session_state.get("auth_view", "landing")
    if auth_view not in {"landing", "login", "register", "reset_password"}:
        auth_view = "landing"
        st.session_state.auth_view = auth_view
    if auth_view == "landing" and st.session_state.get("otp_sent"):
        auth_view = "register"
        st.session_state.auth_view = auth_view
    if auth_view == "landing" and st.session_state.get("password_reset_sent"):
        auth_view = "reset_password"
        st.session_state.auth_view = auth_view

    auth_notice = str(st.session_state.pop("auth_notice", "") or "").strip()
    auth_error = str(st.session_state.pop("auth_error", "") or "").strip()
    mobile_auth_feedback_in_modal = mobile_layout and auth_view != "landing"
    desktop_auth_feedback_in_modal = (not mobile_layout) and auth_view != "landing"
    if auth_notice:
        if mobile_layout and not mobile_auth_feedback_in_modal:
            _render_mobile_auth_feedback(auth_notice, title="Done", kind="success")
        elif not desktop_auth_feedback_in_modal:
            st.success(auth_notice)
    if auth_error:
        if mobile_layout and not mobile_auth_feedback_in_modal:
            _render_mobile_auth_feedback(auth_error, title="Action Needed", kind="error")
        elif not desktop_auth_feedback_in_modal:
            st.error(auth_error)

    hero_display = "block" if auth_view == "landing" else "none"
    hero_logo = (
        f'<img src="{APP_LOGO_DATA_URI}" alt="Finwise AI logo" />'
        if APP_LOGO_DATA_URI else
        "<span>F</span>"
    )
    if mobile_layout:
        _render_mobile_auth_landing(hero_logo, auth_view=auth_view)
        if auth_view == "landing":
            return

    if mobile_layout and auth_view == "login":
        with st.container(key="mobile_auth_overlay"):
            _render_mobile_auth_overlay_shell(auth_view=auth_view)
            st.markdown(
                """
                <div class="fw-mobile-auth-overlay-headline">
                    <div class="fw-mobile-auth-overlay-headline-kicker">Login</div>
                    <div class="fw-mobile-auth-overlay-headline-title">Welcome back to Finwise AI.</div>
                    <div class="fw-mobile-auth-overlay-headline-copy">Sign in and return to your market workspace without leaving the mobile surface.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if auth_notice:
                _render_mobile_auth_feedback(auth_notice, title="Done", kind="success")
            if auth_error:
                _render_mobile_auth_feedback(auth_error, title="Action Needed", kind="error")
            with st.form("login_form"):
                st.markdown('<div class="fw-mobile-auth-field-label">Username</div>', unsafe_allow_html=True)
                username = st.text_input(
                    "Username",
                    key="login_username_field",
                    placeholder="Your workspace username",
                    label_visibility="collapsed",
                ).strip()
                st.markdown('<div class="fw-mobile-auth-field-label">Password</div>', unsafe_allow_html=True)
                password = st.text_input(
                    "Password",
                    key="login_password_field",
                    type="password",
                    placeholder="Your password",
                    label_visibility="collapsed",
                )
                login_submit = st.form_submit_button("Login To Workspace", use_container_width=True, type="primary")

            if login_submit:
                if not username or not password:
                    st.error("Please enter your username and password.")
                    st.stop()
                lock_message = get_login_lock_message(username)
                if lock_message:
                    st.error(lock_message)
                    st.stop()
                account = authenticate_registered_user(username, password)
                if account:
                    clear_login_failures(username)
                    clear_login_failures(account["username"])
                    _finish_password_login(account["username"])
                    st.rerun()
                record_login_failure(username)
                lock_message = get_login_lock_message(username)
                if lock_message:
                    st.error(lock_message)
                else:
                    st.error("Invalid username or password.")

            _render_mobile_auth_links(
                [
                    ("Forgot Password", _mobile_auth_href(auth="reset_password", action="to_reset"), True),
                    ("Create Account", _mobile_auth_href(auth="register"), False),
                ]
            )
        return

    if mobile_layout and auth_view == "register":
        with st.container(key="mobile_auth_overlay"):
            _render_mobile_auth_overlay_shell(auth_view=auth_view)
            st.markdown(
                """
                <div class="fw-mobile-auth-overlay-headline">
                    <div class="fw-mobile-auth-overlay-headline-kicker">Register</div>
                    <div class="fw-mobile-auth-overlay-headline-title">Create your Finwise AI workspace.</div>
                    <div class="fw-mobile-auth-overlay-headline-copy">Set up your account, verify your email, and move straight into the live trading flow.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if auth_notice:
                _render_mobile_auth_feedback(auth_notice, title="Done", kind="success")
            if auth_error:
                _render_mobile_auth_feedback(auth_error, title="Action Needed", kind="error")
            if not st.session_state.otp_sent:
                with st.form("register_details_form"):
                    st.markdown('<div class="fw-mobile-auth-field-label">Username</div>', unsafe_allow_html=True)
                    username = st.text_input(
                        "Username",
                        key="register_username_field",
                        placeholder="Choose a workspace username",
                        label_visibility="collapsed",
                    ).strip()
                    st.markdown('<div class="fw-mobile-auth-field-label">Password</div>', unsafe_allow_html=True)
                    password = st.text_input(
                        "Password",
                        key="register_password_field",
                        type="password",
                        placeholder="Create a strong password",
                        label_visibility="collapsed",
                    )
                    st.markdown('<div class="fw-mobile-auth-field-label">Email</div>', unsafe_allow_html=True)
                    email = st.text_input(
                        "Email",
                        key="register_email_field",
                        placeholder="you@example.com",
                        label_visibility="collapsed",
                    ).strip()
                    st.markdown('<div class="fw-mobile-auth-field-label">Phone</div>', unsafe_allow_html=True)
                    phone = st.text_input(
                        "Phone (+234...)",
                        key="register_phone_field",
                        placeholder="+234...",
                        label_visibility="collapsed",
                    ).strip()
                    send_otp = st.form_submit_button("Send Verification Code", use_container_width=True, type="primary")

                if send_otp:
                    if not email or not username or not password:
                        st.error("Please fill in all required fields.")
                        st.stop()
                    password_ok, password_error = password_meets_policy(password)
                    if not password_ok:
                        st.error(password_error)
                        st.stop()
                    cursor.execute("SELECT 1 FROM users WHERE username=?", (username,))
                    if cursor.fetchone():
                        st.error("Username already exists. Please choose another.")
                        st.stop()
                    pw_hash = hash_password(password)
                    save_pending_user(username, pw_hash, email, phone)
                    st.session_state.pending_email = email
                    st.session_state.pending_username = username
                    st.session_state.temp_user = {
                        "username": username,
                        "password": pw_hash.decode() if isinstance(pw_hash, bytes) else pw_hash,
                        "email": email,
                        "phone": phone,
                    }
                    st.session_state.auth_otp_context = "register"
                    if send_email_otp(email, username):
                        st.session_state.otp_sent = True
                        st.rerun()
                    st.error("We could not send the OTP right now. Please try again.")

            if st.session_state.otp_sent:
                pending_email = str((st.session_state.get("temp_user") or {}).get("email") or "your email")
                _render_mobile_auth_feedback(
                    f"We sent a verification code to {pending_email}. Enter it below to finish creating your workspace.",
                    title="Verification Code Sent",
                    kind="success",
                )
                with st.form("register_otp_form"):
                    st.markdown('<div class="fw-mobile-auth-field-label">OTP Code</div>', unsafe_allow_html=True)
                    otp = st.text_input(
                        "Enter OTP",
                        key="register_otp_field",
                        placeholder="Enter the code from your email",
                        label_visibility="collapsed",
                    ).strip()
                    verify_submit = st.form_submit_button("Verify and Create Account", use_container_width=True, type="primary")

                if verify_submit:
                    if not otp:
                        st.error("Please enter the OTP.")
                        st.stop()
                    stored_username = st.session_state.temp_user.get("username", "")
                    if verify_otp(stored_username, otp):
                        data = st.session_state.temp_user
                        try:
                            create_registered_user(
                                data["username"],
                                data["password"],
                                data["email"],
                                data.get("phone", ""),
                            )
                            st.session_state.otp_sent = False
                            st.session_state.temp_user = {}
                            st.session_state.auth_otp_context = ""
                            st.session_state.auth_notice = "Account created successfully. Sign in to continue."
                            st.session_state.auth_view = "login"
                            st.session_state.login_username_field = data["username"]
                            clear_pending_user(stored_username)
                            st.balloons()
                            st.rerun()
                        except Exception as e:
                            if is_integrity_error(e):
                                st.error("Username already exists. Please choose another.")
                            else:
                                _show_safe_operation_error("Account creation", e)
                    else:
                        st.error("Invalid or expired OTP. Please try again.")

            if st.session_state.otp_sent:
                _render_mobile_auth_links(
                    [
                        ("Start Over", _mobile_auth_href(auth="register", action="restart_register"), True),
                        ("Go to Login", _mobile_auth_href(auth="login", action="register_to_login"), False),
                    ]
                )
            else:
                _render_mobile_auth_links(
                    [("Already have an account? Login", _mobile_auth_href(auth="login"), False)],
                    single=True,
                )
        return

    if mobile_layout and auth_view == "reset_password":
        with st.container(key="mobile_auth_overlay"):
            _render_mobile_auth_overlay_shell(auth_view=auth_view)
            st.markdown(
                """
                <div class="fw-mobile-auth-overlay-headline">
                    <div class="fw-mobile-auth-overlay-headline-kicker">Reset Password</div>
                    <div class="fw-mobile-auth-overlay-headline-title">Recover access to Finwise AI.</div>
                    <div class="fw-mobile-auth-overlay-headline-copy">Confirm your account email, verify the reset code, and choose a new password from this same mobile sheet.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if auth_notice:
                _render_mobile_auth_feedback(auth_notice, title="Done", kind="success")
            if auth_error:
                _render_mobile_auth_feedback(auth_error, title="Action Needed", kind="error")
            _render_password_reset_flow(mobile=True)
        return

    desktop_landing_href = build_query_href(auth="landing", auth_action=None, resume_session=None)
    desktop_login_href = build_query_href(auth="login", auth_action=None, resume_session=None)
    desktop_register_href = build_query_href(auth="register", auth_action=None, resume_session=None)
    desktop_reset_href = build_query_href(auth="reset_password", auth_action=None, resume_session=None)
    desktop_resume_href = build_query_href(resume_session="1", auth="landing", auth_action=None)
    pending_signed_session = _get_pending_signed_session()
    desktop_resume_markup = ""
    if pending_signed_session:
        desktop_resume_markup = (
            f'<a class="public-hero-action-link public-hero-session" '
            f'href="{escape(desktop_resume_href, quote=True)}" target="_top">'
            f'Continue as {escape(pending_signed_session["username"])}'
            f"</a>"
        )

    st.html(
        dedent(
            f"""
        <style>
        .public-page-label {{
            color:#9bc2d3;
            font-size:12px;
            font-weight:700;
            letter-spacing:0.14em;
            text-transform:uppercase;
            margin-top:4px;
        }}
        .public-hero-head {{
            display:flex;
            align-items:flex-start;
            justify-content:space-between;
            gap:14px;
            margin-bottom:16px;
        }}
        .public-hero-actions {{
            display:flex;
            align-items:center;
            justify-content:flex-end;
            flex-wrap:wrap;
            gap:8px;
            margin-left:auto;
        }}
        .public-hero-action-link {{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            min-height:34px;
            padding:0 12px;
            border-radius:999px;
            border:1px solid rgba(255,255,255,0.08);
            background:rgba(255,255,255,0.03);
            color:#e8f5ff !important;
            text-decoration:none !important;
            font-size:11px;
            font-weight:700;
            letter-spacing:0.04em;
            text-transform:uppercase;
            transition:all .2s ease;
        }}
        .public-hero-action-link:hover {{
            border-color:rgba(0,245,212,0.22);
            color:#ffffff !important;
            transform:translateY(-1px);
        }}
        .public-hero-action-link.is-active {{
            border-color:rgba(0,245,212,0.22);
            background:rgba(0,245,212,0.10);
            color:#d8fffa !important;
        }}
        .public-hero-action-link.is-primary {{
            border-color:rgba(0,245,212,0.16);
            background:rgba(0,245,212,0.08);
            color:#e6fffb !important;
        }}
        .public-hero-session {{
            border-color:rgba(0,245,212,0.16);
            background:rgba(0,245,212,0.08);
            color:#d8fffa !important;
        }}
        .public-hero {{
            position:relative;
            overflow:hidden;
            border-radius:30px;
            padding:36px 34px 32px;
            border:1px solid rgba(0,245,212,0.14);
            background:
                radial-gradient(circle at top right, rgba(0,245,212,0.20), transparent 32%),
                radial-gradient(circle at 12% 18%, rgba(30,78,255,0.18), transparent 24%),
                linear-gradient(180deg, #112338 0%, #0b1827 100%);
            box-shadow:0 24px 60px rgba(0,0,0,0.34);
            margin:16px 0 24px;
            max-width:1180px;
            margin-left:auto;
            margin-right:auto;
        }}
        .public-kicker {{
            display:inline-flex;
            align-items:center;
            gap:8px;
            padding:7px 12px;
            border-radius:999px;
            background:rgba(0,245,212,0.10);
            border:1px solid rgba(0,245,212,0.18);
            color:#a6fff2;
            font-size:11px;
            font-weight:700;
            letter-spacing:0.12em;
            text-transform:uppercase;
        }}
        .public-hero-shell {{
            display:grid;
            grid-template-columns:minmax(0, 1.4fr) minmax(280px, 0.9fr);
            gap:24px;
            align-items:stretch;
            margin-top:18px;
            min-width:0;
        }}
        .public-hero-shell > div,
        .public-hero-visual,
        .public-visual-grid,
        .public-visual-stage-grid,
        .public-proof,
        .public-grid {{
            min-width:0;
        }}
        .public-brand {{
            display:flex;
            align-items:center;
            gap:14px;
        }}
        .public-logo {{
            width:68px;
            height:68px;
            border-radius:22px;
            overflow:hidden;
            flex:0 0 auto;
            background:rgba(255,255,255,0.05);
            border:1px solid rgba(255,255,255,0.08);
            display:flex;
            align-items:center;
            justify-content:center;
        }}
        .public-logo img {{
            width:100%;
            height:100%;
            object-fit:cover;
            display:block;
        }}
        .public-logo span {{
            color:#00f5d4;
            font-size:28px;
            font-weight:800;
        }}
        .public-title {{
            color:white;
            font-size:44px;
            line-height:1.04;
            font-weight:800;
            letter-spacing:-0.03em;
            margin:22px 0 14px;
            max-width:11ch;
            overflow-wrap:anywhere;
        }}
        .public-copy {{
            color:#9bb8c9;
            font-size:15px;
            line-height:1.8;
            max-width:760px;
        }}
        .public-hero-visual {{
            position:relative;
            min-height:100%;
            border-radius:24px;
            padding:20px;
            border:1px solid rgba(255,255,255,0.08);
            background:
                radial-gradient(circle at top right, rgba(0,245,212,0.14), transparent 35%),
                linear-gradient(180deg, rgba(7,19,31,0.92) 0%, rgba(5,13,22,0.96) 100%);
            box-shadow:inset 0 1px 0 rgba(255,255,255,0.03);
        }}
        .public-visual-kicker {{
            color:#7ad8cc;
            font-size:11px;
            font-weight:800;
            letter-spacing:0.12em;
            text-transform:uppercase;
        }}
        .public-visual-header {{
            display:flex;
            justify-content:space-between;
            align-items:flex-start;
            gap:12px;
            margin-top:14px;
        }}
        .public-visual-symbol {{
            color:white;
            font-size:28px;
            font-weight:800;
            letter-spacing:-0.04em;
        }}
        .public-visual-subtitle {{
            color:#7ea8bf;
            font-size:12px;
            margin-top:5px;
        }}
        .public-visual-badge {{
            padding:8px 12px;
            border-radius:999px;
            background:rgba(0,245,212,0.10);
            border:1px solid rgba(0,245,212,0.18);
            color:#cbfff8;
            font-size:11px;
            font-weight:700;
            white-space:nowrap;
        }}
        .public-visual-quote {{
            margin-top:18px;
            padding:14px 16px;
            border-radius:18px;
            background:rgba(255,255,255,0.03);
            border:1px solid rgba(255,255,255,0.06);
        }}
        .public-visual-price {{
            color:white;
            font-size:30px;
            font-weight:800;
            letter-spacing:-0.04em;
        }}
        .public-visual-delta {{
            color:#00f5d4;
            font-size:12px;
            font-weight:700;
            margin-top:4px;
        }}
        .public-visual-grid {{
            display:grid;
            grid-template-columns:repeat(2, minmax(0,1fr));
            gap:12px;
            margin-top:16px;
        }}
        .public-visual-card {{
            padding:14px;
            border-radius:16px;
            border:1px solid rgba(255,255,255,0.06);
            background:rgba(255,255,255,0.03);
        }}
        .public-visual-card-label {{
            color:#7ea0b5;
            font-size:10px;
            font-weight:700;
            letter-spacing:0.12em;
            text-transform:uppercase;
        }}
        .public-visual-card-value {{
            color:white;
            font-size:18px;
            font-weight:800;
            margin-top:10px;
        }}
        .public-visual-card-copy {{
            color:#89afc1;
            font-size:12px;
            line-height:1.55;
            margin-top:6px;
        }}
        .public-visual-lower {{
            margin-top:16px;
            padding:16px;
            border-radius:18px;
            border:1px solid rgba(255,255,255,0.06);
            background:
                radial-gradient(circle at top left, rgba(0,245,212,0.07), transparent 28%),
                linear-gradient(180deg, rgba(9,20,32,0.94) 0%, rgba(7,17,28,0.98) 100%);
            min-height:220px;
            display:flex;
            flex-direction:column;
            justify-content:space-between;
            gap:14px;
        }}
        .public-visual-lower-head {{
            display:flex;
            align-items:flex-start;
            justify-content:space-between;
            gap:12px;
        }}
        .public-visual-lower-title {{
            color:white;
            font-size:16px;
            font-weight:800;
        }}
        .public-visual-lower-copy {{
            color:#7ea8bf;
            font-size:12px;
            line-height:1.6;
            margin-top:6px;
        }}
        .public-visual-mini-badge {{
            padding:6px 10px;
            border-radius:999px;
            background:rgba(255,255,255,0.04);
            border:1px solid rgba(255,255,255,0.07);
            color:#cbdee8;
            font-size:10px;
            font-weight:700;
            white-space:nowrap;
        }}
        .public-visual-stage-grid {{
            display:grid;
            grid-template-columns:repeat(3, minmax(0,1fr));
            gap:10px;
        }}
        .public-visual-stage {{
            padding:12px;
            border-radius:14px;
            background:rgba(255,255,255,0.03);
            border:1px solid rgba(255,255,255,0.05);
        }}
        .public-visual-stage-label {{
            color:#7ea0b5;
            font-size:10px;
            font-weight:700;
            letter-spacing:0.12em;
            text-transform:uppercase;
        }}
        .public-visual-stage-value {{
            color:white;
            font-size:14px;
            font-weight:800;
            margin-top:8px;
        }}
        .public-visual-stage-copy {{
            color:#86aec0;
            font-size:11px;
            line-height:1.55;
            margin-top:5px;
        }}
        .public-visual-chart-shell {{
            padding:12px 12px 10px;
            border-radius:16px;
            background:rgba(5,14,23,0.70);
            border:1px solid rgba(255,255,255,0.05);
        }}
        .public-visual-chart-top {{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:10px;
            margin-bottom:10px;
        }}
        .public-visual-chart-label {{
            color:#8fb2c5;
            font-size:11px;
            font-weight:700;
            letter-spacing:0.10em;
            text-transform:uppercase;
        }}
        .public-visual-chart-delta {{
            color:#00f5d4;
            font-size:11px;
            font-weight:700;
        }}
        .public-visual-chart-svg {{
            width:100%;
            height:74px;
            display:block;
        }}
        .public-visual-flow {{
            display:flex;
            flex-wrap:wrap;
            gap:8px;
        }}
        @media (max-width: 1220px) {{
            .public-hero-shell {{
                grid-template-columns:1fr;
            }}
            .public-visual-grid,
            .public-visual-stage-grid,
            .public-proof,
            .public-grid {{
                grid-template-columns:repeat(2, minmax(0,1fr));
            }}
            .public-title {{
                max-width:14ch;
            }}
            .public-hero-visual {{
                margin-top:4px;
            }}
        }}
        .public-visual-flow-pill {{
            padding:7px 10px;
            border-radius:999px;
            background:rgba(255,255,255,0.04);
            border:1px solid rgba(255,255,255,0.06);
            color:#d5edf4;
            font-size:11px;
            font-weight:700;
        }}
        .public-chip-row {{
            display:flex;
            flex-wrap:wrap;
            gap:10px;
            margin-top:20px;
        }}
        .public-chip {{
            padding:8px 12px;
            border-radius:999px;
            background:rgba(255,255,255,0.04);
            border:1px solid rgba(255,255,255,0.08);
            color:#d8eef5;
            font-size:12px;
            font-weight:700;
        }}
        .public-grid {{
            display:grid;
            grid-template-columns:repeat(2, minmax(0,1fr));
            gap:14px;
            margin-top:28px;
        }}
        .public-card {{
            background:rgba(8,18,28,0.58);
            border:1px solid rgba(255,255,255,0.07);
            border-radius:18px;
            padding:16px 16px 14px;
            min-height:126px;
        }}
        .public-card-kicker {{
            color:#00f5d4;
            font-size:11px;
            font-weight:800;
            letter-spacing:0.12em;
            text-transform:uppercase;
        }}
        .public-card-title {{
            color:white;
            font-size:18px;
            font-weight:700;
            margin-top:10px;
        }}
        .public-card-copy {{
            color:#8ab4c8;
            font-size:13px;
            line-height:1.65;
            margin-top:7px;
        }}
        .public-proof {{
            display:grid;
            grid-template-columns:repeat(3, minmax(0,1fr));
            gap:12px;
            margin-top:22px;
        }}
        .public-proof-item {{
            background:rgba(255,255,255,0.03);
            border:1px solid rgba(255,255,255,0.07);
            border-radius:16px;
            padding:14px;
        }}
        .public-proof-value {{
            color:white;
            font-size:22px;
            font-weight:800;
        }}
        .public-proof-label {{
            color:#7ea0b5;
            font-size:11px;
            line-height:1.5;
            margin-top:4px;
            text-transform:uppercase;
            letter-spacing:0.08em;
        }}
        .public-note {{
            margin-top:18px;
            padding:13px 14px;
            border-radius:16px;
            background:rgba(0,245,212,0.08);
            border:1px solid rgba(0,245,212,0.14);
            color:#cdeceb;
            font-size:12px;
            line-height:1.7;
        }}
        .auth-choice-head {{
            margin:8px 0 14px;
        }}
        .auth-choice-kicker {{
            color:#7ad8cc;
            font-size:11px;
            font-weight:800;
            letter-spacing:0.14em;
            text-transform:uppercase;
        }}
        .auth-choice-title {{
            color:white;
            font-size:30px;
            font-weight:800;
            letter-spacing:-0.03em;
            margin-top:10px;
        }}
        .auth-choice-copy {{
            color:#8caec0;
            font-size:14px;
            line-height:1.7;
            margin-top:8px;
            max-width:760px;
        }}
        .auth-choice-note {{
            margin-top:14px;
            padding:14px 16px;
            border-radius:18px;
            background:rgba(255,255,255,0.03);
            border:1px solid rgba(255,255,255,0.06);
            color:#8fb4c7;
            font-size:13px;
            line-height:1.7;
        }}
        .auth-page-head {{
            margin:10px 0 18px;
        }}
        .auth-page-kicker {{
            color:#7ad8cc;
            font-size:11px;
            font-weight:800;
            letter-spacing:0.14em;
            text-transform:uppercase;
        }}
        .auth-page-title {{
            color:white;
            font-size:28px;
            font-weight:800;
            letter-spacing:-0.03em;
            margin-top:10px;
        }}
        .auth-page-copy {{
            color:#8caec0;
            font-size:14px;
            line-height:1.7;
            margin-top:8px;
        }}
        .st-key-desktop_auth_modal {{
            position:fixed;
            inset:0;
            z-index:9999;
            display:flex;
            align-items:flex-start;
            justify-content:center;
            padding:84px 20px 28px;
            background:rgba(4, 11, 19, 0.56);
            backdrop-filter:blur(18px);
            overflow-y:auto;
        }}
        .st-key-desktop_auth_modal > div {{
            width:min(720px, 100%);
            padding:20px 22px 22px;
            border-radius:28px;
            border:1px solid rgba(255,255,255,0.08);
            background:
                radial-gradient(circle at top right, rgba(0,245,212,0.08), transparent 30%),
                linear-gradient(180deg, rgba(10,19,31,0.97) 0%, rgba(7,14,24,0.98) 100%);
            box-shadow:0 26px 70px rgba(0,0,0,0.34);
        }}
        .desktop-auth-modal-head {{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:14px;
            margin-bottom:14px;
        }}
        .desktop-auth-modal-close {{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            min-height:42px;
            padding:0 16px;
            border-radius:999px;
            border:1px solid rgba(255,255,255,0.08);
            background:rgba(255,255,255,0.03);
            color:#e7f4ff !important;
            text-decoration:none !important;
            font-size:12px;
            font-weight:800;
        }}
        .desktop-auth-modal-tabs {{
            display:flex;
            align-items:center;
            justify-content:flex-end;
            flex-wrap:wrap;
            gap:10px;
        }}
        .desktop-auth-modal-tab {{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            min-height:42px;
            padding:0 16px;
            border-radius:999px;
            border:1px solid rgba(255,255,255,0.08);
            background:rgba(255,255,255,0.03);
            color:#dbeaf7 !important;
            text-decoration:none !important;
            font-size:12px;
            font-weight:800;
        }}
        .desktop-auth-modal-tab.is-active {{
            border-color:rgba(0,245,212,0.22);
            background:rgba(0,245,212,0.10);
            color:#e8fffb !important;
        }}
        .st-key-desktop_auth_modal [data-testid="stForm"] {{
            border:none !important;
            background:transparent !important;
            padding:0 !important;
            box-shadow:none !important;
        }}
        .st-key-desktop_auth_modal .stTextInput > div > div > input {{
            min-height:52px !important;
            border-radius:16px !important;
            border:1px solid rgba(255,255,255,0.08) !important;
            background:rgba(12, 22, 36, 0.92) !important;
            color:#edf8ff !important;
            font-size:15px !important;
            padding-left:14px !important;
        }}
        .st-key-desktop_auth_modal .stTextInput > label {{
            color:#9fc0d2 !important;
            font-weight:700 !important;
        }}
        .st-key-desktop_auth_modal .stButton > button,
        .st-key-desktop_auth_modal [data-testid="stFormSubmitButton"] > button {{
            min-height:50px !important;
            border-radius:16px !important;
        }}
        .st-key-desktop_auth_modal [data-testid="stAlert"] {{
            border-radius:16px !important;
        }}
        @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500;700&display=swap');
        .st-key-desktop_auth_panel {{
            width:min(1120px, calc(100vw - 48px));
            margin:20px auto 42px;
            color:#e8f4f2;
            font-family:'DM Sans', 'Segoe UI', sans-serif;
        }}
        .st-key-desktop_auth_panel > div {{
            padding:0;
            overflow:hidden;
            border-radius:24px;
            border:1px solid rgba(0,230,200,0.10);
            background:
                linear-gradient(rgba(0,230,200,0.035) 1px, transparent 1px),
                linear-gradient(90deg, rgba(0,230,200,0.035) 1px, transparent 1px),
                #07111a;
            background-size:48px 48px, 48px 48px, auto;
            box-shadow:0 28px 74px rgba(0,0,0,0.34);
        }}
        .st-key-desktop_auth_panel [data-testid="stHorizontalBlock"]:has(.fw-auth-left-panel) {{
            gap:0 !important;
            min-height:min(720px, calc(100vh - 86px));
        }}
        .st-key-desktop_auth_panel [data-testid="stHorizontalBlock"]:has(.fw-auth-left-panel) > div:first-child {{
            border-right:1px solid rgba(0,230,200,0.10);
            background:
                linear-gradient(180deg, rgba(13,31,45,0.72), rgba(7,17,26,0.92));
        }}
        .st-key-desktop_auth_panel [data-testid="stHorizontalBlock"]:has(.fw-auth-left-panel) > div:last-child {{
            background:rgba(7,17,26,0.76);
            display:flex;
            flex-direction:column;
            justify-content:center;
            min-height:min(720px, calc(100vh - 86px));
            padding:54px 52px;
        }}
        .fw-auth-left-panel {{
            min-height:min(720px, calc(100vh - 86px));
            display:flex;
            flex-direction:column;
            justify-content:space-between;
            padding:48px 52px;
        }}
        .fw-auth-logo {{
            font-family:'Syne', 'Segoe UI', sans-serif;
            font-size:1.05rem;
            font-weight:800;
            letter-spacing:0.12em;
            text-transform:uppercase;
            color:#00e6c8;
        }}
        .fw-auth-logo span {{
            color:#e8f4f2;
        }}
        .fw-auth-tagline {{
            margin-top:auto;
        }}
        .fw-auth-tagline h2 {{
            margin:0;
            color:#e8f4f2;
            font-family:'Syne', 'Segoe UI', sans-serif;
            font-size:clamp(2rem, 3.5vw, 3.2rem);
            font-weight:800;
            line-height:1.1;
            letter-spacing:0;
        }}
        .fw-auth-tagline h2 em {{
            color:#00e6c8;
            font-style:normal;
        }}
        .fw-auth-tagline p {{
            max-width:340px;
            margin:16px 0 0;
            color:#6e9b96;
            font-size:0.92rem;
            font-weight:300;
            line-height:1.7;
        }}
        .fw-auth-stats {{
            display:flex;
            gap:34px;
            margin-top:46px;
            flex-wrap:wrap;
        }}
        .fw-auth-stat {{
            display:flex;
            flex-direction:column;
            gap:5px;
        }}
        .fw-auth-stat strong {{
            color:#00e6c8;
            font-family:'Syne', 'Segoe UI', sans-serif;
            font-size:1.45rem;
            font-weight:700;
        }}
        .fw-auth-stat span {{
            color:#5c8a85;
            font-size:0.74rem;
            letter-spacing:0.06em;
            text-transform:uppercase;
        }}
        .fw-auth-ticker {{
            width:fit-content;
            max-width:100%;
            display:flex;
            align-items:center;
            gap:9px;
            margin-top:38px;
            padding:10px 15px;
            border:1px solid rgba(0,230,200,0.10);
            border-radius:8px;
            background:rgba(0,230,200,0.05);
            color:#6e9b96;
            font-size:0.78rem;
            line-height:1.5;
        }}
        .fw-auth-ticker-dot {{
            width:7px;
            height:7px;
            flex:none;
            border-radius:50%;
            background:#00e6c8;
            animation:fwAuthPulse 1.6s ease infinite;
        }}
        .fw-auth-ticker strong,
        .fw-auth-ticker .up {{
            color:#e8f4f2;
        }}
        .fw-auth-ticker .up {{
            color:#00e6c8;
        }}
        .fw-auth-chart-grid {{
            display:grid;
            grid-template-columns:repeat(3, minmax(0, 1fr));
            gap:12px;
            margin-top:22px;
            max-width:100%;
        }}
        .fw-auth-chart-card {{
            min-width:0;
            padding:12px 12px 11px;
            border-radius:14px;
            border:1px solid rgba(0,230,200,0.18);
            background:
                linear-gradient(180deg, rgba(13,31,45,0.68), rgba(8,21,32,0.78)),
                rgba(8,21,32,0.58);
            box-shadow:
                0 0 0 1px rgba(0,230,200,0.035) inset,
                0 16px 34px rgba(0,0,0,0.22),
                0 0 28px rgba(0,230,200,0.08);
            backdrop-filter:blur(12px);
            animation:fwAuthCardFloat 5.6s ease-in-out infinite;
        }}
        .fw-auth-chart-card:nth-child(2) {{
            animation-delay:0.35s;
        }}
        .fw-auth-chart-card:nth-child(3) {{
            animation-delay:0.7s;
        }}
        .fw-auth-chart-head {{
            display:flex;
            align-items:flex-start;
            justify-content:space-between;
            gap:8px;
            margin-bottom:9px;
        }}
        .fw-auth-chart-name {{
            color:#e8f4f2;
            font-size:0.78rem;
            font-weight:800;
            line-height:1.1;
        }}
        .fw-auth-chart-symbol {{
            display:block;
            margin-top:3px;
            color:#5c8a85;
            font-size:0.62rem;
            font-weight:700;
            letter-spacing:0.10em;
            text-transform:uppercase;
        }}
        .fw-auth-chart-badge {{
            flex:none;
            padding:3px 6px;
            border-radius:999px;
            background:rgba(0,230,200,0.12);
            color:#00e6c8;
            font-size:0.62rem;
            font-weight:800;
            line-height:1;
            border:1px solid rgba(0,230,200,0.18);
        }}
        .fw-auth-chart-svg {{
            display:block;
            width:100%;
            height:44px;
            overflow:visible;
        }}
        .fw-auth-chart-line {{
            stroke-dasharray:100;
            stroke-dashoffset:100;
            filter:drop-shadow(0 0 6px rgba(0,230,200,0.45));
            transform-origin:center;
            animation:
                fwAuthChartDraw 1.8s ease-out forwards,
                fwAuthChartLive 3.8s ease-in-out 1.8s infinite;
        }}
        .fw-auth-chart-card:nth-child(2) .fw-auth-chart-line {{
            animation-delay:0.18s, 1.98s;
        }}
        .fw-auth-chart-card:nth-child(3) .fw-auth-chart-line {{
            animation-delay:0.36s, 2.16s;
        }}
        .fw-auth-chart-price {{
            margin-top:8px;
            color:#e8f4f2;
            font-family:'Syne', 'Segoe UI', sans-serif;
            font-size:0.92rem;
            font-weight:800;
            letter-spacing:0;
        }}
        @keyframes fwAuthPulse {{
            0%, 100% {{ opacity:1; transform:scale(1); }}
            50% {{ opacity:0.42; transform:scale(0.72); }}
        }}
        @keyframes fwAuthCardFloat {{
            0%, 100% {{ transform:translateY(0); box-shadow:0 0 0 1px rgba(0,230,200,0.035) inset, 0 16px 34px rgba(0,0,0,0.22), 0 0 28px rgba(0,230,200,0.08); }}
            50% {{ transform:translateY(-3px); box-shadow:0 0 0 1px rgba(0,230,200,0.07) inset, 0 20px 38px rgba(0,0,0,0.25), 0 0 34px rgba(0,230,200,0.13); }}
        }}
        @keyframes fwAuthChartDraw {{
            to {{ stroke-dashoffset:0; }}
        }}
        @keyframes fwAuthChartLive {{
            0%, 100% {{ transform:translateY(0) scaleY(1); opacity:0.95; }}
            45% {{ transform:translateY(-2px) scaleY(1.08); opacity:1; }}
            70% {{ transform:translateY(1px) scaleY(0.96); opacity:0.9; }}
        }}
        .fw-auth-mini-nav {{
            display:flex;
            align-items:center;
            gap:10px;
            margin-bottom:28px;
        }}
        .fw-auth-mini-nav a {{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            min-height:34px;
            padding:0 13px;
            border-radius:8px;
            border:1px solid rgba(0,230,200,0.10);
            background:rgba(255,255,255,0.02);
            color:#78aaa5 !important;
            text-decoration:none !important;
            font-size:0.75rem;
            font-weight:700;
        }}
        .fw-auth-mini-nav a.is-active {{
            background:rgba(0,230,200,0.12);
            color:#e8f4f2 !important;
        }}
        .auth-page-head {{
            margin:0 0 36px;
        }}
        .auth-page-kicker {{
            color:#00e6c8;
            font-size:0.7rem;
            font-weight:600;
            letter-spacing:0.14em;
            text-transform:uppercase;
        }}
        .auth-page-title {{
            margin-top:12px;
            color:#e8f4f2;
            font-family:'Syne', 'Segoe UI', sans-serif;
            font-size:2rem;
            font-weight:800;
            line-height:1.15;
            letter-spacing:0;
        }}
        .fw-auth-typewriter {{
            display:inline-block;
            width:0;
            max-width:max-content;
            overflow:hidden;
            white-space:nowrap;
            animation:
                fwAuthTyping 1.42s steps(18, end) 0.14s forwards;
        }}
        @keyframes fwAuthTyping {{
            from {{ width:0; }}
            to {{ width:18ch; }}
        }}
        .auth-page-copy {{
            margin-top:10px;
            color:#6e9b96;
            font-size:0.86rem;
            line-height:1.6;
        }}
        .st-key-desktop_auth_panel [data-testid="stForm"] {{
            border:none !important;
            background:transparent !important;
            padding:0 !important;
            box-shadow:none !important;
        }}
        .st-key-desktop_auth_panel .stTextInput > div > div > input {{
            min-height:50px !important;
            border-radius:10px !important;
            border:1px solid rgba(0,230,200,0.12) !important;
            background:#081520 !important;
            color:#e8f4f2 !important;
            font-size:0.92rem !important;
            padding-left:15px !important;
            caret-color:#00e6c8 !important;
        }}
        .st-key-desktop_auth_panel .stTextInput > div > div > input:focus {{
            border-color:#00e6c8 !important;
            box-shadow:0 0 0 3px rgba(0,230,200,0.08) !important;
        }}
        .st-key-desktop_auth_panel .stTextInput > label {{
            color:#5c8a85 !important;
            font-size:0.72rem !important;
            font-weight:700 !important;
            letter-spacing:0.10em !important;
            text-transform:uppercase !important;
        }}
        .st-key-desktop_auth_panel .stCheckbox label {{
            color:#6e9b96 !important;
            font-size:0.84rem !important;
        }}
        .st-key-desktop_auth_panel .stButton > button,
        .st-key-desktop_auth_panel [data-testid="stFormSubmitButton"] > button {{
            min-height:50px !important;
            border-radius:10px !important;
            border:0 !important;
            background:#00e6c8 !important;
            color:#07111a !important;
            font-family:'Syne', 'Segoe UI', sans-serif !important;
            font-size:0.88rem !important;
            font-weight:800 !important;
            letter-spacing:0.06em !important;
            text-transform:uppercase !important;
            transition:transform .15s ease, box-shadow .2s ease !important;
        }}
        .st-key-desktop_auth_panel [data-testid="stFormSubmitButton"] > button:hover {{
            transform:translateY(-1px);
            box-shadow:0 8px 28px rgba(0,230,200,0.28) !important;
        }}
        .fw-auth-forgot,
        .fw-auth-register-cta a {{
            color:#00e6c8 !important;
            text-decoration:none !important;
            font-size:0.84rem;
            font-weight:600;
        }}
        .fw-auth-forgot {{
            display:block;
            padding-top:7px;
            text-align:right;
        }}
        .fw-auth-register-cta {{
            margin-top:26px;
            text-align:center;
            color:#6e9b96;
            font-size:0.84rem;
        }}
        .fw-auth-register-cta a:hover,
        .fw-auth-forgot:hover {{
            text-decoration:underline !important;
        }}
        .st-key-desktop_auth_panel [data-testid="stAlert"] {{
            border-radius:10px !important;
        }}
        .st-key-desktop_auth_panel_legacy {{
            width:min(760px, 100%);
            margin:18px auto 36px;
        }}
        .st-key-desktop_auth_panel_legacy > div {{
            padding:22px;
            border-radius:22px;
            border:1px solid rgba(0,245,212,0.12);
            background:
                radial-gradient(circle at top right, rgba(0,245,212,0.08), transparent 30%),
                linear-gradient(180deg, rgba(10,20,33,0.96) 0%, rgba(7,15,27,0.98) 100%);
            box-shadow:0 18px 44px rgba(0,0,0,0.24);
        }}
        .st-key-desktop_auth_panel_legacy [data-testid="stForm"] {{
            border:none !important;
            background:transparent !important;
            padding:0 !important;
            box-shadow:none !important;
        }}
        .st-key-desktop_auth_panel_legacy .stTextInput > div > div > input {{
            min-height:52px !important;
            border-radius:14px !important;
            border:1px solid rgba(255,255,255,0.10) !important;
            background:rgba(7,14,24,0.92) !important;
            color:#edf8ff !important;
            font-size:15px !important;
            padding-left:14px !important;
        }}
        .st-key-desktop_auth_panel_legacy .stTextInput > label {{
            color:#9fc0d2 !important;
            font-weight:700 !important;
        }}
        .st-key-desktop_auth_panel_legacy .stButton > button,
        .st-key-desktop_auth_panel_legacy [data-testid="stFormSubmitButton"] > button {{
            min-height:50px !important;
            border-radius:14px !important;
        }}
        @media (max-width: 700px) {{
            .public-hero-head,
            .desktop-auth-modal-head {{
                flex-direction:column;
                align-items:stretch;
            }}
            .public-hero-actions,
            .desktop-auth-modal-tabs {{
                justify-content:stretch;
            }}
            .public-hero-action-link,
            .desktop-auth-modal-close,
            .desktop-auth-modal-tab {{
                width:100%;
            }}
            .public-hero {{
                padding:24px 18px 20px;
                border-radius:22px;
            }}
            .public-hero-shell,
            .public-visual-grid,
            .public-visual-stage-grid {{
                grid-template-columns:1fr;
            }}
            .public-title {{
                font-size:31px;
                max-width:none;
            }}
            .public-grid,
            .public-proof {{
                grid-template-columns:1fr;
            }}
            .auth-choice-title,
            .auth-page-title {{
                font-size:24px;
            }}
            .st-key-desktop_auth_modal {{
                padding:72px 14px 20px;
            }}
            .st-key-desktop_auth_modal > div {{
                padding:16px 16px 18px;
                border-radius:22px;
            }}
            .st-key-desktop_auth_panel {{
                width:min(100%, calc(100vw - 20px));
                margin:10px auto 24px;
            }}
            .st-key-desktop_auth_panel_legacy {{
                width:min(100%, calc(100vw - 20px));
                margin:10px auto 24px;
            }}
            .st-key-desktop_auth_panel [data-testid="stHorizontalBlock"]:has(.fw-auth-left-panel) {{
                display:block !important;
                min-height:auto;
            }}
            .st-key-desktop_auth_panel [data-testid="stHorizontalBlock"]:has(.fw-auth-left-panel) > div:first-child {{
                display:none;
            }}
            .fw-auth-right-panel {{
                min-height:auto;
                padding:34px 24px;
            }}
            .fw-auth-chart-grid {{
                grid-template-columns:1fr;
            }}
            .st-key-desktop_auth_panel [data-testid="stHorizontalBlock"]:has(.fw-auth-left-panel) > div:last-child {{
                min-height:auto;
                padding:34px 24px;
            }}
        }}
        </style>
        <section class="public-hero" style="display:{hero_display};">
            <div class="public-hero-head">
                <div class="public-kicker">API Broker Platform</div>
                <div class="public-hero-actions">
                    {desktop_resume_markup}
                    <a class="public-hero-action-link{" is-active" if auth_view == "login" else ""}" href="{escape(desktop_login_href, quote=True)}" target="_top">Login</a>
                    <a class="public-hero-action-link is-primary{" is-active" if auth_view == "register" else ""}" href="{escape(desktop_register_href, quote=True)}" target="_top">Sign Up</a>
                </div>
            </div>
            <div class="public-hero-shell">
                <div>
                    <div class="public-brand">
                        <div class="public-logo">{hero_logo}</div>
                        <div>
                            <div style="color:white;font-size:20px;font-weight:800;">Finwise AI</div>
                            <div style="color:#7da4b8;font-size:12px;margin-top:4px;">Market intelligence, broker connectivity, and execution in one workspace.</div>
                        </div>
                    </div>
                    <div class="public-title">Move from market insight to broker execution in one clean workspace.</div>
                    <div class="public-copy">
                        Finwise AI brings live market analysis, AI-assisted signal context, and broker handoff together so users can review the market, confirm a trade idea, and act from the same interface.
                    </div>
                    <div class="public-chip-row">
                        <span class="public-chip">Live Market Analysis</span>
                        <span class="public-chip">Signal Workspace</span>
                        <span class="public-chip">Broker Routing</span>
                        <span class="public-chip">Mobile Responsive</span>
                    </div>
                    <div class="public-grid">
                        <div class="public-card">
                            <div class="public-card-kicker">Analysis</div>
                            <div class="public-card-title">Multi-panel market view</div>
                            <div class="public-card-copy">Track charts, order books, live market panels, and execution context from a single dashboard.</div>
                        </div>
                        <div class="public-card">
                            <div class="public-card-kicker">Broker Access</div>
                            <div class="public-card-title">Secure account connection</div>
                            <div class="public-card-copy">Connect supported exchanges for balance visibility, signal handoff, and execution routing.</div>
                        </div>
                        <div class="public-card">
                            <div class="public-card-kicker">Signals</div>
                            <div class="public-card-title">AI-assisted trade ideas</div>
                            <div class="public-card-copy">Review confidence, support, resistance, and market context before you decide what to do next.</div>
                        </div>
                        <div class="public-card">
                            <div class="public-card-kicker">Operations</div>
                            <div class="public-card-title">Built for broker workflow</div>
                            <div class="public-card-copy">Designed to carry users from analysis into connected broker workflows with less friction.</div>
                        </div>
                    </div>
                    <div class="public-proof">
                        <div class="public-proof-item">
                            <div class="public-proof-value">24/7</div>
                            <div class="public-proof-label">Live market monitoring</div>
                        </div>
                        <div class="public-proof-item">
                            <div class="public-proof-value">1 Flow</div>
                            <div class="public-proof-label">Analysis to execution path</div>
                        </div>
                        <div class="public-proof-item">
                            <div class="public-proof-value">Secure</div>
                            <div class="public-proof-label">Broker connection architecture</div>
                        </div>
                    </div>
                </div>
                <div class="public-hero-visual">
                    <div class="public-visual-kicker">Workspace Snapshot</div>
                    <div class="public-visual-header">
                        <div>
                            <div class="public-visual-symbol">BTCUSDT</div>
                            <div class="public-visual-subtitle">Signal, chart, and broker routing aligned in one view.</div>
                        </div>
                        <div class="public-visual-badge">Live Feed Ready</div>
                    </div>
                    <div class="public-visual-quote">
                        <div class="public-visual-price">77,676.60</div>
                        <div class="public-visual-delta">AI signal engine, order context, and broker handoff remain inside the same workflow.</div>
                    </div>
                    <div class="public-visual-grid">
                        <div class="public-visual-card">
                            <div class="public-visual-card-label">Signal Engine</div>
                            <div class="public-visual-card-value">Neutral</div>
                            <div class="public-visual-card-copy">Structured confidence and key-level context before execution.</div>
                        </div>
                        <div class="public-visual-card">
                            <div class="public-visual-card-label">Broker Mode</div>
                            <div class="public-visual-card-value">Connected</div>
                            <div class="public-visual-card-copy">Switch from signal review into broker execution without leaving the workspace.</div>
                        </div>
                        <div class="public-visual-card">
                            <div class="public-visual-card-label">Market Panels</div>
                            <div class="public-visual-card-value">Live</div>
                            <div class="public-visual-card-copy">Chart, order book, and market stats stay visible together while you trade.</div>
                        </div>
                        <div class="public-visual-card">
                            <div class="public-visual-card-label">Mobile View</div>
                            <div class="public-visual-card-value">Ready</div>
                            <div class="public-visual-card-copy">Optimized to keep the core workflow intact across phones, tablets, and desktop.</div>
                        </div>
                    </div>
                    <div class="public-visual-lower">
                        <div class="public-visual-lower-head">
                            <div>
                                <div class="public-visual-lower-title">Signal To Execution Flow</div>
                                <div class="public-visual-lower-copy">A compact preview of how Finwise carries a user from market scan into signal review and broker routing.</div>
                            </div>
                            <div class="public-visual-mini-badge">Preview Rail</div>
                        </div>
                        <div class="public-visual-stage-grid">
                            <div class="public-visual-stage">
                                <div class="public-visual-stage-label">Scan</div>
                                <div class="public-visual-stage-value">Live Market</div>
                                <div class="public-visual-stage-copy">Track structure, liquidity, and active momentum.</div>
                            </div>
                            <div class="public-visual-stage">
                                <div class="public-visual-stage-label">Signal</div>
                                <div class="public-visual-stage-value">62% Confidence</div>
                                <div class="public-visual-stage-copy">AI context with support, resistance, and regime.</div>
                            </div>
                            <div class="public-visual-stage">
                                <div class="public-visual-stage-label">Route</div>
                                <div class="public-visual-stage-value">Broker Ready</div>
                                <div class="public-visual-stage-copy">Move from signal review into connected execution.</div>
                            </div>
                        </div>
                        <div class="public-visual-chart-shell">
                            <div class="public-visual-chart-top">
                                <div class="public-visual-chart-label">BTCUSDT Session Preview</div>
                                <div class="public-visual-chart-delta">+0.34%</div>
                            </div>
                            <svg viewBox="0 0 320 74" class="public-visual-chart-svg" preserveAspectRatio="none" aria-hidden="true">
                                <defs>
                                    <linearGradient id="publicChartGlow" x1="0" x2="0" y1="0" y2="1">
                                        <stop offset="0%" stop-color="rgba(0,245,212,0.30)"></stop>
                                        <stop offset="100%" stop-color="rgba(0,245,212,0.01)"></stop>
                                    </linearGradient>
                                </defs>
                                <path d="M0 60 L28 58 L56 54 L84 56 L112 45 L140 41 L168 44 L196 35 L224 39 L252 24 L280 18 L320 20 L320 74 L0 74 Z" fill="url(#publicChartGlow)"></path>
                                <path d="M0 60 L28 58 L56 54 L84 56 L112 45 L140 41 L168 44 L196 35 L224 39 L252 24 L280 18 L320 20" fill="none" stroke="#19dfd0" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></path>
                                <path d="M0 63 L320 63" fill="none" stroke="rgba(255,255,255,0.07)" stroke-width="1" stroke-dasharray="4 5"></path>
                            </svg>
                        </div>
                        <div class="public-visual-flow">
                            <span class="public-visual-flow-pill">Market Analysis</span>
                            <span class="public-visual-flow-pill">AI Signal</span>
                            <span class="public-visual-flow-pill">Broker Handoff</span>
                        </div>
                    </div>
                </div>
            </div>
            <div class="public-note">
                Public website direction for broker reviews:
                use a real HTTPS domain for Finwise AI, then register that same domain as your broker OAuth callback base.
            </div>
        </section>
        """,
        ).strip()
    )

    if auth_view == "landing":
        return

    if auth_view != "login":
        with st.container(key="desktop_auth_panel_legacy"):
            if auth_view == "reset_password":
                if st.button("Back", key="desktop_auth_reset_back", use_container_width=True):
                    clear_password_reset_state()
                    st.session_state.auth_view = "login"
                    try:
                        st.query_params["auth"] = "login"
                    except Exception:
                        pass
                    st.rerun()
            else:
                auth_tab_login, auth_tab_register = st.columns(2, gap="small")
                with auth_tab_login:
                    if st.button("Login", key="desktop_auth_tab_login", use_container_width=True):
                        clear_password_reset_state()
                        st.session_state.auth_view = "login"
                        try:
                            st.query_params["auth"] = "login"
                        except Exception:
                            pass
                        st.rerun()
                with auth_tab_register:
                    if st.button(
                        "Sign Up",
                        key="desktop_auth_tab_register",
                        use_container_width=True,
                        disabled=auth_view == "register",
                    ):
                        clear_password_reset_state()
                        st.session_state.auth_view = "register"
                        try:
                            st.query_params["auth"] = "register"
                        except Exception:
                            pass
                        st.rerun()

            if auth_notice:
                st.success(auth_notice)
            if auth_error:
                st.error(auth_error)
            if pending_signed_session:
                _render_saved_session_prompt(button_key="desktop_continue_saved_session")

            if auth_view == "reset_password":
                st.markdown(
                    """
                    <div class="auth-page-head">
                        <div class="auth-page-kicker">Reset Password</div>
                        <div class="auth-page-title">Recover access.</div>
                        <div class="auth-page-copy">Confirm your account email, enter the reset code we send, and choose a new password.</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                _render_password_reset_flow(mobile=False)
            else:
                st.markdown(
                    """
                    <div class="auth-page-head">
                        <div class="auth-page-kicker">Create Account</div>
                        <div class="auth-page-title">Start your workspace.</div>
                        <div class="auth-page-copy">Create your account, verify your email with OTP, and return to the live trading workspace.</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if not st.session_state.otp_sent:
                    with st.form("register_details_form"):
                        username = st.text_input("Username", key="register_username_field", placeholder="Choose a username").strip()
                        password = st.text_input("Password", type="password", key="register_password_field", placeholder="Create a strong password")
                        email = st.text_input("Email", key="register_email_field", placeholder="you@example.com").strip()
                        phone = st.text_input("Phone (+234...)", key="register_phone_field", placeholder="+234...").strip()
                        send_otp = st.form_submit_button("Send OTP", use_container_width=True, type="primary")

                    if send_otp:
                        if not email or not username or not password:
                            st.error("Please fill in all required fields.")
                            st.stop()
                        password_ok, password_error = password_meets_policy(password)
                        if not password_ok:
                            st.error(password_error)
                            st.stop()
                        cursor.execute("SELECT 1 FROM users WHERE username=?", (username,))
                        if cursor.fetchone():
                            st.error("Username already exists. Please choose another.")
                            st.stop()
                        pw_hash = hash_password(password)
                        save_pending_user(username, pw_hash, email, phone)
                        st.session_state.pending_email = email
                        st.session_state.pending_username = username
                        st.session_state.temp_user = {
                            "username": username,
                            "password": pw_hash.decode() if isinstance(pw_hash, bytes) else pw_hash,
                            "email": email,
                            "phone": phone,
                        }
                        st.session_state.auth_otp_context = "register"
                        if send_email_otp(email, username):
                            st.session_state.otp_sent = True
                            st.rerun()
                        st.error("We could not send the OTP right now. Please try again.")

                if st.session_state.otp_sent:
                    pending_email = st.session_state.temp_user.get("email", "your email")
                    st.info(f"OTP sent to {pending_email}")

                    with st.form("register_otp_form"):
                        otp = st.text_input("Enter OTP", key="register_otp_field", placeholder="6-digit code").strip()
                        verify_submit = st.form_submit_button("Verify and Create Account", use_container_width=True, type="primary")

                    if verify_submit:
                        if not otp:
                            st.error("Please enter the OTP.")
                            st.stop()
                        stored_username = st.session_state.temp_user.get("username", "")
                        if verify_otp(stored_username, otp):
                            data = st.session_state.temp_user
                            try:
                                create_registered_user(
                                    data["username"],
                                    data["password"],
                                    data["email"],
                                    data.get("phone", ""),
                                )
                                st.success("Account created successfully.")
                                st.session_state.otp_sent = False
                                st.session_state.temp_user = {}
                                st.session_state.auth_otp_context = ""
                                st.session_state.auth_view = "login"
                                st.session_state.login_username_field = data["username"]
                                clear_pending_user(stored_username)
                                st.balloons()
                                st.rerun()
                            except Exception as e:
                                if is_integrity_error(e):
                                    st.error("Username already exists. Please choose another.")
                                else:
                                    _show_safe_operation_error("Account creation", e)
                        else:
                            st.error("Invalid or expired OTP. Please try again.")

                    otp_action_left, otp_action_right = st.columns(2, gap="medium")
                    with otp_action_left:
                        if st.button("Start Over", key="restart_registration", use_container_width=True):
                            pending_username = st.session_state.temp_user.get("username", "")
                            clear_pending_user(pending_username)
                            st.session_state.otp_sent = False
                            st.session_state.temp_user = {}
                            st.session_state.auth_otp_context = ""
                            st.rerun()
                    with otp_action_right:
                        if st.button("Go to Login", key="switch_register_to_login", use_container_width=True):
                            st.session_state.auth_otp_context = ""
                            st.session_state.auth_view = "login"
                            st.rerun()

                if not st.session_state.otp_sent:
                    st.markdown(
                        f'<div class="fw-auth-register-cta">Already have an account? <a href="{escape(desktop_login_href, quote=True)}" target="_top">Login</a></div>',
                        unsafe_allow_html=True,
                    )
        return

    with st.container(key="desktop_auth_panel"):
        auth_left, auth_right = st.columns([1.08, 0.92], gap="small")
        with auth_left:
            st.markdown(
                dedent(
                    """
                    <div class="fw-auth-left-panel">
                        <div class="fw-auth-logo">Fin<span>wise</span> AI</div>
                        <div class="fw-auth-tagline">
                            <h2><span class="fw-auth-typewriter">Markets move fast.</span><br><em>Move faster.</em></h2>
                            <p>Your intelligent trading workspace - real-time analysis, AI-driven signals, and broker execution in one place.</p>
                            <div class="fw-auth-stats">
                                <div class="fw-auth-stat">
                                    <strong>$4.2B</strong>
                                    <span>Volume tracked</span>
                                </div>
                                <div class="fw-auth-stat">
                                    <strong>98.4%</strong>
                                    <span>Uptime SLA</span>
                                </div>
                                <div class="fw-auth-stat">
                                    <strong>12ms</strong>
                                    <span>Avg latency</span>
                                </div>
                            </div>
                            <div class="fw-auth-ticker">
                                <div class="fw-auth-ticker-dot"></div>
                                <span>Live &mdash; <strong>BTC/USD</strong> <span class="up">UP 2.34%</span> &nbsp;|&nbsp; <strong>SPX</strong> <span class="up">UP 0.61%</span> &nbsp;|&nbsp; <strong>ETH/USD</strong> <span class="up">UP 1.87%</span></span>
                            </div>
                            <div class="fw-auth-chart-grid">
                                <div class="fw-auth-chart-card">
                                    <div class="fw-auth-chart-head">
                                        <div class="fw-auth-chart-name">Bitcoin<span class="fw-auth-chart-symbol">BTC</span></div>
                                        <div class="fw-auth-chart-badge">+2.34%</div>
                                    </div>
                                    <svg class="fw-auth-chart-svg" viewBox="0 0 132 44" preserveAspectRatio="none" aria-hidden="true">
                                        <defs>
                                            <linearGradient id="fwAuthBtcLine" x1="0" x2="1" y1="0" y2="0">
                                                <stop offset="0%" stop-color="rgba(0,230,200,0.18)" />
                                                <stop offset="55%" stop-color="#00e6c8" />
                                                <stop offset="100%" stop-color="#8ffcf0" />
                                            </linearGradient>
                                        </defs>
                                        <path class="fw-auth-chart-line" pathLength="100" d="M2 34 C14 30, 18 22, 31 25 C42 28, 48 16, 60 18 C72 20, 78 10, 91 12 C105 14, 113 7, 130 9" fill="none" stroke="url(#fwAuthBtcLine)" stroke-width="3" stroke-linecap="round" />
                                    </svg>
                                    <div class="fw-auth-chart-price">$67,420</div>
                                </div>
                                <div class="fw-auth-chart-card">
                                    <div class="fw-auth-chart-head">
                                        <div class="fw-auth-chart-name">Ethereum<span class="fw-auth-chart-symbol">ETH</span></div>
                                        <div class="fw-auth-chart-badge">+1.87%</div>
                                    </div>
                                    <svg class="fw-auth-chart-svg" viewBox="0 0 132 44" preserveAspectRatio="none" aria-hidden="true">
                                        <defs>
                                            <linearGradient id="fwAuthEthLine" x1="0" x2="1" y1="0" y2="0">
                                                <stop offset="0%" stop-color="rgba(0,230,200,0.16)" />
                                                <stop offset="58%" stop-color="#00e6c8" />
                                                <stop offset="100%" stop-color="#9dfff4" />
                                            </linearGradient>
                                        </defs>
                                        <path class="fw-auth-chart-line" pathLength="100" d="M2 30 C13 27, 19 31, 30 25 C42 18, 49 22, 60 17 C73 11, 78 18, 90 15 C104 12, 113 20, 130 14" fill="none" stroke="url(#fwAuthEthLine)" stroke-width="3" stroke-linecap="round" />
                                    </svg>
                                    <div class="fw-auth-chart-price">$3,118</div>
                                </div>
                                <div class="fw-auth-chart-card">
                                    <div class="fw-auth-chart-head">
                                        <div class="fw-auth-chart-name">Solana<span class="fw-auth-chart-symbol">SOL</span></div>
                                        <div class="fw-auth-chart-badge">+4.12%</div>
                                    </div>
                                    <svg class="fw-auth-chart-svg" viewBox="0 0 132 44" preserveAspectRatio="none" aria-hidden="true">
                                        <defs>
                                            <linearGradient id="fwAuthSolLine" x1="0" x2="1" y1="0" y2="0">
                                                <stop offset="0%" stop-color="rgba(0,230,200,0.18)" />
                                                <stop offset="52%" stop-color="#00e6c8" />
                                                <stop offset="100%" stop-color="#b2fff7" />
                                            </linearGradient>
                                        </defs>
                                        <path class="fw-auth-chart-line" pathLength="100" d="M2 36 C16 30, 20 34, 32 27 C43 21, 50 26, 62 20 C74 14, 79 18, 91 11 C102 6, 112 12, 130 7" fill="none" stroke="url(#fwAuthSolLine)" stroke-width="3" stroke-linecap="round" />
                                    </svg>
                                    <div class="fw-auth-chart-price">$148.76</div>
                                </div>
                            </div>
                        </div>
                    </div>
                    """
                ).strip(),
                unsafe_allow_html=True,
            )

        with auth_right:
            nav_markup = ""
            if auth_view != "login":
                nav_markup = f"""
                    <div class="fw-auth-mini-nav">
                        <a class="{'is-active' if auth_view == 'login' else ''}" href="{escape(desktop_login_href, quote=True)}" target="_top">Login</a>
                        <a class="{'is-active' if auth_view == 'register' else ''}" href="{escape(desktop_register_href, quote=True)}" target="_top">Sign Up</a>
                    </div>
                """
                st.markdown(nav_markup, unsafe_allow_html=True)

            if auth_notice:
                st.success(auth_notice)
            if auth_error:
                st.error(auth_error)
            if pending_signed_session:
                _render_saved_session_prompt(button_key="desktop_continue_saved_session")

            if auth_view == "login":
                st.markdown(
                    """
                    <div class="auth-page-head">
                        <div class="auth-page-kicker">Secure Login</div>
                        <div class="auth-page-title">Welcome back.</div>
                        <div class="auth-page-copy">Sign in to open your trading workspace, market analysis dashboard, and broker execution tools.</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                with st.form("login_form"):
                    username = st.text_input("Username", key="login_username_field", placeholder="workspace username").strip()
                    password = st.text_input("Password", type="password", key="login_password_field", placeholder="Password")
                    login_meta_left, login_meta_right = st.columns([0.95, 1.05], gap="small")
                    with login_meta_left:
                        remember_me = st.checkbox("Remember me", value=True, key="desktop_login_remember")
                    with login_meta_right:
                        st.markdown(
                            f'<a class="fw-auth-forgot" href="{escape(desktop_reset_href, quote=True)}" target="_top">Forgot password?</a>',
                            unsafe_allow_html=True,
                        )
                    login_submit = st.form_submit_button("Login", use_container_width=True, type="primary")

                if login_submit:
                    if not username or not password:
                        st.error("Please enter your username and password.")
                        st.stop()
                    lock_message = get_login_lock_message(username)
                    if lock_message:
                        st.error(lock_message)
                        st.stop()
                    account = authenticate_registered_user(username, password)
                    if account:
                        clear_login_failures(username)
                        clear_login_failures(account["username"])
                        _finish_password_login(account["username"], remember_me=remember_me)
                        st.rerun()
                    else:
                        record_login_failure(username)
                        lock_message = get_login_lock_message(username)
                        if lock_message:
                            st.error(lock_message)
                        else:
                            st.error("Invalid username or password.")

                st.markdown(
                    f'<div class="fw-auth-register-cta">Don&apos;t have an account? <a href="{escape(desktop_register_href, quote=True)}" target="_top">Create one free</a></div>',
                    unsafe_allow_html=True,
                )

            elif auth_view == "reset_password":
                st.markdown(
                    """
                    <div class="auth-page-head">
                        <div class="auth-page-kicker">Reset Password</div>
                        <div class="auth-page-title">Recover access.</div>
                        <div class="auth-page-copy">Confirm your account email, enter the reset code we send, and choose a new password.</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                _render_password_reset_flow(mobile=False)

            else:
                st.markdown(
                    """
                    <div class="auth-page-head">
                        <div class="auth-page-kicker">Create Account</div>
                        <div class="auth-page-title">Start your workspace.</div>
                        <div class="auth-page-copy">Create your account, verify your email with OTP, and return to the live trading workspace.</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if not st.session_state.otp_sent:
                    with st.form("register_details_form"):
                        username = st.text_input("Username", key="register_username_field", placeholder="Choose a username").strip()
                        password = st.text_input("Password", type="password", key="register_password_field", placeholder="Create a strong password")
                        email = st.text_input("Email", key="register_email_field", placeholder="you@example.com").strip()
                        phone = st.text_input("Phone (+234...)", key="register_phone_field", placeholder="+234...").strip()
                        send_otp = st.form_submit_button("Send OTP", use_container_width=True, type="primary")

                    if send_otp:
                        if not email or not username or not password:
                            st.error("Please fill in all required fields.")
                            st.stop()
                        password_ok, password_error = password_meets_policy(password)
                        if not password_ok:
                            st.error(password_error)
                            st.stop()
                        cursor.execute("SELECT 1 FROM users WHERE username=?", (username,))
                        if cursor.fetchone():
                            st.error("Username already exists. Please choose another.")
                            st.stop()
                        pw_hash = hash_password(password)
                        save_pending_user(username, pw_hash, email, phone)
                        st.session_state.pending_email = email
                        st.session_state.pending_username = username
                        st.session_state.temp_user = {
                            "username": username,
                            "password": pw_hash.decode() if isinstance(pw_hash, bytes) else pw_hash,
                            "email": email,
                            "phone": phone,
                        }
                        st.session_state.auth_otp_context = "register"
                        if send_email_otp(email, username):
                            st.session_state.otp_sent = True
                            st.rerun()
                        st.error("We could not send the OTP right now. Please try again.")

                if st.session_state.otp_sent:
                    pending_email = st.session_state.temp_user.get("email", "your email")
                    st.info(f"OTP sent to {pending_email}")

                    with st.form("register_otp_form"):
                        otp = st.text_input("Enter OTP", key="register_otp_field", placeholder="6-digit code").strip()
                        verify_submit = st.form_submit_button("Verify and Create Account", use_container_width=True, type="primary")

                    if verify_submit:
                        if not otp:
                            st.error("Please enter the OTP.")
                            st.stop()
                        stored_username = st.session_state.temp_user.get("username", "")
                        if verify_otp(stored_username, otp):
                            data = st.session_state.temp_user
                            try:
                                create_registered_user(
                                    data["username"],
                                    data["password"],
                                    data["email"],
                                    data.get("phone", ""),
                                )
                                st.success("Account created successfully.")
                                st.session_state.otp_sent = False
                                st.session_state.temp_user = {}
                                st.session_state.auth_otp_context = ""
                                st.session_state.auth_view = "login"
                                st.session_state.login_username_field = data["username"]
                                clear_pending_user(stored_username)
                                st.balloons()
                                st.rerun()
                            except Exception as e:
                                if is_integrity_error(e):
                                    st.error("Username already exists. Please choose another.")
                                else:
                                    _show_safe_operation_error("Account creation", e)
                        else:
                            st.error("Invalid or expired OTP. Please try again.")

                    otp_action_left, otp_action_right = st.columns(2, gap="medium")
                    with otp_action_left:
                        if st.button("Start Over", key="restart_registration", use_container_width=True):
                            pending_username = st.session_state.temp_user.get("username", "")
                            clear_pending_user(pending_username)
                            st.session_state.otp_sent = False
                            st.session_state.temp_user = {}
                            st.session_state.auth_otp_context = ""
                            st.rerun()
                    with otp_action_right:
                        if st.button("Go to Login", key="switch_register_to_login", use_container_width=True):
                            st.session_state.auth_otp_context = ""
                            st.session_state.auth_view = "login"
                            st.rerun()

                if not st.session_state.otp_sent:
                    st.markdown(
                        f'<div class="fw-auth-register-cta">Already have an account? <a href="{escape(desktop_login_href, quote=True)}" target="_top">Login</a></div>',
                        unsafe_allow_html=True,
                    )

    return

    if choice == "Register":
        email = st.text_input("Email").strip()
        phone = st.text_input("Phone (+234...)").strip()

        if not st.session_state.otp_sent:
            if st.button("Send OTP"):
                if not email or not username or not password:
                    st.error("❌ Please fill in all fields")
                    st.stop()
                password_ok, password_error = password_meets_policy(password)
                if not password_ok:
                    st.error(f"âŒ {password_error}")
                    st.stop()
                cursor.execute("SELECT 1 FROM users WHERE username=?", (username,))
                if cursor.fetchone():
                    st.error("âŒ Username already exists. Please choose another.")
                    st.stop()
                pw_hash = hash_password(password)
                save_pending_user(username, pw_hash, email, phone)
                st.session_state.pending_email    = email
                st.session_state.pending_username = username
                st.session_state.temp_user = {
                    "username": username,
                    "password": pw_hash.decode() if isinstance(pw_hash, bytes) else pw_hash,
                    "email": email,
                    "phone": phone
                }
                if send_email_otp(email, username):
                    st.session_state.otp_sent = True
                    st.rerun()

        if st.session_state.otp_sent:
            st.info(f"📧 OTP sent to {st.session_state.temp_user.get('email', 'your email')}")
            otp = st.text_input("Enter OTP", key="otp_input")
            if st.button("Verify & Create Account"):
                if not otp:
                    st.error("❌ Please enter the OTP")
                    st.stop()
                stored_username = st.session_state.temp_user.get("username", "")
                if verify_otp(stored_username, otp):
                    data = st.session_state.temp_user
                    try:
                        create_registered_user(
                            data["username"],
                            data["password"],
                            data["email"],
                            data.get("phone", ""),
                        )
                        st.success("✅ Account created successfully!")
                        st.session_state.otp_sent  = False
                        st.session_state.temp_user = {}
                        clear_pending_user(stored_username)
                        st.balloons()
                        st.rerun()
                    except Exception as e:
                        if is_integrity_error(e):
                            st.error("❌ Username already exists. Please choose another.")
                        else:
                            _show_safe_operation_error("Account creation", e)
                else:
                    st.error("❌ Invalid or expired OTP. Please try again.")
    else:
        if st.button("Login"):
            if not username or not password:
                st.error("❌ Please enter username and password")
                st.stop()
            lock_message = get_login_lock_message(username)
            if lock_message:
                st.error(f"âŒ {lock_message}")
                st.stop()
            account = authenticate_registered_user(username, password)
            # ✅ FIXED: use verify_password (bcrypt check) not hash_password
            if account:
                clear_login_failures(username)
                clear_login_failures(account["username"])
                _finish_password_login(account["username"])
                st.rerun()
            else:
                record_login_failure(username)
                lock_message = get_login_lock_message(username)
                if lock_message:
                    st.error(f"❌ {lock_message}")
                else:
                    st.error("❌ Invalid username or password")

# -----------------------------------
# PREMIUM
# -----------------------------------
def is_premium(username):
    cursor.execute("SELECT premium FROM users WHERE username=?", (username,))
    row = cursor.fetchone()
    return row[0] if row else 0

def upgrade_user_to_premium(username):
    cursor.execute("UPDATE users SET premium=1 WHERE username=?", (username,))
    conn.commit()


def get_user_notification_settings(username: str) -> dict:
    cursor.execute(
        """
        SELECT
            email,
            phone,
            premium,
            COALESCE(notification_whatsapp, 0),
            COALESCE(notification_telegram, 0),
            COALESCE(telegram_chat_id, '')
        FROM users
        WHERE username=?
        """,
        (username,),
    )
    row = cursor.fetchone()
    if not row:
        return {
            "email": "",
            "phone": "",
            "premium": 0,
            "notification_whatsapp": 0,
            "notification_telegram": 0,
            "telegram_chat_id": "",
        }
    return {
        "email": row[0] or "",
        "phone": row[1] or "",
        "premium": int(row[2] or 0),
        "notification_whatsapp": int(row[3] or 0),
        "notification_telegram": int(row[4] or 0),
        "telegram_chat_id": row[5] or "",
    }


def save_user_notification_settings(
    username: str,
    phone: str,
    telegram_chat_id: str,
    whatsapp_enabled: bool,
    telegram_enabled: bool,
):
    normalized_phone = normalize_phone_number(phone)
    cursor.execute(
        """
        UPDATE users
        SET phone=?,
            telegram_chat_id=?,
            notification_whatsapp=?,
            notification_telegram=?
        WHERE username=?
        """,
        (
            normalized_phone,
            telegram_chat_id.strip(),
            int(bool(whatsapp_enabled)),
            int(bool(telegram_enabled)),
            username,
        ),
    )
    conn.commit()


def get_user_account_preferences(username: str) -> dict:
    cursor.execute(
        """
        SELECT
            COALESCE(notify_buy_signals, 1),
            COALESCE(notify_sell_signals, 1),
            COALESCE(notify_signal_updates, 0),
            COALESCE(notify_high_confidence_only, 0),
            COALESCE(notify_market_digest, 1),
            COALESCE(security_authenticator_2fa, 0),
            COALESCE(security_sms_verification, 1),
            COALESCE(security_login_alerts, 1)
        FROM users
        WHERE username=?
        """,
        (username,),
    )
    row = cursor.fetchone()
    if not row:
        return {
            "notify_buy_signals": 1,
            "notify_sell_signals": 1,
            "notify_signal_updates": 0,
            "notify_high_confidence_only": 0,
            "notify_market_digest": 1,
            "security_authenticator_2fa": 0,
            "security_sms_verification": 1,
            "security_login_alerts": 1,
        }
    return {
        "notify_buy_signals": int(row[0] or 0),
        "notify_sell_signals": int(row[1] or 0),
        "notify_signal_updates": int(row[2] or 0),
        "notify_high_confidence_only": int(row[3] or 0),
        "notify_market_digest": int(row[4] or 0),
        "security_authenticator_2fa": int(row[5] or 0),
        "security_sms_verification": int(row[6] or 0),
        "security_login_alerts": int(row[7] or 0),
    }


def save_user_account_preferences(
    username: str,
    *,
    notify_buy_signals: bool,
    notify_sell_signals: bool,
    notify_signal_updates: bool,
    notify_high_confidence_only: bool,
    notify_market_digest: bool,
    security_authenticator_2fa: bool,
    security_sms_verification: bool,
    security_login_alerts: bool,
):
    cursor.execute(
        """
        UPDATE users
        SET notify_buy_signals=?,
            notify_sell_signals=?,
            notify_signal_updates=?,
            notify_high_confidence_only=?,
            notify_market_digest=?,
            security_authenticator_2fa=?,
            security_sms_verification=?,
            security_login_alerts=?
        WHERE username=?
        """,
        (
            int(bool(notify_buy_signals)),
            int(bool(notify_sell_signals)),
            int(bool(notify_signal_updates)),
            int(bool(notify_high_confidence_only)),
            int(bool(notify_market_digest)),
            int(bool(security_authenticator_2fa)),
            int(bool(security_sms_verification)),
            int(bool(security_login_alerts)),
            username,
        ),
    )
    conn.commit()


def reset_user_signal_destinations(username: str):
    cursor.execute(
        """
        UPDATE users
        SET phone='',
            telegram_chat_id='',
            notification_whatsapp=0,
            notification_telegram=0
        WHERE username=?
        """,
        (username,),
    )
    conn.commit()


def change_user_password(username: str, current_password: str, new_password: str):
    cursor.execute("SELECT password FROM users WHERE username=?", (username,))
    row = cursor.fetchone()
    if not row:
        return False, "Account could not be found."
    stored_hash = row[0]
    if not verify_password(current_password, stored_hash):
        return False, "Current password is incorrect."
    password_ok, password_error = password_meets_policy(new_password)
    if not password_ok:
        return False, password_error
    if verify_password(new_password, stored_hash):
        return False, "New password must be different from your current password."
    update_user_password(username, new_password)
    clear_login_failures(username)
    return True, "Password updated successfully."


def render_toggle_input(label: str, *, value: bool = False, key: str, help: str = None, disabled: bool = False) -> bool:
    toggle_fn = getattr(st, "toggle", None)
    if callable(toggle_fn):
        return toggle_fn(label, value=value, key=key, help=help, disabled=disabled)
    return st.checkbox(label, value=value, key=key, help=help, disabled=disabled)


def notify_premium_user(signal, username, *, signal_type: str = "", confidence: float = 0.0, is_update: bool = False, category: str = "signal"):
    if not is_premium(username):
        return

    preferences = get_user_account_preferences(username)
    normalized_category = str(category or "signal").strip().lower()
    normalized_signal_type = str(signal_type or "").strip().upper()
    confidence_value = float(confidence or 0.0)

    if normalized_category == "digest" and not preferences["notify_market_digest"]:
        return
    if normalized_category == "signal":
        if is_update and not preferences["notify_signal_updates"]:
            return
        if normalized_signal_type == "BUY" and not preferences["notify_buy_signals"]:
            return
        if normalized_signal_type == "SELL" and not preferences["notify_sell_signals"]:
            return
        if preferences["notify_high_confidence_only"] and confidence_value < 80.0:
            return

    settings = get_user_notification_settings(username)
    if settings["notification_whatsapp"] and settings["phone"]:
        whatsapp_sent, whatsapp_error = send_whatsapp_message(signal, settings["phone"])
        if not whatsapp_sent:
            print(f"WhatsApp delivery failed for {username}: {whatsapp_error}")
    if settings["notification_telegram"] and settings["telegram_chat_id"]:
        telegram_sent, telegram_error = send_telegram_message(signal, settings["telegram_chat_id"])
        if not telegram_sent:
            print(f"Telegram delivery failed for {username}: {telegram_error}")

# -----------------------------------
# SIGNAL USAGE
# -----------------------------------
def get_used(username):
    today = str(date.today())
    cursor.execute("SELECT used FROM usage WHERE username=? AND day=?",
                   (username, today))
    row = cursor.fetchone()
    return row[0] if row else 0

def use_signal(username):
    today = str(date.today())
    used  = get_used(username)
    if used == 0:
        cursor.execute("INSERT INTO usage VALUES (?, ?, ?)", (username, today, 1))
    else:
        cursor.execute("UPDATE usage SET used=? WHERE username=? AND day=?",
                       (used + 1, username, today))
    conn.commit()

def get_limit(username):
    cursor.execute("SELECT premium FROM users WHERE username=?", (username,))
    row = cursor.fetchone()
    premium = row[0] if row else 0
    if premium:
        return 999999  # unlimited
    else:
        return 5  # free users = 5 signals/day

# -----------------------------------
# CHART CACHING (prevent refresh flashing)
# -----------------------------------
def _cache_chart_data(symbol: str, tf_label: str, df: pd.DataFrame):
    """Cache chart candles to prevent redraw on every rerun."""
    cache_key = f"{symbol}_{tf_label}"
    if cache_key not in st.session_state.chart_cache:
        st.session_state.chart_cache[cache_key] = {
            "candles": [],
            "last_time": None,
            "hash": None
        }
    
    # Convert df to candles
    candles = []
    for _, row in df.tail(220).iterrows():
        ts = row.get("timestamp")
        if hasattr(ts, "timestamp"):
            time_val = int(ts.timestamp())
        else:
            time_val = int(pd.Timestamp(ts).timestamp())
        candles.append({
            "time": time_val,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"])
        })
    
    st.session_state.chart_cache[cache_key]["candles"] = candles
    if candles:
        st.session_state.chart_cache[cache_key]["last_time"] = candles[-1]["time"]
    st.session_state.last_chart_update[cache_key] = time.time()

def _get_cached_chart_data(symbol: str, tf_label: str):
    """Retrieve cached chart candles."""
    cache_key = f"{symbol}_{tf_label}"
    if cache_key in st.session_state.chart_cache:
        return st.session_state.chart_cache[cache_key].get("candles", [])
    return []

# -----------------------------------
# LIVE CHART STREAMING & AUTO-REFRESH
# -----------------------------------
def _render_live_chart_with_streaming(df: pd.DataFrame, symbol: str, tf_label: str, snapshot: dict, update_interval: int = 1000):
    """
    Renders a real-time chart using Lightweight Charts (TradingView).
    Smooth candle building without Plotly.
    """
    if df is None or df.empty or len(df) < CHART_MIN_READY_CANDLES:
        st.info("⏳ Warming up chart data...")
        return
    
    # ✅ Use Lightweight Charts directly - no Plotly, no Advanced Chart
    _render_lightweight_terminal_chart(df, symbol, tf_label)


# -----------------------------------
# CANDLESTICK CHART
# -----------------------------------
def build_candlestick_chart(df: pd.DataFrame, symbol: str, tf_label: str, show_live_updates: bool = True):
    # ✅ Merge live candle data for smooth real-time building
    if show_live_updates:
        df = _merge_live_candle_with_history(df, symbol, tf_label)
    
    df = df.copy()

    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()

    delta = df["close"].diff()
    gain  = delta.where(delta > 0, 0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs    = gain / loss.replace(0, 1e-9)
    df["rsi"] = 100 - (100 / (1 + rs))

    vol_colors = [
        "#26a69a" if c >= o else "#ef5350"
        for c, o in zip(df["close"], df["open"])
    ]

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        vertical_spacing=0.02, row_heights=[0.60, 0.20, 0.20],
    )

    fig.add_trace(go.Candlestick(
        x=df["timestamp"],
        open=df["open"], high=df["high"],
        low=df["low"],   close=df["close"],
        name=symbol,
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        increasing_fillcolor="#26a69a",  decreasing_fillcolor="#ef5350",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["ema20"].round(8), name="EMA 20",
        line=dict(color="#ffd166", width=1.2), hovertemplate="%{y:.4f}",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["ema50"].round(8), name="EMA 50",
        line=dict(color="#74b9ff", width=1.2), hovertemplate="%{y:.4f}",
    ), row=1, col=1)

    fig.add_trace(go.Bar(
        x=df["timestamp"], y=df["volume"], name="Volume",
        marker_color=vol_colors, showlegend=False,
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["rsi"].round(2), name="RSI 14",
        line=dict(color="#a29bfe", width=1.2), hovertemplate="RSI: %{y:.1f}",
    ), row=3, col=1)

    for level, color in [(70, "rgba(239,83,80,0.35)"),
                         (30, "rgba(38,166,154,0.35)")]:
        fig.add_hline(y=level,
                      line=dict(color=color, dash="dash", width=1),
                      row=3, col=1)

    fig.update_layout(
        plot_bgcolor="#0b1e2d", paper_bgcolor="#0f2639",
        font=dict(color="#8ab4c8", size=11),
        height=560, margin=dict(l=0, r=60, t=30, b=0),
        legend=dict(orientation="h", x=0, y=1.02,
                    font=dict(size=11, color="#8ab4c8"),
                    bgcolor="rgba(0,0,0,0)"),
        xaxis_rangeslider_visible=False,
        title=dict(text=f"<b>{symbol}</b>  ·  {tf_label}",
                   font=dict(color="#00f5d4", size=14), x=0.01),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#1a3a52", font_color="#e8f4f8", font_size=11),
    )

    axis_style = dict(
        gridcolor="rgba(255,255,255,0.04)",
        zerolinecolor="rgba(255,255,255,0.06)",
        tickfont=dict(color="#4a7a94", size=10), showgrid=True,
    )
    fig.update_xaxes(**axis_style)
    fig.update_yaxes(**axis_style)
    fig.update_yaxes(range=[0, 100], row=3, col=1)

    return fig


def _fmt_price(value):
    if value is None:
        return "--"
    value = float(value)
    abs_value = abs(value)
    if abs_value >= 1000:
        return f"{value:,.2f}"
    if abs_value >= 100:
        return f"{value:,.3f}"
    if abs_value >= 1:
        return f"{value:,.5f}"
    return f"{value:,.6f}"


def _fmt_pct(value):
    if value is None:
        return "--"
    return f"{value:+.2f}%"


def _fmt_compact(value):
    if value is None:
        return "--"
    value = float(value)
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.2f}K"
    return f"{value:,.2f}"


def _coalesce_market_number(*values):
    for value in values:
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except TypeError:
            pass
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _market_last_candle(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {}

    last = df.iloc[-1]
    return {
        "open": _coalesce_market_number(last.get("open")),
        "high": _coalesce_market_number(last.get("high")),
        "low": _coalesce_market_number(last.get("low")),
        "close": _coalesce_market_number(last.get("close")),
        "volume": _coalesce_market_number(last.get("volume")),
    }


def _market_series(df: pd.DataFrame, column: str, limit: int = 28) -> list[float]:
    if df is None or df.empty or column not in df.columns:
        return []
    series = pd.to_numeric(df[column], errors="coerce").dropna().tail(limit)
    return [float(value) for value in series.tolist()]


def _base_asset_from_symbol(symbol: str) -> str:
    base, _quote = split_market_symbol(symbol)
    return base or str(symbol or "").upper()


def _build_sparkline_svg(values: list[float], stroke: str = "#19dfd0") -> str:
    clean = []
    for value in values or []:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if pd.isna(numeric):
            continue
        clean.append(numeric)

    if len(clean) < 2:
        return '<div class="market-spark-empty">Waiting for live data...</div>'

    width = 120
    height = 40
    min_value = min(clean)
    max_value = max(clean)
    span = max(max_value - min_value, 1e-9)
    points = []

    for index, value in enumerate(clean):
        x = 2 + (index / (len(clean) - 1)) * (width - 4)
        y = 4 + (1 - ((value - min_value) / span)) * (height - 8)
        points.append((x, y))

    line_points = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    area_points = " ".join(
        [f"{x:.2f},{y:.2f}" for x, y in points] + [f"{width - 2:.2f},{height - 1:.2f}", f"2.00,{height - 1:.2f}"]
    )
    last_x, last_y = points[-1]
    mid_y = height / 2
    return dedent(
        f"""
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" class="market-live-svg" aria-hidden="true">
            <line x1="2" y1="4" x2="{width - 2:.2f}" y2="4" stroke="rgba(255,255,255,0.05)" stroke-width="1"></line>
            <line x1="2" y1="{mid_y:.2f}" x2="{width - 2:.2f}" y2="{mid_y:.2f}" stroke="rgba(255,255,255,0.04)" stroke-width="1" stroke-dasharray="3 3"></line>
            <line x1="2" y1="{height - 2:.2f}" x2="{width - 2:.2f}" y2="{height - 2:.2f}" stroke="rgba(255,255,255,0.05)" stroke-width="1"></line>
            <polygon points="{area_points}" fill="{stroke}" opacity="0.05"></polygon>
            <polyline points="{line_points}" fill="none" stroke="{stroke}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"></polyline>
            <circle cx="{last_x:.2f}" cy="{last_y:.2f}" r="2.9" fill="{stroke}" opacity="0.98"></circle>
        </svg>
        """
    ).strip()


def _build_volume_bar_svg(values: list[float], color: str = "#19dfd0") -> str:
    clean = []
    for value in values or []:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if pd.isna(numeric):
            continue
        clean.append(max(0.0, numeric))

    if len(clean) < 2:
        return '<div class="market-spark-empty">Waiting for live data...</div>'

    bars = clean[-14:]
    width = 88
    height = 54
    step = width / len(bars)
    max_value = max(bars) or 1
    rects = []

    for index, value in enumerate(bars):
        bar_height = max(5, (value / max_value) * (height - 10))
        x = index * step + 1.5
        y = height - bar_height - 2
        rects.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(3.5, step - 2.5):.2f}" height="{bar_height:.2f}" rx="2.2" fill="{color}" opacity="{0.35 + ((index + 1) / len(bars)) * 0.45:.2f}"></rect>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" class="market-summary-chart" aria-hidden="true">'
        f'{"".join(rects)}</svg>'
    )


def _describe_market_regime(df: pd.DataFrame) -> str:
    closes = _market_series(df, "close", limit=30)
    if len(closes) < 6:
        return "Developing"

    fast = sum(closes[-5:]) / min(5, len(closes))
    slow_window = closes[-20:] if len(closes) >= 20 else closes
    slow = sum(slow_window) / len(slow_window)
    baseline = closes[0] or 0
    momentum_pct = ((closes[-1] - baseline) / baseline) * 100 if baseline else 0.0

    if fast > slow * 1.0015 and momentum_pct > 0.18:
        return "Trend Up"
    if fast < slow * 0.9985 and momentum_pct < -0.18:
        return "Trend Down"
    if abs(momentum_pct) < 0.10:
        return "Range"
    return "Balance"


def _build_signal_gauge_svg(confidence: int, momentum_score: int, tone_color: str, regime: str, volatility_pct: float) -> str:
    confidence = max(0, min(100, int(confidence or 0)))
    momentum_score = max(0, min(100, int(momentum_score or 0)))
    outer_angle = round((confidence / 100) * 360, 2)
    inner_angle = round((momentum_score / 100) * 360, 2)
    momentum_color = "#19dfd0" if momentum_score >= 50 else "#ff6b7d"
    volatility_label = f"{volatility_pct:.2f}% avg range" if volatility_pct else "Awaiting volatility"

    return dedent(
        f"""
        <div class="signal-orb" aria-hidden="true">
            <div class="signal-orb-glow" style="background:radial-gradient(circle, {tone_color}33 0%, transparent 68%);"></div>
            <div class="signal-orb-ring signal-orb-ring-outer"
                 style="background:conic-gradient({tone_color} 0deg {outer_angle}deg, rgba(255,255,255,0.06) {outer_angle}deg 360deg);"></div>
            <div class="signal-orb-ring signal-orb-ring-inner"
                 style="background:conic-gradient({momentum_color} 0deg {inner_angle}deg, rgba(255,255,255,0.05) {inner_angle}deg 360deg);"></div>
            <div class="signal-orb-core">
                <div class="signal-orb-value">{confidence}%</div>
                <div class="signal-orb-label">Confidence</div>
            </div>
            <div class="signal-orb-regime" style="color:{momentum_color};">{escape(regime.upper())}</div>
            <div class="signal-orb-volatility">{escape(volatility_label)}</div>
        </div>
        """
    ).strip()


def _render_component_html(html: str, *, height: int):
    frame_html = dedent(html).strip()
    base_style = dedent(
        """
        <style>
        html, body {
          margin: 0 !important;
          width: 100% !important;
          overflow-x: hidden !important;
          max-width: 100% !important;
        }
        body > * {
          max-width: 100% !important;
        }
        </style>
        """
    ).strip()
    if "<head>" in frame_html:
        frame_html = frame_html.replace("<head>", f"<head>\n{base_style}\n", 1)
    else:
        frame_html = f"{base_style}\n{frame_html}"
    components.html(frame_html, height=height, scrolling=False)


def _render_scripted_html(html: str, *, height: int):
    frame_html = dedent(html).strip()
    base_style = dedent(
        """
        <style>
        html, body {
          margin: 0 !important;
          width: 100% !important;
          max-width: 100% !important;
          overflow-x: hidden !important;
        }
        body > * {
          max-width: 100% !important;
        }
        </style>
        """
    ).strip()
    if "<head>" in frame_html:
        frame_html = frame_html.replace("<head>", f"<head>\n{base_style}\n", 1)
    else:
        frame_html = f"{base_style}\n{frame_html}"
    components.html(frame_html, height=height, scrolling=False)


def _trigger_ai_signal(
    username: str,
    symbol: str,
    tf_label: str,
    df: pd.DataFrame,
    *,
    next_view: str = "Signal Result",
):
    balance_basis = 10000.0
    trade_style = _current_trade_style()
    try:
        profile = st.session_state.get("manual_broker_profile") or {}
        balance_basis = float(
            st.session_state.get("auto_trade_balance_snapshot")
            or profile.get("balance")
            or balance_basis
        )
    except Exception:
        balance_basis = 10000.0

    with st.spinner("AI analyzing market structure, regime, risk & entry..."):
        result = ai_signal_for_user(
            username,
            df,
            symbol=symbol,
            current_balance=balance_basis,
            timeframe=tf_label,
            trade_style=trade_style,
        )

    try:
        _update_hidden_crypto_instant_signal(
            username=username,
            symbol=symbol,
            tf_label=tf_label,
            df=df,
            snapshot=engine.get_market_snapshot(symbol) or {},
            orderbook=engine.get_orderbook(symbol, depth=10) or {},
            force=True,
        )
    except Exception as exc:
        APP_LOGGER.warning("Live crypto signal refresh failed after AI signal request: %s", exc)

    st.session_state["last_signal"] = result
    st.session_state["last_signal_meta"] = {
        "symbol": symbol,
        "tf_label": tf_label,
        "trade_style": trade_style,
        "checked_at": time.time(),
        "updated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "refresh_trigger": "manual",
    }
    use_signal(username)

    notification_payload = _build_signal_notification_payload(username, symbol, tf_label, result)
    notify_premium_user(
        notification_payload["message"],
        username,
        signal_type=notification_payload["signal_type"],
        confidence=notification_payload["confidence"],
        is_update=notification_payload["is_update"],
    )
    if next_view == "Trading Desk":
        st.session_state["trading_desk_view"] = "Signal Workspace"
        st.query_params["mdeskmode"] = "Signal Workspace"
        st.query_params["mnav"] = "Trading Desk"
        st.session_state["nav_choice"] = "Trading Desk"
    elif next_view:
        st.query_params["mnav"] = next_view
        st.session_state["nav_choice"] = next_view
    st.rerun()


def _refresh_signal_result_crypto_signal(
    username: str,
    symbol: str,
    tf_label: str,
    trade_style: str,
    *,
    trigger: str = "auto",
) -> tuple[bool, str]:
    normalized_style = normalize_trade_style(trade_style or _current_trade_style())
    is_auto_refresh = str(trigger or "").strip().lower() == "auto_refresh"
    premium = bool(is_premium(username))
    if not premium and not is_auto_refresh and int(get_used(username) or 0) >= int(get_limit(username) or 0):
        return False, "Daily signal limit reached. Upgrade for more signals."

    prior_style = _current_trade_style()
    _set_current_trade_style(normalized_style)
    try:
        try:
            engine.refresh_symbol(symbol)
        except Exception as exc:
            APP_LOGGER.warning("Signal result market refresh failed for %s: %s", symbol, exc)

        df = engine.get_history(symbol, tf_label)
        if df is None or df.empty:
            df, _, _ = _load_trading_desk_panel_data(symbol, tf_label)
        if df is None or df.empty or len(df) < AI_SIGNAL_MIN_READY_CANDLES:
            return False, "Waiting for enough fresh candle history to refresh this signal."

        balance_basis = 10000.0
        try:
            profile = st.session_state.get("manual_broker_profile") or {}
            balance_basis = float(
                st.session_state.get("auto_trade_balance_snapshot")
                or profile.get("balance")
                or balance_basis
            )
        except Exception:
            balance_basis = 10000.0

        result = ai_signal_for_user(
            username,
            df,
            symbol=symbol,
            current_balance=balance_basis,
            timeframe=tf_label,
            trade_style=normalized_style,
        )
        try:
            _update_hidden_crypto_instant_signal(
                username=username,
                symbol=symbol,
                tf_label=tf_label,
                df=df,
                snapshot=engine.get_market_snapshot(symbol) or {},
                orderbook=engine.get_orderbook(symbol, depth=10) or {},
                force=True,
            )
        except Exception as exc:
            APP_LOGGER.warning("Live crypto signal refresh failed on result page: %s", exc)

        now = time.time()
        st.session_state["last_signal"] = result
        st.session_state["last_signal_meta"] = {
            "symbol": symbol,
            "tf_label": tf_label,
            "trade_style": normalized_style,
            "checked_at": now,
            "updated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "refresh_trigger": trigger,
        }
        if not is_auto_refresh:
            use_signal(username)
        return True, ""
    except Exception as exc:
        APP_LOGGER.warning("Signal result crypto refresh failed for %s %s: %s", symbol, tf_label, exc)
        return False, f"Signal refresh failed: {exc}"
    finally:
        _set_current_trade_style(prior_style)


def _render_market_analysis_summary(
    symbol: str,
    tf_label: str,
    snapshot: dict,
    df: pd.DataFrame,
    *,
    mobile_layout: bool = False,
):
    snapshot = snapshot or {}
    forex_market = is_forex_symbol(symbol) or snapshot.get("asset_class") == "forex"
    last_candle = _market_last_candle(df)
    last_price = _coalesce_market_number(snapshot.get("last_price"), last_candle.get("close"))
    mark_price = _coalesce_market_number(snapshot.get("mark_price"), last_price)
    day_change = _coalesce_market_number(snapshot.get("price_24h_pcnt"))
    if day_change is not None:
        day_change *= 100
    session_change = _coalesce_market_number(snapshot.get("candle_change_pct"))
    if session_change is None and last_candle.get("open") not in (None, 0):
        session_change = ((last_candle.get("close", 0) - last_candle.get("open", 0)) / last_candle.get("open", 1)) * 100
    volume_value = _coalesce_market_number(snapshot.get("volume_24h"), last_candle.get("volume"))
    open_interest = _coalesce_market_number(snapshot.get("open_interest"))
    base_asset = _base_asset_from_symbol(symbol)
    volume_svg = _build_volume_bar_svg(_market_series(df, "volume", limit=20))
    market_kind = "Forex spot" if forex_market else "Perpetual"
    price_anchor_label = "Mid" if forex_market else "Mark"
    range_value = None
    if snapshot.get("high_24h") is not None and snapshot.get("low_24h") is not None:
        range_value = _coalesce_market_number(snapshot.get("high_24h")) - _coalesce_market_number(snapshot.get("low_24h"))
    turnover_meta = f"Range {_fmt_price(range_value)}" if forex_market else f"Turnover {_fmt_compact(snapshot.get('turnover_24h'))}"

    summary_cards = [
        {
            "kicker": "Market",
            "value": escape(symbol),
            "meta": f"{market_kind} | {escape(tf_label)}",
            "small": True,
            "delta": "",
            "card_class": "",
            "extra": "",
        },
        {
            "kicker": "Last Price",
            "value": _fmt_price(last_price),
            "meta": f"{price_anchor_label} {_fmt_price(mark_price)}",
            "small": False,
            "delta": "",
            "card_class": "",
            "extra": "",
        },
        {
            "kicker": "24h Change",
            "value": _fmt_pct(day_change),
            "meta": turnover_meta,
            "small": True,
            "delta": _fmt_pct(day_change),
            "card_class": "",
            "extra": "",
        },
        {
            "kicker": "Session",
            "value": _fmt_pct(session_change),
            "meta": "Current candle move",
            "small": True,
            "delta": _fmt_pct(session_change),
            "card_class": "",
            "extra": "",
        },
        {
            "kicker": "Tick Volume" if forex_market else "24h Volume",
            "value": _fmt_compact(volume_value),
            "meta": "Indicative FX feed" if forex_market else base_asset,
            "small": True,
            "delta": "",
            "card_class": " market-summary-card-volume",
            "extra": volume_svg,
        },
    ]

    card_html = []
    for card in summary_cards:
        delta_color = "#19dfd0"
        delta_value = card["delta"]
        if delta_value.startswith("-"):
            delta_color = "#ff6b7d"
        elif delta_value in {"", "--"}:
            delta_color = "#7f9ab0"

        value_class = "market-summary-value-small" if card["small"] else "market-summary-value"
        delta_html = ""
        if delta_value:
            delta_html = f'<div class="market-summary-delta" style="color:{delta_color};">{escape(delta_value)}</div>'

        extra_html = card.get("extra", "")
        card_html.append(
            dedent(
                f"""
                <div class="market-summary-card{card.get("card_class", "")}">
                    <div>
                        <div class="market-summary-kicker">{escape(card["kicker"])}</div>
                        <div class="{value_class}">{escape(card["value"])}</div>
                        {delta_html}
                        <div class="market-summary-meta">{escape(card["meta"])}</div>
                    </div>
                    {extra_html}
                </div>
                """
            ).strip()
        )

    if mobile_layout:
        summary_layout_css = """
      .market-summary-grid {
        display: flex;
        gap: 10px;
        overflow-x: auto;
        overflow-y: hidden;
        padding-bottom: 2px;
        scroll-snap-type: x proximity;
        scrollbar-width: none;
      }
      .market-summary-grid::-webkit-scrollbar {
        display: none;
      }
      .market-summary-card {
        flex: 0 0 min(14.8rem, 84vw);
        min-height: 102px;
        padding: 14px 15px;
        position: relative;
        overflow: hidden;
        scroll-snap-align: start;
        background:
          radial-gradient(circle at top right, rgba(25, 223, 208, 0.08), transparent 28%),
          linear-gradient(180deg, rgba(10, 23, 36, 0.98) 0%, rgba(8, 19, 31, 0.98) 100%);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 18px;
        box-shadow: 0 18px 34px rgba(0,0,0,0.2);
      }
      .market-summary-card-volume {
        flex-basis: min(17.2rem, 92vw);
        display: grid;
        grid-template-columns: minmax(0, 1fr) 78px;
        gap: 10px;
        align-items: end;
      }
      .market-summary-value {
        color: white;
        font-size: 21px;
        font-weight: 800;
        margin-top: 10px;
        letter-spacing: -0.02em;
      }
      .market-summary-value-small {
        color: white;
        font-size: 17px;
        font-weight: 800;
        margin-top: 10px;
      }
      .market-summary-chart {
        width: 100%;
        height: 46px;
        align-self: center;
      }
      @media (max-width: 390px) {
        .market-summary-card {
          flex-basis: min(13.6rem, 84vw);
          padding: 13px 14px;
        }
        .market-summary-card-volume {
          flex-basis: min(15.8rem, 92vw);
          grid-template-columns: minmax(0, 1fr) 68px;
        }
        .market-summary-value {
          font-size: 19px;
        }
        .market-summary-value-small {
          font-size: 16px;
        }
      }
        """
        component_height = 146
    else:
        summary_layout_css = """
      .market-summary-grid {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 12px;
      }
      .market-summary-card {
        min-height: 108px;
        padding: 16px 18px;
        position: relative;
        overflow: hidden;
        background:
          radial-gradient(circle at top right, rgba(25, 223, 208, 0.08), transparent 28%),
          linear-gradient(180deg, rgba(10, 23, 36, 0.98) 0%, rgba(8, 19, 31, 0.98) 100%);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 22px;
        box-shadow: 0 22px 48px rgba(0,0,0,0.22);
      }
      .market-summary-card-volume {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 86px;
        gap: 12px;
        align-items: end;
      }
      .market-summary-value {
        color: white;
        font-size: 24px;
        font-weight: 800;
        margin-top: 12px;
        letter-spacing: -0.02em;
      }
      .market-summary-value-small {
        color: white;
        font-size: 19px;
        font-weight: 800;
        margin-top: 12px;
      }
      .market-summary-chart {
        width: 100%;
        height: 58px;
        align-self: center;
      }
      @media (max-width: 700px) {
        .market-summary-grid {
          grid-template-columns: 1fr;
          gap: 10px;
        }
        .market-summary-card {
          min-height: 0;
          padding: 14px 15px;
          border-radius: 18px;
        }
        .market-summary-card-volume {
          grid-template-columns: 1fr;
        }
        .market-summary-value {
          font-size: 22px;
          margin-top: 10px;
        }
        .market-summary-value-small {
          font-size: 18px;
          margin-top: 10px;
        }
        .market-summary-chart {
          height: 48px;
        }
      }
        """
        component_height = 136

    summary_html = f"""
    <html>
    <head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      * {{ box-sizing: border-box; }}
      html, body {{
        margin: 0;
        padding: 0;
        background: transparent;
        font-family: "Segoe UI", Arial, sans-serif;
        color: #e8f4f8;
      }}
      .market-summary-kicker {{
        color: #5f7f93;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}
      .market-summary-meta {{
        color: #7f9ab0;
        font-size: 11px;
        margin-top: 5px;
      }}
      .market-summary-delta {{
        font-size: 12px;
        font-weight: 800;
        margin-top: 7px;
      }}
      {summary_layout_css}
    </style>
    </head>
    <body>
      <div class="market-summary-grid">{"".join(card_html)}</div>
    </body>
    </html>
    """
    _render_component_html(
        summary_html,
        height=component_height,
    )


def _render_market_analysis_overview(
    symbol: str,
    tf_label: str,
    snapshot: dict,
    df: pd.DataFrame,
    *,
    mobile_layout: bool = False,
):
    snapshot = snapshot or {}
    forex_market = is_forex_symbol(symbol) or snapshot.get("asset_class") == "forex"
    last_candle = _market_last_candle(df)
    day_change = _coalesce_market_number(snapshot.get("price_24h_pcnt"))
    if day_change is not None:
        day_change *= 100
    high_24h = _coalesce_market_number(snapshot.get("high_24h"))
    low_24h = _coalesce_market_number(snapshot.get("low_24h"))
    range_24h = (high_24h - low_24h) if high_24h is not None and low_24h is not None else None
    if forex_market:
        overview_items = [
            ("Open", _fmt_price(last_candle.get("open"))),
            ("High", _fmt_price(last_candle.get("high"))),
            ("Low", _fmt_price(last_candle.get("low"))),
            ("Close", _fmt_price(last_candle.get("close"))),
            ("24h Change", _fmt_pct(day_change)),
            ("24h High", _fmt_price(high_24h)),
            ("24h Low", _fmt_price(low_24h)),
            ("24h Range", _fmt_price(range_24h)),
            ("Tick Volume", _fmt_compact(snapshot.get("volume_24h"))),
            ("Feed", escape(str(snapshot.get("feed_source") or "Yahoo Finance FX"))),
        ]
    else:
        overview_items = [
            ("Open", _fmt_price(last_candle.get("open"))),
            ("High", _fmt_price(last_candle.get("high"))),
            ("Low", _fmt_price(last_candle.get("low"))),
            ("Close", _fmt_price(last_candle.get("close"))),
            ("24h Change", _fmt_pct(day_change)),
            ("24h High", _fmt_price(snapshot.get("high_24h"))),
            ("24h Low", _fmt_price(snapshot.get("low_24h"))),
            ("24h Volume", _fmt_compact(snapshot.get("volume_24h"))),
            ("Open Interest", _fmt_compact(snapshot.get("open_interest"))),
            ("Funding", "--" if snapshot.get("funding_rate") is None else f"{snapshot.get('funding_rate') * 100:.4f}%"),
        ]
    overview_html = "".join(
        dedent(
            f"""
            <div class="market-overview-item">
                <div class="market-overview-label">{escape(label)}</div>
                <div class="market-overview-value">{value}</div>
            </div>
            """
        ).strip()
        for label, value in overview_items
    )
    if mobile_layout:
        overview_layout_css = """
      .market-overview-card {
        padding: 16px;
        background:
          radial-gradient(circle at top right, rgba(25, 223, 208, 0.08), transparent 28%),
          linear-gradient(180deg, rgba(10, 23, 36, 0.98) 0%, rgba(8, 19, 31, 0.98) 100%);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 18px;
        box-shadow: 0 18px 36px rgba(0,0,0,0.2);
      }
      .market-card-header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 12px;
      }
      .market-card-title {
        color: white;
        font-size: 16px;
        font-weight: 800;
        margin-top: 6px;
      }
      .market-card-sub {
        color: #7f9ab0;
        font-size: 11px;
        margin-top: 4px;
      }
      .market-overview-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }
      .market-overview-item {
        background: rgba(10, 24, 38, 0.86);
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 12px;
        padding: 11px 12px;
      }
      .market-overview-value {
        color: white;
        font-size: 13px;
        font-weight: 700;
        margin-top: 6px;
      }
      @media (max-width: 360px) {
        .market-overview-grid {
          gap: 8px;
        }
        .market-overview-item {
          padding: 10px 11px;
        }
        .market-overview-value {
          font-size: 12px;
        }
      }
        """
        component_height = 426
    else:
        overview_layout_css = """
      .market-overview-card {
        padding: 18px;
        background:
          radial-gradient(circle at top right, rgba(25, 223, 208, 0.08), transparent 28%),
          linear-gradient(180deg, rgba(10, 23, 36, 0.98) 0%, rgba(8, 19, 31, 0.98) 100%);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 22px;
        box-shadow: 0 22px 48px rgba(0,0,0,0.22);
      }
      .market-card-header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 16px;
      }
      .market-card-title {
        color: white;
        font-size: 18px;
        font-weight: 800;
        margin-top: 6px;
      }
      .market-card-sub {
        color: #7f9ab0;
        font-size: 12px;
        margin-top: 4px;
      }
      .market-overview-grid {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 12px;
      }
      .market-overview-item {
        background: rgba(10, 24, 38, 0.86);
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 14px;
        padding: 12px 14px;
      }
      .market-overview-value {
        color: white;
        font-size: 15px;
        font-weight: 700;
        margin-top: 6px;
      }
      @media (max-width: 700px) {
        .market-overview-card {
          padding: 16px;
          border-radius: 18px;
        }
        .market-card-header {
          margin-bottom: 12px;
        }
        .market-card-title {
          font-size: 16px;
        }
        .market-overview-grid {
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 10px;
        }
        .market-overview-item {
          padding: 11px 12px;
          border-radius: 12px;
        }
        .market-overview-value {
          font-size: 14px;
        }
      }
      @media (max-width: 460px) {
        .market-overview-grid {
          grid-template-columns: 1fr;
        }
      }
        """
        component_height = 292

    overview_panel_html = f"""
    <html>
    <head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      * {{ box-sizing: border-box; }}
      html, body {{
        margin: 0;
        padding: 0;
        background: transparent;
        font-family: "Segoe UI", Arial, sans-serif;
        color: #e8f4f8;
      }}
      .market-card-kicker {{
        color: #5f7f93;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}
      .market-overview-label {{
        color: #5f7f93;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}
      {overview_layout_css}
    </style>
    </head>
    <body>
      <div class="market-overview-card">
        <div class="market-card-header">
          <div>
            <div class="market-card-kicker">Market Overview</div>
            <div class="market-card-title">{escape(symbol)}</div>
            <div class="market-card-sub">Execution levels and live quote context for the active market.</div>
          </div>
        </div>
        <div class="market-overview-grid">{overview_html}</div>
      </div>
    </body>
    </html>
    """
    _render_component_html(
        overview_panel_html,
        height=component_height,
    )


def _render_market_analysis_live_board(symbol: str, tf_label: str, snapshot: dict, df: pd.DataFrame):
    snapshot = snapshot or {}
    forex_market = is_forex_symbol(symbol) or snapshot.get("asset_class") == "forex"
    market_subtitle = "Spot FX" if forex_market else "Perpetual"
    close_series = engine.get_metric_series(symbol, "last_price", limit=30) or _market_series(df, "close", limit=30)
    high_series = engine.get_metric_series(symbol, "high_24h", limit=30) or _market_series(df, "high", limit=30)
    low_series = engine.get_metric_series(symbol, "low_24h", limit=30) or _market_series(df, "low", limit=30)
    volume_series = engine.get_metric_series(symbol, "volume_24h", limit=30) or _market_series(df, "volume", limit=30)
    mark_series = engine.get_metric_series(symbol, "mark_price", limit=30) or close_series
    funding_series = engine.get_metric_series(symbol, "funding_rate", limit=30)
    open_interest_series = engine.get_metric_series(symbol, "open_interest", limit=30)
    index_series = engine.get_metric_series(symbol, "index_price", limit=30) or mark_series
    if df is not None and not df.empty:
        working = df.tail(30).copy()
        working["range"] = pd.to_numeric(working["high"], errors="coerce") - pd.to_numeric(working["low"], errors="coerce")
        range_series = pd.to_numeric(working["range"], errors="coerce").dropna().tolist()
    else:
        range_series = []

    funding_rate = snapshot.get("funding_rate")
    funding_display = "--" if funding_rate is None else f"{funding_rate * 100:.4f}%"
    last_price = _coalesce_market_number(snapshot.get("last_price"), (df.iloc[-1]["close"] if df is not None and not df.empty else None))
    day_change = _coalesce_market_number(snapshot.get("price_24h_pcnt"))
    if day_change is not None:
        day_change *= 100
    notional_change = None
    if last_price is not None and day_change is not None:
        notional_change = last_price * (day_change / 100)
    delta_text = _fmt_pct(day_change)
    if notional_change is not None:
        delta_text = f"{_fmt_pct(day_change)} | {_fmt_price(abs(notional_change))}"
    delta_color = "#19dfd0" if (day_change or 0) >= 0 else "#ff6b7d"
    if forex_market:
        high_24h = _coalesce_market_number(snapshot.get("high_24h"))
        low_24h = _coalesce_market_number(snapshot.get("low_24h"))
        range_24h = (high_24h - low_24h) if high_24h is not None and low_24h is not None else None
        live_cards = [
            ("Spot Price", _fmt_price(snapshot.get("last_price")), "Latest FX quote", close_series, "#19dfd0"),
            ("Mid Price", _fmt_price(snapshot.get("mark_price")), "Quote anchor", mark_series, "#4fa2ff"),
            ("24h Change", _fmt_pct(day_change), "Daily pressure", close_series, delta_color),
            ("24h High", _fmt_price(high_24h), "Session ceiling", high_series or close_series, "#8ec5ff"),
            ("24h Low", _fmt_price(low_24h), "Session floor", low_series or close_series, "#19dfd0"),
            ("24h Range", _fmt_price(range_24h), "High-low spread", range_series or close_series, "#8ec5ff"),
            ("Tick Volume", _fmt_compact(snapshot.get("volume_24h")), "Indicative activity", volume_series or close_series, "#19dfd0"),
            ("Feed", "Yahoo FX", "Indicative spot data", close_series, "#4fa2ff"),
        ]
    else:
        live_cards = [
            ("Perpetual", _fmt_price(snapshot.get("last_price")), "Terminal price", close_series, "#19dfd0"),
            ("Mark Price", _fmt_price(snapshot.get("mark_price")), "Index anchor", mark_series, "#4fa2ff"),
            ("Funding Rate", funding_display, "Current funding estimate", funding_series or range_series or close_series, "#ff6b7d" if (funding_rate or 0) < 0 else "#19dfd0"),
            ("24h High", _fmt_price(snapshot.get("high_24h")), "Session ceiling", high_series or close_series, "#8ec5ff"),
            ("24h Low", _fmt_price(snapshot.get("low_24h")), "Session floor", low_series or close_series, "#19dfd0"),
            ("Open Interest", _fmt_compact(snapshot.get("open_interest")), "Active futures positioning", open_interest_series or close_series, "#8ec5ff"),
            ("24h Volume", _fmt_compact(snapshot.get("volume_24h")), f"{_base_asset_from_symbol(symbol)} volume", volume_series or close_series, "#19dfd0"),
            ("Index Price", _fmt_price(snapshot.get("index_price")), "Composite reference", index_series or close_series, "#4fa2ff"),
        ]

    live_html = "".join(
        dedent(
            f"""
            <div class="market-live-item">
                <div class="market-live-label">{escape(label)}</div>
                <div class="market-live-value">{value}</div>
                <div class="market-live-sub">{escape(subtitle)}</div>
                {_build_sparkline_svg(series, stroke=color)}
            </div>
            """
        ).strip()
        for label, value, subtitle, series, color in live_cards
    )

    live_board_html = f"""
    <html>
    <head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      * {{ box-sizing: border-box; }}
      html, body {{
        margin: 0;
        padding: 0;
        background: transparent;
        font-family: "Segoe UI", Arial, sans-serif;
        color: #e8f4f8;
      }}
      .market-live-card {{
        padding: 16px;
        background:
          radial-gradient(circle at top right, rgba(25, 223, 208, 0.08), transparent 28%),
          linear-gradient(180deg, rgba(10, 23, 36, 0.98) 0%, rgba(8, 19, 31, 0.98) 100%);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 22px;
        box-shadow: 0 22px 48px rgba(0,0,0,0.22);
      }}
      .market-card-header {{
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 12px;
      }}
      .market-card-kicker {{
        color: #5f7f93;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}
      .market-card-title {{
        color: white;
        font-size: 17px;
        font-weight: 800;
        margin-top: 5px;
      }}
      .market-card-sub {{
        color: #7f9ab0;
        font-size: 12px;
        margin-top: 4px;
      }}
      .market-live-hero {{
        display: flex;
        align-items: flex-start;
        justify-content: flex-end;
        gap: 12px;
        margin-bottom: 14px;
      }}
      .market-live-hero-price {{
        color: white;
        font-size: 26px;
        font-weight: 800;
        line-height: 1;
        text-align: right;
      }}
      .market-live-hero-delta {{
        font-size: 12px;
        font-weight: 800;
        margin-top: 6px;
        text-align: right;
      }}
      .market-live-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }}
      .market-live-item {{
        background: rgba(10, 24, 38, 0.86);
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 14px;
        padding: 10px 12px;
      }}
      .market-live-label {{
        color: #5f7f93;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}
      .market-live-value {{
        color: white;
        font-size: 16px;
        font-weight: 800;
        margin-top: 4px;
      }}
      .market-live-sub {{
        color: #7f9ab0;
        font-size: 11px;
        margin-top: 3px;
      }}
      .market-live-svg {{
        width: 100%;
        height: 38px;
        margin-top: 8px;
      }}
      .market-spark-empty {{
        color: #58778b;
        font-size: 11px;
        margin-top: 16px;
      }}
      @media (max-width: 700px) {{
        .market-live-card {{
          padding: 16px;
          border-radius: 18px;
        }}
        .market-live-hero {{
          flex-direction: column;
          align-items: flex-start;
          gap: 10px;
        }}
        .market-live-hero-price,
        .market-live-hero-delta {{
          text-align: left;
        }}
        .market-live-hero-price {{
          font-size: 24px;
        }}
        .market-live-grid {{
          grid-template-columns: 1fr;
          gap: 10px;
        }}
        .market-live-item {{
          padding: 11px 12px;
          border-radius: 12px;
        }}
      }}
    </style>
    </head>
    <body>
      <div class="market-live-card">
        <div class="market-card-header">
          <div>
            <div class="market-card-kicker">Live Market</div>
            <div class="market-card-title">{escape(symbol)}</div>
            <div class="market-card-sub">{market_subtitle} | {escape(tf_label)} terminal</div>
          </div>
        </div>
        <div class="market-live-hero">
          <div>
            <div class="market-live-hero-price">{_fmt_price(last_price)}</div>
            <div class="market-live-hero-delta" style="color:{delta_color};">{delta_text}</div>
          </div>
        </div>
        <div class="market-live-grid">{live_html}</div>
      </div>
    </body>
    </html>
    """
    _render_component_html(
        live_board_html,
        height=612,
    )


def _render_market_signal_sidebar(
    username: str,
    symbol: str,
    tf_label: str,
    df: pd.DataFrame,
    *,
    cta_mode: str = "generate",
    mobile_target: bool = False,
):
    try:
        _update_hidden_crypto_instant_signal(
            username=username,
            symbol=symbol,
            tf_label=tf_label,
            df=df,
            snapshot=engine.get_market_snapshot(symbol) or {},
            orderbook=engine.get_orderbook(symbol, depth=10) or {},
        )
    except Exception as exc:
        APP_LOGGER.warning("Hidden crypto instant signal update failed in signal sidebar: %s", exc)

    signal_result = st.session_state.get("last_signal") or {}
    signal_meta = st.session_state.get("last_signal_meta") or {}
    active_trade_style = _current_trade_style()
    has_matching_signal = bool(signal_result) and (
        not signal_meta
        or (
            signal_meta.get("symbol") == symbol
            and signal_meta.get("tf_label") == tf_label
            and str(signal_meta.get("trade_style", active_trade_style) or active_trade_style) == active_trade_style
        )
    )
    premium = is_premium(username)
    used = get_used(username)
    limit = get_limit(username)
    usage_label = f"{used}x used today"

    last_candle = _market_last_candle(df)
    close_series = _market_series(df, "close", limit=24)
    volume_series = _market_series(df, "volume", limit=24)
    regime_label = _describe_market_regime(df)
    trend_pct = None
    if len(close_series) >= 2 and close_series[0]:
        trend_pct = ((close_series[-1] - close_series[0]) / close_series[0]) * 100
    momentum_score = 50 if trend_pct is None else int(max(0, min(100, 50 + (trend_pct * 8.0))))
    session_move = None
    if last_candle.get("open") not in (None, 0):
        session_move = ((last_candle.get("close", 0) - last_candle.get("open", 0)) / last_candle.get("open", 1)) * 100

    avg_range_pct = 0.0
    if df is not None and not df.empty:
        working = df.tail(24).copy()
        highs = pd.to_numeric(working.get("high"), errors="coerce")
        lows = pd.to_numeric(working.get("low"), errors="coerce")
        closes = pd.to_numeric(working.get("close"), errors="coerce").replace(0, pd.NA)
        range_pct = (((highs - lows) / closes) * 100).dropna()
        if not range_pct.empty:
            avg_range_pct = float(range_pct.mean())

    volume_state = "Stable"
    if len(volume_series) >= 10:
        recent_volume = sum(volume_series[-5:]) / 5
        prior_volume = sum(volume_series[-10:-5]) / 5
        if prior_volume:
            volume_ratio = recent_volume / prior_volume
            if volume_ratio >= 1.10:
                volume_state = "Expanding"
            elif volume_ratio <= 0.90:
                volume_state = "Cooling"

    levels = {}
    active_trade_style = TRADE_STYLE_LABELS.get(_current_trade_style(), "Day Trade")
    if has_matching_signal:
        signal_label = signal_result.get("signal", "HOLD")
        display_label = signal_label if signal_label in {"BUY", "SELL"} else "NEUTRAL"
        confidence = int(signal_result.get("confidence", 0) or 0)
        reason = signal_result.get("reason", "Waiting for a clean setup.")
        levels = signal_result.get("entry_exit", {}) or {}
        active_trade_style = str(signal_result.get("trade_style", active_trade_style) or active_trade_style)
        support = levels.get("stop_loss") or last_candle.get("low")
        resistance = levels.get("take_profit") or last_candle.get("high")
        entry_value = levels.get("actual_entry") or levels.get("entry_price") or last_candle.get("close")
    else:
        display_label = "NEUTRAL"
        confidence = 62
        reason = "Wait for breakout confirmation."
        support = last_candle.get("low")
        resistance = last_candle.get("high")
        entry_value = last_candle.get("close")

    if display_label == "BUY":
        tone_color = "#19dfd0"
    elif display_label == "SELL":
        tone_color = "#ff6b7d"
    else:
        tone_color = "#5ce1d5"

    risk_reward = _coalesce_market_number(levels.get("risk_reward_ratio"))
    gauge_svg = _build_signal_gauge_svg(confidence, momentum_score, tone_color, regime_label, avg_range_pct)
    bias_parts = [f"Trend {_fmt_pct(trend_pct)}", f"Session {_fmt_pct(session_move)}", f"Volume {volume_state}"]
    signal_bias = " | ".join(part for part in bias_parts if part and "--" not in part)
    context_cards = [
        ("Regime", regime_label, "Current structure"),
        ("Trend", _fmt_pct(trend_pct), "24-bar move"),
        ("Avg Range", f"{avg_range_pct:.2f}%" if avg_range_pct else "--", "Per candle"),
        ("Volume", volume_state, "Participation"),
        ("Entry", _fmt_price(entry_value), "Signal anchor"),
        ("Reward / Risk", f"{risk_reward:.2f}x" if risk_reward is not None else "--", "Trade quality"),
    ]
    context_html = "".join(
        dedent(
            f"""
            <div class="context-card">
              <div class="section-label">{escape(label)}</div>
              <div class="context-value">{escape(value)}</div>
              <div class="context-sub">{escape(subtitle)}</div>
            </div>
            """
        ).strip()
        for label, value, subtitle in context_cards
    )

    signal_html = dedent(
        f"""
        <html>
        <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
          * {{ box-sizing: border-box; }}
          html, body {{
            margin: 0;
            padding: 0;
            background: transparent;
            font-family: "Segoe UI", Arial, sans-serif;
            color: #e8f4f8;
          }}
          .signal-card {{
            background:
              radial-gradient(circle at top right, rgba(25,223,208,0.10), transparent 26%),
              linear-gradient(180deg, rgba(10,23,36,0.98) 0%, rgba(8,19,31,0.98) 100%);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 22px;
            padding: 16px 16px 14px;
            box-shadow: 0 22px 44px rgba(0,0,0,0.22);
            min-height: 430px;
          }}
          .signal-top {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 10px;
          }}
          .signal-title {{
            color: white;
            font-size: 16px;
            font-weight: 800;
          }}
          .signal-sub {{
            color: #7f9ab0;
            font-size: 11px;
            margin-top: 4px;
          }}
          .signal-pill {{
            padding: 5px 9px;
            border-radius: 999px;
            background: rgba(25,223,208,0.08);
            border: 1px solid rgba(25,223,208,0.16);
            color: #7de8db;
            font-size: 10px;
            font-weight: 700;
            white-space: nowrap;
          }}
          .signal-gauge-wrap {{
            width: 188px;
            height: 188px;
            margin: 16px auto 0;
            display: flex;
            align-items: center;
            justify-content: center;
          }}
          .signal-orb {{
            width: 188px;
            height: 188px;
            position: relative;
            display: block;
          }}
          .signal-orb-glow {{
            position: absolute;
            inset: 18px;
            border-radius: 50%;
            filter: blur(18px);
            opacity: 0.9;
          }}
          .signal-orb-ring {{
            position: absolute;
            border-radius: 50%;
          }}
          .signal-orb-ring-outer {{
            inset: 10px;
            -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 12px), #000 calc(100% - 11px));
            mask: radial-gradient(farthest-side, transparent calc(100% - 12px), #000 calc(100% - 11px));
            box-shadow: 0 0 22px rgba(92, 225, 213, 0.16);
          }}
          .signal-orb-ring-inner {{
            inset: 28px;
            -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 10px), #000 calc(100% - 9px));
            mask: radial-gradient(farthest-side, transparent calc(100% - 10px), #000 calc(100% - 9px));
          }}
          .signal-orb-core {{
            position: absolute;
            inset: 48px;
            border-radius: 50%;
            background:
              radial-gradient(circle at 50% 38%, rgba(92,225,213,0.18), transparent 32%),
              linear-gradient(180deg, rgba(8, 21, 34, 0.98) 0%, rgba(10, 26, 40, 0.98) 100%);
            border: 1px solid rgba(255,255,255,0.06);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
          }}
          .signal-orb-value {{
            color: white;
            font-size: 28px;
            font-weight: 800;
            line-height: 1;
          }}
          .signal-orb-label {{
            color: #7f9ab0;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-top: 10px;
          }}
          .signal-orb-regime {{
            position: absolute;
            left: 0;
            right: 0;
            bottom: 18px;
            text-align: center;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.08em;
          }}
          .signal-orb-volatility {{
            position: absolute;
            left: 0;
            right: 0;
            bottom: 4px;
            text-align: center;
            color: #7f9ab0;
            font-size: 9px;
          }}
          .signal-word {{
            margin-top: 10px;
            text-align: center;
            color: {tone_color};
            font-size: 20px;
            font-weight: 800;
            letter-spacing: 0.14em;
          }}
          .signal-bias {{
            text-align: center;
            color: #7f9ab0;
            font-size: 11px;
            margin-top: 5px;
            line-height: 1.6;
          }}
          .section {{
            margin-top: 14px;
            background: rgba(12,27,42,0.78);
            border: 1px solid rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 12px 14px;
          }}
          .section-label {{
            color: #5f7f93;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
          }}
          .confidence-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            margin-top: 8px;
          }}
          .confidence-value {{
            color: white;
            font-size: 13px;
            font-weight: 800;
          }}
          .meter {{
            height: 8px;
            border-radius: 999px;
            background: rgba(255,255,255,0.06);
            overflow: hidden;
            margin-top: 10px;
          }}
          .meter-fill {{
            width: {max(0, min(100, confidence))}%;
            height: 100%;
            border-radius: 999px;
            background: {tone_color};
          }}
          .analysis-copy {{
            color: #cfe3ec;
            font-size: 12px;
            line-height: 1.7;
            margin-top: 8px;
          }}
          .context-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
            margin-top: 14px;
          }}
          .context-card {{
            background: rgba(12,27,42,0.78);
            border: 1px solid rgba(255,255,255,0.05);
            border-radius: 14px;
            padding: 10px 12px;
          }}
          .context-value {{
            color: white;
            font-size: 14px;
            font-weight: 800;
            margin-top: 6px;
          }}
          .context-sub {{
            color: #7f9ab0;
            font-size: 11px;
            margin-top: 4px;
          }}
          .levels {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
            margin-top: 14px;
          }}
          .level-card {{
            background: rgba(12,27,42,0.78);
            border: 1px solid rgba(255,255,255,0.05);
            border-radius: 14px;
            padding: 10px 12px;
          }}
          .level-value {{
            font-size: 14px;
            font-weight: 800;
            margin-top: 6px;
          }}
          .support {{ color: #19dfd0; }}
          .entry {{ color: #ffffff; }}
          .resistance {{ color: #ff6b7d; }}
          .signal-foot {{
            color: #6e8797;
            font-size: 10px;
            margin-top: 12px;
            text-align: center;
          }}
          @media (max-width: 700px) {{
            .signal-card {{
              padding: 14px 14px 12px;
              border-radius: 18px;
              min-height: 0;
            }}
            .signal-top {{
              flex-direction: column;
              align-items: flex-start;
            }}
            .signal-gauge-wrap,
            .signal-orb {{
              width: 168px;
              height: 168px;
            }}
            .signal-orb-core {{
              inset: 42px;
            }}
            .signal-orb-value {{
              font-size: 24px;
            }}
            .signal-word {{
              font-size: 18px;
            }}
            .context-grid {{
              grid-template-columns: 1fr;
            }}
            .levels {{
              grid-template-columns: 1fr;
            }}
          }}
        </style>
        </head>
        <body>
          <div class="signal-card">
            <div class="signal-top">
              <div>
                <div class="signal-title">AI Signal</div>
                <div class="signal-sub">{escape(symbol)} | {escape(tf_label)} live analysis</div>
              </div>
              <div class="signal-pill">{escape(usage_label)}</div>
            </div>

            <div class="signal-gauge-wrap">
              {gauge_svg}
            </div>

            <div class="signal-word">{display_label}</div>
            <div class="signal-bias">{escape(signal_bias or "Model posture for the active market")}</div>

            <div class="section">
              <div class="section-label">Confidence</div>
              <div class="confidence-row">
                <div class="signal-sub">Execution threshold</div>
                <div class="confidence-value">{confidence}%</div>
              </div>
              <div class="meter"><div class="meter-fill"></div></div>
            </div>

            <div class="context-grid">
              {context_html}
            </div>

            <div class="section">
              <div class="section-label">Analysis</div>
              <div class="analysis-copy">{escape(reason)}</div>
            </div>

            <div class="levels">
              <div class="level-card">
                <div class="section-label">Support</div>
                <div class="level-value support">{_fmt_price(support)}</div>
              </div>
              <div class="level-card">
                <div class="section-label">Entry</div>
                <div class="level-value entry">{_fmt_price(entry_value)}</div>
              </div>
              <div class="level-card">
                <div class="section-label">Resistance</div>
                <div class="level-value resistance">{_fmt_price(resistance)}</div>
              </div>
            </div>

            <div class="signal-foot">AI powered by Finwise engine</div>
          </div>
        </body>
        </html>
        """
    ).strip()
    _render_component_html(signal_html, height=486)

    has_signal_history = df is not None and not df.empty and len(df) >= AI_SIGNAL_MIN_READY_CANDLES
    if cta_mode == "open_trade_desk":
        if st.button(
            "Open Trade Desk",
            use_container_width=True,
            key=f"signal_open_desk_{symbol}_{tf_label}",
            type="primary",
        ):
            _open_trading_desk_signal_workspace(symbol, tf_label, mobile_layout=mobile_target)
        st.caption("Trade Desk now owns AI signal requests, broker routing, and execution handoff for this market.")
        if not has_signal_history:
            missing_bars = max(0, AI_SIGNAL_MIN_READY_CANDLES - len(df))
            st.caption(f"AI signal analysis unlocks after {missing_bars} more candles sync for this timeframe.")
        if not premium and used >= limit:
            st.warning("Daily signal limit reached. Open the desk to review execution context or upgrade for more signals.")
        return

    button_label = "Refresh AI Signal" if has_matching_signal else "Get AI Signal"
    if st.button(
        button_label,
        disabled=((not premium and used >= limit) or not has_signal_history),
        use_container_width=True,
        key=f"signal_btn_{symbol}_{tf_label}",
        type="primary",
    ):
        _trigger_ai_signal(username, symbol, tf_label, df)

    if not has_signal_history:
        missing_bars = max(0, AI_SIGNAL_MIN_READY_CANDLES - len(df))
        st.caption(f"AI signal analysis unlocks after {missing_bars} more candles sync for this timeframe.")
    if not premium and used >= limit:
        st.warning("Daily signal limit reached. Upgrade for more signals.")
    # The instant-entry card belongs on the focused Signal Result page.
    # Keeping it out of the sidebar prevents the rail from growing after
    # a signal is generated.


def _render_market_analysis_upgrade_banner(
    username: str,
    *,
    show_action: bool = True,
    mobile_layout: bool = False,
):
    premium = is_premium(username)
    used = get_used(username)
    limit = get_limit(username)
    feed_live = bool(_engine_ready.is_set() and _engine_status.get("ok", True))
    try:
        pair_count = len(_get_pair_universe())
    except Exception:
        pair_count = len(DEFAULT_TRACKED_SYMBOLS)
    title = "Premium Workspace Active" if premium else "Unlock Full Potential"
    copy = (
        "Your account already has Premium access. Jump into Trading Desk to use broker execution and manual order tools."
        if premium else
        "Upgrade to Premium for advanced AI signals, broker execution, backtesting, and expanded signal limits."
    )
    action_label = "Open Trading Desk" if premium else "Upgrade Now"
    target_page = "Trading Desk" if premium else "Upgrade"
    status_cards = [
        ("Plan", "Premium" if premium else "Free", "Workspace tier"),
        ("Feed", "Live" if feed_live else "Warming", "Market engine"),
        ("Signals", f"{used} today" if premium else f"{used}/{limit}", "Daily usage"),
        ("Pairs", str(pair_count), "Search universe"),
    ]
    stats_html = "".join(
        dedent(
            f"""
            <div class="market-upgrade-stat">
              <div class="market-card-kicker">{escape(label)}</div>
              <div class="market-upgrade-stat-value">{escape(value)}</div>
              <div class="market-upgrade-stat-sub">{escape(subtitle)}</div>
            </div>
            """
        ).strip()
        for label, value, subtitle in status_cards
    )

    if mobile_layout:
        upgrade_layout_css = """
      .market-upgrade-banner {
        display: grid;
        grid-template-columns: 1fr;
        gap: 14px;
        align-items: center;
        padding: 16px;
        position: relative;
        overflow: hidden;
        background:
          radial-gradient(circle at top right, rgba(25, 223, 208, 0.08), transparent 28%),
          linear-gradient(180deg, rgba(10, 23, 36, 0.98) 0%, rgba(8, 19, 31, 0.98) 100%);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 18px;
        box-shadow: 0 18px 36px rgba(0,0,0,0.2);
      }
      .market-upgrade-title {
        color: white;
        font-size: 20px;
        font-weight: 800;
        margin-top: 8px;
      }
      .market-upgrade-copy {
        color: #8aa5b7;
        font-size: 12px;
        line-height: 1.65;
        margin-top: 8px;
      }
      .market-upgrade-stats {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }
      .market-upgrade-stat {
        min-height: 78px;
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,0.05);
        background: rgba(10, 24, 38, 0.92);
        padding: 12px 13px;
      }
      .market-upgrade-stat-value {
        color: white;
        font-size: 16px;
        font-weight: 800;
        margin-top: 7px;
      }
      .market-upgrade-stat-sub {
        color: #7f9ab0;
        font-size: 10px;
        margin-top: 4px;
      }
      @media (max-width: 360px) {
        .market-upgrade-stats {
          grid-template-columns: 1fr;
        }
      }
        """
        component_height = 304
    else:
        upgrade_layout_css = """
      .market-upgrade-banner {
        display: grid;
        grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr);
        gap: 16px;
        align-items: center;
        padding: 20px 22px;
        position: relative;
        overflow: hidden;
        background:
          radial-gradient(circle at top right, rgba(25, 223, 208, 0.08), transparent 28%),
          linear-gradient(180deg, rgba(10, 23, 36, 0.98) 0%, rgba(8, 19, 31, 0.98) 100%);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 22px;
        box-shadow: 0 22px 48px rgba(0,0,0,0.22);
      }
      .market-upgrade-title {
        color: white;
        font-size: 22px;
        font-weight: 800;
        margin-top: 8px;
      }
      .market-upgrade-copy {
        color: #8aa5b7;
        font-size: 13px;
        line-height: 1.7;
        margin-top: 8px;
      }
      .market-upgrade-stats {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }
      .market-upgrade-stat {
        min-height: 86px;
        border-radius: 16px;
        border: 1px solid rgba(255,255,255,0.05);
        background: rgba(10, 24, 38, 0.92);
        padding: 12px 14px;
      }
      .market-upgrade-stat-value {
        color: white;
        font-size: 18px;
        font-weight: 800;
        margin-top: 7px;
      }
      .market-upgrade-stat-sub {
        color: #7f9ab0;
        font-size: 11px;
        margin-top: 4px;
      }
      @media (max-width: 700px) {
        .market-upgrade-banner {
          grid-template-columns: 1fr;
          padding: 16px;
          border-radius: 18px;
        }
        .market-upgrade-title {
          font-size: 20px;
        }
      }
      @media (max-width: 460px) {
        .market-upgrade-stats {
          grid-template-columns: 1fr;
        }
      }
        """
        component_height = 208

    upgrade_html = f"""
    <html>
    <head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      * {{ box-sizing: border-box; }}
      html, body {{
        margin: 0;
        padding: 0;
        background: transparent;
        font-family: "Segoe UI", Arial, sans-serif;
        color: #e8f4f8;
      }}
      .market-card-kicker {{
        color: #5f7f93;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}
      {upgrade_layout_css}
    </style>
    </head>
    <body>
      <div class="market-upgrade-banner">
        <div>
          <div class="market-card-kicker">Workspace Boost</div>
          <div class="market-upgrade-title">{title}</div>
          <div class="market-upgrade-copy">{copy}</div>
        </div>
        <div class="market-upgrade-stats">{stats_html}</div>
      </div>
    </body>
    </html>
    """
    _render_component_html(
        upgrade_html,
        height=component_height,
    )

    if show_action:
        if mobile_layout:
            if st.button(action_label, key="market_analysis_upgrade_cta", use_container_width=True, type="primary"):
                st.session_state.nav_choice = target_page
                st.rerun()
        else:
            _, action_col = st.columns([1.6, 0.45])
            with action_col:
                if st.button(action_label, key="market_analysis_upgrade_cta", use_container_width=True, type="primary"):
                    st.session_state.nav_choice = target_page
                    st.rerun()


def _render_market_analysis_ticker_strip(active_symbol: str, *, mobile_layout: bool = False):
    ticker_symbols = []
    for symbol in [active_symbol] + list(DEFAULT_TRACKED_SYMBOLS):
        symbol = str(symbol or "").upper()
        if symbol and symbol not in ticker_symbols:
            ticker_symbols.append(symbol)

    ticker_html = []
    for symbol in ticker_symbols[:6]:
        try:
            snapshot = engine.get_market_snapshot(symbol) or {}
        except Exception:
            snapshot = {}

        change_pct = _coalesce_market_number(snapshot.get("price_24h_pcnt"))
        if change_pct is not None:
            change_pct *= 100
        change_color = "#19dfd0" if (change_pct or 0) >= 0 else "#ff6b7d"
        ticker_html.append(
            dedent(
                f"""
                <div class="market-ticker-item">
                    <div class="market-ticker-symbol">{escape(symbol)}</div>
                    <div class="market-ticker-price">{_fmt_price(snapshot.get("last_price"))}</div>
                    <div class="market-ticker-change" style="color:{change_color};">{_fmt_pct(change_pct)}</div>
                </div>
                """
            ).strip()
        )

    if mobile_layout:
        ticker_layout_css = """
      .market-ticker-strip {
        display: flex;
        gap: 8px;
        overflow-x: auto;
        overflow-y: hidden;
        padding-bottom: 2px;
        scrollbar-width: none;
        scroll-snap-type: x proximity;
      }
      .market-ticker-strip::-webkit-scrollbar {
        display: none;
      }
      .market-ticker-item {
        flex: 0 0 min(6.9rem, 42vw);
        scroll-snap-align: start;
        background: rgba(10, 24, 38, 0.92);
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 12px;
        padding: 10px 10px;
      }
        """
    else:
        ticker_layout_css = """
      .market-ticker-strip {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 10px;
      }
      .market-ticker-item {
        background: rgba(10, 24, 38, 0.92);
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 14px;
        padding: 10px 12px;
      }
      @media (max-width: 700px) {
        .market-ticker-strip {
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 8px;
        }
        .market-ticker-item {
          border-radius: 12px;
          padding: 10px 10px;
        }
      }
      @media (max-width: 420px) {
        .market-ticker-strip {
          grid-template-columns: 1fr;
        }
      }
        """

    ticker_strip_html = f"""
    <html>
    <head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      * {{ box-sizing: border-box; }}
      html, body {{
        margin: 0;
        padding: 0;
        background: transparent;
        font-family: "Segoe UI", Arial, sans-serif;
        color: #e8f4f8;
      }}
      {ticker_layout_css}
      .market-ticker-symbol {{
        color: white;
        font-size: 12px;
        font-weight: 800;
      }}
      .market-ticker-price {{
        color: #d9eef4;
        font-size: 12px;
        font-weight: 700;
        margin-top: 6px;
      }}
      .market-ticker-change {{
        font-size: 11px;
        font-weight: 800;
        margin-top: 4px;
      }}
    </style>
    </head>
    <body>
      <div class="market-ticker-strip">{"".join(ticker_html)}</div>
    </body>
    </html>
    """
    _render_component_html(
        ticker_strip_html,
        height=84,
    )


def _render_binance_style_chart(df: pd.DataFrame, symbol: str, tf_label: str, height: int = 520):
    """
    Binance-style no-flicker chart.

    Strategy:
    - Render ONCE via components.html() — Streamlit never touches it again.
    - Seed the chart with initial candle data (passed as inline JSON).
    - JavaScript polls /api/market/terminal every 2 s and calls
      series.update() in-place — zero flicker, zero re-mount.
    - Lightweight Charts v4 is loaded from CDN, so no extra pip package.
    """
    if df is None or df.empty or len(df) < CHART_MIN_READY_CANDLES:
        st.info("⏳ Warming up chart data...")
        return

    # --- Build initial seed candles (last 300 candles) ---
    indicator_pipeline = IndicatorPipeline(st.session_state.chart_indicators)
    chart_df = indicator_pipeline.calculate_indicators(df.tail(300).copy())

    seed_candles = []
    seed_volumes = []
    ema20_seed = []
    ema50_seed = []

    for _, row in chart_df.iterrows():
        ts = row.get("timestamp")
        t = int(ts.timestamp()) if hasattr(ts, "timestamp") else int(pd.Timestamp(ts).timestamp())
        o = round(float(row["open"]),  8)
        h = round(float(row["high"]),  8)
        lo = round(float(row["low"]),  8)
        c = round(float(row["close"]), 8)
        v = round(float(row["volume"]), 4)
        is_up = c >= o
        seed_candles.append({"time": t, "open": o, "high": h, "low": lo, "close": c})
        seed_volumes.append({"time": t, "value": v, "color": "rgba(38,166,154,0.45)" if is_up else "rgba(239,83,80,0.45)"})
        e20 = row.get("ema_20")
        e50 = row.get("ema_50")
        if pd.notna(e20):
            ema20_seed.append({"time": t, "value": round(float(e20), 8)})
        if pd.notna(e50):
            ema50_seed.append({"time": t, "value": round(float(e50), 8)})

    last_close = float(chart_df["close"].iloc[-1])
    first_close = float(chart_df["close"].iloc[0])
    session_pct = ((last_close - first_close) / first_close * 100) if first_close else 0.0
    pct_color = "#26a69a" if session_pct >= 0 else "#ef5350"

    seed_json    = json.dumps(seed_candles)
    vol_json     = json.dumps(seed_volumes)
    ema20_json   = json.dumps(ema20_seed)
    ema50_json   = json.dumps(ema50_seed)
    symbol_safe  = escape(symbol)
    tf_safe      = escape(tf_label)
    interval_api = tf_label  # api_server uses the same tf_label strings

    chart_html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #08111d; font-family: 'Segoe UI', sans-serif; color: #e8f4f8; overflow: hidden; }}
  #header {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 14px 8px;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    background: linear-gradient(180deg,#0d1828,#0a1421);
  }}
  #header-left {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  #sym {{ font-size: 17px; font-weight: 700; color: white; }}
  .badge {{
    font-size: 10px; color: #7fa6bd; padding: 3px 8px;
    border-radius: 999px; background: #102235;
  }}
  #price-row {{
    display: flex; align-items: flex-end; gap: 10px;
    padding: 6px 14px 4px;
  }}
  #last-price {{ font-size: 26px; font-weight: 800; color: white; }}
  #session-pct {{ font-size: 13px; font-weight: 700; padding-bottom: 2px; color: {pct_color}; }}
  #stats-row {{
    display: grid; grid-template-columns: repeat(4,1fr); gap: 6px;
    padding: 0 14px 8px;
  }}
  .stat-box {{
    background: #0c1b2a; border-radius: 10px; padding: 7px 10px;
  }}
  .stat-lbl {{ color: #587b92; font-size: 9px; text-transform: uppercase; letter-spacing: 0.7px; }}
  .stat-val {{ color: white; font-size: 13px; font-weight: 700; margin-top: 2px; }}
  #live-dot {{
    width: 7px; height: 7px; border-radius: 50%;
    background: #00f5d4; box-shadow: 0 0 8px #00f5d4;
    display: inline-block; margin-right: 5px;
    animation: pulse 1.4s ease-in-out infinite;
  }}
  @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.2}} }}
  #chart-wrap {{ width: 100%; }}
  #vol-wrap  {{ width: 100%; }}
  #error-bar {{
    display: none; padding: 6px 14px;
    color: #ef5350; font-size: 11px;
    border-top: 1px solid rgba(239,83,80,0.2);
  }}
</style>
</head>
<body>
<div id="header">
  <div id="header-left">
    <div id="sym">{symbol_safe}</div>
    <span class="badge">{tf_safe} chart</span>
    <span class="badge">TradingView Lightweight</span>
  </div>
  <div style="display:flex;align-items:center;gap:6px;">
    <span id="live-dot"></span>
    <span style="font-size:11px;color:#9bc1d4;">Live</span>
  </div>
</div>

<div id="price-row">
  <div id="last-price">--</div>
  <div id="session-pct">{session_pct:+.2f}% session</div>
</div>

<div id="stats-row">
  <div class="stat-box"><div class="stat-lbl">High</div><div class="stat-val" id="stat-high">--</div></div>
  <div class="stat-box"><div class="stat-lbl">Low</div><div class="stat-val" id="stat-low">--</div></div>
  <div class="stat-box"><div class="stat-lbl">Volume</div><div class="stat-val" id="stat-vol">--</div></div>
  <div class="stat-box"><div class="stat-lbl">24h Change</div><div class="stat-val" id="stat-chg">--</div></div>
</div>

<div id="chart-wrap"></div>
<div id="vol-wrap"></div>
<div id="error-bar">⚠ Live feed paused — retrying...</div>

<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script>
(function() {{
  // ── seed data from Python ──────────────────────────
  const SEED_CANDLES = {seed_json};
  const SEED_VOLUMES = {vol_json};
  const SEED_EMA20   = {ema20_json};
  const SEED_EMA50   = {ema50_json};
  const SYMBOL       = "{symbol_safe}";
  const TF           = "{tf_safe}";
  const API_BASE     = (() => {{
    const configuredBase = "{escape(_configured_chart_public_base())}";
    if (configuredBase) return configuredBase;
    const hostname = window.location.hostname || "127.0.0.1";
    const normalizedHost = hostname.toLowerCase();
    const isLocalHost = ["127.0.0.1", "localhost", "::1"].includes(normalizedHost);
    if (!isLocalHost) return "";
    const protocol = window.location.protocol === "https:" ? "https:" : "http:";
    return `${{protocol}}//${{hostname}}:{API_SERVER_PORT}`;
  }})();
  const POLL_MS      = 2000;  // update every 2 s — same as Binance default

  // ── helpers ───────────────────────────────────────
  const fmtP = (v, d=2) => v == null ? "--" : Number(v).toLocaleString(undefined,{{minimumFractionDigits:d,maximumFractionDigits:d}});
  const fmtK = v => {{
    if (v == null) return "--";
    const n = Number(v);
    if (n >= 1e9) return (n/1e9).toFixed(2)+"B";
    if (n >= 1e6) return (n/1e6).toFixed(2)+"M";
    if (n >= 1e3) return (n/1e3).toFixed(2)+"K";
    return n.toFixed(2);
  }};
  const viewportWidth = () => Math.max(
    document.documentElement ? document.documentElement.clientWidth || 0 : 0,
    document.body ? document.body.clientWidth || 0 : 0,
    window.innerWidth || 0
  );

  // ── chart sizes (computed from outer iframe width) ─
  const totalH   = window.innerHeight || {height + 170};
  const priceH   = Math.round(totalH * 0.72);
  const volH     = Math.round(totalH * 0.20);
  const chartWidth = viewportWidth();

  // ── Lightweight Charts: price chart ───────────────
  const priceChart = LightweightCharts.createChart(document.getElementById("chart-wrap"), {{
    width:  chartWidth,
    height: priceH,
    layout: {{ background: {{ type:"solid", color:"#08111d" }}, textColor:"#d1d4dc", fontSize:11 }},
    grid:   {{ vertLines:{{color:"rgba(42,46,57,0.18)"}}, horzLines:{{color:"rgba(42,46,57,0.6)"}} }},
    crosshair: {{ mode: 0 }},
    rightPriceScale: {{ borderColor:"rgba(197,203,206,0.18)" }},
    timeScale: {{
      borderColor:"rgba(197,203,206,0.18)",
      timeVisible: true,
      secondsVisible: false,
    }},
    watermark: {{
      visible: true, fontSize: 32, horzAlign: "center", vertAlign: "center",
      color: "rgba(127,166,189,0.07)", text: SYMBOL
    }},
  }});

  const candleSeries = priceChart.addCandlestickSeries({{
    upColor:"#26a69a", downColor:"#ef5350",
    borderVisible: false,
    wickUpColor:"#26a69a", wickDownColor:"#ef5350",
    priceLineVisible: true, lastValueVisible: true,
  }});

  const ema20Series = priceChart.addLineSeries({{
    color:"#ffd166", lineWidth:1.5,
    priceLineVisible:false, lastValueVisible:false, title:"EMA 20",
  }});

  const ema50Series = priceChart.addLineSeries({{
    color:"#74b9ff", lineWidth:1.5,
    priceLineVisible:false, lastValueVisible:false, title:"EMA 50",
  }});

  // ── Lightweight Charts: volume chart ──────────────
  const volChart = LightweightCharts.createChart(document.getElementById("vol-wrap"), {{
    width:  chartWidth,
    height: volH,
    layout: {{ background:{{type:"solid",color:"#08111d"}}, textColor:"#6f8aa0", fontSize:10 }},
    grid:   {{ vertLines:{{color:"rgba(42,46,57,0)"}}, horzLines:{{color:"rgba(42,46,57,0.35)"}} }},
    crosshair: {{ mode:0 }},
    rightPriceScale: {{ borderColor:"rgba(197,203,206,0.18)", scaleMargins:{{top:0.1,bottom:0}} }},
    timeScale: {{
      borderColor:"rgba(197,203,206,0.18)",
      timeVisible:true, secondsVisible:false,
    }},
    handleScroll: false,
    handleScale:  false,
  }});

  const volSeries = volChart.addHistogramSeries({{
    priceFormat: {{type:"volume"}},
    priceScaleId: "",
  }});

  // ── seed initial data ─────────────────────────────
  candleSeries.setData(SEED_CANDLES);
  volSeries.setData(SEED_VOLUMES);
  if (SEED_EMA20.length) ema20Series.setData(SEED_EMA20);
  if (SEED_EMA50.length) ema50Series.setData(SEED_EMA50);

  // show latest price from seed
  if (SEED_CANDLES.length) {{
    const last = SEED_CANDLES[SEED_CANDLES.length-1];
    document.getElementById("last-price").textContent = fmtP(last.close);
  }}

  // fit all candles on first render
  priceChart.timeScale().fitContent();
  volChart.timeScale().fitContent();

  // ── sync timeScales on scroll ─────────────────────
  let syncing = false;
  priceChart.timeScale().subscribeVisibleLogicalRangeChange(range => {{
    if (syncing || !range) return;
    syncing = true;
    volChart.timeScale().setVisibleLogicalRange(range);
    syncing = false;
  }});
  volChart.timeScale().subscribeVisibleLogicalRangeChange(range => {{
    if (syncing || !range) return;
    syncing = true;
    priceChart.timeScale().setVisibleLogicalRange(range);
    syncing = false;
  }});

  // ── crosshair hover → update header price ─────────
  priceChart.subscribeCrosshairMove(param => {{
    if (!param || !param.seriesData) return;
    const c = param.seriesData.get(candleSeries);
    if (c) document.getElementById("last-price").textContent = fmtP(c.close);
  }});

  // ── keep track of last candle time ───────────────
  let lastCandleTime = SEED_CANDLES.length ? SEED_CANDLES[SEED_CANDLES.length-1].time : 0;
  let firstCandleClose = SEED_CANDLES.length ? SEED_CANDLES[0].close : null;
  let failCount = 0;
  const errBar = document.getElementById("error-bar");

  // ── polling function ──────────────────────────────
  function pollMarket() {{
    if (!API_BASE) {{
      errBar.textContent = "Live feed needs FINWISE_PUBLIC_CHART_API_BASE for phone or tunnel access.";
      errBar.style.display = "block";
      return;
    }}
    fetch(API_BASE + "/api/market/terminal?symbol=" + SYMBOL + "&interval=" + TF)
      .then(r => {{ if (!r.ok) throw new Error(r.status); return r.json(); }})
      .then(data => {{
        failCount = 0;
        errBar.style.display = "none";

        const candles = data.candles || [];
        if (!candles.length) return;

        // update only the latest candle (or add a new one)
        const latest = candles[candles.length - 1];
        const isNew  = latest.time > lastCandleTime;

        const candleUpdate = {{
          time:  latest.time,
          open:  latest.open,
          high:  latest.high,
          low:   latest.low,
          close: latest.close,
        }};
        const isUp = latest.close >= latest.open;
        const volUpdate = {{
          time:  latest.time,
          value: latest.volume,
          color: isUp ? "rgba(38,166,154,0.45)" : "rgba(239,83,80,0.45)",
        }};

        // series.update() NEVER re-creates the chart — no flicker
        candleSeries.update(candleUpdate);
        volSeries.update(volUpdate);

        if (isNew) lastCandleTime = latest.time;

        // ── update EMA in-place ───────────────────
        // recalc last EMA point from the close prices we already have
        // (lightweight approach: just update the last value)
        const market = data.market || {{}};
        const lp = market.last_price || latest.close;

        // update header stats
        document.getElementById("last-price").textContent = fmtP(lp);
        const chg24 = market.price_24h_pcnt != null ? (market.price_24h_pcnt * 100) : null;
        const chgEl = document.getElementById("stat-chg");
        if (chg24 != null) {{
          chgEl.textContent  = (chg24 >= 0 ? "+" : "") + chg24.toFixed(2) + "%";
          chgEl.style.color  = chg24 >= 0 ? "#26a69a" : "#ef5350";
        }}
        document.getElementById("stat-high").textContent = fmtP(market.high_24h || latest.high);
        document.getElementById("stat-low").textContent  = fmtP(market.low_24h  || latest.low);
        document.getElementById("stat-vol").textContent  = fmtK(market.volume_24h || latest.volume);

        // session % (vs first candle in current dataset)
        if (firstCandleClose && lp) {{
          const sp = ((lp - firstCandleClose) / firstCandleClose) * 100;
          const el = document.getElementById("session-pct");
          el.textContent = (sp >= 0 ? "+" : "") + sp.toFixed(2) + "% session";
          el.style.color = sp >= 0 ? "#26a69a" : "#ef5350";
        }}
      }})
      .catch(() => {{
        failCount++;
        if (failCount >= 3) errBar.style.display = "block";
      }});
  }}

  // ── start polling ─────────────────────────────────
  setInterval(pollMarket, POLL_MS);
  // first poll immediately after 500ms (let chart settle first)
  setTimeout(pollMarket, 500);

  // ── responsive resize ─────────────────────────────
  window.addEventListener("resize", () => {{
    const nextWidth = viewportWidth();
    priceChart.resize(nextWidth, priceH);
    volChart.resize(nextWidth, volH);
  }});
}})();
</script>
</body>
</html>
"""
    total_height = height + 170  # header + stats row + vol chart
    _render_scripted_html(chart_html, height=total_height)

 
def _render_exchange_terminal_chart(
    df: pd.DataFrame,
    symbol: str,
    tf_label: str,
    height: int = 520,
    compact_layout: bool = False,
):
    if df is None or df.empty or len(df) < CHART_MIN_READY_CANDLES:
        st.info("Warming up chart data...")
        return

    chart_seed_limit = 540 if compact_layout else CHART_SEED_CANDLES
    chart_df = df.tail(chart_seed_limit).copy()
    chart_df["timestamp"] = pd.to_datetime(chart_df["timestamp"], errors="coerce")
    numeric_cols = ["open", "high", "low", "close", "volume"]
    chart_df[numeric_cols] = chart_df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    chart_df = chart_df.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
    if chart_df.empty or len(chart_df) < 30:
        st.info("Warming up chart data...")
        return

    indicator_config = st.session_state.chart_indicators
    moving_average_config = indicator_config.get("moving_averages", {})
    bollinger_config = indicator_config.get("bollinger_bands", {})
    rsi_config = indicator_config.get("rsi", {})
    macd_config = indicator_config.get("macd", {})

    ema_periods = moving_average_config.get("ema", []) or []
    show_ma = bool(moving_average_config.get("enabled"))
    show_ema20 = show_ma and 20 in ema_periods
    show_ema50 = show_ma and 50 in ema_periods
    show_bb = bool(bollinger_config.get("enabled"))
    show_rsi = bool(rsi_config.get("enabled"))
    show_macd = bool(macd_config.get("enabled"))

    seed_candles = []
    for _, row in chart_df.iterrows():
        ts = row.get("timestamp")
        time_value = int(ts.timestamp()) if hasattr(ts, "timestamp") else int(pd.Timestamp(ts).timestamp())
        seed_candles.append(
            {
                "time": time_value,
                "open": round(float(row["open"]), 8),
                "high": round(float(row["high"]), 8),
                "low": round(float(row["low"]), 8),
                "close": round(float(row["close"]), 8),
                "volume": round(float(row["volume"]), 8),
            }
        )

    last_close = float(chart_df["close"].iloc[-1])
    first_close = float(chart_df["close"].iloc[0])
    session_pct = ((last_close - first_close) / first_close * 100) if first_close else 0.0
    pct_color = "#26a69a" if session_pct >= 0 else "#ef5350"

    indicator_flags = json.dumps(
        {
            "show_ema20": show_ema20,
            "show_ema50": show_ema50,
            "show_bb": show_bb,
            "show_rsi": show_rsi,
            "show_macd": show_macd,
            "rsi_period": int(rsi_config.get("period", 14)),
            "bb_period": int(bollinger_config.get("period", 20)),
            "bb_std_dev": float(bollinger_config.get("std_dev", 2)),
            "macd_fast": int(macd_config.get("fast", 12)),
            "macd_slow": int(macd_config.get("slow", 26)),
            "macd_signal": int(macd_config.get("signal", 9)),
        }
    )

    timeframe_chip_html = "".join(
        f'<span class="tool-chip {"active" if timeframe == tf_label else ""}">{escape(timeframe)}</span>'
        for timeframe in DEFAULT_TIMEFRAMES
    )

    active_indicator_labels = []
    if show_ma:
        active_indicator_labels.append("EMA 20/50")
    if show_bb:
        active_indicator_labels.append("Bollinger")
    if show_rsi:
        active_indicator_labels.append("RSI 14")
    if show_macd:
        active_indicator_labels.append("MACD")
    if not active_indicator_labels:
        active_indicator_labels.append("Price Only")

    indicator_chip_html = "".join(
        f'<span class="tool-chip active">{escape(label)}</span>' for label in active_indicator_labels
    )

    extra_height = 0
    if show_rsi:
        extra_height += 128
    if show_macd:
        extra_height += 148
    total_height = height + (112 if compact_layout else 210) + extra_height
    chart_radius = 18 if compact_layout else 22
    header_padding = "10px 12px 8px" if compact_layout else "12px 14px 10px"
    price_row_padding = "8px 12px 2px" if compact_layout else "10px 14px 2px"
    price_font_size = 22 if compact_layout else 30
    badge_font_size = 9 if compact_layout else 10
    badge_padding = "4px 7px" if compact_layout else "4px 9px"
    chip_font_size = 9 if compact_layout else 10
    chip_padding = "5px 8px" if compact_layout else "6px 10px"
    quote_gap = 9 if compact_layout else 12
    body_radius = "0px" if compact_layout else "22px"
    body_shadow = "none" if compact_layout else "0 22px 48px rgba(0,0,0,0.22)"
    compact_layout_css = dedent(
        f"""
        #header,
        #price-row,
        #toolbar-row,
        #hover-strip,
        #stats-row {{
          display: none;
        }}
        body {{
          background:
            radial-gradient(circle at top right, rgba(20, 224, 206, 0.08), transparent 24%),
            linear-gradient(180deg, rgba(7, 19, 31, 0.99) 0%, rgba(4, 13, 24, 0.99) 100%);
          border-left: 1px solid rgba(92, 118, 151, 0.16);
          border-right: 1px solid rgba(92, 118, 151, 0.16);
          border-top: none;
          border-bottom: none;
          box-shadow: none;
        }}
        #terminal-root {{
          background:
            radial-gradient(circle at top right, rgba(20, 224, 206, 0.05), transparent 26%),
            linear-gradient(180deg, rgba(7, 19, 31, 0.98) 0%, rgba(4, 13, 24, 0.98) 100%);
        }}
        #chart-wrap {{
          margin-top: 0;
          border-top: 1px solid rgba(255,255,255,0.04);
          background: linear-gradient(180deg, rgba(7,19,31,0.95) 0%, rgba(6,17,29,0.98) 100%);
        }}
        #vol-wrap,
        #rsi-wrap,
        #macd-wrap {{
          border-top: 1px solid rgba(255,255,255,0.04);
          background: linear-gradient(180deg, rgba(6,17,29,0.98) 0%, rgba(4,13,24,0.99) 100%);
        }}
        #error-bar {{
          padding-left: 12px;
          padding-right: 12px;
        }}
        """
    ).strip()

    chart_html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    background: #08111d;
    font-family: "Segoe UI", Arial, sans-serif;
    color: #e8f4f8;
    overflow: hidden;
    width: 100%;
    max-width: 100%;
  }}
  body {{
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: {body_radius};
    background:
      radial-gradient(circle at top left, rgba(0,245,212,0.08), transparent 24%),
      linear-gradient(180deg, #0d1828 0%, #08111d 100%);
    width: 100%;
    max-width: 100%;
    box-shadow: {body_shadow};
  }}
  #header {{
    padding: {header_padding};
    border-bottom: 1px solid rgba(255,255,255,0.05);
    background: linear-gradient(180deg, rgba(13,24,40,0.96), rgba(10,20,33,0.92));
  }}
  #header-top {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }}
  #header-left {{
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }}
  #sym {{
    font-size: 18px;
    font-weight: 800;
    color: white;
    letter-spacing: 0.02em;
  }}
  .badge {{
    font-size: {badge_font_size}px;
    color: #7fa6bd;
    padding: {badge_padding};
    border-radius: 999px;
    background: #102235;
    border: 1px solid rgba(255,255,255,0.04);
  }}
  #live-pill {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: #9bc1d4;
    padding: 5px 10px;
    border-radius: 999px;
    background: rgba(0,245,212,0.08);
    border: 1px solid rgba(0,245,212,0.14);
  }}
  #live-dot {{
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #00f5d4;
    box-shadow: 0 0 10px #00f5d4;
    animation: pulse 1.4s ease-in-out infinite;
  }}
  @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.2}} }}
  #toolbar-row {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    margin-top: 10px;
    flex-wrap: wrap;
  }}
  .toolbar-strip {{
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }}
  .tool-chip {{
    font-size: {chip_font_size}px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #6f8aa0;
    padding: {chip_padding};
    border-radius: 999px;
    background: rgba(12,27,42,0.9);
    border: 1px solid rgba(255,255,255,0.05);
  }}
  .tool-chip.active {{
    color: #dffeff;
    background: rgba(0,245,212,0.08);
    border-color: rgba(0,245,212,0.22);
  }}
  #price-row {{
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 14px;
    padding: {price_row_padding};
  }}
  #quote-block {{
    display: flex;
    align-items: flex-end;
    gap: {quote_gap}px;
    flex-wrap: wrap;
  }}
  #last-price {{
    font-size: {price_font_size}px;
    font-weight: 800;
    color: white;
    line-height: 1;
  }}
  #session-pct {{
    font-size: 13px;
    font-weight: 700;
    padding-bottom: 4px;
    color: {pct_color};
  }}
  #hover-strip {{
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 8px;
    padding: 8px 14px 10px;
  }}
  .hover-box, .stat-box {{
    background: #0c1b2a;
    border-radius: 12px;
    padding: 8px 10px;
    border: 1px solid rgba(255,255,255,0.04);
  }}
  .hover-lbl, .stat-lbl {{
    color: #587b92;
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }}
  .hover-val {{
    color: #f7fbff;
    font-size: 12px;
    font-weight: 700;
    margin-top: 4px;
  }}
  #stats-row {{
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
    padding: 0 14px 10px;
  }}
  .stat-val {{
    color: white;
    font-size: 13px;
    font-weight: 700;
    margin-top: 3px;
  }}
  .chart-pane {{
    width: 100%;
    border-top: 1px solid rgba(255,255,255,0.03);
  }}
  #chart-wrap {{
    margin-top: 4px;
  }}
  #terminal-root {{
    width: 100%;
    max-width: 100%;
    min-width: 0;
    overflow: hidden;
  }}
  #header,
  #price-row,
  #hover-strip,
  #stats-row,
  #chart-wrap,
  #vol-wrap,
  #rsi-wrap,
  #macd-wrap {{
    width: 100%;
    max-width: 100%;
    min-width: 0;
  }}
  .chart-pane > div,
  .chart-pane canvas {{
    max-width: 100% !important;
  }}
  #error-bar {{
    display: none;
    padding: 8px 14px 10px;
    color: #ef5350;
    font-size: 11px;
    border-top: 1px solid rgba(239,83,80,0.2);
  }}
  @media (max-width: 980px) {{
    #header {{
      padding: 12px;
    }}
    #header-top,
    #price-row {{
      flex-direction: column;
      align-items: flex-start;
    }}
    #last-price {{
      font-size: 26px;
    }}
    #hover-strip,
    #stats-row {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
  }}
  @media (max-width: 620px) {{
    #hover-strip,
    #stats-row {{
      grid-template-columns: 1fr;
    }}
    .tool-chip,
    .badge {{
      font-size: 9px;
      padding: 5px 8px;
    }}
  }}
  {compact_layout_css if compact_layout else ''}
</style>
</head>
<body>
<div id="terminal-root">
<div id="header">
  <div id="header-top">
    <div id="header-left">
      <div id="sym">{escape(symbol)}</div>
      <span class="badge">{'Spot FX' if is_forex_symbol(symbol) else 'Perpetual'}</span>
      <span class="badge">{escape(tf_label)}</span>
      <span class="badge">Exchange View</span>
    </div>
    <div id="live-pill">
      <span id="live-dot"></span>
      <span>Live</span>
    </div>
  </div>
  <div id="toolbar-row">
    <div class="toolbar-strip">{timeframe_chip_html}</div>
    <div class="toolbar-strip">{indicator_chip_html}</div>
  </div>
</div>

<div id="price-row">
  <div id="quote-block">
    <div id="last-price">--</div>
    <div id="session-pct">{session_pct:+.2f}% session</div>
  </div>
  <span class="badge">Hover OHLC</span>
</div>

<div id="hover-strip">
  <div class="hover-box"><div class="hover-lbl">Open</div><div class="hover-val" id="hover-open">--</div></div>
  <div class="hover-box"><div class="hover-lbl">High</div><div class="hover-val" id="hover-high">--</div></div>
  <div class="hover-box"><div class="hover-lbl">Low</div><div class="hover-val" id="hover-low">--</div></div>
  <div class="hover-box"><div class="hover-lbl">Close</div><div class="hover-val" id="hover-close">--</div></div>
  <div class="hover-box"><div class="hover-lbl">Move</div><div class="hover-val" id="hover-move">--</div></div>
</div>

<div id="stats-row">
  <div class="stat-box"><div class="stat-lbl">High</div><div class="stat-val" id="stat-high">--</div></div>
  <div class="stat-box"><div class="stat-lbl">Low</div><div class="stat-val" id="stat-low">--</div></div>
  <div class="stat-box"><div class="stat-lbl">Volume</div><div class="stat-val" id="stat-vol">--</div></div>
  <div class="stat-box"><div class="stat-lbl">24h Change</div><div class="stat-val" id="stat-chg">--</div></div>
</div>

<div id="chart-wrap" class="chart-pane"></div>
<div id="vol-wrap" class="chart-pane"></div>
<div id="rsi-wrap" class="chart-pane" style="display:{'block' if show_rsi else 'none'};"></div>
<div id="macd-wrap" class="chart-pane" style="display:{'block' if show_macd else 'none'};"></div>
<div id="error-bar">Live feed paused. Retrying...</div>
</div>

<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script>
(function() {{
  const SEED_CANDLES = {json.dumps(seed_candles)};
  const FLAGS = {indicator_flags};
  const SYMBOL = "{escape(symbol)}";
  const TF = "{escape(tf_label)}";
  const API_BASE = (() => {{
    const configuredBase = "{escape(_configured_chart_public_base())}";
    if (configuredBase) return configuredBase;
    const hostname = window.location.hostname || "127.0.0.1";
    const normalizedHost = hostname.toLowerCase();
    const isLocalHost = ["127.0.0.1", "localhost", "::1"].includes(normalizedHost);
    if (!isLocalHost) return "";
    const protocol = window.location.protocol === "https:" ? "https:" : "http:";
    return `${{protocol}}//${{hostname}}:{API_SERVER_PORT}`;
  }})();
  const POLL_MS = 1500;
  const LIVE_WINDOW = {CHART_POLL_WINDOW_CANDLES};
  const BACKFILL_BATCH = {CHART_BACKFILL_BATCH_CANDLES};
  const BACKFILL_TRIGGER_BARS = {CHART_BACKFILL_TRIGGER_BARS};

  const priceDigits = (value) => {{
    if (value == null) return 2;
    const absValue = Math.abs(Number(value));
    if (absValue >= 1000) return 2;
    if (absValue >= 10) return 3;
    if (absValue >= 1) return 4;
    return 6;
  }};

  const fmtP = (value, digits) => {{
    if (value == null || Number.isNaN(Number(value))) return "--";
    const nextDigits = digits == null ? priceDigits(value) : digits;
    return Number(value).toLocaleString(undefined, {{
      minimumFractionDigits: nextDigits,
      maximumFractionDigits: nextDigits,
    }});
  }};

  const fmtK = (value) => {{
    if (value == null || Number.isNaN(Number(value))) return "--";
    const n = Number(value);
    if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(2) + "K";
    return n.toFixed(2);
  }};

  const fmtPct = (value) => {{
    if (value == null || Number.isNaN(Number(value))) return "--";
    const n = Number(value);
    return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
  }};

  const normalizeCandle = (candle) => ({{
    time: Number(candle.time),
    open: Number(candle.open),
    high: Number(candle.high),
    low: Number(candle.low),
    close: Number(candle.close),
    volume: Number(candle.volume || 0),
  }});

  const mergeCandles = (baseCandles, incomingCandles) => {{
    const merged = new Map();
    (baseCandles || []).forEach((candle) => {{
      const normalized = normalizeCandle(candle);
      if (!Number.isFinite(normalized.time)) return;
      merged.set(normalized.time, normalized);
    }});
    (incomingCandles || []).forEach((candle) => {{
      const normalized = normalizeCandle(candle);
      if (!Number.isFinite(normalized.time)) return;
      merged.set(normalized.time, normalized);
    }});
    return Array.from(merged.values()).sort((left, right) => left.time - right.time);
  }};

  const toCandleData = (candles) => candles.map((candle) => ({{
    time: candle.time,
    open: Number(candle.open),
    high: Number(candle.high),
    low: Number(candle.low),
    close: Number(candle.close),
  }}));

  const toVolumeData = (candles) => candles.map((candle) => ({{
    time: candle.time,
    value: Number(candle.volume),
    color: Number(candle.close) >= Number(candle.open) ? "rgba(38,166,154,0.45)" : "rgba(239,83,80,0.45)",
  }}));

  const emaArray = (values, period) => {{
    if (!values.length) return [];
    const multiplier = 2 / (period + 1);
    const output = [];
    let ema = Number(values[0] || 0);
    for (let index = 0; index < values.length; index += 1) {{
      const value = Number(values[index] || 0);
      ema = index === 0 ? value : ((value - ema) * multiplier) + ema;
      output.push(ema);
    }}
    return output;
  }};

  const calcEMA = (candles, period) => {{
    const closes = candles.map((candle) => Number(candle.close));
    const values = emaArray(closes, period);
    return candles
      .map((candle, index) => index >= period - 1 ? {{ time: candle.time, value: values[index] }} : null)
      .filter(Boolean);
  }};

  const calcBollinger = (candles, period, stdDev) => {{
    const upper = [];
    const middle = [];
    const lower = [];
    const closes = candles.map((candle) => Number(candle.close));
    for (let index = period - 1; index < closes.length; index += 1) {{
      const window = closes.slice(index - period + 1, index + 1);
      const mean = window.reduce((sum, value) => sum + value, 0) / period;
      const variance = window.reduce((sum, value) => sum + Math.pow(value - mean, 2), 0) / period;
      const sigma = Math.sqrt(variance);
      const time = candles[index].time;
      upper.push({{ time, value: mean + (stdDev * sigma) }});
      middle.push({{ time, value: mean }});
      lower.push({{ time, value: mean - (stdDev * sigma) }});
    }}
    return {{ upper, middle, lower }};
  }};

  const calcRSI = (candles, period) => {{
    if (candles.length <= period) return [];
    const closes = candles.map((candle) => Number(candle.close));
    let gainSum = 0;
    let lossSum = 0;
    for (let index = 1; index <= period; index += 1) {{
      const diff = closes[index] - closes[index - 1];
      gainSum += Math.max(diff, 0);
      lossSum += Math.max(-diff, 0);
    }}

    let avgGain = gainSum / period;
    let avgLoss = lossSum / period;
    const result = [];
    const firstRsi = avgLoss === 0 ? 100 : 100 - (100 / (1 + (avgGain / avgLoss)));
    result.push({{ time: candles[period].time, value: firstRsi }});

    for (let index = period + 1; index < closes.length; index += 1) {{
      const diff = closes[index] - closes[index - 1];
      const gain = Math.max(diff, 0);
      const loss = Math.max(-diff, 0);
      avgGain = ((avgGain * (period - 1)) + gain) / period;
      avgLoss = ((avgLoss * (period - 1)) + loss) / period;
      const rsi = avgLoss === 0 ? 100 : 100 - (100 / (1 + (avgGain / avgLoss)));
      result.push({{ time: candles[index].time, value: rsi }});
    }}

    return result;
  }};

  const calcMACD = (candles, fast, slow, signalPeriod) => {{
    const closes = candles.map((candle) => Number(candle.close));
    const fastValues = emaArray(closes, fast);
    const slowValues = emaArray(closes, slow);
    const macdValues = closes.map((_, index) => fastValues[index] - slowValues[index]);
    const signalValues = emaArray(macdValues, signalPeriod);
    const macd = [];
    const signal = [];
    const histogram = [];

    for (let index = 0; index < candles.length; index += 1) {{
      if (index >= slow - 1) {{
        macd.push({{ time: candles[index].time, value: macdValues[index] }});
      }}
      if (index >= slow + signalPeriod - 2) {{
        const histValue = macdValues[index] - signalValues[index];
        signal.push({{ time: candles[index].time, value: signalValues[index] }});
        histogram.push({{
          time: candles[index].time,
          value: histValue,
          color: histValue >= 0 ? "rgba(38,166,154,0.55)" : "rgba(239,83,80,0.55)",
        }});
      }}
    }}

    return {{ macd, signal, histogram }};
  }};

  const rootEl = document.getElementById("terminal-root");
  const containerWidth = () => {{
    const chartWrap = document.getElementById("chart-wrap");
    const rootWidth = rootEl ? rootEl.getBoundingClientRect().width : 0;
    const parentWidth = rootEl && rootEl.parentElement ? rootEl.parentElement.getBoundingClientRect().width : 0;
    const wrapWidth = chartWrap ? chartWrap.getBoundingClientRect().width : 0;
    const headerWidth = document.getElementById("header") ? document.getElementById("header").getBoundingClientRect().width : 0;
    const candidateWidth = rootWidth || parentWidth || wrapWidth || headerWidth || 0;
    return Math.max(Math.floor(candidateWidth), 320);
  }};
  const totalH = {total_height};
  const volumeHeight = 96;
  const rsiHeight = FLAGS.show_rsi ? 118 : 0;
  const macdHeight = FLAGS.show_macd ? 138 : 0;
  const compactLayout = () => containerWidth() < 760;
  const currentPriceHeight = () => compactLayout() ? 300 : Math.max(340, totalH - 222 - volumeHeight - rsiHeight - macdHeight);

  const baseChartOptions = {{
    width: containerWidth(),
    layout: {{
      background: {{ type: "solid", color: "#08111d" }},
      textColor: "#b9cad6",
      fontSize: 11,
    }},
    grid: {{
      vertLines: {{ color: "rgba(42,46,57,0.18)" }},
      horzLines: {{ color: "rgba(42,46,57,0.52)" }},
    }},
    crosshair: {{ mode: 0 }},
    rightPriceScale: {{ borderColor: "rgba(197,203,206,0.16)" }},
    timeScale: {{
      borderColor: "rgba(197,203,206,0.14)",
      timeVisible: true,
      secondsVisible: false,
      barSpacing: 8,
      rightOffset: 1,
      rightBarStaysOnScroll: true,
      shiftVisibleRangeOnNewBar: true,
    }},
  }};

  const priceChart = LightweightCharts.createChart(document.getElementById("chart-wrap"), {{
    ...baseChartOptions,
    height: currentPriceHeight(),
    rightPriceScale: {{
      borderColor: "rgba(197,203,206,0.16)",
      scaleMargins: {{ top: 0.08, bottom: 0.02 }},
    }},
    watermark: {{
      visible: true,
      fontSize: 34,
      horzAlign: "center",
      vertAlign: "center",
      color: "rgba(127,166,189,0.07)",
      text: SYMBOL,
    }},
  }});

  const candleSeries = priceChart.addCandlestickSeries({{
    upColor: "#26a69a",
    downColor: "#ef5350",
    borderVisible: false,
    wickUpColor: "#26a69a",
    wickDownColor: "#ef5350",
    priceLineVisible: true,
    lastValueVisible: true,
  }});

  const ema20Series = FLAGS.show_ema20 ? priceChart.addLineSeries({{
    color: "#ffd166",
    lineWidth: 1.6,
    priceLineVisible: false,
    lastValueVisible: false,
  }}) : null;

  const ema50Series = FLAGS.show_ema50 ? priceChart.addLineSeries({{
    color: "#74b9ff",
    lineWidth: 1.6,
    priceLineVisible: false,
    lastValueVisible: false,
  }}) : null;

  const bbUpperSeries = FLAGS.show_bb ? priceChart.addLineSeries({{
    color: "rgba(173,127,255,0.72)",
    lineWidth: 1.2,
    lineStyle: 2,
    priceLineVisible: false,
    lastValueVisible: false,
  }}) : null;

  const bbMiddleSeries = FLAGS.show_bb ? priceChart.addLineSeries({{
    color: "rgba(214,184,255,0.68)",
    lineWidth: 1.1,
    priceLineVisible: false,
    lastValueVisible: false,
  }}) : null;

  const bbLowerSeries = FLAGS.show_bb ? priceChart.addLineSeries({{
    color: "rgba(173,127,255,0.72)",
    lineWidth: 1.2,
    lineStyle: 2,
    priceLineVisible: false,
    lastValueVisible: false,
  }}) : null;

  const volChart = LightweightCharts.createChart(document.getElementById("vol-wrap"), {{
    ...baseChartOptions,
    height: volumeHeight,
    layout: {{
      background: {{ type: "solid", color: "#08111d" }},
      textColor: "#6f8aa0",
      fontSize: 10,
    }},
    grid: {{
      vertLines: {{ color: "rgba(42,46,57,0)" }},
      horzLines: {{ color: "rgba(42,46,57,0.28)" }},
    }},
    rightPriceScale: {{
      borderColor: "rgba(197,203,206,0.14)",
      scaleMargins: {{ top: 0.18, bottom: 0.0 }},
    }},
  }});

  const volSeries = volChart.addHistogramSeries({{
    priceFormat: {{ type: "volume" }},
    priceScaleId: "",
  }});

  let rsiChart = null;
  let rsiSeries = null;
  let macdChart = null;
  let macdSeries = null;
  let macdSignalSeries = null;
  let macdHistSeries = null;

  if (FLAGS.show_rsi) {{
    rsiChart = LightweightCharts.createChart(document.getElementById("rsi-wrap"), {{
      ...baseChartOptions,
      height: rsiHeight,
      rightPriceScale: {{
        borderColor: "rgba(197,203,206,0.14)",
        scaleMargins: {{ top: 0.12, bottom: 0.12 }},
      }},
    }});
    rsiSeries = rsiChart.addLineSeries({{
      color: "#a29bfe",
      lineWidth: 1.5,
      priceLineVisible: false,
      lastValueVisible: false,
    }});
    rsiSeries.createPriceLine({{
      price: 70,
      color: "rgba(239,83,80,0.45)",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: false,
      title: "70",
    }});
    rsiSeries.createPriceLine({{
      price: 30,
      color: "rgba(38,166,154,0.45)",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: false,
      title: "30",
    }});
  }}

  if (FLAGS.show_macd) {{
    macdChart = LightweightCharts.createChart(document.getElementById("macd-wrap"), {{
      ...baseChartOptions,
      height: macdHeight,
      rightPriceScale: {{
        borderColor: "rgba(197,203,206,0.14)",
        scaleMargins: {{ top: 0.14, bottom: 0.12 }},
      }},
    }});
    macdHistSeries = macdChart.addHistogramSeries({{
      priceScaleId: "",
      priceFormat: {{ type: "price", precision: 4, minMove: 0.0001 }},
    }});
    macdSeries = macdChart.addLineSeries({{
      color: "#00f5d4",
      lineWidth: 1.4,
      priceLineVisible: false,
      lastValueVisible: false,
    }});
    macdSignalSeries = macdChart.addLineSeries({{
      color: "#ff6b9d",
      lineWidth: 1.4,
      priceLineVisible: false,
      lastValueVisible: false,
    }});
  }}

  const allCharts = [priceChart, volChart].concat(rsiChart ? [rsiChart] : []).concat(macdChart ? [macdChart] : []);
  let candleCache = mergeCandles([], SEED_CANDLES);
  let failCount = 0;
  let firstCandleClose = candleCache.length ? Number(candleCache[0].close) : null;
  let lastCandleTime = candleCache.length ? Number(candleCache[candleCache.length - 1].time) : 0;
  let backfillPending = false;
  let reachedHistoryStart = false;
  const errBar = document.getElementById("error-bar");

  function setOHLC(candle) {{
    if (!candle) return;
    document.getElementById("hover-open").textContent = fmtP(candle.open);
    document.getElementById("hover-high").textContent = fmtP(candle.high);
    document.getElementById("hover-low").textContent = fmtP(candle.low);
    document.getElementById("hover-close").textContent = fmtP(candle.close);
    const movePct = candle.open ? ((Number(candle.close) - Number(candle.open)) / Number(candle.open)) * 100 : null;
    const moveEl = document.getElementById("hover-move");
    moveEl.textContent = fmtPct(movePct);
    moveEl.style.color = movePct == null ? "#f7fbff" : (movePct >= 0 ? "#26a69a" : "#ef5350");
  }}

  function setStats(market, latest) {{
    const livePrice = market.last_price != null ? market.last_price : latest.close;
    document.getElementById("last-price").textContent = fmtP(livePrice);

    const chg24 = market.price_24h_pcnt != null ? Number(market.price_24h_pcnt) * 100 : null;
    const chgEl = document.getElementById("stat-chg");
    chgEl.textContent = fmtPct(chg24);
    chgEl.style.color = chg24 == null ? "#ffffff" : (chg24 >= 0 ? "#26a69a" : "#ef5350");

    document.getElementById("stat-high").textContent = fmtP(market.high_24h != null ? market.high_24h : latest.high);
    document.getElementById("stat-low").textContent = fmtP(market.low_24h != null ? market.low_24h : latest.low);
    document.getElementById("stat-vol").textContent = fmtK(market.volume_24h != null ? market.volume_24h : latest.volume);

    if (firstCandleClose) {{
      const session = ((Number(livePrice) - firstCandleClose) / firstCandleClose) * 100;
      const sessionEl = document.getElementById("session-pct");
      sessionEl.textContent = fmtPct(session) + " session";
      sessionEl.style.color = session >= 0 ? "#26a69a" : "#ef5350";
    }}
  }}

  function applySeries(candles) {{
    candleCache = mergeCandles([], candles);
    if (!candleCache.length) return;
    firstCandleClose = Number(candleCache[0].close) || null;
    lastCandleTime = Number(candleCache[candleCache.length - 1].time) || 0;

    candleSeries.setData(toCandleData(candleCache));
    volSeries.setData(toVolumeData(candleCache));

    if (ema20Series) ema20Series.setData(calcEMA(candleCache, 20));
    if (ema50Series) ema50Series.setData(calcEMA(candleCache, 50));

    if (FLAGS.show_bb) {{
      const bands = calcBollinger(candleCache, FLAGS.bb_period, FLAGS.bb_std_dev);
      bbUpperSeries.setData(bands.upper);
      bbMiddleSeries.setData(bands.middle);
      bbLowerSeries.setData(bands.lower);
    }}

    if (FLAGS.show_rsi && rsiSeries) {{
      rsiSeries.setData(calcRSI(candleCache, FLAGS.rsi_period));
    }}

    if (FLAGS.show_macd && macdSeries && macdSignalSeries && macdHistSeries) {{
      const macd = calcMACD(candleCache, FLAGS.macd_fast, FLAGS.macd_slow, FLAGS.macd_signal);
      macdSeries.setData(macd.macd);
      macdSignalSeries.setData(macd.signal);
      macdHistSeries.setData(macd.histogram);
    }}

    setOHLC(candleCache[candleCache.length - 1]);
  }}

  applySeries(candleCache);
  if (candleCache.length) {{
    setStats({{}}, candleCache[candleCache.length - 1]);
  }}
  let syncing = false;
  if (candleCache.length) {{
    const initialVisibleBars = compactLayout() ? 72 : 120;
    const initialRange = {{
      from: Math.max(candleCache.length - initialVisibleBars, 0),
      to: candleCache.length + 3,
    }};
    syncing = true;
    allCharts.forEach((chart) => chart.timeScale().setVisibleLogicalRange(initialRange));
    syncing = false;
  }}
  allCharts.forEach((chart) => {{
    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {{
      if (syncing || !range) return;
      syncing = true;
      allCharts.forEach((otherChart) => {{
        if (otherChart !== chart) {{
          otherChart.timeScale().setVisibleLogicalRange(range);
        }}
      }});
      syncing = false;
    }});
  }});

  function requestBackfill(anchorRange) {{
    if (!API_BASE || backfillPending || reachedHistoryStart || !candleCache.length) return;
    const earliestTime = Number(candleCache[0].time || 0);
    if (!earliestTime) return;

    backfillPending = true;
    fetch(API_BASE + "/api/market/terminal?symbol=" + SYMBOL + "&interval=" + TF + "&limit=" + BACKFILL_BATCH + "&before=" + earliestTime)
      .then((response) => {{
        if (!response.ok) throw new Error(response.status);
        return response.json();
      }})
      .then((payload) => {{
        const olderCandles = Array.isArray(payload.candles) ? payload.candles : [];
        if (!olderCandles.length) {{
          reachedHistoryStart = true;
          return;
        }}

        const previousLength = candleCache.length;
        const merged = mergeCandles(olderCandles, candleCache);
        const addedCount = Math.max(0, merged.length - previousLength);
        applySeries(merged);

        if (anchorRange && addedCount > 0) {{
          const shiftedRange = {{
            from: anchorRange.from + addedCount,
            to: anchorRange.to + addedCount,
          }};
          syncing = true;
          allCharts.forEach((chart) => chart.timeScale().setVisibleLogicalRange(shiftedRange));
          syncing = false;
        }}
      }})
      .catch(() => {{
      }})
      .finally(() => {{
        backfillPending = false;
      }});
  }}

  priceChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {{
    if (!range || backfillPending || reachedHistoryStart) return;
    if (range.from <= BACKFILL_TRIGGER_BARS) {{
      requestBackfill(range);
    }}
  }});

  priceChart.subscribeCrosshairMove((param) => {{
    if (!param || !param.seriesData) {{
      if (candleCache.length) {{
        const latest = candleCache[candleCache.length - 1];
        document.getElementById("last-price").textContent = fmtP(latest.close);
        setOHLC(latest);
      }}
      return;
    }}

    const candle = param.seriesData.get(candleSeries);
    if (candle) {{
      document.getElementById("last-price").textContent = fmtP(candle.close);
      setOHLC(candle);
    }}
  }});

  function pollMarket() {{
    if (!API_BASE) {{
      errBar.textContent = "Live feed needs FINWISE_PUBLIC_CHART_API_BASE for phone or tunnel access.";
      errBar.style.display = "block";
      return;
    }}
    fetch(API_BASE + "/api/market/terminal?symbol=" + SYMBOL + "&interval=" + TF + "&limit=" + LIVE_WINDOW)
      .then((response) => {{
        if (!response.ok) throw new Error(response.status);
        return response.json();
      }})
      .then((payload) => {{
        failCount = 0;
        errBar.style.display = "none";

        const candles = Array.isArray(payload.candles) ? payload.candles : [];
        if (!candles.length) return;

        const merged = mergeCandles(candleCache, candles);
        applySeries(merged);
        setStats(payload.market || {{}}, merged[merged.length - 1]);
      }})
      .catch(() => {{
        failCount += 1;
        if (failCount >= 3) {{
          errBar.style.display = "block";
        }}
      }});
  }}

  const resizeCharts = () => {{
    const width = containerWidth();
    const nextPriceHeight = currentPriceHeight();
    priceChart.resize(width, nextPriceHeight);
    volChart.resize(width, volumeHeight);
    if (rsiChart) rsiChart.resize(width, rsiHeight);
    if (macdChart) macdChart.resize(width, macdHeight);
  }};

  window.addEventListener("resize", resizeCharts);
  setTimeout(resizeCharts, 60);
  setTimeout(resizeCharts, 240);
  setTimeout(pollMarket, 350);
  setInterval(pollMarket, POLL_MS);
}})();
</script>
</body>
</html>
"""
    _render_scripted_html(chart_html, height=total_height)


def _render_lightweight_terminal_chart(
    df: pd.DataFrame,
    symbol: str,
    tf_label: str,
    height: int = 520,
    compact_layout: bool = False,
):
    # Cache the chart data to prevent refresh flashing
    _cache_chart_data(symbol, tf_label, df)
    cached_candles = _get_cached_chart_data(symbol, tf_label)
    
    chart_df = df.tail(160 if compact_layout else 220).copy()
    if chart_df.empty:
        st.info("No chart data yet.")
        return
    
    # ✅ Phase 1 (MVP): Calculate Moving Averages using modular indicator pipeline
    indicator_pipeline = IndicatorPipeline(st.session_state.chart_indicators)
    chart_df = indicator_pipeline.calculate_indicators(chart_df)

    price_rows = []
    volume_rows = []
    for _, row in chart_df.iterrows():
        ts = row.get("timestamp")
        if hasattr(ts, "timestamp"):
            time_value = int(ts.timestamp())
        else:
            time_value = int(pd.Timestamp(ts).timestamp())

        is_up = float(row["close"]) >= float(row["open"])
        vol_color = "rgba(38, 166, 154, 0.45)" if is_up else "rgba(239, 83, 80, 0.45)"

        price_rows.append(
            {
                "time": time_value,
                "open": round(float(row["open"]), 8),
                "high": round(float(row["high"]), 8),
                "low": round(float(row["low"]), 8),
                "close": round(float(row["close"]), 8),
            }
        )
        volume_rows.append(
            {
                "time": time_value,
                "value": round(float(row["volume"]), 4),
                "color": vol_color,
            }
        )

    last_close = float(chart_df["close"].iloc[-1])
    first_close = float(chart_df["close"].iloc[0])
    session_change = ((last_close - first_close) / first_close * 100) if first_close else 0.0

    mobile_bar_spacing = 7 if compact_layout else 10
    mobile_right_offset = 1 if compact_layout else 0
    common_layout = {
        "layout": {
            "background": {"type": "solid", "color": "#08111d"},
            "textColor": "#d1d4dc",
            "fontSize": 12,
        },
        "grid": {
            "vertLines": {"color": "rgba(42,46,57,0.18)"},
            "horzLines": {"color": "rgba(42,46,57,0.6)"},
        },
        "crosshair": {"mode": 0},
        "rightPriceScale": {
            "borderColor": "rgba(197,203,206,0.18)",
        },
        "timeScale": {
            "borderColor": "rgba(197,203,206,0.18)",
            "timeVisible": True,
            "secondsVisible": False,
            "barSpacing": mobile_bar_spacing,
            "minBarSpacing": 5 if compact_layout else 3,
            "rightOffset": mobile_right_offset,
            "fixLeftEdge": bool(compact_layout),
            "fixRightEdge": False,
            "lockVisibleTimeRangeOnResize": True,
            "rightBarStaysOnScroll": True,
            "shiftVisibleRangeOnNewBar": True,
        },
        "localization": {
            "locale": "en-US",
        },
    }

    price_chart_height = max(240, int(height * 0.76))
    volume_chart_height = max(72, int(height * 0.20))

    charts = [
        {
            "chart": {
                "height": price_chart_height,
                "rightPriceScale": {
                    "scaleMargins": {"top": 0.08, "bottom": 0.24},
                    "borderColor": "rgba(197,203,206,0.18)",
                },
                "timeScale": common_layout["timeScale"],
                "layout": common_layout["layout"],
                "grid": common_layout["grid"],
                "crosshair": common_layout["crosshair"],
                "localization": common_layout["localization"],
                "watermark": {
                    "visible": True,
                    "fontSize": 36,
                    "horzAlign": "center",
                    "vertAlign": "center",
                    "color": "rgba(127,166,189,0.08)",
                    "text": symbol,
                },
            },
            "series": [
                {
                    "type": "Candlestick",
                    "data": price_rows,
                    "options": {
                        "upColor": "#26a69a",
                        "downColor": "#ef5350",
                        "borderVisible": False,
                        "wickUpColor": "#26a69a",
                        "wickDownColor": "#ef5350",
                        "priceLineVisible": True,
                        "lastValueVisible": True,
                    },
                }
            ] + indicator_pipeline.format_series(chart_df),
        },
        {
            "chart": {
                "height": volume_chart_height,
                "layout": {
                    "background": {"type": "solid", "color": "#08111d"},
                    "textColor": "#6f8aa0",
                },
                "grid": {
                    "vertLines": {"color": "rgba(42,46,57,0)"},
                    "horzLines": {"color": "rgba(42,46,57,0.35)"},
                },
                "crosshair": {"mode": 0},
                "rightPriceScale": {
                    "borderColor": "rgba(197,203,206,0.18)",
                    "scaleMargins": {"top": 0.15, "bottom": 0.0},
                },
                "timeScale": {
                    "borderColor": "rgba(197,203,206,0.18)",
                    "timeVisible": True,
                    "secondsVisible": False,
                    "barSpacing": 10,
                },
                "localization": common_layout["localization"],
            },
            "series": [
                {
                    "type": "Histogram",
                    "data": volume_rows,
                    "options": {
                        "priceFormat": {"type": "volume"},
                        "priceScaleId": "",
                    },
                    "priceScale": {
                        "scaleMargins": {"top": 0.0, "bottom": 0.0},
                    },
                }
            ],
        },
    ]

    stats_grid = "repeat(2,1fr)" if compact_layout else "repeat(4,1fr)"
    card_padding = "12px 13px 8px" if compact_layout else "14px 16px 10px"
    card_radius = 18 if compact_layout else 20
    symbol_font = 16 if compact_layout else 18
    metric_font = 14 if compact_layout else 17

    st.markdown(
        f"""
        <div style="background:#08111d;border:1px solid rgba(255,255,255,0.06);border-radius:{card_radius}px;
                    padding:{card_padding};margin-bottom:12px;box-shadow:0 20px 45px rgba(0,0,0,0.24);">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px;">
                <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                    <div style="color:white;font-size:{symbol_font}px;font-weight:700;">{escape(symbol)}</div>
                    <div style="font-size:11px;color:#7fa6bd;padding:4px 8px;border-radius:999px;background:#102235;">
                        {escape(tf_label)} candlestick
                    </div>
                    <div style="font-size:11px;color:#7fa6bd;padding:4px 8px;border-radius:999px;background:#102235;{'display:none;' if compact_layout else ''}">
                        TradingView lightweight
                    </div>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <span style="width:8px;height:8px;border-radius:999px;background:#00f5d4;box-shadow:0 0 10px #00f5d4;"></span>
                    <span style="font-size:11px;color:#9bc1d4;">Exchange style</span>
                </div>
            </div>
            <div style="display:grid;grid-template-columns:{stats_grid};gap:8px;margin-bottom:8px;">
                <div style="background:#0c1b2a;border-radius:12px;padding:10px 12px;">
                    <div style="color:#587b92;font-size:10px;text-transform:uppercase;letter-spacing:0.8px;">Last</div>
                    <div style="color:white;font-size:{metric_font}px;font-weight:800;margin-top:4px;">{_fmt_price(last_close)}</div>
                </div>
                <div style="background:#0c1b2a;border-radius:12px;padding:10px 12px;">
                    <div style="color:#587b92;font-size:10px;text-transform:uppercase;letter-spacing:0.8px;">Session</div>
                    <div style="color:{'#26a69a' if session_change >= 0 else '#ef5350'};font-size:{metric_font}px;font-weight:800;margin-top:4px;">{_fmt_pct(session_change)}</div>
                </div>
                <div style="background:#0c1b2a;border-radius:12px;padding:10px 12px;">
                    <div style="color:#587b92;font-size:10px;text-transform:uppercase;letter-spacing:0.8px;">High</div>
                    <div style="color:white;font-size:{metric_font}px;font-weight:800;margin-top:4px;">{_fmt_price(chart_df['high'].max())}</div>
                </div>
                <div style="background:#0c1b2a;border-radius:12px;padding:10px 12px;">
                    <div style="color:#587b92;font-size:10px;text-transform:uppercase;letter-spacing:0.8px;">Low</div>
                    <div style="color:white;font-size:{metric_font}px;font-weight:800;margin-top:4px;">{_fmt_price(chart_df['low'].min())}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    # Use container with stable key to prevent flashing on each rerun
    with st.container():
        renderLightweightCharts(charts, key=f"lw_chart_{symbol}_{tf_label}_stable")


def _render_pro_terminal_chart(df: pd.DataFrame, symbol: str, tf_label: str, snapshot: dict):
    chart_df = df.tail(180).copy()
    candles = []
    for _, row in chart_df.iterrows():
        ts = row.get("timestamp")
        if hasattr(ts, "isoformat"):
            ts_val = ts.isoformat()
        else:
            ts_val = str(ts)
        candles.append(
            {
                "time": ts_val,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
        )

    change_pct = snapshot.get("price_24h_pcnt")
    if change_pct is not None:
        change_pct *= 100
    session_pct = snapshot.get("candle_change_pct")
    last_price = snapshot.get("last_price")
    payload = {
        "symbol": symbol,
        "timeframe": tf_label,
        "last_price": None if last_price is None else float(last_price),
        "change_pct": None if change_pct is None else float(change_pct),
        "session_pct": None if session_pct is None else float(session_pct),
        "candles": candles,
    }
    payload_json = json.dumps(payload)
    symbol_safe = escape(symbol)
    tf_safe = escape(tf_label)

    chart_html = f"""
    <div id="finwise-pro-terminal" style="background:#08111d;border:1px solid rgba(255,255,255,0.06);
         border-radius:22px;overflow:hidden;height:620px;font-family:Segoe UI,sans-serif;color:#e8f4f8;
         box-shadow:0 20px 45px rgba(0,0,0,0.24);">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 16px;
           border-bottom:1px solid rgba(255,255,255,0.05);background:linear-gradient(180deg,#0d1828,#0a1421);">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
          <div style="font-size:17px;font-weight:700;color:white;">{symbol_safe}</div>
          <div style="font-size:11px;color:#7fa6bd;padding:4px 8px;border-radius:999px;background:#102235;">
            {tf_safe} live terminal
          </div>
          <div style="font-size:11px;color:#7fa6bd;padding:4px 8px;border-radius:999px;background:#102235;">
            Canvas chart
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="width:8px;height:8px;border-radius:999px;background:#00f5d4;box-shadow:0 0 10px #00f5d4;"></span>
          <span style="font-size:11px;color:#9bc1d4;">Live feed</span>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr auto;gap:12px;padding:12px 16px 0;">
        <div style="display:flex;align-items:flex-end;gap:12px;">
          <div id="ft-last" style="font-size:30px;font-weight:800;color:white;">--</div>
          <div id="ft-change" style="font-size:13px;font-weight:700;padding-bottom:4px;">--</div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;">
          <div style="font-size:10px;color:#4a7a94;padding:6px 9px;border-radius:999px;background:#0c1b2a;">Drag-free view</div>
          <div style="font-size:10px;color:#4a7a94;padding:6px 9px;border-radius:999px;background:#0c1b2a;">180 candles</div>
        </div>
      </div>
      <div style="position:relative;padding:10px 12px 12px;">
        <canvas id="ft-canvas" style="width:100%;height:520px;display:block;background:
            linear-gradient(180deg,rgba(255,255,255,0.01),rgba(255,255,255,0));border-radius:16px;"></canvas>
        <div id="ft-tip" style="position:absolute;display:none;pointer-events:none;background:rgba(5,10,18,0.96);
             border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:8px 10px;font-size:11px;
             color:#e8f4f8;box-shadow:0 10px 20px rgba(0,0,0,0.25);"></div>
      </div>
    </div>
    <script>
      (function() {{
        const payload = {payload_json};
        const root = document.getElementById("finwise-pro-terminal");
        const canvas = document.getElementById("ft-canvas");
        const tip = document.getElementById("ft-tip");
        const lastNode = document.getElementById("ft-last");
        const changeNode = document.getElementById("ft-change");
        const candles = payload.candles || [];
        const fmt = (value, digits = 2) => Number(value || 0).toLocaleString(undefined, {{
          minimumFractionDigits: digits, maximumFractionDigits: digits
        }});

        function paint() {{
          const rect = canvas.getBoundingClientRect();
          const dpr = window.devicePixelRatio || 1;
          canvas.width = rect.width * dpr;
          canvas.height = rect.height * dpr;
          const ctx = canvas.getContext("2d");
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          ctx.clearRect(0, 0, rect.width, rect.height);

          if (!candles.length) return;

          const W = rect.width;
          const H = rect.height;
          const pad = {{ top: 18, right: 64, bottom: 26, left: 10 }};
          const volumeH = Math.max(80, H * 0.20);
          const chartH = H - pad.top - pad.bottom - volumeH - 14;
          const plotW = W - pad.left - pad.right;
          const lows = candles.map(c => c.low);
          const highs = candles.map(c => c.high);
          const maxP = Math.max(...highs);
          const minP = Math.min(...lows);
          const range = (maxP - minP) || 1;
          const maxVol = Math.max(...candles.map(c => c.volume || 0), 1);
          const candleW = Math.max(3, (plotW / candles.length) * 0.62);

          const yFor = (price) => pad.top + chartH - ((price - minP) / range) * chartH;
          const xFor = (index) => pad.left + (index / Math.max(candles.length - 1, 1)) * plotW;

          ctx.strokeStyle = "rgba(255,255,255,0.05)";
          ctx.lineWidth = 1;
          for (let i = 0; i <= 5; i++) {{
            const y = pad.top + (chartH / 5) * i;
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(pad.left + plotW, y);
            ctx.stroke();

            const price = maxP - (range / 5) * i;
            ctx.fillStyle = "#557a92";
            ctx.font = "10px JetBrains Mono, monospace";
            ctx.textAlign = "right";
            ctx.fillText(fmt(price, 2), W - 8, y + 3);
          }}

          candles.forEach((candle, index) => {{
            const x = xFor(index);
            const open = candle.open;
            const close = candle.close;
            const high = candle.high;
            const low = candle.low;
            const up = close >= open;
            const color = up ? "#26a69a" : "#ef5350";
            const bodyTop = yFor(Math.max(open, close));
            const bodyBottom = yFor(Math.min(open, close));
            const bodyH = Math.max(2, bodyBottom - bodyTop);

            ctx.strokeStyle = color;
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.moveTo(x, yFor(high));
            ctx.lineTo(x, yFor(low));
            ctx.stroke();
            ctx.fillRect(x - candleW / 2, bodyTop, candleW, bodyH);

            const volTop = pad.top + chartH + 14 + (1 - ((candle.volume || 0) / maxVol)) * volumeH;
            ctx.globalAlpha = 0.34;
            ctx.fillRect(x - candleW / 2, volTop, candleW, H - pad.bottom - volTop);
            ctx.globalAlpha = 1;
          }});

          const latest = candles[candles.length - 1];
          const latestY = yFor(latest.close);
          ctx.strokeStyle = "rgba(0,245,212,0.75)";
          ctx.setLineDash([4, 4]);
          ctx.beginPath();
          ctx.moveTo(pad.left, latestY);
          ctx.lineTo(pad.left + plotW, latestY);
          ctx.stroke();
          ctx.setLineDash([]);

          ctx.fillStyle = "#00f5d4";
          ctx.fillRect(W - pad.right + 6, latestY - 11, pad.right - 14, 22);
          ctx.fillStyle = "#041018";
          ctx.font = "bold 11px JetBrains Mono, monospace";
          ctx.textAlign = "right";
          ctx.fillText(fmt(latest.close, 2), W - 12, latestY + 4);

          canvas.onmousemove = (event) => {{
            const rect2 = canvas.getBoundingClientRect();
            const mx = event.clientX - rect2.left;
            const my = event.clientY - rect2.top;
            if (mx < pad.left || mx > pad.left + plotW || my < pad.top || my > pad.top + chartH) {{
              tip.style.display = "none";
              paint();
              return;
            }}

            const idx = Math.max(0, Math.min(candles.length - 1, Math.round(((mx - pad.left) / plotW) * (candles.length - 1))));
            const point = candles[idx];
            paint();

            const px = xFor(idx);
            const py = yFor(point.close);
            ctx.strokeStyle = "rgba(255,255,255,0.14)";
            ctx.beginPath();
            ctx.moveTo(px, pad.top);
            ctx.lineTo(px, pad.top + chartH);
            ctx.stroke();
            ctx.beginPath();
            ctx.moveTo(pad.left, py);
            ctx.lineTo(pad.left + plotW, py);
            ctx.stroke();

            tip.style.display = "block";
            tip.style.left = Math.min(rect2.width - 150, px + 16) + "px";
            tip.style.top = Math.max(18, py - 18) + "px";
            tip.innerHTML = `
              <div style="color:#7fa6bd;font-size:10px;margin-bottom:3px;">${{point.time}}</div>
              <div>O ${{fmt(point.open, 2)}} H ${{fmt(point.high, 2)}}</div>
              <div>L ${{fmt(point.low, 2)}} C <b>${{fmt(point.close, 2)}}</b></div>
            `;
          }};

          canvas.onmouseleave = () => {{
            tip.style.display = "none";
            paint();
          }};
        }}

        const change = Number(payload.change_pct || 0);
        lastNode.textContent = payload.last_price == null ? "--" : fmt(payload.last_price, 2);
        changeNode.textContent = `${{change >= 0 ? "+" : ""}}${{change.toFixed(2)}}%  /  Session ${{Number(payload.session_pct || 0).toFixed(2)}}%`;
        changeNode.style.color = change >= 0 ? "#26a69a" : "#ef5350";
        paint();
        if (window.ResizeObserver) {{
          new ResizeObserver(paint).observe(root);
        }} else {{
          window.addEventListener("resize", paint);
        }}
      }})();
    </script>
    """
    _render_scripted_html(chart_html, height=620)


def _render_market_snapshot(snapshot: dict, symbol: str, tf_label: str):
    forex_market = is_forex_symbol(symbol) or snapshot.get("asset_class") == "forex"
    change_pct = snapshot.get("price_24h_pcnt")
    if change_pct is not None:
        change_pct *= 100
    last_price = snapshot.get("last_price")
    mark_price = snapshot.get("mark_price")
    index_price = snapshot.get("index_price")
    funding_rate = snapshot.get("funding_rate")
    high_24h = snapshot.get("high_24h")
    low_24h = snapshot.get("low_24h")
    volume_24h = snapshot.get("volume_24h")
    turnover_24h = snapshot.get("turnover_24h")
    candle_change_pct = snapshot.get("candle_change_pct")
    change_color = "#26a69a" if (change_pct or 0) >= 0 else "#ef5350"

    if forex_market:
        stats = [
            ("Mid", _fmt_price(mark_price)),
            ("Reference", _fmt_price(index_price)),
            ("24h Change", _fmt_pct(change_pct)),
            ("24h High", _fmt_price(high_24h)),
            ("24h Low", _fmt_price(low_24h)),
            ("Tick Volume", _fmt_compact(volume_24h)),
            ("Feed", "Yahoo FX"),
            ("Market", "Spot FX"),
        ]
    else:
        stats = [
            ("Mark", _fmt_price(mark_price)),
            ("Index", _fmt_price(index_price)),
            ("Funding", "--" if funding_rate is None else f"{funding_rate * 100:.4f}%"),
            ("24h Change", _fmt_pct(change_pct)),
            ("24h High", _fmt_price(high_24h)),
            ("24h Low", _fmt_price(low_24h)),
            ("24h Volume", _fmt_compact(volume_24h)),
            ("24h Turnover", _fmt_compact(turnover_24h)),
        ]
    stat_html = "".join(
        f"""
        <div style="background:#0b1e2d;border:1px solid rgba(255,255,255,0.05);
                    border-radius:10px;padding:10px 12px;">
            <div style="color:#4a7a94;font-size:10px;text-transform:uppercase;
                        letter-spacing:0.8px;">{label}</div>
            <div style="color:#e8f4f8;font-size:14px;font-weight:700;margin-top:4px;">{value}</div>
        </div>
        """
        for label, value in stats
    )

    st.markdown(
        f"""
        <div style="background:#0f2639;border:1px solid rgba(0,245,212,0.16);
                    border-radius:18px;padding:18px 18px 14px;margin-bottom:16px;">
            <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;">
                <div>
                    <div style="color:white;font-size:20px;font-weight:700;">{symbol}</div>
                    <div style="color:#8ab4c8;font-size:12px;margin-top:4px;">{'Spot FX' if forex_market else 'Perpetual'} · {tf_label} chart</div>
                </div>
                <div style="text-align:right;">
                    <div style="color:white;font-size:28px;font-weight:800;">{_fmt_price(last_price)}</div>
                    <div style="color:{change_color};font-size:13px;font-weight:700;margin-top:4px;">
                        24h {_fmt_pct(change_pct)} · Candle {_fmt_pct(candle_change_pct)}
                    </div>
                </div>
            </div>
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:16px;">
                {stat_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_orderbook(snapshot: dict):
    bids = snapshot.get("bids", [])
    asks = list(reversed(snapshot.get("asks", [])))

    def _rows(items, color):
        if not items:
            return '<tr><td colspan="2" style="padding:8px;color:#4a7a94;">Waiting for depth...</td></tr>'
        return "".join(
            f"""
            <tr>
                <td style="padding:6px 0;color:{color};font-family:monospace;">{item['price']:,.2f}</td>
                <td style="padding:6px 0;text-align:right;color:#e8f4f8;font-family:monospace;">{item['size']:,.4f}</td>
            </tr>
            """
            for item in items
        )

    st.markdown(
        f"""
        <div style="background:#0f2639;border:1px solid rgba(0,245,212,0.12);
                    border-radius:16px;padding:16px;margin-bottom:16px;">
            <div style="color:white;font-size:16px;font-weight:700;margin-bottom:10px;">Order Book</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
                <div>
                    <div style="color:#ef5350;font-size:11px;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;">Asks</div>
                    <table style="width:100%;border-collapse:collapse;">
                        <thead>
                            <tr>
                                <th style="text-align:left;color:#4a7a94;font-size:10px;padding-bottom:6px;">Price</th>
                                <th style="text-align:right;color:#4a7a94;font-size:10px;padding-bottom:6px;">Size</th>
                            </tr>
                        </thead>
                        <tbody>{_rows(asks, "#ef5350")}</tbody>
                    </table>
                </div>
                <div>
                    <div style="color:#26a69a;font-size:11px;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;">Bids</div>
                    <table style="width:100%;border-collapse:collapse;">
                        <thead>
                            <tr>
                                <th style="text-align:left;color:#4a7a94;font-size:10px;padding-bottom:6px;">Price</th>
                                <th style="text-align:right;color:#4a7a94;font-size:10px;padding-bottom:6px;">Size</th>
                            </tr>
                        </thead>
                        <tbody>{_rows(bids, "#26a69a")}</tbody>
                    </table>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_chart_shell(fig):
    st.markdown(
        """
        <div style="background:#0f2639;border:1px solid rgba(0,245,212,0.12);
                    border-radius:18px;padding:10px 10px 0;margin-bottom:16px;">
        """,
        unsafe_allow_html=True,
    )
    renderLightweightCharts([{"chart": {"height": 400}, "series": []}], key="chart_shell")
    st.markdown("</div>", unsafe_allow_html=True)


def _render_market_snapshot_terminal(snapshot: dict, symbol: str, tf_label: str):
    forex_market = is_forex_symbol(symbol) or snapshot.get("asset_class") == "forex"
    change_pct = snapshot.get("price_24h_pcnt")
    if change_pct is not None:
        change_pct *= 100
    last_price = snapshot.get("last_price")
    candle_change_pct = snapshot.get("candle_change_pct")
    change_color = "#26a69a" if (change_pct or 0) >= 0 else "#ef5350"
    if forex_market:
        stats = [
            ("Mid", _fmt_price(snapshot.get("mark_price"))),
            ("Reference", _fmt_price(snapshot.get("index_price"))),
            ("24h High", _fmt_price(snapshot.get("high_24h"))),
            ("24h Low", _fmt_price(snapshot.get("low_24h"))),
            ("Tick Volume", _fmt_compact(snapshot.get("volume_24h"))),
            ("Feed", "Yahoo FX"),
            ("Market", "Spot FX"),
            ("Quote", symbol),
        ]
    else:
        stats = [
            ("Mark", _fmt_price(snapshot.get("mark_price"))),
            ("Index", _fmt_price(snapshot.get("index_price"))),
            ("Funding", "--" if snapshot.get("funding_rate") is None else f"{snapshot.get('funding_rate') * 100:.4f}%"),
            ("24h High", _fmt_price(snapshot.get("high_24h"))),
            ("24h Low", _fmt_price(snapshot.get("low_24h"))),
            ("Open Int.", _fmt_compact(snapshot.get("open_interest"))),
            ("24h Volume", _fmt_compact(snapshot.get("volume_24h"))),
            ("24h Turnover", _fmt_compact(snapshot.get("turnover_24h"))),
        ]
    stats_html = "".join(
        f"""
        <div style="background:#0b1e2d;border:1px solid rgba(255,255,255,0.05);border-radius:12px;padding:10px 12px;">
            <div style="color:#4a7a94;font-size:10px;text-transform:uppercase;letter-spacing:0.8px;">{label}</div>
            <div style="color:#e8f4f8;font-size:14px;font-weight:700;margin-top:4px;">{value}</div>
        </div>
        """
        for label, value in stats
    )
    st.markdown(
        f"""
        <div style="background:#111c2a;border:1px solid rgba(255,255,255,0.06);
                    border-radius:20px;padding:16px 18px 14px;margin-bottom:14px;
                    box-shadow:0 20px 40px rgba(0,0,0,0.22);">
            <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;
                        padding-bottom:14px;border-bottom:1px solid rgba(255,255,255,0.05);">
                <div>
                    <div style="color:#8ab4c8;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Live Market</div>
                    <div style="color:white;font-size:20px;font-weight:700;margin-top:4px;">{symbol}</div>
                    <div style="color:#8ab4c8;font-size:12px;margin-top:4px;">{'Spot FX' if forex_market else 'Perpetual'} | {tf_label} terminal</div>
                </div>
                <div style="text-align:right;">
                    <div style="color:white;font-size:30px;font-weight:800;letter-spacing:0.3px;">{_fmt_price(last_price)}</div>
                    <div style="color:{change_color};font-size:13px;font-weight:700;margin-top:4px;">
                        24h {_fmt_pct(change_pct)} | Session {_fmt_pct(candle_change_pct)}
                    </div>
                </div>
            </div>
            <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:14px;">
                {stats_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_orderbook_terminal(snapshot: dict):
    if not isinstance(snapshot, dict):
        snapshot = {}
    forex_quote = snapshot.get("source") == "forex_quote"
    bids = snapshot.get("bids", [])
    asks = list(reversed(snapshot.get("asks", [])))
    best_bid = bids[0]["price"] if bids else None
    best_ask = asks[-1]["price"] if asks else None
    spread = (best_ask - best_bid) if best_bid is not None and best_ask is not None else None
    spread_pct = ((spread / best_ask) * 100) if spread is not None and best_ask else None
    bid_total = sum(item["size"] for item in bids)
    ask_total = sum(item["size"] for item in asks)
    imbalance = ((bid_total - ask_total) / (bid_total + ask_total) * 100) if (bid_total + ask_total) else 0
    max_depth = max([item["size"] for item in bids + asks], default=1)

    def _rows(items, color):
        if not items:
            empty_message = "Spot FX depth is not available from this quote feed." if forex_quote else "Waiting for depth..."
            return f'<tr><td colspan="3" style="padding:8px;color:#4a7a94;">{empty_message}</td></tr>'
        return "".join(
            f"""
            <tr>
                <td style="padding:6px 0;color:{color};font-family:monospace;">{item['price']:,.2f}</td>
                <td style="padding:6px 0;text-align:right;color:#e8f4f8;font-family:monospace;">{item['size']:,.4f}</td>
                <td style="padding-left:8px;width:36%;">
                    <div style="height:6px;background:rgba(255,255,255,0.04);border-radius:999px;overflow:hidden;">
                        <div style="width:{max(4, int((item['size'] / max_depth) * 100))}%;height:100%;background:{color};opacity:0.55;"></div>
                    </div>
                </td>
            </tr>
            """
            for item in items
        )

    spread_label = _fmt_pct(spread_pct) if spread_pct is not None else "--"
    mid_price = ((best_bid + best_ask) / 2) if best_bid is not None and best_ask is not None else None
    bid_share = (bid_total / (bid_total + ask_total) * 100) if (bid_total + ask_total) else 0
    ask_share = 100 - bid_share if (bid_total + ask_total) else 0
    orderbook_html = f"""
        <html>
        <head>
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <style>
            * {{ box-sizing: border-box; }}
            html, body {{
              margin: 0;
              padding: 0;
              background: transparent;
              font-family: "Segoe UI", Arial, sans-serif;
              color: white;
              width: 100%;
              max-width: 100%;
              overflow-x: hidden;
            }}
            .orderbook-card {{
              background: linear-gradient(180deg, rgba(10,23,36,0.98) 0%, rgba(8,19,31,0.98) 100%);
              border: 1px solid rgba(255,255,255,0.06);
              border-radius: 22px;
              padding: 16px 16px 14px;
              font-family: "Segoe UI", Arial, sans-serif;
              color: white;
              box-shadow: 0 22px 44px rgba(0,0,0,0.22);
              overflow: hidden;
              width: 100%;
              max-width: 100%;
            }}
            .orderbook-top {{
              display: flex;
              align-items: flex-start;
              justify-content: space-between;
              gap: 12px;
            }}
            .orderbook-title {{
              color: white;
              font-size: 17px;
              font-weight: 800;
            }}
            .orderbook-sub {{
              color: #7f9ab0;
              font-size: 11px;
              margin-top: 4px;
            }}
            .orderbook-pill-row {{
              display: flex;
              gap: 6px;
              flex-wrap: wrap;
            }}
            .orderbook-pill {{
              font-size: 10px;
              color: #8ab4c8;
              padding: 4px 8px;
              border-radius: 999px;
              background: rgba(12,27,42,0.92);
              border: 1px solid rgba(255,255,255,0.05);
            }}
            .orderbook-metrics {{
              display: grid;
              grid-template-columns: repeat(2, 1fr);
              gap: 10px;
              margin-top: 14px;
            }}
            .orderbook-metric {{
              background: rgba(12,27,42,0.82);
              border: 1px solid rgba(255,255,255,0.05);
              border-radius: 14px;
              padding: 10px 12px;
            }}
            .metric-label {{
              color: #5f7f93;
              font-size: 10px;
              text-transform: uppercase;
              letter-spacing: 0.08em;
            }}
            .metric-value {{
              color: white;
              font-size: 16px;
              font-weight: 800;
              font-family: monospace;
              margin-top: 6px;
            }}
            .orderbook-bar-wrap {{
              margin-top: 14px;
            }}
            .orderbook-bar-top {{
              display: flex;
              align-items: center;
              justify-content: space-between;
              margin-bottom: 8px;
              gap: 10px;
            }}
            .orderbook-depth-bar {{
              display: grid;
              grid-template-columns: {bid_share:.2f}fr {ask_share:.2f}fr;
              height: 8px;
              border-radius: 999px;
              overflow: hidden;
            }}
            .book-side-grid {{
              display: grid;
              grid-template-columns: 1fr 1fr;
              gap: 12px;
              margin-top: 14px;
            }}
            .book-side-title {{
              font-size: 11px;
              text-transform: uppercase;
              letter-spacing: 0.08em;
              margin-bottom: 8px;
              font-weight: 700;
            }}
            table {{
              width: 100%;
              border-collapse: collapse;
              table-layout: fixed;
            }}
            th {{
              text-align: left;
              color: #5f7f93;
              font-size: 10px;
              padding-bottom: 6px;
            }}
            td {{
              font-size: 11px;
              min-width: 0;
              white-space: nowrap;
            }}
            th.right, td.right {{
              text-align: right;
            }}
            td.depth-cell {{
              padding-left: 8px;
              width: 36%;
            }}
            @media (max-width: 700px) {{
              .orderbook-card {{
                padding: 14px 14px 12px;
                border-radius: 18px;
              }}
              .orderbook-top {{
                flex-direction: column;
                align-items: flex-start;
              }}
              .orderbook-metrics,
              .book-side-grid {{
                grid-template-columns: 1fr;
              }}
              .metric-value {{
                font-size: 14px;
              }}
              td {{
                font-size: 10px;
              }}
            }}
          </style>
        </head>
        <body>
          <div class="orderbook-card">
            <div class="orderbook-top">
              <div>
                <div class="orderbook-title">{'FX Quote Feed' if forex_quote else 'Order Book'}</div>
                <div class="orderbook-sub">{'Indicative spot feed without exchange depth' if forex_quote else 'Live depth ladder'}</div>
              </div>
              <div class="orderbook-pill-row">
                <span class="orderbook-pill">{'FX Spot' if forex_quote else 'Depth'}</span>
                <span class="orderbook-pill">Spread {spread_label}</span>
              </div>
            </div>

            <div class="orderbook-metrics">
              <div class="orderbook-metric">
                <div class="metric-label">Best Bid</div>
                <div class="metric-value" style="color:#19dfd0;">{_fmt_price(best_bid)}</div>
              </div>
              <div class="orderbook-metric">
                <div class="metric-label">Spread</div>
                <div class="metric-value">{_fmt_price(spread)}</div>
              </div>
              <div class="orderbook-metric">
                <div class="metric-label">Mid Price</div>
                <div class="metric-value">{_fmt_price(mid_price)}</div>
              </div>
              <div class="orderbook-metric">
                <div class="metric-label">Imbalance</div>
                <div class="metric-value" style="color:{'#19dfd0' if imbalance >= 0 else '#ff6b7d'};">{imbalance:+.2f}%</div>
              </div>
            </div>

            <div class="orderbook-bar-wrap">
              <div class="orderbook-bar-top">
                <div style="color:#19dfd0;font-size:11px;font-weight:800;">Bids {bid_share:.1f}%</div>
                <div style="color:#ff6b7d;font-size:11px;font-weight:800;">Asks {ask_share:.1f}%</div>
              </div>
              <div class="orderbook-depth-bar">
                <div style="background:rgba(25,223,208,0.76);"></div>
                <div style="background:rgba(255,107,125,0.76);"></div>
              </div>
            </div>

            <div class="book-side-grid">
              <div>
                <div class="book-side-title" style="color:#ff6b7d;">Asks</div>
                <table>
                  <thead>
                    <tr>
                      <th>Price</th>
                      <th class="right">Size</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>{_rows(asks, "#ff6b7d")}</tbody>
                </table>
              </div>
              <div>
                <div class="book-side-title" style="color:#19dfd0;">Bids</div>
                <table>
                  <thead>
                    <tr>
                      <th>Price</th>
                      <th class="right">Size</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>{_rows(bids, "#19dfd0")}</tbody>
                </table>
              </div>
            </div>
          </div>
        </body>
        </html>
        """
    _render_component_html(orderbook_html, height=430)



def _load_trading_desk_panel_data(symbol: str, tf_label: str, *, allow_blocking_refresh: bool = True):
    if allow_blocking_refresh and not _engine_ready.is_set():
        _load_symbol_if_stale(symbol)

    df = engine.get_history(symbol, tf_label)
    if allow_blocking_refresh and (df is None or df.empty):
        try:
            _load_symbol_if_stale(symbol)
        except Exception:
            _engine_status["ok"] = False
            _engine_status["message"] = "Live market feed is temporarily unavailable."
        df = engine.get_history(symbol, tf_label)

    if allow_blocking_refresh and (df is None or df.empty):
        try:
            df = engine.ensure_history_depth(symbol, tf_label, min_candles=CHART_SEED_CANDLES)
        except Exception as exc:
            APP_LOGGER.warning("Active market history fetch failed for %s %s: %s", symbol, tf_label, exc)
            _engine_status["ok"] = False
            _engine_status["message"] = "Live market data is unreachable right now. Check your internet/DNS connection and retry the market feed."
            df = pd.DataFrame()

    if df is not None and not df.empty:
        _engine_status["ok"] = True
        _engine_status["message"] = "Live market feed ready."

    snapshot = engine.get_market_snapshot(symbol)
    orderbook = engine.get_orderbook(symbol, depth=10)

    if (df is None or df.empty) and not snapshot.get("last_price"):
        _engine_status["ok"] = False
        _engine_status["message"] = "Live market data is unreachable right now. Check your internet/DNS connection and retry the market feed."

    return df, snapshot, orderbook


def _crypto_confirmation_timeframe(tf_label: str) -> str:
    return {
        "1m": "5m",
        "3m": "15m",
        "5m": "15m",
        "15m": "1h",
        "30m": "1h",
        "1h": "4h",
        "4h": "1d",
    }.get(str(tf_label or "1m"), "5m")


def _prepare_crypto_indicator_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    working = df.copy()
    for column in ["open", "high", "low", "close", "volume"]:
        if column not in working.columns:
            working[column] = 0.0
        working[column] = pd.to_numeric(working.get(column), errors="coerce")
    working = working.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if working.empty:
        return working

    previous_close = working["close"].shift()
    true_range = pd.concat(
        [
            (working["high"] - working["low"]).abs(),
            (working["high"] - previous_close).abs(),
            (working["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    working["atr_14"] = true_range.rolling(14).mean()
    working["ema_20"] = working["close"].ewm(span=20).mean()
    working["ema_50"] = working["close"].ewm(span=50).mean()
    working["momentum_5"] = working["close"].pct_change(5) * 100
    working["volume_ma_20"] = working["volume"].rolling(20).mean()

    delta = working["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-9)
    working["rsi_14"] = 100 - (100 / (1 + rs))
    return working


def _crypto_orderbook_checks(orderbook: dict, side: str, entry_price: float) -> tuple[list[str], dict]:
    if not isinstance(orderbook, dict):
        return [], {}

    bids = list(orderbook.get("bids") or [])
    asks = list(orderbook.get("asks") or [])
    bid_prices = [_safe_float((item or {}).get("price"), None) for item in bids]
    ask_prices = [_safe_float((item or {}).get("price"), None) for item in asks]
    bid_prices = [value for value in bid_prices if value is not None and value > 0]
    ask_prices = [value for value in ask_prices if value is not None and value > 0]
    if not bid_prices or not ask_prices:
        return [], {}

    best_bid = max(bid_prices)
    best_ask = min(ask_prices)
    spread = max(best_ask - best_bid, 0.0)
    spread_pct = (spread / max(entry_price, 1e-9)) * 100

    bid_total = sum(_safe_float((item or {}).get("size")) for item in bids)
    ask_total = sum(_safe_float((item or {}).get("size")) for item in asks)
    book_total = bid_total + ask_total
    imbalance = ((bid_total - ask_total) / book_total * 100) if book_total else 0.0

    failures = []
    if spread_pct > 0.12:
        failures.append(f"spread is too wide ({spread_pct:.3f}%)")
    side = str(side or "").upper()
    if side == "BUY" and imbalance < -25:
        failures.append("order book is leaning too heavily against buys")
    if side == "SELL" and imbalance > 25:
        failures.append("order book is leaning too heavily against sells")

    return failures, {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_pct": spread_pct,
        "depth_imbalance": imbalance,
    }


def _crypto_candle_checks(indicator_df: pd.DataFrame, side: str) -> tuple[list[str], dict]:
    if indicator_df is None or indicator_df.empty:
        return ["latest candle is unavailable"], {}

    last = indicator_df.iloc[-1]
    open_price = _safe_float(last.get("open"))
    high_price = _safe_float(last.get("high"))
    low_price = _safe_float(last.get("low"))
    close_price = _safe_float(last.get("close"))
    ema_20 = _safe_float(last.get("ema_20"))
    ema_50 = _safe_float(last.get("ema_50"))
    momentum = _safe_float(last.get("momentum_5"))
    rsi = _safe_float(last.get("rsi_14"), 50.0)
    volume = _safe_float(last.get("volume"))
    volume_ma = _safe_float(last.get("volume_ma_20"))
    candle_range = max(high_price - low_price, 1e-9)
    body_ratio = abs(close_price - open_price) / candle_range
    upper_wick_ratio = (high_price - max(open_price, close_price)) / candle_range
    lower_wick_ratio = (min(open_price, close_price) - low_price) / candle_range

    side = str(side or "").upper()
    failures = []
    if side == "BUY":
        if not (close_price > ema_20 > ema_50):
            failures.append("EMA trend is not aligned upward")
        if momentum <= 0:
            failures.append("momentum is not positive")
        if not (48 <= rsi <= 74):
            failures.append(f"RSI is not in the buy zone ({rsi:.1f})")
        if close_price <= open_price:
            failures.append("latest candle is not closing bullish")
        if upper_wick_ratio > 0.48:
            failures.append("latest candle has too much upper rejection")
    elif side == "SELL":
        if not (close_price < ema_20 < ema_50):
            failures.append("EMA trend is not aligned downward")
        if momentum >= 0:
            failures.append("momentum is not negative")
        if not (26 <= rsi <= 52):
            failures.append(f"RSI is not in the sell zone ({rsi:.1f})")
        if close_price >= open_price:
            failures.append("latest candle is not closing bearish")
        if lower_wick_ratio > 0.48:
            failures.append("latest candle has too much lower rejection")
    else:
        failures.append("AI signal is not Buy or Sell")

    if body_ratio < 0.14:
        failures.append("latest candle body is too weak for instant entry")
    if volume_ma > 0 and volume < (volume_ma * 0.65):
        failures.append("volume is too thin versus recent activity")

    return failures, {
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "ema_20": ema_20,
        "ema_50": ema_50,
        "momentum": momentum,
        "rsi": rsi,
        "body_ratio": body_ratio,
        "upper_wick_ratio": upper_wick_ratio,
        "lower_wick_ratio": lower_wick_ratio,
        "volume": volume,
        "volume_ma": volume_ma,
    }


def _build_hidden_crypto_instant_signal(
    username: str,
    symbol: str,
    tf_label: str,
    df: pd.DataFrame,
    snapshot: dict = None,
    orderbook: dict = None,
    *,
    min_confidence: float = 68.0,
    min_rr: float = 4.0,
    risk_percent: float = 1.0,
    trade_style: str = "",
    balance_basis: float | None = None,
) -> tuple[dict, str]:
    symbol = str(symbol or "").upper().strip()
    tf_label = str(tf_label or "1m").strip()
    if not symbol:
        return {}, "Crypto instant signal has no symbol."
    if is_forex_symbol(symbol):
        return {
            "status": "DISABLED",
            "side": "WAIT",
            "symbol": symbol,
            "tf_label": tf_label,
            "reason": "Hidden instant crypto signal is skipped for forex symbols.",
        }, ""
    if df is None or df.empty or len(df) < 60:
        return {}, "Crypto instant signal needs more candle history."

    confirmation_tf = _crypto_confirmation_timeframe(tf_label)
    confirm_df = engine.get_history(symbol, confirmation_tf)
    if confirm_df is None or confirm_df.empty or len(confirm_df) < 60:
        failures_for_wait = [f"{confirmation_tf} confirmation history is not ready"]
        confirm_df = df
    else:
        failures_for_wait = []

    snapshot = snapshot or {}
    indicator_df = _prepare_crypto_indicator_frame(df)
    if indicator_df.empty or len(indicator_df) < 60:
        return {}, "Crypto instant signal could not prepare indicator history."

    if balance_basis is None:
        try:
            profile = st.session_state.get("manual_broker_profile") or {}
            balance_basis = float(
                st.session_state.get("auto_trade_balance_snapshot")
                or profile.get("balance")
                or 10000.0
            )
        except Exception:
            balance_basis = 10000.0
    trade_style = normalize_trade_style(trade_style or _current_trade_style())
    try:
        main_signal = ai_signal_for_user(
            username,
            df,
            symbol=symbol,
            current_balance=balance_basis,
            timeframe=tf_label,
            trade_style=trade_style,
        )
        confirm_signal = ai_signal_for_user(
            username,
            confirm_df,
            symbol=symbol,
            current_balance=balance_basis,
            timeframe=confirmation_tf,
            trade_style=trade_style,
        )
    except Exception as exc:
        APP_LOGGER.warning("Hidden crypto instant AI signal failed for %s %s: %s", symbol, tf_label, exc)
        return {}, f"Hidden crypto instant AI signal failed: {exc}"

    side = str(main_signal.get("signal", "HOLD") or "HOLD").upper()
    confirm_side = str(confirm_signal.get("signal", "HOLD") or "HOLD").upper()
    confidence = _safe_float(main_signal.get("confidence"))
    confirm_confidence = _safe_float(confirm_signal.get("confidence"))
    entry_exit = main_signal.get("entry_exit") if isinstance(main_signal.get("entry_exit"), dict) else {}

    last = indicator_df.iloc[-1]
    entry_price = _coalesce_market_number(
        snapshot.get("last_price"),
        snapshot.get("mark_price"),
        snapshot.get("index_price"),
        last.get("close"),
    )
    entry_price = _safe_float(entry_price)
    atr = _safe_float(last.get("atr_14"))
    reward_multiple = _bounded_reward_multiple(min_rr, default=4.0, maximum=4.0)
    stop_distance = max(atr * 1.2, entry_price * 0.0015, 1e-9)

    candle_failures, candle_metrics = _crypto_candle_checks(indicator_df, side)
    book_failures, book_metrics = _crypto_orderbook_checks(orderbook or {}, side, entry_price)

    failures = list(failures_for_wait)
    requested_rr = _safe_float(min_rr, reward_multiple)
    if requested_rr > reward_multiple:
        failures.append(f"requested reward/risk is capped at {reward_multiple:.2f}R for instant crypto signals")
    if side not in {"BUY", "SELL"} or not bool(main_signal.get("trade_allowed")):
        failures.append("current crypto AI signal is not a tradable Buy/Sell")
    if confidence < float(min_confidence or 0):
        failures.append(f"confidence {confidence:.1f}% is below {float(min_confidence or 0):.1f}%")
    if confirm_side != side or not bool(confirm_signal.get("trade_allowed")):
        failures.append(f"{confirmation_tf} confirmation is {confirm_side}, not {side}")
    elif confirm_confidence < max(50.0, float(min_confidence or 0) - 10.0):
        failures.append(f"{confirmation_tf} confirmation confidence is too low ({confirm_confidence:.1f}%)")
    if _safe_float(entry_exit.get("risk_reward_ratio")) < 1.5:
        failures.append("base AI reward/risk is too weak")
    failures.extend(candle_failures)
    failures.extend(book_failures)

    if side == "BUY":
        stop_loss = entry_price - stop_distance
        take_profit = entry_price + (stop_distance * reward_multiple)
    elif side == "SELL":
        stop_loss = entry_price + stop_distance
        take_profit = entry_price - (stop_distance * reward_multiple)
    else:
        stop_loss = 0.0
        take_profit = 0.0

    level_failures, level_metrics = _validate_instant_price_levels(
        side,
        entry_price,
        stop_loss,
        take_profit,
        atr_value=atr,
        requested_rr=reward_multiple,
        min_stop_pct=0.0015,
    )
    failures.extend(level_failures)

    timestamp = ""
    try:
        timestamp = str(df.iloc[-1].get("timestamp") or "")
    except (AttributeError, IndexError):
        timestamp = ""

    account_risk = balance_basis * max(float(risk_percent or 0), 0.0) / 100
    actual_rr = _safe_float(level_metrics.get("actual_rr"), reward_multiple)
    actual_risk_distance = _safe_float(level_metrics.get("risk_distance"), stop_distance)
    return {
        "status": "OPEN NOW" if not failures else "WAIT",
        "side": side if side in {"BUY", "SELL"} else "WAIT",
        "symbol": symbol,
        "tf_label": tf_label,
        "confirmation_timeframe": confirmation_tf,
        "entry_price": round(entry_price, 8),
        "stop_loss": round(stop_loss, 8),
        "take_profit": round(take_profit, 8),
        "risk_distance": round(actual_risk_distance, 8),
        "target_distance": round(_safe_float(level_metrics.get("reward_distance")), 8),
        "risk_distance_pct": round(_safe_float(level_metrics.get("risk_distance_pct")), 4),
        "target_distance_pct": round(_safe_float(level_metrics.get("target_distance_pct")), 4),
        "risk_reward_ratio": round(actual_rr, 2),
        "confidence": round(confidence, 1),
        "confirmation_confidence": round(confirm_confidence, 1),
        "account_risk": round(account_risk, 2),
        "target_amount": round(account_risk * actual_rr, 2),
        "risk_percent": round(float(risk_percent or 0), 2),
        "timestamp": timestamp,
        "failures": list(dict.fromkeys(failures)),
        "metrics": {**candle_metrics, **book_metrics, **level_metrics},
        "reason": str(main_signal.get("reason") or ""),
        "source": "hidden_crypto_instant",
        "updated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }, ""


def _render_crypto_instant_signal_card(instant_signal: dict, error: str = "") -> None:
    if error:
        st.warning(error)
        return
    if not instant_signal:
        st.caption("Live crypto signal is waiting for enough current market data.")
        return

    status = str(instant_signal.get("status") or "WAIT").upper()
    side = str(instant_signal.get("side") or "WAIT").upper()
    is_open = status == "OPEN NOW" and side in {"BUY", "SELL"}
    tone = "#19dfd0" if side == "BUY" else "#ff6b7d" if side == "SELL" else "#ffc107"
    bg = "rgba(25,223,208,0.10)" if side == "BUY" else "rgba(255,107,125,0.10)" if side == "SELL" else "rgba(255,193,7,0.10)"
    failures = list(instant_signal.get("failures") or [])
    failure_text = " | ".join(str(item) for item in failures[:4]) if failures else "All live-entry filters agree."
    status_label = f"{status} {side}" if side != "WAIT" else status
    reason = str(instant_signal.get("reason") or "").strip()
    if reason and len(reason) > 180:
        reason = f"{reason[:177].rstrip()}..."

    st.markdown(
        f"""
        <div style="margin-top:0.85rem;border:1px solid {tone};border-radius:18px;
                    background:linear-gradient(180deg,{bg},rgba(7,15,27,0.96));
                    padding:15px 15px 14px;box-shadow:0 18px 40px rgba(0,0,0,0.20);">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px;">
            <div>
              <div style="color:#7eece0;font-size:10px;font-weight:850;letter-spacing:0.15em;text-transform:uppercase;">Live Crypto Signal</div>
              <div style="color:{tone};font-size:22px;font-weight:900;letter-spacing:0.06em;margin-top:5px;">{escape(status_label)}</div>
              <div style="color:#88a7bc;font-size:11px;margin-top:4px;">
                {escape(str(instant_signal.get("symbol") or ""))} {escape(str(instant_signal.get("tf_label") or ""))}
                + {escape(str(instant_signal.get("confirmation_timeframe") or ""))}
              </div>
            </div>
            <div style="min-width:78px;text-align:right;color:#ffffff;font-weight:850;">
              {float(instant_signal.get("confidence") or 0):.1f}%
              <div style="color:#88a7bc;font-size:10px;font-weight:700;margin-top:3px;">confirm {float(instant_signal.get("confirmation_confidence") or 0):.1f}%</div>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:12px;">
            <div style="padding:9px;border-radius:12px;background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.05);">
              <div style="color:#6f90a6;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:0.1em;">Entry</div>
              <div style="color:#fff;font-size:13px;font-weight:850;margin-top:5px;">{_fmt_price(instant_signal.get("entry_price"))}</div>
            </div>
            <div style="padding:9px;border-radius:12px;background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.05);">
              <div style="color:#6f90a6;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:0.1em;">Stop</div>
              <div style="color:#ff9ba7;font-size:13px;font-weight:850;margin-top:5px;">{_fmt_price(instant_signal.get("stop_loss"))}</div>
            </div>
            <div style="padding:9px;border-radius:12px;background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.05);">
              <div style="color:#6f90a6;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:0.1em;">Target</div>
              <div style="color:#8cffdf;font-size:13px;font-weight:850;margin-top:5px;">{_fmt_price(instant_signal.get("take_profit"))}</div>
            </div>
          </div>
          <div style="display:flex;justify-content:space-between;gap:8px;margin-top:10px;color:#d8e8f2;font-size:11px;">
            <span>R/R {float(instant_signal.get("risk_reward_ratio") or 0):.2f}x</span>
            <span>Risk {float(instant_signal.get("risk_percent") or 0):.2f}%</span>
            <span>{escape(str(instant_signal.get("updated_at") or "live"))}</span>
          </div>
          <div style="margin-top:10px;color:{tone};font-size:11px;line-height:1.55;">{escape(failure_text)}</div>
          {f'<div style="margin-top:8px;color:#9eb6c6;font-size:11px;line-height:1.55;">{escape(reason)}</div>' if reason else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_requested_crypto_instant_signal_card(symbol: str, tf_label: str, trade_style: str = "") -> None:
    meta = st.session_state.get("crypto_instant_signal_meta") or {}
    expected_style = normalize_trade_style(trade_style or _current_trade_style())
    meta_style = str(meta.get("trade_style") or "").strip()
    if not meta_style:
        meta_key = str(meta.get("key") or "")
        meta_style = meta_key.rsplit("|", 1)[-1] if "|" in meta_key else ""
    meta_style = normalize_trade_style(meta_style)
    matches_context = (
        str(meta.get("symbol") or "").upper() == str(symbol or "").upper()
        and str(meta.get("tf_label") or "") == str(tf_label or "")
        and meta_style == expected_style
    )
    if not matches_context:
        return
    _render_crypto_instant_signal_card(
        st.session_state.get("crypto_instant_signal") or {},
        str(st.session_state.get("crypto_instant_signal_error", "") or ""),
    )


def _update_hidden_crypto_instant_signal(
    username: str,
    symbol: str,
    tf_label: str,
    df: pd.DataFrame,
    snapshot: dict = None,
    orderbook: dict = None,
    *,
    force: bool = False,
) -> None:
    key = f"{str(username or '').lower()}|{str(symbol or '').upper()}|{str(tf_label or '')}|{_current_trade_style()}"
    now = time.time()
    state_key = "crypto_instant_signal_meta"
    previous_meta = st.session_state.get(state_key) or {}
    if not force and previous_meta.get("key") == key and (now - float(previous_meta.get("checked_at") or 0)) < 12:
        return

    signal, error = _build_hidden_crypto_instant_signal(
        username=username,
        symbol=symbol,
        tf_label=tf_label,
        df=df,
        snapshot=snapshot or {},
        orderbook=orderbook or {},
    )
    st.session_state.crypto_instant_signal = signal
    st.session_state.crypto_instant_signal_error = error
    st.session_state.crypto_instant_signal_meta = {
        "key": key,
        "symbol": str(symbol or "").upper(),
        "tf_label": str(tf_label or ""),
        "trade_style": _current_trade_style(),
        "checked_at": now,
        "updated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "visible": False,
    }


def _render_hidden_crypto_instant_signal_fragment(username: str, symbol: str, tf_label: str, *, run_every: int = 15) -> None:
    def refresh_hidden_signal() -> None:
        try:
            active_df = engine.get_history(symbol, tf_label)
            if active_df is None or active_df.empty:
                active_df = pd.DataFrame()
            _update_hidden_crypto_instant_signal(
                username=username,
                symbol=symbol,
                tf_label=tf_label,
                df=active_df,
                snapshot=engine.get_market_snapshot(symbol) or {},
                orderbook=engine.get_orderbook(symbol, depth=10) or {},
                force=True,
            )
        except Exception as exc:
            APP_LOGGER.warning("Hidden crypto instant signal fragment failed: %s", exc)
            st.session_state.crypto_instant_signal_error = str(exc)
        st.markdown('<span style="display:none" data-finwise-hidden="crypto-instant"></span>', unsafe_allow_html=True)

    st.fragment(refresh_hidden_signal, run_every=max(10, int(run_every or 15)))()


def _render_native_responsive_market_chart(symbol: str, tf_label: str, df: pd.DataFrame, snapshot: dict = None):
    chart_df = df.tail(72).copy() if df is not None else pd.DataFrame()
    if chart_df.empty:
        st.info("Fetching live chart...")
        return

    chart_df["timestamp"] = pd.to_datetime(chart_df.get("timestamp"), errors="coerce")
    for column in ["open", "high", "low", "close", "volume"]:
        chart_df[column] = pd.to_numeric(chart_df.get(column), errors="coerce")
    chart_df = chart_df.dropna(subset=["open", "high", "low", "close", "volume"])
    if chart_df.empty:
        st.info("Fetching live chart...")
        return

    lows = chart_df["low"].astype(float)
    highs = chart_df["high"].astype(float)
    min_price = float(lows.min())
    max_price = float(highs.max())
    span = max(max_price - min_price, 1e-9)
    plot_top = 28.0
    plot_height = 300.0
    volume_top = 350.0
    volume_height = 54.0
    width = 1000.0
    count = max(len(chart_df), 1)
    step = width / max(count - 1, 1)
    candle_width = max(5.0, min(12.0, step * 0.52))
    max_volume = max(float(chart_df["volume"].max() or 0.0), 1.0)

    def y_for(value: float) -> float:
        return plot_top + ((max_price - float(value)) / span) * plot_height

    candle_markup = []
    close_points = []
    for index, row in enumerate(chart_df.itertuples(index=False)):
        x = index * step
        open_value = float(getattr(row, "open"))
        high_value = float(getattr(row, "high"))
        low_value = float(getattr(row, "low"))
        close_value = float(getattr(row, "close"))
        volume_value = float(getattr(row, "volume"))
        is_up = close_value >= open_value
        tone = "#20e7b5" if is_up else "#ff6075"
        wick_y1 = y_for(high_value)
        wick_y2 = y_for(low_value)
        body_y = min(y_for(open_value), y_for(close_value))
        body_h = max(abs(y_for(open_value) - y_for(close_value)), 3.0)
        volume_h = max(2.0, (volume_value / max_volume) * volume_height)
        close_points.append(f"{x:.1f},{y_for(close_value):.1f}")
        candle_markup.append(
            f'<line x1="{x:.1f}" y1="{wick_y1:.1f}" x2="{x:.1f}" y2="{wick_y2:.1f}" stroke="{tone}" stroke-width="2" opacity="0.84"/>'
            f'<rect x="{x - candle_width / 2:.1f}" y="{body_y:.1f}" width="{candle_width:.1f}" height="{body_h:.1f}" rx="2" fill="{tone}" opacity="0.92"/>'
            f'<rect x="{x - candle_width / 2:.1f}" y="{volume_top + volume_height - volume_h:.1f}" width="{candle_width:.1f}" height="{volume_h:.1f}" rx="2" fill="{tone}" opacity="0.22"/>'
        )

    last_close = float(chart_df["close"].iloc[-1])
    first_close = float(chart_df["close"].iloc[0])
    session_change = ((last_close - first_close) / first_close * 100) if first_close else 0.0
    session_tone = "#20e7b5" if session_change >= 0 else "#ff6075"
    snapshot = snapshot or engine.get_market_snapshot(symbol) or {}
    day_change = _coalesce_market_number(snapshot.get("price_24h_pcnt"))
    if day_change is not None:
        day_change *= 100

    st.markdown(
        f"""
        <style>
        .fw-native-chart-card {{
            width: 100%;
            max-width: 100%;
            min-width: 0;
            overflow: hidden;
            border-radius: 1rem;
            border: 1px solid rgba(255,255,255,0.07);
            background:
                radial-gradient(circle at 50% 24%, rgba(25,223,208,0.12), transparent 32%),
                linear-gradient(180deg, rgba(10,24,38,0.98), rgba(5,15,27,0.99));
            box-shadow: 0 18px 38px rgba(0,0,0,0.22);
        }}
        .fw-native-chart-head {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: .75rem;
            padding: .78rem .86rem .55rem;
        }}
        .fw-native-chart-title {{
            color: #f4fbff;
            font-size: .98rem;
            font-weight: 850;
            line-height: 1.1;
        }}
        .fw-native-chart-sub {{
            color: #8ba3bc;
            font-size: .7rem;
            margin-top: .22rem;
        }}
        .fw-native-chart-live {{
            display: inline-flex;
            align-items: center;
            gap: .34rem;
            color: #9bfff0;
            font-size: .68rem;
            font-weight: 800;
            padding: .32rem .54rem;
            border-radius: 999px;
            background: rgba(25,223,208,0.08);
            border: 1px solid rgba(25,223,208,0.16);
            white-space: nowrap;
        }}
        .fw-native-chart-live span {{
            width: .42rem;
            height: .42rem;
            border-radius: 999px;
            background: currentColor;
            box-shadow: 0 0 12px currentColor;
        }}
        .fw-native-chart-stats {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: .46rem;
            padding: 0 .86rem .7rem;
        }}
        .fw-native-chart-stat {{
            min-width: 0;
            padding: .58rem .62rem;
            border-radius: .78rem;
            background: rgba(255,255,255,0.035);
            border: 1px solid rgba(255,255,255,0.045);
        }}
        .fw-native-chart-stat span {{
            display: block;
            color: #7892ad;
            font-size: .6rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: .06em;
        }}
        .fw-native-chart-stat strong {{
            display: block;
            color: #f4fbff;
            font-size: .78rem;
            font-weight: 850;
            margin-top: .28rem;
            overflow-wrap: anywhere;
        }}
        .fw-native-chart-canvas {{
            width: 100%;
            height: auto;
            display: block;
            background: linear-gradient(180deg, rgba(6,18,31,0.28), rgba(6,18,31,0.68));
            border-top: 1px solid rgba(255,255,255,0.04);
        }}
        @media (max-width: 760px) {{
            .fw-native-chart-card {{
                border-radius: .95rem;
            }}
            .fw-native-chart-head {{
                padding: .72rem .74rem .46rem;
            }}
            .fw-native-chart-stats {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
                padding: 0 .74rem .64rem;
            }}
            .fw-native-chart-stat strong {{
                font-size: .74rem;
            }}
        }}
        </style>
        <section class="fw-native-chart-card" aria-label="{escape(symbol)} chart">
            <div class="fw-native-chart-head">
                <div>
                    <div class="fw-native-chart-title">{escape(symbol)} {'Spot FX' if is_forex_symbol(symbol) else 'Perpetual'}</div>
                    <div class="fw-native-chart-sub">{escape(tf_label)} live market view</div>
                </div>
                <div class="fw-native-chart-live"><span></span>Live</div>
            </div>
            <div class="fw-native-chart-stats">
                <div class="fw-native-chart-stat"><span>Last</span><strong>{_fmt_price(last_close)}</strong></div>
                <div class="fw-native-chart-stat"><span>Session</span><strong style="color:{session_tone};">{_fmt_pct(session_change)}</strong></div>
                <div class="fw-native-chart-stat"><span>24h</span><strong style="color:{'#20e7b5' if (day_change or 0) >= 0 else '#ff6075'};">{_fmt_pct(day_change)}</strong></div>
                <div class="fw-native-chart-stat"><span>Volume</span><strong>{_fmt_compact(snapshot.get('volume_24h') or chart_df['volume'].sum())}</strong></div>
            </div>
            <svg class="fw-native-chart-canvas" viewBox="0 0 1000 420" preserveAspectRatio="none" role="img" aria-label="{escape(symbol)} candle chart">
                <defs>
                    <linearGradient id="fwChartLine" x1="0" x2="1">
                        <stop offset="0%" stop-color="#24e7c8" stop-opacity="0.18"/>
                        <stop offset="100%" stop-color="#62d0ff" stop-opacity="0.72"/>
                    </linearGradient>
                </defs>
                <g opacity="0.18">
                    <line x1="0" y1="88" x2="1000" y2="88" stroke="#ffffff"/>
                    <line x1="0" y1="172" x2="1000" y2="172" stroke="#ffffff"/>
                    <line x1="0" y1="256" x2="1000" y2="256" stroke="#ffffff"/>
                    <line x1="0" y1="340" x2="1000" y2="340" stroke="#ffffff"/>
                </g>
                <polyline points="{' '.join(close_points)}" fill="none" stroke="url(#fwChartLine)" stroke-width="3" opacity="0.75"/>
                {''.join(candle_markup)}
            </svg>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_fast_market_panel_fragment(username: str, symbol: str, tf_label: str, df: pd.DataFrame = None, orderbook: dict = None):
    if df is None or orderbook is None:
        df, _, orderbook = _load_trading_desk_panel_data(symbol, tf_label)

    if not _engine_status.get("ok") and (df is None or df.empty):
        st.write("Fetching live feed...")
        return

    if df is None or df.empty:
        st.write("Fetching live feed...")
        return

    try:
        _update_hidden_crypto_instant_signal(
            username=username,
            symbol=symbol,
            tf_label=tf_label,
            df=df,
            snapshot=engine.get_market_snapshot(symbol) or {},
            orderbook=orderbook or {},
        )
    except Exception as exc:
        APP_LOGGER.warning("Hidden crypto instant signal update failed in fast panel: %s", exc)

    signal_result = st.session_state.get("last_signal") or {}
    signal_meta = st.session_state.get("last_signal_meta") or {}
    active_trade_style = _current_trade_style()
    has_matching_signal = bool(signal_result) and (
        not signal_meta
        or (
            signal_meta.get("symbol") == symbol
            and signal_meta.get("tf_label") == tf_label
            and str(signal_meta.get("trade_style", active_trade_style) or active_trade_style) == active_trade_style
        )
    )
    premium = is_premium(username)
    used = get_used(username)
    limit = get_limit(username)
    usage_label = f"{used}/{limit} used today" if limit else f"{used} used today"

    last_candle = _market_last_candle(df)
    close_series = _market_series(df, "close", limit=24)
    volume_series = _market_series(df, "volume", limit=24)
    regime_label = _describe_market_regime(df)
    trend_pct = None
    if len(close_series) >= 2 and close_series[0]:
        trend_pct = ((close_series[-1] - close_series[0]) / close_series[0]) * 100
    momentum_score = 50 if trend_pct is None else int(max(0, min(100, 50 + (trend_pct * 8.0))))
    session_move = None
    if last_candle.get("open") not in (None, 0):
        session_move = ((last_candle.get("close", 0) - last_candle.get("open", 0)) / last_candle.get("open", 1)) * 100

    avg_range_pct = 0.0
    if df is not None and not df.empty:
        working = df.tail(24).copy()
        highs = pd.to_numeric(working.get("high"), errors="coerce")
        lows = pd.to_numeric(working.get("low"), errors="coerce")
        closes = pd.to_numeric(working.get("close"), errors="coerce").replace(0, pd.NA)
        range_pct = (((highs - lows) / closes) * 100).dropna()
        if not range_pct.empty:
            avg_range_pct = float(range_pct.mean())

    volume_state = "Stable"
    if len(volume_series) >= 10:
        recent_volume = sum(volume_series[-5:]) / 5
        prior_volume = sum(volume_series[-10:-5]) / 5
        if prior_volume:
            volume_ratio = recent_volume / prior_volume
            if volume_ratio >= 1.10:
                volume_state = "Expanding"
            elif volume_ratio <= 0.90:
                volume_state = "Cooling"

    levels = {}
    if has_matching_signal:
        signal_label = signal_result.get("signal", "HOLD")
        display_label = signal_label if signal_label in {"BUY", "SELL"} else "NEUTRAL"
        confidence = int(signal_result.get("confidence", 0) or 0)
        reason = signal_result.get("reason", "Waiting for a clean setup.")
        levels = signal_result.get("entry_exit", {}) or {}
        support = levels.get("stop_loss") or last_candle.get("low")
        resistance = levels.get("take_profit") or last_candle.get("high")
        entry_value = levels.get("actual_entry") or levels.get("entry_price") or last_candle.get("close")
    else:
        display_label = "NEUTRAL"
        confidence = 62
        reason = "Wait for breakout confirmation."
        support = last_candle.get("low")
        resistance = last_candle.get("high")
        entry_value = last_candle.get("close")

    if display_label == "BUY":
        tone_color = "#19dfd0"
    elif display_label == "SELL":
        tone_color = "#ff6b7d"
    else:
        tone_color = "#5ce1d5"

    risk_reward = _coalesce_market_number(levels.get("risk_reward_ratio"))
    gauge_svg = _build_signal_gauge_svg(confidence, momentum_score, tone_color, regime_label, avg_range_pct)

    bid_rows = []
    ask_rows = []
    if isinstance(orderbook, dict):
        bid_rows = orderbook.get("bids", []) or []
        ask_rows = list(reversed(orderbook.get("asks", []) or []))

    best_bid = bid_rows[0]["price"] if bid_rows else None
    best_ask = ask_rows[-1]["price"] if ask_rows else None
    spread = (best_ask - best_bid) if best_bid is not None and best_ask is not None else None
    spread_pct = ((spread / best_ask) * 100) if spread is not None and best_ask else None
    bid_total = sum(item.get("size", 0) for item in bid_rows)
    ask_total = sum(item.get("size", 0) for item in ask_rows)
    book_total = bid_total + ask_total
    bid_share = (bid_total / book_total * 100) if book_total else 50.0
    ask_share = 100.0 - bid_share if book_total else 50.0
    imbalance = ((bid_total - ask_total) / book_total * 100) if book_total else 0.0
    max_depth = max([item.get("size", 0) for item in bid_rows + ask_rows], default=1.0) or 1.0
    mid_price = ((best_bid + best_ask) / 2) if best_bid is not None and best_ask is not None else None

    def _rail_book_rows(items, tone: str) -> str:
        if not items:
            return '<div class="desk-rail-empty">Waiting for live depth...</div>'
        row_markup = []
        for item in items[:6]:
            size = float(item.get("size", 0) or 0)
            width = max(8, min(100, int((size / max_depth) * 100))) if max_depth else 8
            row_markup.append(
                dedent(
                    f"""
                    <div class="desk-rail-book-row">
                        <div class="desk-rail-book-fill" style="width:{width}%; background:{tone};"></div>
                        <span class="desk-rail-book-price" style="color:{tone};">{_fmt_price(item.get("price"))}</span>
                        <span class="desk-rail-book-size">{size:,.4f}</span>
                    </div>
                    """
                ).strip()
            )
        return "".join(row_markup)

    context_cards = [
        ("Style", active_trade_style, "User-selected mode"),
        ("Regime", regime_label, "Current structure"),
        ("Trend", _fmt_pct(trend_pct), "24-bar move"),
        ("Session", _fmt_pct(session_move), "Current candle bias"),
        ("Volume", volume_state, "Participation"),
        ("Avg Range", f"{avg_range_pct:.2f}%" if avg_range_pct else "--", "Per candle"),
        ("Reward / Risk", f"{risk_reward:.2f}x" if risk_reward is not None else "--", "Trade quality"),
    ]
    context_html = "".join(
        dedent(
            f"""
            <div class="desk-rail-context-card">
                <div class="desk-rail-context-label">{escape(label)}</div>
                <div class="desk-rail-context-value">{escape(value)}</div>
                <div class="desk-rail-context-sub">{escape(subtitle)}</div>
            </div>
            """
        ).strip()
        for label, value, subtitle in context_cards
    )

    signal_rail_html = f"""
        <html>
        <head>
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <style>
            * {{ box-sizing: border-box; }}
            html, body {{
              margin: 0;
              padding: 0;
              background: transparent;
              font-family: "Segoe UI", Arial, sans-serif;
              color: #e8f4f8;
            }}
            @keyframes deskRailPulse {{
              0% {{ opacity: 0.48; transform: scale(0.98); }}
              50% {{ opacity: 0.9; transform: scale(1.02); }}
              100% {{ opacity: 0.48; transform: scale(0.98); }}
            }}
            @keyframes deskRailShift {{
              0% {{ transform: translate3d(-2%, -2%, 0); }}
              50% {{ transform: translate3d(2%, 1%, 0); }}
              100% {{ transform: translate3d(-1%, 2%, 0); }}
            }}
            .desk-rail-shell {{
              position: relative;
              overflow: hidden;
              width: 100%;
              min-height: 980px;
              padding: 18px;
              border-radius: 24px;
              border: 1px solid rgba(255,255,255,0.08);
              background:
                radial-gradient(circle at 14% 10%, rgba(43,233,209,0.18), transparent 24%),
                radial-gradient(circle at 88% 0%, rgba(74,127,255,0.14), transparent 28%),
                linear-gradient(180deg, rgba(8,19,31,0.99) 0%, rgba(5,13,24,1) 100%);
              box-shadow: 0 30px 72px rgba(0,0,0,0.28);
              isolation: isolate;
            }}
            .desk-rail-shell::before {{
              content: "";
              position: absolute;
              inset: -18%;
              background:
                radial-gradient(circle at top right, rgba(43,233,209,0.18), transparent 26%),
                radial-gradient(circle at bottom left, rgba(79,162,255,0.10), transparent 22%);
              filter: blur(28px);
              opacity: 0.95;
              animation: deskRailShift 10s ease-in-out infinite alternate;
              z-index: 0;
            }}
            .desk-rail-content {{
              position: relative;
              z-index: 1;
              display: grid;
              gap: 14px;
            }}
            .desk-rail-top {{
              display: flex;
              align-items: flex-start;
              justify-content: space-between;
              gap: 12px;
            }}
            .desk-rail-kicker {{
              color: #82f0e4;
              font-size: 10px;
              font-weight: 800;
              letter-spacing: 0.16em;
              text-transform: uppercase;
            }}
            .desk-rail-title {{
              color: white;
              font-size: 22px;
              font-weight: 820;
              letter-spacing: -0.04em;
              margin-top: 6px;
            }}
            .desk-rail-sub {{
              color: #89a8bc;
              font-size: 12px;
              margin-top: 6px;
              line-height: 1.6;
            }}
            .desk-rail-pills {{
              display: flex;
              flex-wrap: wrap;
              justify-content: flex-end;
              gap: 8px;
            }}
            .desk-rail-pill {{
              min-height: 32px;
              padding: 0 11px;
              border-radius: 999px;
              border: 1px solid rgba(255,255,255,0.08);
              background: rgba(10,24,38,0.84);
              display: inline-flex;
              align-items: center;
              gap: 8px;
              color: #d9edf6;
              font-size: 10px;
              font-weight: 760;
              white-space: nowrap;
            }}
            .desk-rail-pill-dot {{
              width: 8px;
              height: 8px;
              border-radius: 50%;
              background: {tone_color};
              box-shadow: 0 0 0 5px rgba(92,225,213,0.14);
              animation: deskRailPulse 1.7s ease-in-out infinite;
            }}
            .desk-rail-hero {{
              display: grid;
              grid-template-columns: 164px minmax(0, 1fr);
              gap: 14px;
              align-items: center;
              padding: 14px;
              border-radius: 20px;
              border: 1px solid rgba(255,255,255,0.06);
              background: linear-gradient(180deg, rgba(11,24,38,0.92) 0%, rgba(9,20,33,0.84) 100%);
            }}
            .desk-rail-gauge {{
              width: 164px;
              height: 164px;
              margin: 0 auto;
            }}
            .desk-rail-signal {{
              display: grid;
              gap: 10px;
            }}
            .desk-rail-signal-word {{
              color: {tone_color};
              font-size: 24px;
              font-weight: 860;
              letter-spacing: 0.14em;
              text-transform: uppercase;
            }}
            .desk-rail-signal-copy {{
              color: #d8e8f2;
              font-size: 13px;
              line-height: 1.7;
            }}
            .desk-rail-confidence {{
              display: grid;
              gap: 7px;
            }}
            .desk-rail-meter-head {{
              display: flex;
              align-items: center;
              justify-content: space-between;
              gap: 10px;
              color: #86a5ba;
              font-size: 11px;
            }}
            .desk-rail-meter-head strong {{
              color: #ffffff;
              font-size: 16px;
              font-weight: 800;
            }}
            .desk-rail-meter {{
              height: 10px;
              border-radius: 999px;
              overflow: hidden;
              background: rgba(255,255,255,0.06);
            }}
            .desk-rail-meter-fill {{
              width: {max(0, min(100, confidence))}%;
              height: 100%;
              border-radius: 999px;
              background: linear-gradient(90deg, {tone_color}, #62d0ff);
            }}
            .desk-rail-stat-grid {{
              display: grid;
              grid-template-columns: repeat(4, minmax(0, 1fr));
              gap: 10px;
            }}
            .desk-rail-stat {{
              padding: 12px 13px;
              border-radius: 16px;
              background: rgba(10,24,38,0.84);
              border: 1px solid rgba(255,255,255,0.05);
            }}
            .desk-rail-stat-label {{
              color: #6f90a6;
              font-size: 10px;
              font-weight: 760;
              letter-spacing: 0.1em;
              text-transform: uppercase;
            }}
            .desk-rail-stat-value {{
              margin-top: 7px;
              color: #ffffff;
              font-size: 16px;
              font-weight: 800;
            }}
            .desk-rail-book-card,
            .desk-rail-context-grid,
            .desk-rail-level-grid {{
              border-radius: 20px;
            }}
            .desk-rail-book-card {{
              padding: 14px;
              border: 1px solid rgba(255,255,255,0.06);
              background: linear-gradient(180deg, rgba(10,24,38,0.92) 0%, rgba(8,19,31,0.88) 100%);
            }}
            .desk-rail-book-head {{
              display: flex;
              align-items: center;
              justify-content: space-between;
              gap: 10px;
              margin-bottom: 12px;
            }}
            .desk-rail-book-title {{
              color: #ffffff;
              font-size: 16px;
              font-weight: 800;
            }}
            .desk-rail-book-sub {{
              color: #7f9ab0;
              font-size: 11px;
              margin-top: 4px;
            }}
            .desk-rail-book-hero {{
              text-align: right;
            }}
            .desk-rail-book-price {{
              font-family: Consolas, "Segoe UI", monospace;
              font-size: 15px;
              font-weight: 800;
            }}
            .desk-rail-book-price strong {{
              color: #ffffff;
              font-size: 22px;
            }}
            .desk-rail-book-meta {{
              color: #89a8bc;
              font-size: 11px;
              margin-top: 4px;
            }}
            .desk-rail-book-bar {{
              margin-top: 12px;
              display: grid;
              grid-template-columns: {bid_share:.2f}fr {ask_share:.2f}fr;
              height: 10px;
              border-radius: 999px;
              overflow: hidden;
            }}
            .desk-rail-book-bar div:first-child {{
              background: rgba(25,223,208,0.82);
            }}
            .desk-rail-book-bar div:last-child {{
              background: rgba(255,107,125,0.82);
            }}
            .desk-rail-book-grid {{
              margin-top: 14px;
              display: grid;
              grid-template-columns: repeat(2, minmax(0, 1fr));
              gap: 12px;
            }}
            .desk-rail-book-side {{
              display: grid;
              gap: 8px;
            }}
            .desk-rail-book-side-title {{
              display: flex;
              align-items: center;
              justify-content: space-between;
              font-size: 11px;
              font-weight: 760;
              text-transform: uppercase;
              letter-spacing: 0.08em;
            }}
            .desk-rail-book-row {{
              position: relative;
              display: grid;
              grid-template-columns: minmax(0, 1fr) auto;
              align-items: center;
              gap: 10px;
              padding: 8px 10px;
              border-radius: 12px;
              overflow: hidden;
              border: 1px solid rgba(255,255,255,0.04);
              background: rgba(12,27,42,0.68);
            }}
            .desk-rail-book-fill {{
              position: absolute;
              left: 0;
              top: 0;
              bottom: 0;
              opacity: 0.18;
            }}
            .desk-rail-book-price,
            .desk-rail-book-size {{
              position: relative;
              z-index: 1;
              font-family: Consolas, "Segoe UI", monospace;
              font-size: 12px;
              font-weight: 700;
            }}
            .desk-rail-book-size {{
              color: #dcecf5;
              text-align: right;
            }}
            .desk-rail-empty {{
              color: #68879c;
              font-size: 11px;
              padding: 12px 0;
            }}
            .desk-rail-context-grid {{
              display: grid;
              grid-template-columns: repeat(2, minmax(0, 1fr));
              gap: 10px;
            }}
            .desk-rail-context-card,
            .desk-rail-level-card {{
              padding: 12px 13px;
              border-radius: 16px;
              border: 1px solid rgba(255,255,255,0.05);
              background: rgba(10,24,38,0.82);
            }}
            .desk-rail-context-label,
            .desk-rail-level-label {{
              color: #6f90a6;
              font-size: 10px;
              font-weight: 760;
              letter-spacing: 0.1em;
              text-transform: uppercase;
            }}
            .desk-rail-context-value,
            .desk-rail-level-value {{
              margin-top: 7px;
              color: #ffffff;
              font-size: 15px;
              font-weight: 800;
            }}
            .desk-rail-context-sub {{
              color: #86a5ba;
              font-size: 11px;
              margin-top: 4px;
            }}
            .desk-rail-level-grid {{
              display: grid;
              grid-template-columns: repeat(3, minmax(0, 1fr));
              gap: 10px;
            }}
            .desk-rail-level-value.is-support {{ color: #19dfd0; }}
            .desk-rail-level-value.is-entry {{ color: #ffffff; }}
            .desk-rail-level-value.is-resistance {{ color: #ff6b7d; }}
            .desk-rail-foot {{
              color: #88a7bc;
              font-size: 11px;
              line-height: 1.6;
              text-align: center;
              padding-top: 2px;
            }}
          </style>
        </head>
        <body>
          <div class="desk-rail-shell">
            <div class="desk-rail-content">
              <div class="desk-rail-top">
                <div>
                  <div class="desk-rail-kicker">Execution Intelligence</div>
                  <div class="desk-rail-title">{escape(symbol)} signal rail</div>
                  <div class="desk-rail-sub">Live depth, conviction, and execution posture for the active {escape(tf_label)} market.</div>
                </div>
                <div class="desk-rail-pills">
                  <div class="desk-rail-pill"><span class="desk-rail-pill-dot"></span>{'Live feed online' if _engine_status.get('ok') else 'Feed warming'}</div>
                  <div class="desk-rail-pill">{escape(usage_label)}</div>
                </div>
              </div>

              <div class="desk-rail-hero">
                <div class="desk-rail-gauge">{gauge_svg}</div>
                <div class="desk-rail-signal">
                  <div class="desk-rail-signal-word">{escape(display_label)}</div>
                  <div class="desk-rail-signal-copy">{escape(reason)}</div>
                  <div class="desk-rail-confidence">
                    <div class="desk-rail-meter-head">
                      <span>Execution confidence</span>
                      <strong>{confidence}%</strong>
                    </div>
                    <div class="desk-rail-meter"><div class="desk-rail-meter-fill"></div></div>
                  </div>
                </div>
              </div>

              <div class="desk-rail-stat-grid">
                <div class="desk-rail-stat">
                  <div class="desk-rail-stat-label">Regime</div>
                  <div class="desk-rail-stat-value">{escape(regime_label)}</div>
                </div>
                <div class="desk-rail-stat">
                  <div class="desk-rail-stat-label">Trend</div>
                  <div class="desk-rail-stat-value">{_fmt_pct(trend_pct)}</div>
                </div>
                <div class="desk-rail-stat">
                  <div class="desk-rail-stat-label">Session</div>
                  <div class="desk-rail-stat-value">{_fmt_pct(session_move)}</div>
                </div>
                <div class="desk-rail-stat">
                  <div class="desk-rail-stat-label">Imbalance</div>
                  <div class="desk-rail-stat-value" style="color:{'#19dfd0' if imbalance >= 0 else '#ff6b7d'};">{imbalance:+.2f}%</div>
                </div>
              </div>

              <div class="desk-rail-book-card">
                <div class="desk-rail-book-head">
                  <div>
                    <div class="desk-rail-book-title">Order book pressure</div>
                    <div class="desk-rail-book-sub">Mid, spread, and ladder depth in one live rail.</div>
                  </div>
                  <div class="desk-rail-book-hero">
                    <div class="desk-rail-book-price"><strong>{_fmt_price(mid_price)}</strong></div>
                    <div class="desk-rail-book-meta">Spread {_fmt_pct(spread_pct)} | Bids {bid_share:.1f}%</div>
                  </div>
                </div>
                <div class="desk-rail-book-bar"><div></div><div></div></div>
                <div class="desk-rail-book-grid">
                  <div class="desk-rail-book-side">
                    <div class="desk-rail-book-side-title" style="color:#ff6b7d;"><span>Asks</span><span>{_fmt_compact(ask_total)}</span></div>
                    {_rail_book_rows(ask_rows, "#ff6b7d")}
                  </div>
                  <div class="desk-rail-book-side">
                    <div class="desk-rail-book-side-title" style="color:#19dfd0;"><span>Bids</span><span>{_fmt_compact(bid_total)}</span></div>
                    {_rail_book_rows(bid_rows, "#19dfd0")}
                  </div>
                </div>
              </div>

              <div class="desk-rail-context-grid">
                {context_html}
              </div>

              <div class="desk-rail-level-grid">
                <div class="desk-rail-level-card">
                  <div class="desk-rail-level-label">Support</div>
                  <div class="desk-rail-level-value is-support">{_fmt_price(support)}</div>
                </div>
                <div class="desk-rail-level-card">
                  <div class="desk-rail-level-label">Entry</div>
                  <div class="desk-rail-level-value is-entry">{_fmt_price(entry_value)}</div>
                </div>
                <div class="desk-rail-level-card">
                  <div class="desk-rail-level-label">Resistance</div>
                  <div class="desk-rail-level-value is-resistance">{_fmt_price(resistance)}</div>
                </div>
              </div>

              <div class="desk-rail-foot">The rail now owns the side column with live signal posture, depth flow, and execution levels in one surface.</div>
            </div>
          </div>
        </body>
        </html>
    """
    _render_component_html(signal_rail_html, height=1010)

    has_signal_history = df is not None and not df.empty and len(df) >= AI_SIGNAL_MIN_READY_CANDLES
    desk_button_label = "Refresh AI Signal" if has_matching_signal else "Get AI Signal"
    if st.button(
        desk_button_label,
        key=f"trade_desk_signal_btn_{symbol}_{tf_label}",
        disabled=((not premium and used >= limit) or not has_signal_history),
        use_container_width=True,
        type="primary",
    ):
        _trigger_ai_signal(username, symbol, tf_label, df)

    if not has_signal_history:
        missing_bars = max(0, AI_SIGNAL_MIN_READY_CANDLES - len(df))
        st.caption(f"AI signal analysis unlocks after {missing_bars} more candles sync for this timeframe.")
    if not premium and used >= limit:
        st.warning("Daily signal limit reached. Upgrade for more signals.")
    else:
        st.caption("Trade Desk now keeps the signal and routing context in one workflow.")
    # The focused result view renders the instant-entry card after navigation.


def _render_chart_panel_fragment(
    symbol: str,
    tf_label: str,
    df: pd.DataFrame = None,
    *,
    compact_layout: bool = False,
    allow_blocking_refresh: bool = True,
    allow_depth_refresh: bool = True,
):
    """
    Primary Trading Desk chart panel.

    The candle engine is the source of truth here, so this path stays
    fully inside Streamlit and does not depend on any external local API
    server being alive.
    """
    if df is None:
        if allow_blocking_refresh and not _engine_ready.is_set():
            _load_symbol_if_stale(symbol)
        df = engine.get_history(symbol, tf_label)
        if allow_blocking_refresh and (df is None or df.empty):
            try:
                _load_symbol_if_stale(symbol)
            except Exception:
                _engine_status["ok"] = False
                _engine_status["message"] = "Live market feed is temporarily unavailable."
            df = engine.get_history(symbol, tf_label)

    if not _engine_status.get("ok") and (df is None or df.empty):
        st.info("⏳ Fetching live chart...")
        return

    if df is None or df.empty:
        st.info("⏳ Fetching live chart...")
        return

    if allow_depth_refresh:
        try:
            df = engine.ensure_history_depth(symbol, tf_label, min_candles=CHART_INITIAL_FETCH_CANDLES)
        except Exception:
            pass

    if len(df) < CHART_MIN_READY_CANDLES:
        st.info(f"⏳ Loading chart history... {len(df)} candles so far.")
        return

    chart_height = 320 if compact_layout else 520

    # Primary path: render the exchange-style chart backed by the local
    # market API so the chart can update inside the iframe without relying
    # on Streamlit reruns.
    try:
        _render_exchange_terminal_chart(df, symbol, tf_label, height=chart_height, compact_layout=compact_layout)
    except Exception:
        try:
            _render_lightweight_terminal_chart(df, symbol, tf_label, height=chart_height, compact_layout=compact_layout)
        except Exception:
            try:
                snapshot = engine.get_market_snapshot(symbol)
                _render_pro_terminal_chart(df, symbol, tf_label, snapshot)
            except Exception as e3:
                st.error(f"Chart failed: {e3}")
                st.dataframe(df.tail(10))



def _dashboard_insights(metrics: dict, trade_df: pd.DataFrame, closed_df: pd.DataFrame) -> list:
    insights = []

    if closed_df.empty:
        return [
            "No closed trades yet. Start recording trades from Broker & Execution to unlock performance coaching.",
            "Your dashboard will begin ranking your best symbols and timeframes as soon as trade history builds up.",
            "Use the Trade Journal to close open trades so today and lifetime P&L stay accurate.",
        ]

    if metrics["win_rate"] >= 60:
        insights.append(f"Your current win rate is {metrics['win_rate']:.1f}%, which is a strong base to scale carefully.")
    else:
        insights.append(f"Your win rate is {metrics['win_rate']:.1f}%, so focus on tighter trade selection before adding more size.")

    by_symbol = closed_df.groupby("symbol", dropna=False)["pnl_usd"].sum().sort_values(ascending=False)
    if not by_symbol.empty:
        best_symbol = by_symbol.index[0]
        best_symbol_pnl = float(by_symbol.iloc[0])
        insights.append(f"Your best performing market so far is {best_symbol} with ${best_symbol_pnl:,.2f} net P&L.")
        if len(by_symbol) > 1:
            worst_symbol = by_symbol.index[-1]
            worst_symbol_pnl = float(by_symbol.iloc[-1])
            insights.append(f"Your weakest market is {worst_symbol} at ${worst_symbol_pnl:,.2f}. Review whether it fits your edge.")

    by_tf = closed_df.groupby("timeframe", dropna=False)["pnl_usd"].sum().sort_values(ascending=False)
    if not by_tf.empty:
        insights.append(f"Your strongest timeframe currently looks like {by_tf.index[0]}.")

    open_count = int(len(trade_df[trade_df["status"].isin(["open", "executed"])])) if not trade_df.empty else 0
    if open_count >= 3:
        insights.append(f"You have {open_count} open/executed trades being tracked. Watch exposure and avoid stacking correlated risk.")

    low_conf = closed_df[closed_df["confidence"] < 60]
    if len(low_conf) >= 3 and float(low_conf["pnl_usd"].sum()) < 0:
        insights.append("Low-confidence trades are dragging performance. Filter harder below 60% confidence.")

    return insights[:4]


def _classify_session(timestamp_value: str) -> str:
    stamp = str(timestamp_value or "")
    if len(stamp) < 13:
        return "Unknown"
    try:
        hour = int(stamp[11:13])
    except Exception:
        return "Unknown"
    if 0 <= hour < 8:
        return "Asia"
    if 8 <= hour < 13:
        return "London"
    if 13 <= hour < 21:
        return "New York"
    return "After Hours"


def _dashboard_broker_snapshot():
    broker = st.session_state.get("auto_trade_broker")
    profile = st.session_state.get("manual_broker_profile")
    deriv_status = st.session_state.get("deriv_connection_status") or {}
    deriv_connected = bool(deriv_status.get("ok"))

    if deriv_connected:
        deriv_login = str(deriv_status.get("loginid") or "Deriv").strip()
        deriv_currency = str(deriv_status.get("currency") or "USD").strip().upper()
        try:
            deriv_balance = float(deriv_status.get("balance") or 0.0)
        except Exception:
            deriv_balance = 0.0
        return {
            "broker_name": "Deriv",
            "broker_status": "Connected",
            "balance_text": f"{deriv_currency} {deriv_balance:,.2f}",
            "connection_method": f"OAuth Token | {deriv_login}",
            "sync_state": "Live",
            "logo_path": "",
        }

    broker_name = broker.name if broker is not None else (profile.get("broker_name") if profile else "Not connected")
    broker_status = "Connected" if broker is not None else "Profile synced" if profile else "No broker connected"
    connection_method = st.session_state.get("auto_trade_connection_method", "profile" if profile else "none")
    balance_snapshot = st.session_state.get("auto_trade_balance_snapshot")
    balance_text = "--"
    sync_state = "Waiting"
    logo_path = ""

    if broker_name and broker_name != "Not connected":
        try:
            logo_path = BrokerFactory.get_auth_config(broker_name).logo_path
        except Exception:
            logo_path = ""

    if broker is not None:
        if balance_snapshot is not None:
            balance_text = f"${float(balance_snapshot):,.2f}"
            sync_state = "Snapshot"
        else:
            balance_text = "Connected"
            sync_state = "Live"
    elif profile:
        balance_text = f"${float(profile.get('balance', 0)):,.2f}"
        sync_state = "Snapshot"

    return {
        "broker_name": broker_name,
        "broker_status": broker_status,
        "balance_text": balance_text,
        "connection_method": str(connection_method).replace("_", " ").title(),
        "sync_state": sync_state,
        "logo_path": logo_path,
    }


def _dashboard_coach_cards(insights: list[str]) -> str:
    cards = []
    for index, insight in enumerate(insights, start=1):
        cards.append(
            f'<div class="coach-note">'
            f'<div class="coach-note-index">{index:02d}</div>'
            f'<div class="coach-note-text">{escape(str(insight))}</div>'
            f'</div>'
        )
    return "".join(cards)


def _dashboard_recent_activity_feed(recent_df: pd.DataFrame) -> str:
    if recent_df.empty:
        return (
            '<div class="premium-empty-state">'
            '<div class="premium-empty-title">No activity tracked yet</div>'
            '<div class="premium-empty-copy">'
            'Your newest executions, journal updates, and broker-assisted trades will appear here.'
            '</div>'
            '</div>'
        )

    items = []
    for _, row in recent_df.head(5).iterrows():
        symbol = escape(str(row.get("symbol") or "Unknown"))
        side = escape(str(row.get("side") or "Tracked").title())
        timeframe = escape(str(row.get("timeframe") or "--"))
        source = escape(str(row.get("source") or "Manual"))
        status_raw = str(row.get("status") or "tracked").strip().lower()
        status = escape(status_raw.replace("_", " ").title())
        timestamp_value = str(row.get("opened_at") or row.get("closed_at") or row.get("created_at") or "").strip()
        timestamp_text = escape(timestamp_value[:16] if timestamp_value else "Awaiting timestamp")

        pnl_color = "#8ab4c8"
        pnl_text = "--"
        try:
            pnl_value = float(row.get("pnl_usd", 0) or 0)
            if not pd.isna(pnl_value):
                pnl_text = f"${pnl_value:,.2f}"
                if pnl_value > 0:
                    pnl_color = "#26a69a"
                elif pnl_value < 0:
                    pnl_color = "#ef5350"
        except Exception:
            pass

        status_background = "rgba(74,122,148,0.12)"
        status_border = "rgba(74,122,148,0.22)"
        status_color = "#8ab4c8"
        if status_raw in {"closed", "executed"}:
            status_background = "rgba(38,166,154,0.12)"
            status_border = "rgba(38,166,154,0.24)"
            status_color = "#26a69a"
        elif status_raw == "open":
            status_background = "rgba(0,245,212,0.12)"
            status_border = "rgba(0,245,212,0.22)"
            status_color = "#00f5d4"

        items.append(
            f'<div class="activity-item">'
            f'<div class="activity-top">'
            f'<div>'
            f'<div class="activity-symbol">{symbol}</div>'
            f'<div class="activity-meta">{side} &bull; {timeframe} &bull; {source}</div>'
            f'</div>'
            f'<div class="activity-pnl" style="color:{pnl_color};">{pnl_text}</div>'
            f'</div>'
            f'<div class="activity-foot">'
            f'<span class="activity-status" style="background:{status_background};border:1px solid {status_border};color:{status_color};">{status}</span>'
            f'<span class="activity-time">{timestamp_text}</span>'
            f'</div>'
            f'</div>'
        )

    return "".join(items)


def dashboard_page(username):
    return _render_dashboard_page_view(
        username,
        build_trade_metrics=build_trade_metrics,
        get_used=get_used,
        is_premium=is_premium,
        get_limit=get_limit,
        default_tracked_symbols=DEFAULT_TRACKED_SYMBOLS,
        engine=engine,
        ensure_symbol_loaded=_load_symbol_if_stale,
        fmt_price=_fmt_price,
        fmt_pct=_fmt_pct,
        dashboard_broker_snapshot=_dashboard_broker_snapshot,
        dashboard_coach_cards=_dashboard_coach_cards,
        dashboard_insights=_dashboard_insights,
        dashboard_recent_activity_feed=_dashboard_recent_activity_feed,
        classify_session=_classify_session,
    )


def mobile_dashboard_page(username):
    dashboard_logo_inner = (
        f'<img src="{APP_LOGO_DATA_URI}" alt="Finwise AI logo" />'
        if APP_LOGO_DATA_URI else
        "F"
    )
    return _render_mobile_dashboard_page_view(
        username,
        build_trade_metrics=build_trade_metrics,
        get_used=get_used,
        is_premium=is_premium,
        get_limit=get_limit,
        default_tracked_symbols=DEFAULT_TRACKED_SYMBOLS,
        engine=engine,
        ensure_symbol_loaded=_load_symbol_if_stale,
        fmt_price=_fmt_price,
        fmt_pct=_fmt_pct,
        dashboard_broker_snapshot=_dashboard_broker_snapshot,
        dashboard_logo_inner=dashboard_logo_inner,
    )



def dashboard_page_old():
    tracked_symbols = list(DEFAULT_TRACKED_SYMBOLS)
    for start in range(0, len(tracked_symbols), 3):
        row_symbols = tracked_symbols[start:start + 3]
        snapshot_cols = st.columns(len(row_symbols))
        for col, symbol in zip(snapshot_cols, row_symbols):
            snapshot = engine.get_market_snapshot(symbol)
            if snapshot.get("last_price") is None:
                _load_symbol_if_stale(symbol)
            snapshot = engine.get_market_snapshot(symbol)
            price = _fmt_price(snapshot.get("last_price"))
            change = snapshot.get("price_24h_pcnt")
            if change is not None:
                change *= 100
            color = "#26a69a" if (change or 0) >= 0 else "#ef5350"
            with col:
                st.markdown(
                    f"""
                    <div style="background:#0f2639;border:1px solid rgba(0,245,212,0.12);
                                border-radius:16px;padding:16px 18px;min-height:132px;">
                        <div style="display:flex;align-items:center;justify-content:space-between;">
                            <div style="color:white;font-size:16px;font-weight:700;">{symbol}</div>
                            <div style="color:#4a7a94;font-size:11px;">{'Spot FX' if is_forex_symbol(symbol) else 'Perpetual'}</div>
                        </div>
                        <div style="color:white;font-size:28px;font-weight:800;margin-top:16px;">{price}</div>
                        <div style="color:{color};font-size:13px;font-weight:700;margin-top:6px;">
                            {_fmt_pct(change)}
                        </div>
                        <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:16px;">
                            <div style="background:#0b1e2d;border-radius:10px;padding:8px 10px;">
                                <div style="color:#4a7a94;font-size:10px;">24h High</div>
                                <div style="color:#e8f4f8;font-size:13px;font-weight:700;">{_fmt_price(snapshot.get('high_24h'))}</div>
                            </div>
                            <div style="background:#0b1e2d;border-radius:10px;padding:8px 10px;">
                                <div style="color:#4a7a94;font-size:10px;">24h Low</div>
                                <div style="color:#e8f4f8;font-size:13px;font-weight:700;">{_fmt_price(snapshot.get('low_24h'))}</div>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

# -----------------------------------
# AI SIGNALS PAGE
# -----------------------------------
def _render_signal_card(result: dict, symbol: str, tf_label: str):
    sig    = result.get("signal", "HOLD")
    conf   = result.get("confidence", 0)
    reason = result.get("reason", "")
    trade_style_label = str(result.get("trade_style", TRADE_STYLE_LABELS.get(_current_trade_style(), "Day Trade")) or "Day Trade")

    ee            = result.get("entry_exit", {})
    entry         = ee.get("actual_entry") or ee.get("entry_price", 0)
    tp            = ee.get("take_profit",        0)
    sl            = ee.get("stop_loss",          0)
    rr            = ee.get("risk_reward_ratio",  0)
    is_profitable = ee.get("is_profitable_setup", False)

    ps         = result.get("position_size", {})
    size_pct   = ps.get("size_percent",     0)
    vol_reason = ps.get("reason",           "")
    vol_ratio  = ps.get("volatility_ratio", 1)

    regime   = result.get("regime", {})
    reg_name = regime.get("regime", "unknown")

    bs       = result.get("black_swan_risk", {})
    bs_level = bs.get("risk_level", 0)

    rob    = result.get("robustness", {})
    robust = rob.get("robust", True)

    is_buy        = sig == "BUY"
    is_sell       = sig == "SELL"
    sig_color     = "#26a69a" if is_buy else "#ef5350" if is_sell else "#ffc107"
    sig_bg        = "rgba(38,166,154,0.12)" if is_buy else "rgba(239,83,80,0.12)" if is_sell else "rgba(255,193,7,0.12)"
    arrow         = "↑" if is_buy else "↓" if is_sell else "—"
    bs_color      = "#ef5350" if bs_level > 50 else "#26a69a"
    robust_color  = "#26a69a" if robust else "#ef5350"
    robust_label  = "Yes" if robust else "No"
    rr_color      = "#26a69a" if rr >= 1.5 else "#ef5350"
    conf_bar_w    = max(0, min(100, int(conf)))

    warning_html = (
        ""
        if is_profitable else
        """<div style="margin-top:12px;padding:10px 14px;
                      background:rgba(239,83,80,0.10);
                      border-left:3px solid #ef5350;
                      border-radius:6px;
                      color:#ef5350;font-size:12px;line-height:1.5;">
            ⚠️ Setup does not meet minimum reward/risk threshold (1.5x). Trade with caution.
           </div>"""
    )

    signal_html = f"""
    <div style="
        background:#0f2639;
        border:1px solid rgba(0,245,212,0.18);
        border-radius:16px;
        padding:0;
        margin-top:16px;
        overflow:hidden;
        box-shadow:0 4px 24px rgba(0,0,0,0.3);
    ">
        <div style="padding:18px 20px 14px;
                    border-bottom:1px solid rgba(255,255,255,0.06);
                    display:flex;justify-content:space-between;align-items:center;">
            <div style="display:flex;align-items:center;gap:14px;">
                <div style="
                    width:44px;height:44px;border-radius:12px;
                    background:{sig_bg};
                    display:flex;align-items:center;justify-content:center;
                    font-size:22px;font-weight:900;color:{sig_color};
                    flex-shrink:0;">
                    {arrow}
                </div>
                <div>
                    <div style="color:white;font-size:18px;font-weight:700;
                                line-height:1.2;">{symbol}</div>
                    <div style="color:#8ab4c8;font-size:12px;margin-top:2px;
                                display:flex;align-items:center;gap:6px;">
                        🕐 Live
                        <span style="background:#1a3a52;border-radius:10px;
                                     padding:1px 8px;font-size:11px;
                                     color:#00f5d4;">{tf_label}</span>
                        <span style="background:#152a3e;border-radius:10px;
                                     padding:1px 8px;font-size:11px;
                                     color:#ffd166;">{trade_style_label}</span>
                    </div>
                </div>
            </div>
            <div style="text-align:right;">
                <div style="color:{sig_color};font-size:26px;font-weight:800;
                            letter-spacing:3px;line-height:1;">{sig}</div>
                <div style="display:flex;align-items:center;gap:4px;
                            justify-content:flex-end;margin-top:4px;">
                    <span style="color:#00f5d4;font-size:13px;font-weight:700;">{conf}%</span>
                    <span style="color:#8ab4c8;font-size:11px;">confidence</span>
                </div>
                <div style="margin-top:6px;height:4px;width:120px;
                            background:rgba(255,255,255,0.08);border-radius:2px;
                            margin-left:auto;">
                    <div style="height:4px;width:{conf_bar_w}%;
                                background:{sig_color};border-radius:2px;
                                transition:width 0.4s ease;"></div>
                </div>
            </div>
        </div>

        <div style="padding:16px 20px;
                    display:grid;grid-template-columns:repeat(4,1fr);gap:10px;">
            <div style="background:#0b1e2d;padding:12px;border-radius:10px;
                        border:1px solid rgba(255,255,255,0.05);">
                <div style="color:#8ab4c8;font-size:10px;font-weight:700;
                            text-transform:uppercase;letter-spacing:1px;">Entry</div>
                <div style="color:white;font-size:15px;font-weight:700;
                            font-family:monospace;margin-top:4px;">${entry:.4f}</div>
            </div>
            <div style="background:#0b1e2d;padding:12px;border-radius:10px;
                        border:1px solid rgba(255,255,255,0.05);">
                <div style="color:#8ab4c8;font-size:10px;font-weight:700;
                            text-transform:uppercase;letter-spacing:1px;">Target</div>
                <div style="color:#26a69a;font-size:15px;font-weight:700;
                            font-family:monospace;margin-top:4px;">${tp:.4f}</div>
            </div>
            <div style="background:#0b1e2d;padding:12px;border-radius:10px;
                        border:1px solid rgba(255,255,255,0.05);">
                <div style="color:#8ab4c8;font-size:10px;font-weight:700;
                            text-transform:uppercase;letter-spacing:1px;">Stop Loss</div>
                <div style="color:#ef5350;font-size:15px;font-weight:700;
                            font-family:monospace;margin-top:4px;">${sl:.4f}</div>
            </div>
            <div style="background:#0b1e2d;padding:12px;border-radius:10px;
                        border:1px solid rgba(255,255,255,0.05);">
                <div style="color:#8ab4c8;font-size:10px;font-weight:700;
                            text-transform:uppercase;letter-spacing:1px;">Reward/Risk</div>
                <div style="color:{rr_color};font-size:15px;font-weight:700;
                            font-family:monospace;margin-top:4px;">{rr:.2f}x</div>
            </div>
        </div>

        <div style="padding:0 20px 16px;display:flex;gap:8px;flex-wrap:wrap;">
            <span style="background:#1a3a52;border:1px solid rgba(0,245,212,0.15);
                         border-radius:20px;padding:5px 12px;
                         font-size:11px;color:#8ab4c8;display:inline-flex;
                         align-items:center;gap:5px;">
                Regime:&nbsp;<b style="color:#00f5d4;">{reg_name}</b>
            </span>
            <span style="background:#1a3a52;border:1px solid rgba(0,245,212,0.15);
                         border-radius:20px;padding:5px 12px;
                         font-size:11px;color:#8ab4c8;display:inline-flex;
                         align-items:center;gap:5px;">
                Size:&nbsp;<b style="color:#ffd166;">{size_pct:.1f}%</b>
                &nbsp;<span style="color:#4a7a94;">({vol_reason})</span>
            </span>
            <span style="background:#1a3a52;border:1px solid rgba(0,245,212,0.15);
                         border-radius:20px;padding:5px 12px;
                         font-size:11px;color:#8ab4c8;display:inline-flex;
                         align-items:center;gap:5px;">
                Vol:&nbsp;<b style="color:#a29bfe;">{vol_ratio}x</b>
            </span>
            <span style="background:#1a3a52;border:1px solid rgba(0,245,212,0.15);
                         border-radius:20px;padding:5px 12px;
                         font-size:11px;color:#8ab4c8;display:inline-flex;
                         align-items:center;gap:5px;">
                Risk:&nbsp;<b style="color:{bs_color};">{bs_level}/100</b>
            </span>
            <span style="background:#1a3a52;border:1px solid rgba(0,245,212,0.15);
                         border-radius:20px;padding:5px 12px;
                         font-size:11px;color:#8ab4c8;display:inline-flex;
                         align-items:center;gap:5px;">
                Robust:&nbsp;<b style="color:{robust_color};">{robust_label}</b>
            </span>
        </div>

        <div style="margin:0 20px 16px;padding:12px 14px;
                    background:#0b1e2d;border-radius:10px;
                    border:1px solid rgba(255,255,255,0.05);
                    color:#8ab4c8;font-size:13px;line-height:1.6;">
            {reason}
        </div>

        {warning_html}

        <div style="padding:10px 20px;
                    background:rgba(0,0,0,0.2);
                    border-top:1px solid rgba(255,255,255,0.04);
                    display:flex;align-items:center;gap:6px;">
            <span style="color:#4a7a94;font-size:11px;">
                Signals are for informational purposes only. Trade at your own risk.
            </span>
        </div>
    </div>
    """
    _render_component_html(signal_html, height=560)


def _has_connected_broker() -> bool:
    return bool(st.session_state.get("manual_broker_profile")) or (st.session_state.get("auto_trade_broker") is not None)


def _prime_signal_for_broker(result: dict, symbol: str, tf_label: str, username: str):
    profile = st.session_state.get("manual_broker_profile") or {}
    connected_broker = st.session_state.get("auto_trade_broker")
    broker_name = profile.get("broker_name") or (connected_broker.name if connected_broker is not None else "Broker")
    balance_basis = float(profile.get("balance", 1000.0))

    st.session_state.manual_trade_signal = result
    st.session_state.manual_trade_meta = {
        "symbol": symbol,
        "tf_label": tf_label,
        "balance": balance_basis,
        "broker_name": broker_name,
        "account_alias": profile.get("account_alias", username or "Trader"),
    }


def _open_broker_execution_workspace(status_message: str = ""):
    if status_message:
        st.session_state.auto_trade_status = status_message
    st.session_state.trading_desk_view = "Broker & Execution"
    st.query_params["mdeskmode"] = "Broker & Execution"
    st.session_state.open_broker_execution = True
    st.session_state.nav_choice = "Trading Desk"


def _sync_connected_broker_profile(username: str, broker):
    balance_value = 0.0
    try:
        balance_value, _ = _get_cached_broker_balance(broker, "USDT")
    except Exception:
        previous = st.session_state.get("manual_broker_profile") or {}
        balance_value = float(previous.get("balance", 0.0) or 0.0)

    profile = {
        "broker_name": broker.name,
        "account_alias": username or "Trader",
        "balance": balance_value,
    }
    st.session_state.manual_broker_profile = profile
    st.session_state.auto_trade_balance_snapshot = balance_value
    return profile


def _clear_connected_broker_profile():
    st.session_state.manual_broker_profile = None
    st.session_state.auto_trade_balance_snapshot = None
    st.session_state.broker_balance_cache = {}


def _broker_oauth_redirect_uri(broker_name: str = "") -> str:
    try:
        actual_port = st.get_option("server.port") or 8051
    except Exception:
        actual_port = 8051
    return resolve_broker_oauth_redirect_uri(default_port=int(actual_port), broker_name=broker_name)


def _queue_external_redirect(url: str):
    if url:
        st.session_state.pending_external_redirect = url


def _flush_external_redirect():
    redirect_url = str(st.session_state.pop("pending_external_redirect", "") or "").strip()
    if not redirect_url:
        return
    escaped_url = escape(redirect_url, quote=True)
    st.html(
        f"""
        <script>
        (function() {{
            const target = "{escaped_url}";
            try {{
                if (window.top) {{
                    window.top.location.href = target;
                }} else {{
                    window.location.href = target;
                }}
            }} catch (err) {{
                window.location.href = target;
            }}
        }})();
        </script>
        <div style="padding:12px 14px;border-radius:12px;background:rgba(0,245,212,0.10);
                    border:1px solid rgba(0,245,212,0.18);color:#dffaf7;font-size:13px;">
            Redirecting to broker approval...
        </div>
        """,
        width="stretch",
    )


def _launch_broker_oauth(username: str, broker_name: str, state_key: str, metadata: dict = None):
    try:
        state = BrokerFactory.generate_oauth_state(broker_name)
        redirect_uri = _broker_oauth_redirect_uri(broker_name)
        auth_url = BrokerFactory.build_oauth_authorization_url(broker_name, redirect_uri, state)
        from backend.auth.broker_oauth import save_broker_oauth_state

        save_broker_oauth_state(
            username=username,
            broker_name=broker_name,
            state=state,
            redirect_uri=redirect_uri,
            metadata=metadata or {},
        )
        st.session_state[state_key] = auth_url
        st.session_state.auto_trade_status = f"{broker_name.title()} authorization is ready. Continue to the broker approval screen."
        _queue_external_redirect(auth_url)
    except Exception as exc:
        st.session_state.auto_trade_status = f"Broker OAuth setup failed: {exc}"


def _complete_pending_broker_oauth(username: str):
    if not st.session_state.get("broker_oauth_returned"):
        return

    code = st.session_state.get("broker_oauth_code", "")
    state = st.session_state.get("broker_oauth_state", "")
    st.session_state.broker_oauth_returned = False
    st.session_state.broker_oauth_code = ""
    st.session_state.broker_oauth_state = ""

    if not code or not state:
        return

    pending = consume_broker_oauth_state(state)
    if not pending:
        st.session_state.auto_trade_status = "Broker OAuth state expired or was not found."
        return
    if pending.get("username") and pending["username"] != username:
        st.session_state.auto_trade_status = "Broker OAuth returned for a different user session."
        return

    try:
        connection_data = BrokerFactory.exchange_oauth_code_for_connection(
            pending["broker_name"],
            code,
            pending["redirect_uri"],
        )
        broker = BrokerFactory.create_broker_from_connection_data(
            pending["broker_name"],
            connection_data,
        )
        if broker is None:
            st.session_state.auto_trade_status = f"{pending['broker_name'].title()} OAuth completed, but broker session creation failed."
            return

        save_broker_connection(
            username=username,
            broker_name=pending["broker_name"],
            auth_method="oauth",
            access_token=connection_data.get("access_token", ""),
            refresh_token=connection_data.get("refresh_token", ""),
            token_expires_at=connection_data.get("token_expires_at"),
            api_key=connection_data.get("api_key", ""),
            api_secret=connection_data.get("api_secret", ""),
            metadata=connection_data.get("metadata", {}),
        )
        st.session_state.auto_trade_broker = broker
        st.session_state.auto_trade_bot = TradingBot(broker)
        st.session_state.auto_trade_connection_method = "oauth"
        _sync_connected_broker_profile(username, broker)
        _open_broker_execution_workspace(f"{broker.name} connected successfully with OAuth.")
        metadata = pending.get("metadata", {})
        if metadata.get("origin") == "signal_result":
            last_signal = st.session_state.get("last_signal")
            if last_signal:
                _prime_signal_for_broker(
                    last_signal,
                    metadata.get("symbol", st.session_state.get("selected_symbol", "BTCUSDT")),
                    metadata.get("tf_label", "1m"),
                    username,
                )
    except Exception as exc:
        st.session_state.auto_trade_status = f"Broker OAuth failed: {exc}"


def _restore_saved_broker_session(username: str):
    if not username:
        return
    restore_state = st.session_state.get("broker_restore_state", {})
    cache_key = str(username or "").casefold()
    last_check = float((restore_state.get(cache_key) or {}).get("checked_at", 0.0) or 0.0)
    now = time.time()

    if st.session_state.get("auto_trade_broker") is not None:
        restore_state[cache_key] = {"checked_at": now, "status": "connected"}
        st.session_state.broker_restore_state = restore_state
        return
    if last_check and (now - last_check) < BROKER_RESTORE_COOLDOWN_SECONDS:
        return

    def _remember(status: str):
        restore_state[cache_key] = {"checked_at": now, "status": status}
        st.session_state.broker_restore_state = restore_state

    saved = get_active_broker_connection(username)
    if not saved:
        _remember("none")
        return
    if not BrokerFactory.connection_data_is_bootable(saved.get("broker_name", ""), saved):
        metadata = saved.get("metadata", {}) or {}
        if metadata.get("reconnect_required"):
            st.session_state.auto_trade_status = (
                f"{saved.get('broker_name', 'Broker').title()} requires a fresh reconnect because secret persistence is disabled."
            )
        _remember("reconnect_required")
        return

    try:
        broker = BrokerFactory.create_broker_from_connection_data(saved["broker_name"], saved)
        if broker is None:
            _remember("unavailable")
            return
        st.session_state.auto_trade_broker = broker
        st.session_state.auto_trade_bot = TradingBot(broker)
        st.session_state.auto_trade_connection_method = saved.get("auth_method", "oauth")
        _sync_connected_broker_profile(username, broker)
        _remember("restored")
    except Exception:
        _remember("failed")


def _render_broker_logo_picker(prefix: str, broker_catalog: list) -> str:
    catalog = list(broker_catalog or [])
    if not catalog:
        st.info("No broker connections are available right now.")
        return ""

    st.markdown(
        """
        <style>
        .broker-picker-card {
            background: linear-gradient(180deg, rgba(16,37,56,0.98) 0%, rgba(11,30,45,0.98) 100%);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 22px;
            padding: 18px 16px 14px;
            min-height: 188px;
            box-shadow: 0 12px 28px rgba(0,0,0,0.24);
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-bottom: 10px;
        }
        .broker-picker-card.selected {
            border-color: rgba(0,245,212,0.42);
            box-shadow: 0 18px 40px rgba(0,245,212,0.10);
        }
        .broker-picker-head {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
        }
        .broker-picker-mark {
            width: 54px;
            height: 54px;
            border-radius: 16px;
            background: rgba(0,245,212,0.10);
            border: 1px solid rgba(0,245,212,0.18);
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            flex: 0 0 auto;
        }
        .broker-picker-mark img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: block;
        }
        .broker-picker-mark span {
            color: #00f5d4;
            font-size: 18px;
            font-weight: 800;
        }
        .broker-picker-status {
            padding: 5px 10px;
            border-radius: 999px;
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            white-space: nowrap;
        }
        .broker-picker-status.live {
            background: rgba(0,245,212,0.12);
            border: 1px solid rgba(0,245,212,0.18);
            color: #00f5d4;
        }
        .broker-picker-status.pending {
            background: rgba(255,209,102,0.12);
            border: 1px solid rgba(255,209,102,0.18);
            color: #ffd166;
        }
        .broker-picker-status.setup {
            background: rgba(102,196,255,0.12);
            border: 1px solid rgba(102,196,255,0.18);
            color: #8fd8ff;
        }
        .broker-picker-status.planned {
            background: rgba(143,163,181,0.12);
            border: 1px solid rgba(143,163,181,0.18);
            color: #aabccd;
        }
        .broker-picker-name {
            color: white;
            font-size: 18px;
            font-weight: 800;
        }
        .broker-picker-copy {
            color: #8ab4c8;
            font-size: 12px;
            line-height: 1.6;
            min-height: 38px;
        }
        .broker-picker-badges {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }
        .broker-picker-badge {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 999px;
            padding: 3px 8px;
            color: #d8eef5;
            font-size: 10px;
            font-weight: 700;
        }
        .broker-picker-badge.oauth {
            color: #00f5d4;
            border-color: rgba(0,245,212,0.18);
        }
        .broker-picker-badge.api {
            color: #ffd166;
            border-color: rgba(255,209,102,0.18);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("##### Broker Connections")
    st.caption("Finwise now shows the real broker catalog: live adapters first, then OAuth-capable exchanges that still need app-owner setup or exchange approval.")

    cols = st.columns(min(2, max(1, len(catalog))))
    selected = st.session_state.get(f"{prefix}_selected_broker", "")
    connected_profile = st.session_state.get("manual_broker_profile") or {}
    connected_broker = st.session_state.get("auto_trade_broker")
    connected_name = ""
    if connected_broker is not None:
        connected_name = BrokerFactory.get_auth_config(getattr(connected_broker, "name", "")).broker_name
    elif connected_profile.get("broker_name"):
        connected_name = BrokerFactory.get_auth_config(connected_profile.get("broker_name", "")).broker_name
    for idx, broker in enumerate(catalog):
        with cols[idx % len(cols)]:
            connectable = bool(broker.get("connectable", broker.get("oauth_supported") or broker.get("api_key_supported")))
            is_selected = selected == broker["broker_name"]
            is_connected = bool(connected_name and connected_name == broker["broker_name"])
            badges = []
            if broker.get("oauth_supported"):
                badges.append('<span class="broker-picker-badge oauth">OAuth</span>')
            if broker.get("api_key_supported"):
                badges.append('<span class="broker-picker-badge api">API Key</span>')
            if not badges:
                badges.append('<span class="broker-picker-badge">Planned</span>')
            status_tone = escape(str(broker.get("status_tone", "live")))
            status_label = escape(str(broker.get("status_label", "Live Now")))
            description = escape(str(broker.get("description", "Secure broker connection.")))
            logo_html = (
                f'<img src="{escape(broker["logo_path"])}" alt="{escape(broker["display_name"])}" loading="lazy" />'
                if broker.get("logo_path")
                else f'<span>{escape((broker["display_name"] or "B")[:2].upper())}</span>'
            )
            st.markdown(
                f"""
                <div class="broker-picker-card{' selected' if is_selected else ''}">
                    <div class="broker-picker-head">
                        <div class="broker-picker-mark">{logo_html}</div>
                        <div class="broker-picker-status {status_tone}">{status_label}</div>
                    </div>
                    <div class="broker-picker-name">{escape(broker['display_name'])}</div>
                    <div class="broker-picker-copy">{description}</div>
                    <div class="broker-picker-badges">{''.join(badges)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if is_connected:
                button_label = "Open Broker"
            elif is_selected and connectable:
                button_label = "Selected"
            elif connectable:
                button_label = "Use Broker"
            else:
                button_label = status_label
            if st.button(
                button_label,
                key=f"{prefix}_broker_{broker['broker_name']}",
                use_container_width=True,
                disabled=not connectable,
                type="primary" if is_selected and connectable else "secondary",
            ):
                st.session_state[f"{prefix}_selected_broker"] = broker["broker_name"]
                if is_connected:
                    _open_broker_execution_workspace(f"{broker['display_name']} is already connected. Opening Broker & Execution.")
                st.rerun()
    if selected:
        chosen = next((item for item in catalog if item["broker_name"] == selected), None)
        if chosen:
            st.success(f"Selected broker: {chosen['display_name']}")
            if not chosen.get("connectable", True):
                st.info(f"{chosen['display_name']} is visible in the catalog, but live connection is not enabled yet in this build.")
    return selected


@st.dialog("Connect Broker", width="large")
def _render_signal_result_connect_broker(username: str, result: dict, symbol: str, tf_label: str):
    if "auto_trade_broker" not in st.session_state:
        st.session_state.auto_trade_broker = None
    if "auto_trade_bot" not in st.session_state:
        st.session_state.auto_trade_bot = None
    if "auto_trade_status" not in st.session_state:
        st.session_state.auto_trade_status = ""

    st.caption("Connect your broker to continue with this signal.")

    close_col_left, close_col = st.columns([1.0, 0.18])
    with close_col_left:
        st.write("")
    with close_col:
        st.write("")
        if st.button("Close", use_container_width=True, key="close_signal_result_connect"):
            st.session_state.signal_result_connect_broker = False
            st.rerun()

    broker_catalog = BrokerFactory.get_broker_catalog()
    if not broker_catalog:
        st.info("No supported broker is available right now.")
        return

    broker_name = _render_broker_logo_picker("signal_result_dialog", broker_catalog)
    if not broker_name:
        return
    catalog_map = {item["broker_name"]: item for item in broker_catalog}
    broker_config = catalog_map[broker_name]
    st.markdown(f"##### {escape(broker_config['display_name'])} Connection")
    st.caption(broker_config.get("description", "Choose your broker and continue with the secure connection flow."))
    if not broker_config.get("connectable", True):
        st.info(
            f"{broker_config['display_name']} is a real broker entry, but this connection still needs the remaining app-side setup before users can finish it here."
        )
        return

    oauth_request = BrokerFactory.get_oauth_connection_request(broker_name)
    if oauth_request.get("ready"):
        oauth_link_key = f"signal_result_oauth_link_{broker_name}"
        if st.button("Connect with Broker", use_container_width=True, key="signal_result_connect_oauth"):
            _launch_broker_oauth(
                username=username,
                broker_name=broker_name,
                state_key=oauth_link_key,
                metadata={"origin": "signal_result", "symbol": symbol, "tf_label": tf_label},
            )
            st.rerun()
        oauth_link = st.session_state.get(oauth_link_key)
        if oauth_link:
            st.link_button(
                f"Continue with {broker_config['display_name']}",
                oauth_link,
                use_container_width=True,
            )
    else:
        if oauth_request.get("message"):
            oauth_message = oauth_request["message"]
            if oauth_request.get("reason") == "oauth_not_configured":
                oauth_message += (
                    f" This is app-side setup, so being logged into {broker_config['display_name']} on the web "
                    "will not turn OAuth on by itself."
                )
            st.warning(f"OAuth unavailable: {oauth_message}")

    if broker_config["api_key_supported"] and not oauth_request.get("ready"):
        st.caption("Secure instant connection is unavailable right now. Use your broker credentials to continue.")
        api_key = st.text_input("API Key", type="password", key="signal_result_api_key")
        api_secret = st.text_input("API Secret", type="password", key="signal_result_api_secret")

        if st.button("Connect with Broker", use_container_width=True, key="signal_result_connect_api"):
            if not api_key or not api_secret:
                st.error("Enter both API key and API secret to connect your broker.")
                return

            broker = BrokerFactory.connect_broker_with_api(broker_name, api_key, api_secret)
            if broker is None:
                last_error = BrokerFactory.get_last_connection_error() or "Check your credentials and try again."
                APP_LOGGER.warning("Broker API connection failed: %s", last_error)
                st.error("Could not connect the selected broker right now. Check your credentials and try again.")
                return

            st.session_state.auto_trade_broker = broker
            st.session_state.auto_trade_bot = TradingBot(broker)
            st.session_state.auto_trade_connection_method = "api_key"
            _sync_connected_broker_profile(username, broker)
            save_broker_connection(
                username=username,
                broker_name=broker_name,
                auth_method="api_key",
                api_key=api_key,
                api_secret=api_secret,
                metadata={"origin": "signal_result_fallback"},
            )
            _prime_signal_for_broker(result, symbol, tf_label, username)
            st.session_state.signal_result_connect_broker = False
            _open_broker_execution_workspace(f"{broker.name} connected. Signal sent to Broker & Execution.")
            st.rerun()


def log_trade_entry(
    username: str,
    broker_name: str,
    account_alias: str,
    source: str,
    status: str,
    symbol: str,
    timeframe: str,
    side: str,
    confidence: float = 0.0,
    quantity: float = 0.0,
    notional_usd: float = 0.0,
    entry_price: float = 0.0,
    stop_loss: float = 0.0,
    take_profit: float = 0.0,
    fee_paid: float = 0.0,
    regime: str = "",
    setup_quality: str = "",
    risk_reward_ratio: float = 0.0,
    notes: str = "",
    opened_at: str = None,
):
    opened_at = opened_at or datetime.utcnow().isoformat()
    cursor.execute(
        """
        INSERT INTO trade_history (
            username, broker_name, account_alias, source, status, symbol, timeframe, side,
            confidence, quantity, notional_usd, entry_price, stop_loss, take_profit, fee_paid,
            regime, setup_quality, risk_reward_ratio, notes, opened_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            username,
            broker_name,
            account_alias,
            source,
            status,
            symbol,
            timeframe,
            side,
            float(confidence or 0),
            float(quantity or 0),
            float(notional_usd or 0),
            float(entry_price or 0),
            float(stop_loss or 0),
            float(take_profit or 0),
            float(fee_paid or 0),
            regime,
            setup_quality,
            float(risk_reward_ratio or 0),
            notes,
            opened_at,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def close_trade_entry(trade_id: int, exit_price: float, fee_paid: float = 0.0, notes: str = ""):
    cursor.execute(
        """
        SELECT id, side, quantity, entry_price, fee_paid, notes
        FROM trade_history
        WHERE id=? AND status IN ('open', 'executed')
        """,
        (trade_id,),
    )
    row = cursor.fetchone()
    if not row:
        return False

    side = row[1]
    quantity = float(row[2] or 0)
    entry_price = float(row[3] or 0)
    existing_fee = float(row[4] or 0)
    total_fee = existing_fee + float(fee_paid or 0)

    if side == "BUY":
        pnl_usd = ((float(exit_price) - entry_price) * quantity) - total_fee
    else:
        pnl_usd = ((entry_price - float(exit_price)) * quantity) - total_fee

    pnl_pct = ((pnl_usd / max((entry_price * quantity), 1e-9)) * 100) if quantity > 0 and entry_price > 0 else 0.0
    merged_notes = (row[5] or "").strip()
    if notes:
        merged_notes = f"{merged_notes} | {notes}".strip(" |")

    cursor.execute(
        """
        UPDATE trade_history
        SET status='closed', exit_price=?, fee_paid=?, pnl_usd=?, pnl_pct=?, closed_at=?, notes=?
        WHERE id=?
        """,
        (
            float(exit_price),
            total_fee,
            round(pnl_usd, 4),
            round(pnl_pct, 4),
            datetime.utcnow().isoformat(),
            merged_notes,
            trade_id,
        ),
    )
    conn.commit()
    return True


def get_trade_rows(username: str, status: str = None):
    if status:
        cursor.execute(
            """
            SELECT id, broker_name, account_alias, source, status, symbol, timeframe, side, confidence,
                   quantity, notional_usd, entry_price, exit_price, stop_loss, take_profit, fee_paid,
                   pnl_usd, pnl_pct, regime, setup_quality, risk_reward_ratio, notes, opened_at, closed_at, created_at
            FROM trade_history
            WHERE username=? AND status=?
            ORDER BY COALESCE(closed_at, opened_at, created_at) DESC
            """,
            (username, status),
        )
    else:
        cursor.execute(
            """
            SELECT id, broker_name, account_alias, source, status, symbol, timeframe, side, confidence,
                   quantity, notional_usd, entry_price, exit_price, stop_loss, take_profit, fee_paid,
                   pnl_usd, pnl_pct, regime, setup_quality, risk_reward_ratio, notes, opened_at, closed_at, created_at
            FROM trade_history
            WHERE username=?
            ORDER BY COALESCE(closed_at, opened_at, created_at) DESC
            """,
            (username,),
        )
    columns = [
        "id", "broker_name", "account_alias", "source", "status", "symbol", "timeframe", "side", "confidence",
        "quantity", "notional_usd", "entry_price", "exit_price", "stop_loss", "take_profit", "fee_paid",
        "pnl_usd", "pnl_pct", "regime", "setup_quality", "risk_reward_ratio", "notes", "opened_at", "closed_at", "created_at",
    ]
    rows = cursor.fetchall()
    return pd.DataFrame(rows, columns=columns)


def build_trade_metrics(username: str):
    df = get_trade_rows(username)
    if df.empty:
        return {
            "today_trades": 0,
            "today_net": 0.0,
            "today_profit": 0.0,
            "today_loss": 0.0,
            "lifetime_trades": 0,
            "lifetime_net": 0.0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
        }, df, df

    closed_df = df[df["status"] == "closed"].copy()
    today = str(date.today())
    if not closed_df.empty:
        closed_df["closed_day"] = closed_df["closed_at"].fillna("").astype(str).str.slice(0, 10)
    today_df = closed_df[closed_df["closed_day"] == today].copy() if not closed_df.empty else closed_df
    wins = closed_df[closed_df["pnl_usd"] > 0]
    losses = closed_df[closed_df["pnl_usd"] < 0]

    metrics = {
        "today_trades": int(len(today_df)),
        "today_net": float(today_df["pnl_usd"].sum()) if not today_df.empty else 0.0,
        "today_profit": float(today_df[today_df["pnl_usd"] > 0]["pnl_usd"].sum()) if not today_df.empty else 0.0,
        "today_loss": float(today_df[today_df["pnl_usd"] < 0]["pnl_usd"].sum()) if not today_df.empty else 0.0,
        "lifetime_trades": int(len(closed_df)),
        "lifetime_net": float(closed_df["pnl_usd"].sum()) if not closed_df.empty else 0.0,
        "win_rate": float((len(wins) / len(closed_df)) * 100) if len(closed_df) else 0.0,
        "avg_win": float(wins["pnl_usd"].mean()) if not wins.empty else 0.0,
        "avg_loss": float(losses["pnl_usd"].mean()) if not losses.empty else 0.0,
    }
    return metrics, df, closed_df


def _render_signal_result_refresh_controls(username: str, symbol: str, tf_label: str, trade_style: str, *, mobile: bool = False) -> None:
    if is_forex_symbol(symbol):
        return

    meta = st.session_state.get("last_signal_meta") or {}
    current_key = f"{str(symbol or '').upper()}|{str(tf_label or '')}|{normalize_trade_style(trade_style or _current_trade_style())}"
    stored_key = (
        f"{str(meta.get('symbol') or '').upper()}|"
        f"{str(meta.get('tf_label') or '')}|"
        f"{normalize_trade_style(str(meta.get('trade_style') or trade_style or _current_trade_style()))}"
    )
    if current_key != stored_key:
        return

    refresh_options = [0, 15, 30, 60, 120, 300]
    refresh_state_key = "crypto_signal_result_auto_refresh_seconds"
    default_refresh = int(st.session_state.get(refresh_state_key) or 30)
    if default_refresh not in refresh_options:
        default_refresh = 30
        st.session_state[refresh_state_key] = default_refresh

    control_cols = st.columns([0.42, 0.34, 1.0] if not mobile else [0.58, 0.42], gap="small")
    with control_cols[0]:
        interval_seconds = st.selectbox(
            "Auto Refresh",
            refresh_options,
            index=refresh_options.index(default_refresh),
            key=refresh_state_key,
            format_func=lambda value: "Off" if int(value) <= 0 else f"{int(value)}s",
        )
    with control_cols[1]:
        st.write("")
        manual_refresh = st.button(
            "Refresh Now",
            key="crypto_signal_result_refresh_now",
            use_container_width=True,
            type="secondary",
        )
    if not mobile:
        with control_cols[2]:
            updated_at = str(meta.get("updated_at") or "pending")
            st.caption(f"Crypto signal auto refresh follows this result page. Last update: {updated_at}.")

    if mobile:
        updated_at = str(meta.get("updated_at") or "pending")
        st.caption(f"Last update: {updated_at}.")

    if manual_refresh:
        with st.spinner("Refreshing crypto signal..."):
            ok, message = _refresh_signal_result_crypto_signal(
                username,
                symbol,
                tf_label,
                trade_style,
                trigger="manual_refresh",
            )
        if not ok:
            st.warning(message)
        st.rerun()

    if int(interval_seconds or 0) <= 0:
        return

    last_checked_at = float(meta.get("checked_at") or 0)
    if last_checked_at > 0:
        next_refresh_in = max(0, int(interval_seconds) - int(time.time() - last_checked_at))
        st.caption(f"Auto refresh is live: next check in about {next_refresh_in}s.")

    def auto_refresh_signal_result() -> None:
        st.markdown('<span style="display:none" data-finwise-hidden="crypto-result-refresh-heartbeat"></span>', unsafe_allow_html=True)
        active_meta = st.session_state.get("last_signal_meta") or {}
        active_key = (
            f"{str(active_meta.get('symbol') or '').upper()}|"
            f"{str(active_meta.get('tf_label') or '')}|"
            f"{normalize_trade_style(str(active_meta.get('trade_style') or trade_style or _current_trade_style()))}"
        )
        if active_key != current_key:
            return

        last_checked_at = float(active_meta.get("checked_at") or 0)
        interval = int(st.session_state.get(refresh_state_key) or interval_seconds or 30)
        if interval <= 0 or (time.time() - last_checked_at) < interval:
            return

        ok, message = _refresh_signal_result_crypto_signal(
            username,
            symbol,
            tf_label,
            trade_style,
            trigger="auto_refresh",
        )
        if not ok and message:
            st.warning(message)
        if ok:
            st.rerun(scope="app")

    st.fragment(auto_refresh_signal_result, run_every=max(10, int(interval_seconds or 30)))()


def signal_result_page(*, mobile: bool = False):
    result = st.session_state.get("last_signal")
    meta = st.session_state.get("last_signal_meta", {})
    symbol = meta.get("symbol", "BTCUSDT")
    tf_label = meta.get("tf_label", "1m")
    trade_style = str(meta.get("trade_style") or _current_trade_style())
    username = st.session_state.get("username", "")
    if mobile:
        action_col, back_col = st.columns(2, gap="small")
        with action_col:
            if st.button("Auto Trade", key="mobile_signal_result_auto_trade", use_container_width=True):
                if _has_connected_broker():
                    _prime_signal_for_broker(result, symbol, tf_label, username)
                    _open_broker_execution_workspace("Signal moved to Broker & Execution workspace.")
                    st.rerun()
                st.session_state.signal_result_connect_broker = True
                st.rerun()
        with back_col:
            if st.button("Back To Desk", key="mobile_signal_result_back", use_container_width=True):
                _open_trading_desk_signal_workspace(symbol, tf_label, trade_style=trade_style, mobile_layout=True)
    else:
        top_left, action_col, back_col = st.columns([1.0, 0.24, 0.20])
        with top_left:
            st.markdown(
                f"""
                <div class="top-bar" style="margin-bottom:18px;">
                    <div>
                        <div class="top-bar-title">Signal Result</div>
                        <div class="top-bar-sub">
                            Focused AI trade breakdown for {symbol} on {tf_label}.
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with action_col:
            if st.button("Auto Trade", use_container_width=True):
                if _has_connected_broker():
                    _prime_signal_for_broker(result, symbol, tf_label, username)
                    _open_broker_execution_workspace("Signal moved to Broker & Execution workspace.")
                    st.rerun()
                st.session_state.signal_result_connect_broker = True
                st.rerun()
        with back_col:
            if st.button("Back", use_container_width=True):
                _open_trading_desk_signal_workspace(symbol, tf_label, trade_style=trade_style)

    if not result:
        st.info("No signal has been generated yet.")
        return

    _render_signal_result_refresh_controls(username, symbol, tf_label, trade_style, mobile=mobile)

    if st.session_state.get("signal_result_connect_broker"):
        _render_signal_result_connect_broker(username, result, symbol, tf_label)

    _render_requested_crypto_instant_signal_card(
        symbol,
        tf_label,
        trade_style,
    )
    _render_signal_card(result, symbol, tf_label)


def _render_market_analysis_chart_tools():
    return _render_market_analysis_chart_tools_view()


def ai_page(username, *, embedded_in_trading_desk: bool = False):
    return _render_ai_page_view(
        username,
        embedded_in_trading_desk=embedded_in_trading_desk,
        get_pair_universe=_get_pair_universe,
        default_tracked_symbols=DEFAULT_TRACKED_SYMBOLS,
        default_timeframes=DEFAULT_TIMEFRAMES,
        load_trading_desk_panel_data=_load_trading_desk_panel_data,
        render_component_html=_render_scripted_html,
        render_chart_panel_fragment=_render_chart_panel_fragment,
        render_market_signal_sidebar=_render_market_signal_sidebar,
        render_orderbook_terminal=_render_orderbook_terminal,
        render_market_analysis_overview=_render_market_analysis_overview,
        render_market_analysis_live_board=_render_market_analysis_live_board,
        render_market_analysis_upgrade_banner=_render_market_analysis_upgrade_banner,
        render_market_analysis_ticker_strip=_render_market_analysis_ticker_strip,
        coalesce_market_number=_coalesce_market_number,
        market_last_candle=_market_last_candle,
        fmt_price=_fmt_price,
        fmt_pct=_fmt_pct,
        fmt_compact=_fmt_compact,
        base_asset_from_symbol=_base_asset_from_symbol,
        market_series=_market_series,
        build_volume_bar_svg=_build_volume_bar_svg,
        snapshot_for_symbol=lambda pair: engine.get_market_snapshot(pair) or {},
        metric_series_for_symbol=lambda pair, metric, limit=10: engine.get_metric_series(pair, metric, limit=limit) or [],
        trigger_ai_signal=_trigger_ai_signal,
        signal_usage=lambda user: f"{get_used(user)}x used today",
        engine_ready=_engine_ready,
        engine_status=_engine_status,
        start_market_feed=_start_market_feed,
        render_fast_market_panel_fragment=_render_fast_market_panel_fragment,
        render_market_analysis_summary=_render_market_analysis_summary,
        trade_style_options=TRADE_STYLE_OPTIONS,
        default_trade_style=DEFAULT_TRADE_STYLE,
        normalize_trade_style=normalize_trade_style,
    )

# -----------------------------------
# TRADE JOURNAL
# -----------------------------------
def trade_journal_page(username):
    return _render_trade_journal_page_view(
        username,
        build_trade_metrics=build_trade_metrics,
        close_trade_entry=close_trade_entry,
    )


def mobile_trade_journal_page(username):
    return _render_mobile_trade_journal_page_view(
        username,
        build_trade_metrics=build_trade_metrics,
        close_trade_entry=close_trade_entry,
    )

# -----------------------------------
# ACCOUNT PAGE
# -----------------------------------
def account_page(username):
    return _render_account_page_view(
        username,
        get_user_notification_settings=get_user_notification_settings,
        save_user_notification_settings=save_user_notification_settings,
        get_user_account_preferences=get_user_account_preferences,
        save_user_account_preferences=save_user_account_preferences,
        change_user_password=change_user_password,
        verify_otp=verify_otp,
        update_user_password=update_user_password,
        clear_login_failures=clear_login_failures,
        password_meets_policy=password_meets_policy,
        send_email_otp=send_email_otp,
        clear_password_change_state=clear_password_change_state,
        reset_user_signal_destinations=reset_user_signal_destinations,
        upgrade_user_to_premium=upgrade_user_to_premium,
        render_toggle_input=render_toggle_input,
    )


def mobile_account_page(username):
    return _render_mobile_account_page_view(
        username,
        get_user_notification_settings=get_user_notification_settings,
        save_user_notification_settings=save_user_notification_settings,
        get_user_account_preferences=get_user_account_preferences,
        save_user_account_preferences=save_user_account_preferences,
        change_user_password=change_user_password,
        verify_otp=verify_otp,
        update_user_password=update_user_password,
        clear_login_failures=clear_login_failures,
        password_meets_policy=password_meets_policy,
        send_email_otp=send_email_otp,
        clear_password_change_state=clear_password_change_state,
        reset_user_signal_destinations=reset_user_signal_destinations,
        upgrade_user_to_premium=upgrade_user_to_premium,
        render_toggle_input=render_toggle_input,
    )


def mobile_market_analysis_page(username):
    return _render_mobile_market_analysis_page_view(
        username,
        get_pair_universe=_get_pair_universe,
        default_tracked_symbols=DEFAULT_TRACKED_SYMBOLS,
        default_timeframes=DEFAULT_TIMEFRAMES,
        load_trading_desk_panel_data=_load_trading_desk_panel_data,
        render_chart_panel_fragment=_render_chart_panel_fragment,
        render_market_signal_sidebar=_render_market_signal_sidebar,
        render_orderbook_terminal=_render_orderbook_terminal,
        render_market_analysis_overview=_render_market_analysis_overview,
        render_market_analysis_upgrade_banner=_render_market_analysis_upgrade_banner,
        render_market_analysis_ticker_strip=_render_market_analysis_ticker_strip,
        engine_ready=_engine_ready,
        engine_status=_engine_status,
        start_market_feed=_start_market_feed,
        render_market_analysis_summary=_render_market_analysis_summary,
        render_market_analysis_chart_tools=_render_market_analysis_chart_tools,
        trade_style_options=TRADE_STYLE_OPTIONS,
        default_trade_style=DEFAULT_TRADE_STYLE,
        normalize_trade_style=normalize_trade_style,
    )


def mobile_trading_desk_page(username, premium: bool):
    return _render_mobile_trading_desk_page_view(
        username,
        premium,
        auto_trade_page=auto_trade_page,
        render_synthetic_trade_page_fn=_render_synthetic_trade_page,
        get_pair_universe=_get_pair_universe,
        default_tracked_symbols=DEFAULT_TRACKED_SYMBOLS,
        default_timeframes=DEFAULT_TIMEFRAMES,
        load_trading_desk_panel_data=_load_trading_desk_panel_data,
        render_chart_panel_fragment=_render_chart_panel_fragment,
        render_market_signal_sidebar=_render_market_signal_sidebar,
        render_orderbook_terminal=_render_orderbook_terminal,
        render_market_analysis_overview=_render_market_analysis_overview,
        render_market_analysis_upgrade_banner=_render_market_analysis_upgrade_banner,
        render_market_analysis_ticker_strip=_render_market_analysis_ticker_strip,
        engine_ready=_engine_ready,
        engine_status=_engine_status,
        start_market_feed=_start_market_feed,
        render_market_analysis_summary=_render_market_analysis_summary,
        render_market_analysis_chart_tools=_render_market_analysis_chart_tools,
        trade_style_options=TRADE_STYLE_OPTIONS,
        default_trade_style=DEFAULT_TRADE_STYLE,
        normalize_trade_style=normalize_trade_style,
    )


def _user_agent_looks_mobile(user_agent: str) -> bool:
    normalized = str(user_agent or "").strip().lower()
    if not normalized:
        return False
    mobile_markers = (
        "android",
        "iphone",
        "ipad",
        "ipod",
        "mobile",
        "blackberry",
        "opera mini",
        "windows phone",
    )
    return any(marker in normalized for marker in mobile_markers)


def _request_looks_mobile() -> bool:
    user_agent, _ = _client_request_context()
    if _user_agent_looks_mobile(user_agent):
        return True

    sec_ch_mobile = _request_header_value("sec-ch-ua-mobile").lower()
    if sec_ch_mobile in {"?1", "1", "true"}:
        return True

    device_type = _request_header_value("cf-device-type", "x-device-type").lower()
    if device_type in {"mobile", "tablet"}:
        return True

    if _request_header_value("x-wap-profile", "x-operamini-phone-ua", "x-mobile-ua", "profile"):
        return True

    viewport_width = _request_header_value("sec-ch-viewport-width", "viewport-width")
    if viewport_width:
        digits = "".join(ch for ch in viewport_width if ch.isdigit())
        try:
            if digits and int(digits) <= 768:
                return True
        except ValueError:
            pass

    return False


def _resolve_viewport_mode() -> str:
    try:
        viewport = str(st.query_params.get("viewport", "") or "").strip().lower()
    except Exception:
        viewport = ""
    if viewport in {"mobile", "desktop"}:
        return viewport
    return "mobile" if _request_looks_mobile() else "desktop"


def _viewport_debug_enabled() -> bool:
    try:
        raw_value = str(st.query_params.get("debug_viewport", "") or "").strip().lower()
    except Exception:
        raw_value = ""
    return raw_value in {"1", "true", "yes", "on"}


def _render_viewport_debug_panel(layout_mode: str) -> None:
    if not _viewport_debug_enabled():
        return

    user_agent, ip_address = _client_request_context()
    debug_payload = {
        "resolved_mode": layout_mode,
        "query_viewport": str(st.query_params.get("viewport", "") or ""),
        "user_agent_mobile_match": _user_agent_looks_mobile(user_agent),
        "request_mobile_match": _request_looks_mobile(),
        "sec_ch_ua_mobile": _request_header_value("sec-ch-ua-mobile"),
        "sec_ch_viewport_width": _request_header_value("sec-ch-viewport-width", "viewport-width"),
        "cf_device_type": _request_header_value("cf-device-type", "x-device-type"),
        "user_agent": user_agent,
        "ip_address": ip_address,
    }
    with st.expander("Viewport Debug", expanded=True):
        st.json(debug_payload)


SYNTHETIC_MARKETS = [
    {"symbol": "1HZ10V", "label": "Volatility 10 (1s) Index", "profile": "One-second lower-volatility synthetic index"},
    {"symbol": "R_10", "label": "Volatility 10 Index", "profile": "Lower-volatility synthetic index"},
    {"symbol": "1HZ15V", "label": "Volatility 15 (1s) Index", "profile": "One-second synthetic volatility"},
    {"symbol": "1HZ25V", "label": "Volatility 25 (1s) Index", "profile": "One-second balanced synthetic volatility"},
    {"symbol": "R_25", "label": "Volatility 25 Index", "profile": "Balanced synthetic volatility"},
    {"symbol": "1HZ30V", "label": "Volatility 30 (1s) Index", "profile": "One-second synthetic volatility"},
    {"symbol": "1HZ50V", "label": "Volatility 50 (1s) Index", "profile": "One-second fast synthetic volatility"},
    {"symbol": "R_50", "label": "Volatility 50 Index", "profile": "Fast synthetic volatility"},
    {"symbol": "1HZ75V", "label": "Volatility 75 (1s) Index", "profile": "One-second very fast synthetic volatility"},
    {"symbol": "R_75", "label": "Volatility 75 Index", "profile": "Very fast synthetic volatility"},
    {"symbol": "1HZ90V", "label": "Volatility 90 (1s) Index", "profile": "One-second high synthetic volatility"},
    {"symbol": "1HZ100V", "label": "Volatility 100 (1s) Index", "profile": "One-second extreme synthetic volatility"},
    {"symbol": "R_100", "label": "Volatility 100 Index", "profile": "Extreme synthetic volatility"},
    {"symbol": "BOOM1000", "label": "Boom 1000 Index", "profile": "Spike-sensitive synthetic index"},
    {"symbol": "CRASH1000", "label": "Crash 1000 Index", "profile": "Drop-spike synthetic index"},
    {"symbol": "STEP", "label": "Step Index", "profile": "Fixed-step synthetic movement"},
    {"symbol": "JD100", "label": "Jump 100 Index", "profile": "Jump-event synthetic movement"},
    {"symbol": "RB100", "label": "Range Break 100 Index", "profile": "Range-break synthetic index"},
]


def _format_deriv_quote(value: float, pip_size: int = 4) -> str:
    try:
        precision = int(pip_size or 4)
    except (TypeError, ValueError):
        precision = 4
    precision = max(2, min(precision, 8))
    return f"{float(value or 0):,.{precision}f}"


def _fetch_synthetic_live_quote(symbol: str, deriv_token: str = "", *, max_age_seconds: int = 10) -> tuple[dict, str]:
    symbol = str(symbol or "").strip()
    if not symbol:
        return {}, "Deriv symbol is missing."

    cache = st.session_state.get("synthetic_live_quote") or {}
    try:
        fetched_at = float(cache.get("fetched_at") or 0)
    except (TypeError, ValueError):
        fetched_at = 0.0
    if (
        cache.get("symbol") == symbol
        and _safe_float(cache.get("quote")) > 0
        and time.time() - fetched_at < int(max_age_seconds or 10)
    ):
        return cache, ""

    try:
        tick = fetch_deriv_latest_tick(symbol, token=deriv_token, timeout=8)
    except Exception as exc:
        APP_LOGGER.warning("Deriv live tick fetch failed for %s: %s", symbol, exc)
        return {}, str(exc)

    quote = {
        "symbol": str(tick.get("symbol") or symbol),
        "quote": _safe_float(tick.get("quote")),
        "timestamp": str(tick.get("timestamp") or ""),
        "epoch": int(tick.get("epoch") or 0),
        "pip_size": int(tick.get("pip_size") or 4),
        "fetched_at": time.time(),
        "source": "live_tick",
    }
    st.session_state.synthetic_live_quote = quote
    return quote, ""


def _synthetic_direction_from_signal(result: dict) -> str:
    signal = str((result or {}).get("signal", "HOLD") or "HOLD").upper()
    if bool((result or {}).get("trade_allowed")) and signal == "BUY":
        return "Buy"
    if bool((result or {}).get("trade_allowed")) and signal == "SELL":
        return "Sell"
    return "Wait"


def _synthetic_entry_model_from_signal(result: dict, market_label: str = "") -> str:
    result = result or {}
    market_text = str(market_label or "").lower()
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    regime = result.get("regime") if isinstance(result.get("regime"), dict) else {}
    regime_text = " ".join(
        str(value or "").lower()
        for value in [regime.get("regime"), regime.get("reason"), summary.get("setup_quality")]
    )
    try:
        momentum_score = abs(float(summary.get("momentum_score") or 0))
    except (TypeError, ValueError):
        momentum_score = 0.0
    try:
        trend_score = abs(float(summary.get("trend_score") or 0))
    except (TypeError, ValueError):
        trend_score = 0.0

    if any(token in market_text for token in ["boom", "crash", "jump"]) or "spike" in regime_text:
        return "Spike capture"
    if any(token in market_text for token in ["range break", "range"]) or any(token in regime_text for token in ["range", "sideways", "chop"]):
        return "Range break"
    if momentum_score >= max(trend_score * 1.25, 0.18):
        return "Breakout"
    return "Pullback"


def _synthetic_confirmation_timeframe(timeframe: str) -> str:
    timeframe = str(timeframe or "1m")
    return {
        "Ticks": "1m",
        "1m": "5m",
        "5m": "15m",
        "15m": "30m",
        "30m": "1h",
        "1h": "1h",
    }.get(timeframe, "5m")


def _synthetic_trade_style_for_timeframe(timeframe: str) -> str:
    timeframe = str(timeframe or "1m")
    if timeframe in {"Ticks", "1m", "5m"}:
        return "scalp"
    if timeframe in {"15m", "30m"}:
        return "day_trade"
    return "swing"


def _prepare_synthetic_indicator_frame(candle_df: pd.DataFrame) -> pd.DataFrame:
    if candle_df is None or candle_df.empty:
        return pd.DataFrame()

    working = candle_df.copy()
    for column in ["open", "high", "low", "close"]:
        working[column] = pd.to_numeric(working.get(column), errors="coerce")
    working = working.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if working.empty:
        return working

    previous_close = working["close"].shift()
    true_range = pd.concat(
        [
            (working["high"] - working["low"]).abs(),
            (working["high"] - previous_close).abs(),
            (working["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    working["atr_14"] = true_range.rolling(14).mean()
    working["ema_20"] = working["close"].ewm(span=20).mean()
    working["ema_50"] = working["close"].ewm(span=50).mean()
    working["momentum_5"] = working["close"].pct_change(5) * 100

    delta = working["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-9)
    working["rsi_14"] = 100 - (100 / (1 + rs))
    return working


def _synthetic_latest_candle_checks(indicator_df: pd.DataFrame, side: str) -> tuple[list[str], dict]:
    if indicator_df is None or indicator_df.empty:
        return ["latest candle is unavailable"], {}

    last = indicator_df.iloc[-1]
    open_price = _safe_float(last.get("open"))
    high_price = _safe_float(last.get("high"))
    low_price = _safe_float(last.get("low"))
    close_price = _safe_float(last.get("close"))
    ema_20 = _safe_float(last.get("ema_20"))
    ema_50 = _safe_float(last.get("ema_50"))
    momentum = _safe_float(last.get("momentum_5"))
    rsi = _safe_float(last.get("rsi_14"), 50.0)
    candle_range = max(high_price - low_price, 1e-9)
    body_ratio = abs(close_price - open_price) / candle_range
    upper_wick_ratio = (high_price - max(open_price, close_price)) / candle_range
    lower_wick_ratio = (min(open_price, close_price) - low_price) / candle_range

    side = str(side or "").upper()
    failures = []
    if side == "BUY":
        if not (close_price > ema_20 > ema_50):
            failures.append("EMA trend is not aligned upward")
        if momentum <= 0:
            failures.append("momentum is not positive")
        if not (50 <= rsi <= 74):
            failures.append(f"RSI is not in the buy zone ({rsi:.1f})")
        if close_price <= open_price:
            failures.append("latest candle is not closing bullish")
        if upper_wick_ratio > 0.45:
            failures.append("latest candle has too much upper rejection")
    elif side == "SELL":
        if not (close_price < ema_20 < ema_50):
            failures.append("EMA trend is not aligned downward")
        if momentum >= 0:
            failures.append("momentum is not negative")
        if not (26 <= rsi <= 50):
            failures.append(f"RSI is not in the sell zone ({rsi:.1f})")
        if close_price >= open_price:
            failures.append("latest candle is not closing bearish")
        if lower_wick_ratio > 0.45:
            failures.append("latest candle has too much lower rejection")
    else:
        failures.append("AI signal is not Buy or Sell")

    if body_ratio < 0.16:
        failures.append("latest candle body is too weak for instant entry")

    metrics = {
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "ema_20": ema_20,
        "ema_50": ema_50,
        "momentum": momentum,
        "rsi": rsi,
        "body_ratio": body_ratio,
        "upper_wick_ratio": upper_wick_ratio,
        "lower_wick_ratio": lower_wick_ratio,
    }
    return failures, metrics


def _build_synthetic_instant_signal(
    username: str,
    selected_market: dict,
    selected_label: str,
    timeframe: str,
    stake: float,
    deriv_token: str,
    *,
    min_confidence: float = 68.0,
    min_rr: float = 4.0,
    risk_percent: float = 1.0,
    confirmation_timeframe: str = "",
) -> tuple[dict, str]:
    symbol = str((selected_market or {}).get("symbol") or "").strip()
    if not symbol:
        return {}, "Synthetic market symbol is missing."

    confirmation_timeframe = confirmation_timeframe or _synthetic_confirmation_timeframe(timeframe)
    live_tick: dict = {}
    live_tick_error = ""
    try:
        live_tick = fetch_deriv_latest_tick(symbol, token=deriv_token, timeout=8)
    except Exception as exc:
        live_tick_error = str(exc)
        APP_LOGGER.warning("Instant synthetic live tick fetch failed for %s: %s", symbol, exc)

    try:
        main_df = fetch_deriv_candles(
            symbol,
            timeframe=timeframe,
            count=260 if timeframe != "Ticks" else 900,
            token=deriv_token,
        )
        confirm_df = fetch_deriv_candles(
            symbol,
            timeframe=confirmation_timeframe,
            count=220,
            token=deriv_token,
        )
        tick_df = (
            pd.DataFrame()
            if live_tick
            else fetch_deriv_candles(
                symbol,
                timeframe="Ticks",
                count=20,
                token=deriv_token,
            )
        )
    except Exception as exc:
        APP_LOGGER.warning("Instant synthetic signal fetch failed for %s: %s", symbol, exc)
        return {}, f"Instant signal could not fetch Deriv candles: {exc}"

    if main_df is None or main_df.empty or len(main_df) < 60:
        return {}, "Instant signal needs more current candle history before it can call an entry."
    if confirm_df is None or confirm_df.empty or len(confirm_df) < 60:
        return {}, "Higher-timeframe confirmation candles are not ready yet."
    if not live_tick and (tick_df is None or tick_df.empty):
        tick_message = f": {live_tick_error}" if live_tick_error else ""
        return {}, f"Latest Deriv tick is unavailable{tick_message}, so Finwise will not call an instant market entry."

    balance_basis = float((st.session_state.get("deriv_connection_status") or {}).get("balance") or stake or 1.0)
    main_trade_style = _synthetic_trade_style_for_timeframe(timeframe)
    confirm_trade_style = _synthetic_trade_style_for_timeframe(confirmation_timeframe)
    try:
        main_signal = ai_signal_for_user(
            username,
            main_df,
            symbol=symbol,
            current_balance=max(balance_basis, float(stake or 1.0)),
            timeframe=timeframe,
            trade_style=main_trade_style,
        )
        confirm_signal = ai_signal_for_user(
            username,
            confirm_df,
            symbol=symbol,
            current_balance=max(balance_basis, float(stake or 1.0)),
            timeframe=confirmation_timeframe,
            trade_style=confirm_trade_style,
        )
    except Exception as exc:
        APP_LOGGER.warning("Instant synthetic AI signal failed for %s: %s", symbol, exc)
        return {}, f"Instant AI signal failed: {exc}"

    side = str(main_signal.get("signal", "HOLD") or "HOLD").upper()
    confirm_side = str(confirm_signal.get("signal", "HOLD") or "HOLD").upper()
    confidence = _safe_float(main_signal.get("confidence"))
    confirm_confidence = _safe_float(confirm_signal.get("confidence"))
    main_entry = main_signal.get("entry_exit") if isinstance(main_signal.get("entry_exit"), dict) else {}

    indicator_df = _prepare_synthetic_indicator_frame(main_df)
    if indicator_df.empty or len(indicator_df) < 60:
        return {}, "Instant signal could not prepare enough indicator history."

    last = indicator_df.iloc[-1]
    tick_row = tick_df.iloc[-1] if tick_df is not None and not tick_df.empty else {}
    entry_price = _safe_float(live_tick.get("quote") or tick_row.get("close") or last.get("close"))
    atr = _safe_float(last.get("atr_14"))
    reward_multiple = _bounded_reward_multiple(min_rr, default=4.0, maximum=4.0)
    min_stop_distance = max(entry_price * 0.0012, 1e-9)
    stop_distance = max(atr * 1.15, min_stop_distance)
    if stop_distance <= 0 or entry_price <= 0:
        return {}, "Instant signal could not calculate a valid market entry."

    candle_failures, candle_metrics = _synthetic_latest_candle_checks(indicator_df, side)

    failures = []
    requested_rr = _safe_float(min_rr, reward_multiple)
    if requested_rr > reward_multiple:
        failures.append(f"requested reward/risk is capped at {reward_multiple:.2f}R for instant synthetic signals")
    if side not in {"BUY", "SELL"} or not bool(main_signal.get("trade_allowed")):
        failures.append("current AI signal is not a tradable Buy/Sell")
    if confidence < float(min_confidence or 0):
        failures.append(f"confidence {confidence:.1f}% is below {float(min_confidence or 0):.1f}%")
    if confirm_side != side or not bool(confirm_signal.get("trade_allowed")):
        failures.append(f"{confirmation_timeframe} confirmation is {confirm_side}, not {side}")
    elif confirm_confidence < max(50.0, float(min_confidence or 0) - 10.0):
        failures.append(f"{confirmation_timeframe} confirmation confidence is too low ({confirm_confidence:.1f}%)")
    if _safe_float(main_entry.get("risk_reward_ratio")) < 1.5:
        failures.append("base AI reward/risk is too weak")
    failures.extend(candle_failures)

    if side == "BUY":
        stop_loss = entry_price - stop_distance
        take_profit = entry_price + (stop_distance * reward_multiple)
    elif side == "SELL":
        stop_loss = entry_price + stop_distance
        take_profit = entry_price - (stop_distance * reward_multiple)
    else:
        stop_loss = 0.0
        take_profit = 0.0

    level_failures, level_metrics = _validate_instant_price_levels(
        side,
        entry_price,
        stop_loss,
        take_profit,
        atr_value=atr,
        requested_rr=reward_multiple,
        min_stop_pct=0.0012,
    )
    failures.extend(level_failures)

    account_risk = balance_basis * max(float(risk_percent or 0), 0.0) / 100
    actual_rr = _safe_float(level_metrics.get("actual_rr"), reward_multiple)
    actual_risk_distance = _safe_float(level_metrics.get("risk_distance"), stop_distance)
    target_amount = account_risk * actual_rr
    timestamp = ""
    price_source = "live Deriv tick" if live_tick else "tick history"
    try:
        timestamp = str(live_tick.get("timestamp") or tick_row.get("timestamp") or main_df.iloc[-1].get("timestamp") or "")
    except (AttributeError, IndexError):
        timestamp = ""

    return {
        "status": "OPEN NOW" if not failures else "WAIT",
        "side": side if side in {"BUY", "SELL"} else "WAIT",
        "market": selected_label,
        "symbol": symbol,
        "timeframe": timeframe,
        "confirmation_timeframe": confirmation_timeframe,
        "trade_style": main_signal.get("trade_style", main_trade_style),
        "entry_price": round(entry_price, 8),
        "stop_loss": round(stop_loss, 8),
        "take_profit": round(take_profit, 8),
        "risk_distance": round(actual_risk_distance, 8),
        "target_distance": round(_safe_float(level_metrics.get("reward_distance")), 8),
        "risk_distance_pct": round(_safe_float(level_metrics.get("risk_distance_pct")), 4),
        "target_distance_pct": round(_safe_float(level_metrics.get("target_distance_pct")), 4),
        "risk_reward_ratio": round(actual_rr, 2),
        "confidence": round(confidence, 1),
        "confirmation_confidence": round(confirm_confidence, 1),
        "account_risk": round(account_risk, 2),
        "target_amount": round(target_amount, 2),
        "risk_percent": round(float(risk_percent or 0), 2),
        "timestamp": timestamp,
        "price_source": price_source,
        "pip_size": int(live_tick.get("pip_size") or 4) if live_tick else 4,
        "failures": list(dict.fromkeys(failures)),
        "metrics": {**candle_metrics, **level_metrics},
        "reason": str(main_signal.get("reason") or ""),
    }, ""


def _render_synthetic_instant_signal_card(instant_signal: dict, error: str = "") -> None:
    if error:
        st.warning(error)
        return
    if not instant_signal:
        st.caption("Instant Live Signal is waiting for enough current Deriv data.")
        return

    status = str(instant_signal.get("status") or "WAIT")
    side = str(instant_signal.get("side") or "WAIT")
    is_open = status == "OPEN NOW"
    tone = "#26a69a" if is_open and side == "BUY" else "#ef5350" if is_open and side == "SELL" else "#ffc107"
    bg = "rgba(38,166,154,0.12)" if is_open and side == "BUY" else "rgba(239,83,80,0.12)" if is_open and side == "SELL" else "rgba(255,193,7,0.10)"
    failures = instant_signal.get("failures") or []
    failure_text = " | ".join(str(item) for item in failures[:4]) if failures else "All instant-entry filters agree."
    metrics = instant_signal.get("metrics") if isinstance(instant_signal.get("metrics"), dict) else {}
    pip_size = int(instant_signal.get("pip_size") or 4)
    entry_price_text = _format_deriv_quote(_safe_float(instant_signal.get("entry_price")), pip_size)
    stop_loss_text = _format_deriv_quote(_safe_float(instant_signal.get("stop_loss")), pip_size)
    take_profit_text = _format_deriv_quote(_safe_float(instant_signal.get("take_profit")), pip_size)
    price_source = str(instant_signal.get("price_source") or "Deriv tick")

    st.markdown(
        f"""
        <div class="synthetic-panel" style="border-color:{tone};background:linear-gradient(180deg, {bg}, rgba(7,15,27,0.98));">
          <div class="synthetic-kicker">Instant Live Signal</div>
          <div class="synthetic-title" style="font-size:1.42rem;color:{tone};">{escape(status)} {escape(side)}</div>
          <div class="synthetic-copy">
            Market: {escape(str(instant_signal.get("market") or ""))} |
            TF: {escape(str(instant_signal.get("timeframe") or ""))} + {escape(str(instant_signal.get("confirmation_timeframe") or ""))} |
            Confidence: {float(instant_signal.get("confidence") or 0):.1f}% / {float(instant_signal.get("confirmation_confidence") or 0):.1f}%
          </div>
          <div class="synthetic-grid" style="margin-top:0.82rem;">
            <div class="synthetic-metric">
              <div class="synthetic-label">Open At Market</div>
              <div class="synthetic-value">{escape(entry_price_text)}</div>
              <div class="synthetic-note">{escape(price_source)}: {escape(str(instant_signal.get("timestamp") or "live"))}</div>
            </div>
            <div class="synthetic-metric synthetic-warn">
              <div class="synthetic-label">SL Price</div>
              <div class="synthetic-value">{escape(stop_loss_text)}</div>
              <div class="synthetic-note">Distance: {float(instant_signal.get("risk_distance") or 0):,.4f} ({float(instant_signal.get("risk_distance_pct") or 0):.3f}%)</div>
            </div>
            <div class="synthetic-metric synthetic-ok">
              <div class="synthetic-label">TP Price</div>
              <div class="synthetic-value">{escape(take_profit_text)}</div>
              <div class="synthetic-note">Target: {float(instant_signal.get("risk_reward_ratio") or 0):.2f}R ({float(instant_signal.get("target_distance_pct") or 0):.3f}%)</div>
            </div>
            <div class="synthetic-metric">
              <div class="synthetic-label">Account Model</div>
              <div class="synthetic-value">{float(instant_signal.get("risk_percent") or 0):.2f}% -> {float(instant_signal.get("risk_reward_ratio") or 0):.2f}R</div>
              <div class="synthetic-note">Risk {float(instant_signal.get("account_risk") or 0):,.2f}; target {float(instant_signal.get("target_amount") or 0):,.2f}.</div>
            </div>
          </div>
          <div class="synthetic-note" style="margin-top:0.78rem;color:{tone};">{escape(failure_text)}</div>
          <div class="synthetic-note">Use the SL/TP price values on the chart; do not enter the distance value as the stop price.</div>
          <div class="synthetic-note">
            RSI {float(metrics.get("rsi") or 0):.1f} | Momentum {float(metrics.get("momentum") or 0):.3f}% |
            Body {float(metrics.get("body_ratio") or 0) * 100:.1f}%
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _store_synthetic_deriv_analysis(
    username: str,
    selected_market: dict,
    selected_label: str,
    timeframe: str,
    stake: float,
    deriv_token: str = "",
    *,
    trigger: str = "manual",
) -> tuple[dict, str]:
    st.session_state.synthetic_signal_last_checked_at = time.time()
    st.session_state.synthetic_signal_last_key = f"{selected_market['symbol']}|{timeframe}"
    st.session_state.synthetic_signal_error = ""

    try:
        candle_df = fetch_deriv_candles(
            selected_market["symbol"],
            timeframe=timeframe,
            count=420 if timeframe != "Ticks" else 900,
            token=deriv_token,
        )
    except Exception as exc:
        APP_LOGGER.warning("Deriv synthetic candle fetch failed for %s %s: %s", selected_market.get("symbol"), timeframe, exc)
        message = f"Deriv candle fetch failed: {exc}"
        st.session_state.synthetic_signal_error = message
        return {}, message

    if candle_df is None or candle_df.empty or len(candle_df) < 50:
        message = "Deriv did not return enough candle history for analysis. Try another index or timeframe."
        st.session_state.synthetic_signal_error = message
        return {}, message

    balance_basis = float((st.session_state.get("deriv_connection_status") or {}).get("balance") or stake or 1.0)
    trade_style = _synthetic_trade_style_for_timeframe(timeframe)
    try:
        result = ai_signal_for_user(
            username,
            candle_df,
            symbol=selected_market["symbol"],
            current_balance=max(balance_basis, float(stake or 1.0)),
            timeframe=timeframe,
            trade_style=trade_style,
        )
    except Exception as exc:
        APP_LOGGER.warning("Synthetic AI analysis failed for %s %s: %s", selected_market.get("symbol"), timeframe, exc)
        message = f"AI analysis failed for Deriv synthetic candles: {exc}"
        st.session_state.synthetic_signal_error = message
        return {}, message
    result["reason"] = (
        f"{result.get('reason', '')} Synthetic note: analysis uses Deriv synthetic candles; "
        "normal exchange volume/news context is not available."
    ).strip()
    last_close = 0.0
    try:
        last_close = float(candle_df.iloc[-1].get("close") or 0)
    except (AttributeError, IndexError, TypeError, ValueError):
        last_close = 0.0
    live_quote, live_quote_error = _fetch_synthetic_live_quote(
        selected_market["symbol"],
        deriv_token,
        max_age_seconds=5,
    )
    last_quote = _safe_float(live_quote.get("quote"), last_close) if live_quote else last_close

    st.session_state.synthetic_signal = result
    st.session_state.synthetic_signal_meta = {
        "symbol": selected_market["symbol"],
        "label": selected_label,
        "timeframe": timeframe,
        "trade_style": result.get("trade_style", trade_style),
        "rows": len(candle_df),
        "last_close": last_close,
        "last_quote": last_quote,
        "last_quote_timestamp": str(live_quote.get("timestamp") or ""),
        "live_quote_error": live_quote_error,
        "pip_size": int(live_quote.get("pip_size") or 4) if live_quote else 4,
        "trigger": trigger,
        "updated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }
    st.session_state.synthetic_signal_df = candle_df
    return result, ""


def _render_synthetic_deriv_analysis_panel(
    username: str,
    selected_market: dict,
    selected_label: str,
    timeframe: str,
    stake: float,
    deriv_token: str,
    auto_analyze: bool,
    auto_follow_signal: bool,
    auto_refresh_seconds: int,
    instant_signal_enabled: bool,
    instant_min_confidence: float,
    instant_min_rr: float,
    instant_risk_percent: float,
    instant_confirmation_timeframe: str,
) -> None:
    def render_panel() -> None:
        current_signal_meta = st.session_state.get("synthetic_signal_meta") or {}
        has_current_signal = (
            current_signal_meta.get("symbol") == selected_market["symbol"]
            and current_signal_meta.get("timeframe") == timeframe
            and bool(st.session_state.get("synthetic_signal"))
        )
        current_analysis_key = f"{selected_market['symbol']}|{timeframe}"
        last_analysis_key = str(st.session_state.get("synthetic_signal_last_key") or "")
        last_checked_at = float(st.session_state.get("synthetic_signal_last_checked_at") or 0)
        analysis_due = (time.time() - last_checked_at) >= int(auto_refresh_seconds or 30)

        if auto_analyze and (last_analysis_key != current_analysis_key or analysis_due or (not has_current_signal and last_checked_at <= 0)):
            _store_synthetic_deriv_analysis(
                username=username,
                selected_market=selected_market,
                selected_label=selected_label,
                timeframe=timeframe,
                stake=float(stake),
                deriv_token=deriv_token,
                trigger="auto",
            )

        synthetic_signal = st.session_state.get("synthetic_signal") or {}
        synthetic_meta = st.session_state.get("synthetic_signal_meta") or {}
        synthetic_signal_matches_page = (
            synthetic_meta.get("symbol") == selected_market["symbol"]
            and synthetic_meta.get("timeframe") == timeframe
        )
        synthetic_error = st.session_state.get("synthetic_signal_error", "")
        if synthetic_error:
            st.warning(synthetic_error)

        if instant_signal_enabled:
            instant_signal, instant_error = _build_synthetic_instant_signal(
                username=username,
                selected_market=selected_market,
                selected_label=selected_label,
                timeframe=timeframe,
                stake=float(stake),
                deriv_token=deriv_token,
                min_confidence=float(instant_min_confidence or 68.0),
                min_rr=float(instant_min_rr or 4.0),
                risk_percent=float(instant_risk_percent or 1.0),
                confirmation_timeframe=instant_confirmation_timeframe,
            )
            st.session_state.synthetic_instant_signal = instant_signal
            st.session_state.synthetic_instant_signal_error = instant_error
            _render_synthetic_instant_signal_card(instant_signal, instant_error)

        if synthetic_signal and synthetic_signal_matches_page:
            recommended_direction = _synthetic_direction_from_signal(synthetic_signal)
            recommended_entry_model = _synthetic_entry_model_from_signal(synthetic_signal, selected_label)
            st.session_state.synthetic_ai_direction = recommended_direction
            st.session_state.synthetic_ai_entry_model = recommended_entry_model

            if auto_analyze:
                follow_text = "auto recommendation stored" if auto_follow_signal else "display only"
                live_quote_text = _format_deriv_quote(
                    _safe_float(synthetic_meta.get("last_quote"), synthetic_meta.get("last_close") or 0),
                    int(synthetic_meta.get("pip_size") or 4),
                )
                st.caption(
                    f"Auto Deriv analysis is on: {follow_text} | "
                    f"AI ticket: {recommended_direction} / {recommended_entry_model} | "
                    f"live quote {live_quote_text} | "
                    f"updated {synthetic_meta.get('updated_at', 'pending')}."
                )
            live_quote_text = _format_deriv_quote(
                _safe_float(synthetic_meta.get("last_quote"), synthetic_meta.get("last_close") or 0),
                int(synthetic_meta.get("pip_size") or 4),
            )
            candle_close_text = _format_deriv_quote(
                _safe_float(synthetic_meta.get("last_close")),
                int(synthetic_meta.get("pip_size") or 4),
            )
            st.markdown(
                f"""
                <div class="synthetic-panel">
                  <div class="synthetic-kicker">AI-Adjusted Ticket</div>
                  <div class="synthetic-title" style="font-size:1.25rem;">{escape(recommended_direction)} {escape(selected_label)} on {escape(timeframe)}</div>
                  <div class="synthetic-copy">
                    Entry model: {escape(recommended_entry_model)} | Confidence: {float(synthetic_signal.get("confidence") or 0):.1f}% |
                    Live quote: {escape(live_quote_text)} | Candle close: {escape(candle_close_text)}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown("**Synthetic AI Worker Analysis**")
            try:
                _render_signal_card(
                    synthetic_signal,
                    synthetic_meta.get("label") or synthetic_meta.get("symbol", selected_market["symbol"]),
                    synthetic_meta.get("timeframe", timeframe),
                )
            except Exception as exc:
                APP_LOGGER.warning("Synthetic signal card render failed: %s", exc)
                st.warning(f"Synthetic AI result loaded, but the signal card could not render: {exc}")
        else:
            st.caption("AI worker will display here after Analyze Now runs or Auto Analyze is enabled.")

    if auto_analyze or instant_signal_enabled:
        st.fragment(render_panel, run_every=int(auto_refresh_seconds or 30))()
    else:
        render_panel()


def _render_synthetic_trade_page(username: str, *, mobile_layout: bool = False) -> None:
    deriv_token_default = st.session_state.get("deriv_api_token") or deriv_env_token()
    pending_deriv_oauth = st.session_state.get("pending_deriv_oauth_connection") or {}
    pending_deriv_token = str(pending_deriv_oauth.get("token") or "").strip()
    if pending_deriv_token and not pending_deriv_oauth.get("attempted"):
        pending_deriv_oauth["attempted"] = True
        st.session_state.pending_deriv_oauth_connection = pending_deriv_oauth
        with st.spinner("Completing Deriv OAuth connection..."):
            result = test_deriv_connection(pending_deriv_token)
        st.session_state.deriv_connection_status = {
            "ok": result.ok,
            "loginid": result.loginid or pending_deriv_oauth.get("account", ""),
            "currency": result.currency or pending_deriv_oauth.get("currency", ""),
            "balance": result.balance,
            "message": result.message,
        }
        if result.ok:
            st.session_state.deriv_api_token = pending_deriv_token
            st.session_state.synthetic_deriv_token_input = pending_deriv_token
            st.session_state.pending_deriv_oauth_connection = {}
            st.session_state.deriv_oauth_status_tone = "success"
            st.session_state.deriv_oauth_status_message = (
                f"Deriv connected automatically: {result.loginid} | "
                f"{result.currency} {result.balance:,.2f}"
            )
            st.rerun()
        else:
            st.session_state.deriv_oauth_status_tone = "warning"
            st.session_state.deriv_oauth_status_message = (
                result.message or "Deriv returned a token, but Finwise could not validate it automatically."
            )
    deriv_status = st.session_state.get("deriv_connection_status") or {}
    deriv_connected = bool(deriv_status.get("ok"))
    deriv_login = str(deriv_status.get("loginid") or "Deriv").strip()
    deriv_currency = str(deriv_status.get("currency") or "USD").strip().upper()
    deriv_balance = _safe_float(deriv_status.get("balance"))
    if deriv_connected:
        risk_card_class = "synthetic-metric synthetic-ok"
        risk_value = "Live Ready"
        risk_note = (
            f"Deriv execution is connected for {deriv_login} in {deriv_currency}. "
            "Live orders still require all gates and confirmation."
        )
    else:
        risk_card_class = "synthetic-metric synthetic-warn"
        risk_value = "Connect Deriv"
        risk_note = "Connect a Deriv token with trading access to unlock guarded live multiplier execution."

    st.markdown(
        """
        <style>
        .synthetic-shell { display: grid; gap: 1rem; }
        .synthetic-panel {
            border: 1px solid rgba(119,154,186,0.14);
            background: linear-gradient(180deg, rgba(10,20,33,0.98), rgba(7,15,27,0.98));
            border-radius: 1.2rem;
            padding: 1rem;
            box-shadow: 0 22px 48px rgba(0,0,0,0.18);
        }
        .synthetic-hero {
            display: grid;
            grid-template-columns: minmax(0, 1.2fr) minmax(260px, 0.8fr);
            gap: 1rem;
            align-items: stretch;
        }
        .synthetic-kicker {
            color: #7fece0;
            font-size: 0.68rem;
            font-weight: 800;
            letter-spacing: 0.14em;
            text-transform: uppercase;
        }
        .synthetic-title {
            color: #f6fbff;
            font-size: 2rem;
            font-weight: 840;
            line-height: 1.05;
            margin-top: 0.42rem;
        }
        .synthetic-copy {
            color: #8fa8bb;
            font-size: 0.94rem;
            line-height: 1.6;
            margin-top: 0.5rem;
            max-width: 46rem;
        }
        .synthetic-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.78rem;
        }
        .synthetic-metric {
            min-width: 0;
            border: 1px solid rgba(255,255,255,0.06);
            background: rgba(8,17,29,0.86);
            border-radius: 0.92rem;
            padding: 0.82rem 0.86rem;
        }
        .synthetic-label {
            color: #6f8ca2;
            font-size: 0.68rem;
            font-weight: 760;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }
        .synthetic-value {
            color: #f8fbff;
            font-size: 1.25rem;
            font-weight: 820;
            margin-top: 0.38rem;
        }
        .synthetic-note {
            color: #88a0b4;
            font-size: 0.78rem;
            line-height: 1.45;
            margin-top: 0.28rem;
        }
        .synthetic-warn {
            border-color: rgba(255,107,125,0.24);
            background: rgba(46,16,28,0.52);
        }
        .synthetic-ok {
            border-color: rgba(38,166,154,0.28);
            background: rgba(12,43,39,0.54);
        }
        @media (max-width: 900px) {
            .synthetic-hero,
            .synthetic-grid { grid-template-columns: 1fr; }
            .synthetic-title { font-size: 1.55rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="synthetic-shell">
          <div class="synthetic-panel synthetic-hero">
            <div>
              <div class="synthetic-kicker">Synthetic Indices</div>
              <div class="synthetic-title">Synthetic Trade</div>
              <div class="synthetic-copy">
                Build a gated plan for high-volatility synthetic index trades, then execute through Deriv when every check is ready.
              </div>
            </div>
            <div class="{escape(risk_card_class)}">
              <div class="synthetic-label">Risk Mode</div>
              <div class="synthetic-value">{escape(risk_value)}</div>
              <div class="synthetic-note">{escape(risk_note)}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    oauth_message = str(st.session_state.get("deriv_oauth_status_message", "") or "").strip()
    oauth_tone = str(st.session_state.get("deriv_oauth_status_tone", "info") or "info").strip().lower()
    if oauth_message:
        if oauth_tone == "success":
            st.success(oauth_message)
        elif oauth_tone in {"warning", "error"}:
            st.warning(oauth_message)
        else:
            st.info(oauth_message)
    if not deriv_token_default and not pending_deriv_token and not deriv_connected:
        oauth_start_url = str(
            os.getenv(
                "DERIV_OAUTH_START_URL",
                "https://contains-item-tvs-begin.trycloudflare.com/promo/efikemma/",
            )
            or ""
        ).strip()
        st.info(
            "Deriv is not connected yet. Use the efikemma Deriv login page first, then the callback will return here with the token."
        )
        if oauth_start_url:
            st.link_button("Start Deriv OAuth", oauth_start_url, use_container_width=True)

    deriv_cols = st.columns([1.18, 0.42, 1.0], gap="small")
    with deriv_cols[0]:
        deriv_token = st.text_input(
            "Deriv API Token",
            value=deriv_token_default,
            type="password",
            key="synthetic_deriv_token_input",
            help="Use a Deriv API token with read access for validation and trading access for live execution. Candle analysis can still work without trading permissions.",
        ).strip()
    with deriv_cols[1]:
        st.write("")
        st.write("")
        if st.button("Connect Deriv", use_container_width=True):
            if not deriv_token:
                st.warning(
                    "No Deriv token has reached Finwise yet. Start from the efikemma Deriv login page, "
                    "approve the app, then let the callback return here automatically."
                )
            else:
                result = test_deriv_connection(deriv_token)
                st.session_state.deriv_connection_status = {
                    "ok": result.ok,
                    "loginid": result.loginid,
                    "currency": result.currency,
                    "balance": result.balance,
                    "message": result.message,
                }
                if result.ok:
                    st.session_state.deriv_api_token = deriv_token
                    st.success(f"Deriv connected: {result.loginid} | {result.currency} {result.balance:,.2f}")
                    st.rerun()
                else:
                    st.error(result.message or "Deriv connection failed.")
    with deriv_cols[2]:
        if deriv_status:
            if deriv_status.get("ok"):
                st.success(
                    f"Connected {deriv_status.get('loginid', '')} | "
                    f"{deriv_status.get('currency', '')} {float(deriv_status.get('balance', 0) or 0):,.2f}"
                )
            else:
                st.warning(deriv_status.get("message", "Deriv is not connected."))
        else:
            st.info("Connect Deriv for account validation. Analysis can fetch public synthetic candles.")

    market_labels = [market["label"] for market in SYNTHETIC_MARKETS]
    market_by_label = {market["label"]: market for market in SYNTHETIC_MARKETS}
    default_market = st.session_state.get("synthetic_market_label", "Volatility 75 (1s) Index")
    if default_market not in market_by_label:
        default_market = market_labels[0]
    if _safe_float(st.session_state.get("synthetic_instant_min_rr"), 4.0) > 4.0:
        st.session_state.synthetic_instant_min_rr = 4.0
    if (
        _safe_float(st.session_state.get("synthetic_target_profit"), 4.0) == 25.0
        and _safe_float(st.session_state.get("synthetic_max_loss"), 1.0) == 1.0
    ):
        st.session_state.synthetic_target_profit = 4.0

    control_cols = st.columns([1.28, 0.76, 0.76, 0.76], gap="small")
    with control_cols[0]:
        selected_label = st.selectbox(
            "Synthetic Index",
            market_labels,
            index=market_labels.index(default_market),
            key="synthetic_market_label",
            format_func=lambda label: f"{label} ({market_by_label[label]['symbol']})",
            help="Deriv regular volatility indices and 1s volatility indices are separate symbols with different live prices.",
        )
    with control_cols[1]:
        stake = st.number_input(
            "Position Amount",
            min_value=0.35,
            value=1.0,
            step=0.01,
            format="%.2f",
            key="synthetic_stake",
            help="This is the Deriv stake amount Finwise sends when opening the multiplier position.",
        )
    with control_cols[2]:
        target_profit = st.number_input(
            "Target Profit",
            min_value=0.1,
            max_value=10000.0,
            value=4.0,
            step=0.5,
            key="synthetic_target_profit",
        )
    with control_cols[3]:
        max_loss = st.number_input("Max Loss", min_value=0.1, max_value=10000.0, value=1.0, step=0.25, key="synthetic_max_loss")

    selected_market = market_by_label[selected_label]
    selected_symbol = str(selected_market["symbol"])
    timing_cols = st.columns([0.78, 0.78, 1.0, 1.0], gap="small")
    with timing_cols[0]:
        leverage = st.selectbox("Leverage", [100, 300, 500, 1000], index=1, key="synthetic_leverage")
    with timing_cols[1]:
        timeframe = st.selectbox("Timeframe", ["Ticks", "1m", "5m", "15m", "30m", "1h"], index=1, key="synthetic_timeframe")

    auto_cols = st.columns([0.58, 0.58, 0.5, 0.72, 1.0], gap="small")
    with auto_cols[0]:
        auto_analyze = st.checkbox("Auto Analyze", value=True, key="synthetic_auto_analyze")
    with auto_cols[1]:
        auto_follow_signal = st.checkbox(
            "Auto-adjust Ticket",
            value=True,
            key="synthetic_auto_follow_signal",
            disabled=not auto_analyze,
        )
    with auto_cols[2]:
        auto_refresh_seconds = st.selectbox(
            "Refresh",
            [15, 30, 60, 120, 300],
            index=1,
            key="synthetic_auto_refresh_seconds",
            format_func=lambda value: f"{value}s",
        )
    with auto_cols[3]:
        st.write("")
        manual_analysis_requested = st.button("Analyze Now", use_container_width=True, type="primary")
    with auto_cols[4]:
        synthetic_meta_preview = st.session_state.get("synthetic_signal_meta") or {}
        if synthetic_meta_preview.get("symbol") == selected_market["symbol"] and synthetic_meta_preview.get("timeframe") == timeframe:
            st.caption(
                f"Last AI update: {synthetic_meta_preview.get('updated_at', 'pending')} | "
                f"{int(synthetic_meta_preview.get('rows') or 0)} candles"
            )
        else:
            st.caption("Waiting for Deriv synthetic candle analysis.")

    instant_cols = st.columns([0.72, 0.48, 0.48, 0.48, 0.64], gap="small")
    with instant_cols[0]:
        instant_signal_enabled = st.checkbox("Instant Live Signal", value=True, key="synthetic_instant_signal_enabled")
    with instant_cols[1]:
        instant_min_confidence = st.number_input(
            "Min Conf",
            min_value=50.0,
            max_value=95.0,
            value=68.0,
            step=1.0,
            key="synthetic_instant_min_confidence",
            disabled=not instant_signal_enabled,
        )
    with instant_cols[2]:
        instant_min_rr = st.number_input(
            "Min R:R",
            min_value=1.5,
            max_value=4.0,
            value=4.0,
            step=0.25,
            key="synthetic_instant_min_rr",
            disabled=not instant_signal_enabled,
        )
    with instant_cols[3]:
        instant_risk_percent = st.number_input(
            "Risk %",
            min_value=0.1,
            max_value=5.0,
            value=1.0,
            step=0.1,
            key="synthetic_instant_risk_percent",
            disabled=not instant_signal_enabled,
        )
    with instant_cols[4]:
        instant_confirm_choice = st.selectbox(
            "Confirm TF",
            ["Auto", "1m", "5m", "15m", "30m", "1h"],
            index=0,
            key="synthetic_instant_confirm_tf",
            disabled=not instant_signal_enabled,
        )
    instant_confirmation_timeframe = "" if instant_confirm_choice == "Auto" else instant_confirm_choice

    current_signal_meta = st.session_state.get("synthetic_signal_meta") or {}
    has_current_signal = (
        current_signal_meta.get("symbol") == selected_market["symbol"]
        and current_signal_meta.get("timeframe") == timeframe
        and bool(st.session_state.get("synthetic_signal"))
    )

    analysis_result = {}
    if manual_analysis_requested:
        with st.spinner("Fetching Deriv synthetic candles and running AI worker analysis..."):
            analysis_result, analysis_error = _store_synthetic_deriv_analysis(
                username=username,
                selected_market=selected_market,
                selected_label=selected_label,
                timeframe=timeframe,
                stake=float(stake),
                deriv_token=st.session_state.get("deriv_api_token", deriv_token),
                trigger="manual",
            )
        if analysis_error:
            st.warning(analysis_error)
        else:
            st.success(f"AI worker analyzed {int((st.session_state.get('synthetic_signal_meta') or {}).get('rows') or 0)} Deriv candles.")

    if not analysis_result and has_current_signal:
        analysis_result = st.session_state.get("synthetic_signal") or {}

    if auto_analyze and auto_follow_signal and analysis_result:
        st.session_state.synthetic_direction = _synthetic_direction_from_signal(analysis_result)
        st.session_state.synthetic_entry_model = _synthetic_entry_model_from_signal(analysis_result, selected_label)
    elif auto_analyze and auto_follow_signal and has_current_signal:
        recommended_direction = st.session_state.get("synthetic_ai_direction")
        recommended_entry_model = st.session_state.get("synthetic_ai_entry_model")
        if recommended_direction in {"Buy", "Sell", "Wait"}:
            st.session_state.synthetic_direction = recommended_direction
        if recommended_entry_model in {"Breakout", "Pullback", "Spike capture", "Range break"}:
            st.session_state.synthetic_entry_model = recommended_entry_model

    with timing_cols[2]:
        direction = st.selectbox("Direction", ["Buy", "Sell", "Wait"], index=2, key="synthetic_direction")
    with timing_cols[3]:
        entry_model = st.selectbox(
            "Entry Model",
            ["Breakout", "Pullback", "Spike capture", "Range break"],
            index=0,
            key="synthetic_entry_model",
        )

    exposure = stake * float(leverage)
    required_move_pct = (target_profit / exposure) * 100 if exposure else 0.0
    stop_move_pct = (max_loss / exposure) * 100 if exposure else 0.0
    reward_multiple = target_profit / max_loss if max_loss else 0.0
    stop_distance_ready = stop_move_pct >= 0.12
    target_ratio_ready = 2.0 <= reward_multiple <= 4.0
    ticket_safety_failures = []
    if not target_ratio_ready:
        ticket_safety_failures.append("Reward/risk must be between 2R and 4R")
    if not stop_distance_ready:
        ticket_safety_failures.append("Max Loss is too tight for this stake/leverage; widen Max Loss or lower leverage")
    if required_move_pct > 6.0:
        ticket_safety_failures.append("Target move is too far for an instant synthetic ticket")
    if deriv_connected and deriv_balance > 0 and float(stake) > deriv_balance:
        ticket_safety_failures.append("Position amount exceeds connected Deriv balance")

    live_quote, live_quote_error = _fetch_synthetic_live_quote(
        selected_symbol,
        st.session_state.get("deriv_api_token", deriv_token),
        max_age_seconds=10,
    )
    live_quote_value = _safe_float(live_quote.get("quote")) if live_quote else 0.0
    live_quote_pip_size = int(live_quote.get("pip_size") or 4) if live_quote else 4
    live_quote_text = _format_deriv_quote(live_quote_value, live_quote_pip_size) if live_quote_value > 0 else "Unavailable"
    live_quote_note = (
        f"{selected_symbol} | tick {live_quote.get('timestamp') or 'live'}"
        if live_quote_value > 0
        else f"{selected_symbol} | live quote unavailable: {live_quote_error or 'waiting for Deriv'}"
    )

    if required_move_pct <= 0.35 and stop_move_pct <= 0.12:
        heat = "Ultra tight"
        heat_note = "Timing must be very sharp; one small move against entry can end the trade."
    elif required_move_pct <= 1.2:
        heat = "Aggressive"
        heat_note = "The target is reachable only if entry timing and momentum line up."
    else:
        heat = "Slow target"
        heat_note = "The target needs a larger move, so avoid forcing a low-quality entry."

    st.markdown(
        f"""
        <div class="synthetic-panel">
          <div class="synthetic-grid">
            <div class="synthetic-metric">
              <div class="synthetic-label">Market</div>
              <div class="synthetic-value">{escape(selected_label)}</div>
              <div class="synthetic-note">{escape(selected_market["profile"])} | Symbol {escape(selected_symbol)}</div>
            </div>
            <div class="synthetic-metric synthetic-ok">
              <div class="synthetic-label">Live Deriv Price</div>
              <div class="synthetic-value">{escape(live_quote_text)}</div>
              <div class="synthetic-note">{escape(live_quote_note)}</div>
            </div>
            <div class="synthetic-metric">
              <div class="synthetic-label">Controlled Size</div>
              <div class="synthetic-value">${exposure:,.2f}</div>
              <div class="synthetic-note">${stake:,.2f} position amount at 1:{int(leverage)} leverage.</div>
            </div>
            <div class="synthetic-metric">
              <div class="synthetic-label">Move Needed</div>
              <div class="synthetic-value">{required_move_pct:.3f}%</div>
              <div class="synthetic-note">Approximate move needed to reach ${target_profit:,.2f}.</div>
            </div>
            <div class="synthetic-metric synthetic-warn">
              <div class="synthetic-label">Stop Distance</div>
              <div class="synthetic-value">{stop_move_pct:.3f}%</div>
              <div class="synthetic-note">Approximate adverse move that risks ${max_loss:,.2f}.</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    checklist_cols = st.columns([1.05, 1.05, 0.9], gap="medium")
    with checklist_cols[0]:
        st.markdown("**Timing Gate**")
        trigger_ready = st.checkbox("Entry trigger printed", key="synthetic_trigger_ready")
        momentum_ready = st.checkbox("Momentum agrees with direction", key="synthetic_momentum_ready")
        rejection_ready = st.checkbox("No fresh rejection against entry", key="synthetic_rejection_ready")
    with checklist_cols[1]:
        st.markdown("**Risk Gate**")
        stop_ready = st.checkbox("Stop distance is not ultra tight", value=stop_distance_ready, key="synthetic_stop_ready")
        target_ready = st.checkbox("Target is 2R to 4R", value=target_ratio_ready, key="synthetic_target_ready")
        wait_ready = st.checkbox("Willing to skip if late", key="synthetic_skip_ready")
    with checklist_cols[2]:
        ready_count = sum(bool(value) for value in [trigger_ready, momentum_ready, rejection_ready, stop_ready, target_ready, wait_ready])
        ready_status = "Ready" if ready_count == 6 and direction != "Wait" and not ticket_safety_failures else "Wait"
        st.metric("Gate", ready_status)
        st.metric("Checks", f"{ready_count}/6")
        st.metric("Reward/Risk", f"{reward_multiple:.2f}R")
    if ticket_safety_failures:
        st.warning("Ticket safety: " + "; ".join(ticket_safety_failures))

    plan = {
        "username": username,
        "market": selected_label,
        "symbol": selected_market["symbol"],
        "stake": float(stake),
        "position_amount": float(stake),
        "target_profit": float(target_profit),
        "max_loss": float(max_loss),
        "leverage": int(leverage),
        "timeframe": timeframe,
        "direction": direction,
        "entry_model": entry_model,
        "required_move_pct": round(required_move_pct, 6),
        "stop_move_pct": round(stop_move_pct, 6),
        "reward_multiple": round(reward_multiple, 3),
        "heat": heat,
        "ready_status": ready_status,
        "ticket_safety_failures": ticket_safety_failures,
    }

    st.markdown(
        f"""
        <div class="synthetic-panel">
          <div class="synthetic-kicker">Manual Ticket</div>
          <div class="synthetic-title" style="font-size:1.35rem;">{escape(direction)} {escape(selected_label)} on {escape(timeframe)}</div>
          <div class="synthetic-copy">
            Entry model: {escape(entry_model)} | Heat: {escape(heat)} | {escape(heat_note)}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    execution_confirmed = st.checkbox(
        "I understand Execute Live sends a real Deriv multiplier order.",
        key="synthetic_live_execution_confirmed",
        disabled=not deriv_connected,
        help="This must be checked before Finwise sends the Deriv buy request.",
    )
    if not deriv_connected:
        execution_confirmed = False

    live_gate_failures = []
    if not deriv_connected:
        live_gate_failures.append("Connect Deriv first")
    if direction == "Wait":
        live_gate_failures.append("Choose Buy or Sell")
    if ready_count < 6:
        live_gate_failures.append("Complete all timing and risk checks")
    live_gate_failures.extend(ticket_safety_failures)
    if not execution_confirmed:
        live_gate_failures.append("Confirm live execution")
    can_execute_live = not live_gate_failures
    live_button_help = "Ready to send a Deriv multiplier order." if can_execute_live else "; ".join(live_gate_failures)

    action_cols = st.columns([0.42, 0.42, 1.0], gap="small")
    with action_cols[0]:
        if st.button("Save Synthetic Plan", use_container_width=True, type="primary"):
            st.session_state.synthetic_trade_plan = plan
            st.success("Synthetic trade plan saved in this session.")
    with action_cols[1]:
        if st.button("Execute Live", use_container_width=True, disabled=not can_execute_live, help=live_button_help):
            st.session_state.synthetic_trade_plan = plan
            token_for_execution = st.session_state.get("deriv_api_token") or deriv_token
            with st.spinner("Sending Deriv multiplier order..."):
                execution = execute_deriv_multiplier_trade(
                    symbol=selected_market["symbol"],
                    side=direction,
                    stake=float(stake),
                    multiplier=int(leverage),
                    target_profit=float(target_profit),
                    max_loss=float(max_loss),
                    currency=deriv_currency,
                    token=token_for_execution,
                )

            st.session_state.synthetic_last_execution = {
                "ok": execution.ok,
                "message": execution.message,
                "contract_id": execution.contract_id,
                "transaction_id": execution.transaction_id,
                "contract_type": execution.contract_type,
                "buy_price": execution.buy_price,
                "balance_after": execution.balance_after,
            }

            if execution.ok:
                if execution.balance_after > 0:
                    st.session_state.deriv_connection_status = {
                        **deriv_status,
                        "ok": True,
                        "loginid": deriv_login,
                        "currency": deriv_currency,
                        "balance": execution.balance_after,
                        "message": "Deriv API connected.",
                    }
                notes = (
                    f"Deriv {execution.contract_type} contract {execution.contract_id}; "
                    f"transaction {execution.transaction_id}; buy price {execution.buy_price:.2f}; "
                    f"target profit {target_profit:.2f}; max loss {max_loss:.2f}. {execution.longcode}"
                ).strip()
                try:
                    log_trade_entry(
                        username=username,
                        broker_name="Deriv",
                        account_alias=deriv_login,
                        source="synthetic_deriv_live",
                        status="executed",
                        symbol=selected_market["symbol"],
                        timeframe=timeframe,
                        side=direction.upper(),
                        confidence=0.0,
                        quantity=float(stake),
                        notional_usd=float(stake) * float(leverage),
                        entry_price=float(execution.spot or 0),
                        stop_loss=0.0,
                        take_profit=0.0,
                        risk_reward_ratio=float(reward_multiple or 0),
                        notes=notes,
                    )
                except Exception as exc:
                    st.warning(f"Deriv executed the trade, but Finwise could not save it to the journal: {exc}")
                st.success(
                    f"Deriv executed {execution.contract_type} contract {execution.contract_id or ''} "
                    f"at {deriv_currency} {execution.buy_price:,.2f}."
                )
            else:
                st.error(execution.message or "Deriv execution failed.")
    with action_cols[2]:
        saved_plan = st.session_state.get("synthetic_trade_plan")
        if saved_plan:
                st.caption(
                    f"Saved: {saved_plan['direction']} {saved_plan['market']} | "
                    f"amount ${saved_plan['stake']:.2f} | target ${saved_plan['target_profit']:.2f}."
                )
        last_execution = st.session_state.get("synthetic_last_execution")
        if last_execution:
            if last_execution.get("ok"):
                st.caption(
                    f"Last Deriv execution: {last_execution.get('contract_type', '')} "
                    f"{last_execution.get('contract_id', '')} | {deriv_currency} {float(last_execution.get('buy_price') or 0):,.2f}."
                )
            else:
                st.caption(f"Last Deriv execution failed: {last_execution.get('message', 'Unknown error')}")

    _render_synthetic_deriv_analysis_panel(
        username=username,
        selected_market=selected_market,
        selected_label=selected_label,
        timeframe=timeframe,
        stake=float(stake),
        deriv_token=st.session_state.get("deriv_api_token", deriv_token),
        auto_analyze=auto_analyze,
        auto_follow_signal=auto_follow_signal,
        auto_refresh_seconds=int(auto_refresh_seconds or 30),
        instant_signal_enabled=instant_signal_enabled,
        instant_min_confidence=float(instant_min_confidence or 68.0),
        instant_min_rr=float(instant_min_rr or 4.0),
        instant_risk_percent=float(instant_risk_percent or 1.0),
        instant_confirmation_timeframe=instant_confirmation_timeframe,
    )


def _mobile_nav_items():
    return [
        ("Home", "Dashboard", "home"),
        ("Markets", "Market Analysis", "markets"),
        ("Desk", "Trading Desk", "desk"),
        ("Journal", "Trade Journal", "journal"),
        ("Settings", "Account", "settings"),
    ]


def _mobile_web_page_slug(choice: str) -> str:
    page_map = {
        "Dashboard": "home",
        "Market Analysis": "markets",
        "Trading Desk": "desk",
        "Synthetic Trade": "desk",
        "Signal Result": "desk",
        "Trade Journal": "journal",
        "Account": "settings",
        "Upgrade": "settings",
    }
    return page_map.get(choice, "home")


def _configured_mobile_public_base() -> str:
    return (
        str(os.getenv("FINWISE_PUBLIC_MOBILE_BASE", "") or "").strip()
        or str(os.getenv("FINWISE_PUBLIC_CHART_API_BASE", "") or "").strip()
    )


def _configured_chart_public_base() -> str:
    return (
        str(os.getenv("FINWISE_PUBLIC_CHART_API_BASE", "") or "").strip()
        or str(os.getenv("FINWISE_PUBLIC_MOBILE_BASE", "") or "").strip()
    )


def _derived_mobile_public_base() -> str:
    host_candidates = _request_host_candidates()
    if not host_candidates:
        return ""
    host = str(host_candidates[0] or "").strip()
    if not host or _host_is_local_or_private(host):
        return ""
    label, dot, remainder = host.partition(".")
    prefix, dash, port_fragment = label.rpartition("-")
    if not prefix or dash != "-" or not port_fragment.isdigit():
        return ""
    scheme = "https" if _request_uses_https() else "http"
    rewritten_host = f"{prefix}-{API_SERVER_PORT}"
    if remainder:
        rewritten_host = f"{rewritten_host}.{remainder}"
    return f"{scheme}://{rewritten_host}"


def _normalized_request_host(raw_host: str) -> str:
    candidate = str(raw_host or "").strip()
    if not candidate:
        return ""
    if "://" not in candidate:
        candidate = f"//{candidate}"
    parsed = urlparse(candidate)
    host = str(parsed.netloc or parsed.path or "").strip().split("/")[0]
    if host.startswith("[") and "]" in host:
        return host[1:host.index("]")].strip().lower()
    if host.count(":") == 1:
        maybe_host, maybe_port = host.rsplit(":", 1)
        if maybe_port.isdigit():
            host = maybe_host
    return host.strip().lower()


def _request_host_candidates() -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for header_name in (
        "x-forwarded-host",
        "x-original-host",
        "x-host",
        "host",
        ":authority",
    ):
        raw_value = _request_header_value(header_name)
        if not raw_value:
            continue
        for item in str(raw_value).split(","):
            normalized = _normalized_request_host(item)
            if normalized and normalized not in seen:
                values.append(normalized)
                seen.add(normalized)
    return values


def _host_is_local_or_private(hostname: str) -> bool:
    host = _normalized_request_host(hostname)
    if not host:
        return True
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    if host.endswith(".local"):
        return True
    try:
        parsed_ip = ipaddress.ip_address(host)
        return bool(parsed_ip.is_private or parsed_ip.is_loopback or parsed_ip.is_link_local)
    except ValueError:
        return "." not in host


def _can_use_standalone_mobile() -> bool:
    try:
        override = str(st.query_params.get("standalone_mobile", "") or "").strip().lower()
    except Exception:
        override = ""
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False

    if _ensure_streamlit_mobile_proxy_routes():
        return True
    if _configured_mobile_public_base():
        return True
    if _derived_mobile_public_base():
        return True
    host_candidates = _request_host_candidates()
    if not host_candidates:
        return False
    return _host_is_local_or_private(host_candidates[0])


def _render_mobile_web_redirect(choice: str = "Dashboard", *, auth_view: str = "") -> None:
    proxy_ready = _ensure_streamlit_mobile_proxy_routes()
    _start_terminal_chart_api()
    _start_market_feed()
    configured_base = _configured_mobile_public_base()
    derived_public_base = _derived_mobile_public_base()
    page_slug = _mobile_web_page_slug(choice)
    auth_slug = str(auth_view or "").strip().lower()
    if auth_slug == "reset_password":
        auth_slug = "reset"
    target_url = ""
    if proxy_ready:
        target_url = "/mobile/"
    elif derived_public_base:
        target_url = f"{derived_public_base.rstrip('/')}/mobile/"

    if target_url:
        query_parts: list[str] = []
        if page_slug:
            query_parts.append(f"page={quote_plus(page_slug)}")
        if auth_slug:
            query_parts.append(f"auth={quote_plus(auth_slug)}")
        if query_parts:
            target_url = f"{target_url}?{'&'.join(query_parts)}"
        st.html(
            f"""
            <style>
            #MainMenu, header, footer, [data-testid="stToolbar"], [data-testid="stStatusWidget"] {{
                display: none !important;
            }}
            .block-container {{
                padding: 0 !important;
                max-width: 100% !important;
            }}
            [data-testid="stAppViewContainer"] {{
                background: #020816 !important;
            }}
            #finwise-mobile-host-frame {{
                position: fixed;
                inset: 0;
                width: 100vw;
                height: 100vh;
                border: 0;
                background: #020816;
                z-index: 999999;
            }}
            </style>
            <iframe
                id="finwise-mobile-host-frame"
                src="{escape(target_url, quote=True)}"
                title="Finwise Mobile"
                allow="clipboard-read; clipboard-write"
                referrerpolicy="same-origin"
            ></iframe>
            """,
            width="stretch",
        )
        return
    st.html(
        f"""
        <script>
        (function() {{
            const configuredBase = {json.dumps(configured_base)};
            const page = {json.dumps(page_slug)};
            const auth = {json.dumps(auth_slug)};
            let base = configuredBase.trim();
            if (!base) {{
                const protocol = window.location.protocol === "https:" ? "https:" : "http:";
                const hostname = window.location.hostname || "127.0.0.1";
                base = `${{protocol}}//${{hostname}}:{API_SERVER_PORT}`;
            }}
            base = base.replace(/\\/+$/, "");
            const nextUrl = new URL(base + "/mobile/");
            if (page) nextUrl.searchParams.set("page", page);
            if (auth) nextUrl.searchParams.set("auth", auth);
            const target = nextUrl.toString();
            const go = () => {{
                try {{
                    if (window.top && window.top !== window) {{
                        window.top.location.href = target;
                    }} else {{
                        window.location.href = target;
                    }}
                }} catch (err) {{
                    window.location.href = target;
                }}
            }};

            go();
            window.setTimeout(go, 250);
            window.setTimeout(go, 1200);
        }})();
        </script>
        <div style="height:0;overflow:hidden;opacity:0;pointer-events:none;" aria-hidden="true"></div>
        """,
        width="stretch",
    )


def _mobile_page_metadata(choice: str) -> tuple[str, str]:
    page_map = {
        "Dashboard": (
            "Dashboard",
            "Live market overview across your tracked instruments.",
        ),
        "Market Analysis": (
            "Market Analysis",
            "Live chart, depth, and execution levels for your selected market.",
        ),
        "Trading Desk": (
            "Trading Desk",
            "Signal workspace and broker execution in one mobile workflow.",
        ),
        "Synthetic Trade": (
            "Synthetic Trade",
            "Timing and risk plan for synthetic index trades.",
        ),
        "Trade Journal": (
            "Trade Journal",
            "Track every Finwise trade, daily P&L, and lifetime performance.",
        ),
        "Account": (
            "Settings",
            "Notification routes, security, and workspace preferences.",
        ),
        "Upgrade": (
            "Upgrade",
            "Unlock advanced AI signals, broker execution, and premium tools.",
        ),
        "Signal Result": (
            "Signal Result",
            "Focused AI trade breakdown for the active market setup.",
        ),
    }
    return page_map.get(choice, ("Finwise AI", "Live market intelligence for your account."))


def _render_mobile_shell_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --fw-mobile-bg: #0b0e14;
            --fw-mobile-surface: rgba(16, 22, 34, 0.84);
            --fw-mobile-surface-strong: rgba(18, 26, 39, 0.94);
            --fw-mobile-border: rgba(255,255,255,0.07);
            --fw-mobile-text: #e8eef8;
            --fw-mobile-muted: #7d8aa3;
            --fw-mobile-accent: #22e7ca;
        }
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"] {
            background:
                radial-gradient(circle at top center, rgba(34,231,202,0.08), transparent 24%),
                radial-gradient(circle at bottom center, rgba(80,143,255,0.05), transparent 26%),
                var(--fw-mobile-bg) !important;
        }
        [data-testid="stSidebar"],
        [data-testid="stSidebarNav"],
        [data-testid="collapsedControl"] {
            display: none !important;
        }
        [data-testid="stAppViewContainer"] > .main .block-container {
            max-width: 430px !important;
            padding-top: 0.5rem !important;
            padding-right: 0.88rem !important;
            padding-left: 0.88rem !important;
            padding-bottom: calc(6.2rem + env(safe-area-inset-bottom)) !important;
        }
        .st-key-mobile_page_header {
            position: sticky;
            top: 0.12rem;
            z-index: 220;
            margin-bottom: 0.4rem;
        }
        .fw-mobile-header-card {
            position: relative;
            overflow: hidden;
            border-radius: 1rem;
            padding: 0.68rem 0.76rem 0.72rem;
            background:
                radial-gradient(circle at top right, rgba(34,231,202,0.12), transparent 28%),
                linear-gradient(180deg, rgba(11,18,30,0.90) 0%, rgba(10,16,26,0.84) 100%);
            border: 1px solid var(--fw-mobile-border);
            box-shadow: 0 12px 28px rgba(0,0,0,0.2);
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
        }
        .fw-mobile-brand-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.58rem;
            margin-bottom: 0.42rem;
        }
        .fw-mobile-brand-lockup {
            display: flex;
            align-items: center;
            gap: 0.58rem;
            min-width: 0;
        }
        .fw-mobile-brand-logo {
            width: 1.7rem;
            height: 1.7rem;
            border-radius: 0.58rem;
            display: grid;
            place-items: center;
            overflow: hidden;
            color: #041921;
            font-size: 0.76rem;
            font-weight: 900;
            background: linear-gradient(135deg, #2ef1d3 0%, #35d6ff 100%);
            box-shadow: 0 8px 18px rgba(34,231,202,0.18);
        }
        .fw-mobile-brand-logo img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }
        .fw-mobile-brand-name {
            color: #f5fbff;
            font-size: 0.82rem;
            font-weight: 800;
            letter-spacing: -0.02em;
        }
        .fw-mobile-brand-tag {
            color: var(--fw-mobile-muted);
            font-size: 0.58rem;
            margin-top: 0.08rem;
            letter-spacing: 0.04em;
        }
        .fw-mobile-live-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.38rem;
            padding: 0.24rem 0.5rem;
            border-radius: 999px;
            border: 1px solid rgba(34,231,202,0.2);
            background: rgba(34,231,202,0.08);
            color: #8ff6e7;
            font-size: 0.58rem;
            font-weight: 800;
            white-space: nowrap;
        }
        .fw-mobile-live-pill::before {
            content: "";
            width: 0.42rem;
            height: 0.42rem;
            border-radius: 999px;
            background: #22e7ca;
            box-shadow: 0 0 12px rgba(34,231,202,0.72);
        }
        .fw-mobile-page-title {
            color: #ffffff;
            font-size: 1.06rem;
            font-weight: 900;
            letter-spacing: -0.04em;
            line-height: 1.05;
        }
        .fw-mobile-page-subtitle {
            color: #96a8c3;
            font-size: 0.64rem;
            line-height: 1.36;
            margin-top: 0.18rem;
        }
        .fw-mobile-link-tabs {
            display: grid;
            gap: 0.34rem;
            margin: 0.24rem 0 0.58rem;
        }
        .fw-mobile-link-tabs.is-scrollable {
            display: flex;
            align-items: stretch;
            overflow-x: auto;
            overflow-y: hidden;
            gap: 0.34rem;
            padding-bottom: 0.08rem;
            scroll-snap-type: x proximity;
            scrollbar-width: none;
        }
        .fw-mobile-link-tabs.is-scrollable::-webkit-scrollbar {
            display: none;
        }
        .fw-mobile-link-tabs.is-scrollable .fw-mobile-link-tab {
            flex: 0 0 auto;
            min-width: var(--fw-mobile-tab-min, 4.8rem);
            scroll-snap-align: start;
        }
        .fw-mobile-link-tab {
            display: flex;
            align-items: center;
            justify-content: center;
            text-decoration: none !important;
            transition: border-color 140ms ease, transform 140ms ease, color 140ms ease, background 140ms ease;
        }
        .fw-mobile-link-tab--pill {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 1.94rem;
            padding: 0.34rem 0.42rem;
            border-radius: 0.9rem;
            border: 1px solid rgba(255,255,255,0.06);
            background: rgba(14, 22, 34, 0.78);
            color: #91a2ba !important;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.01em;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.02);
        }
        .fw-mobile-link-tab--pill.is-active {
            color: #ebfffc !important;
            border-color: rgba(34,231,202,0.22);
            background: linear-gradient(180deg, rgba(34,231,202,0.16) 0%, rgba(53,214,255,0.08) 100%);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.04), 0 10px 22px rgba(0,0,0,0.14);
        }
        .fw-mobile-link-tab--pill:hover {
            color: #dbeaf8 !important;
            border-color: rgba(255,255,255,0.09);
            transform: translateY(-1px);
        }
        .fw-mobile-link-tabs--rail {
            gap: 0.22rem;
            margin: 0.22rem 0 0.56rem;
            padding: 0.16rem;
            border-radius: 1rem;
            border: 1px solid rgba(255,255,255,0.05);
            background: rgba(12, 19, 31, 0.62);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.02);
        }
        .fw-mobile-link-tab--rail {
            min-height: 1.8rem;
            padding: 0.18rem 0.28rem 0.28rem;
            border-radius: 0.76rem;
            border-bottom: 2px solid transparent;
            color: #8092ac !important;
            font-size: 0.68rem;
            font-weight: 800;
            letter-spacing: 0.01em;
            background: transparent;
        }
        .fw-mobile-link-tab--rail.is-active {
            color: #ecfffb !important;
            background: linear-gradient(180deg, rgba(34,231,202,0.10) 0%, rgba(53,214,255,0.04) 100%);
            border-bottom-color: rgba(34,231,202,0.7);
        }
        .fw-mobile-link-tab--rail:hover {
            color: #dbeaf8 !important;
            background: rgba(255,255,255,0.03);
        }
        .st-key-mobile_bottom_nav_shell {
            position: fixed;
            left: 50%;
            bottom: calc(env(safe-area-inset-bottom) + 0.38rem);
            transform: translateX(-50%);
            width: min(430px, calc(100vw - 0.7rem));
            z-index: 260;
            border-radius: 1.32rem;
            padding: 0.32rem;
            background: rgba(12, 18, 29, 0.68);
            border: 1px solid rgba(255,255,255,0.08);
            box-shadow: 0 16px 40px rgba(0,0,0,0.3);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
        }
        .fw-mobile-bottom-nav-grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 0.22rem;
            align-items: stretch;
        }
        .fw-mobile-bottom-nav-item {
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 0.12rem !important;
            min-height: 2.72rem;
            border-radius: 0.9rem;
            border: 1px solid rgba(255,255,255,0.04);
            background: rgba(255,255,255,0.02);
            color: #94a4bd !important;
            padding: 0.24rem 0.14rem;
            text-decoration: none !important;
            line-height: 1;
            box-shadow: none;
            transition: border-color 140ms ease, transform 140ms ease, color 140ms ease, background 140ms ease;
        }
        .fw-mobile-bottom-nav-icon {
            width: 1rem;
            height: 1rem;
            display: grid;
            place-items: center;
        }
        .fw-mobile-bottom-nav-icon svg {
            width: 1rem;
            height: 1rem;
            stroke: currentColor;
            stroke-width: 1.8;
            stroke-linecap: round;
            stroke-linejoin: round;
            fill: none;
        }
        .fw-mobile-bottom-nav-label {
            width: 100%;
            display: block;
            margin: 0;
            text-align: center;
            white-space: nowrap;
            font-size: 0.5rem;
            font-weight: 800;
            letter-spacing: 0.01em;
        }
        .fw-mobile-bottom-nav-item.is-active {
            color: #d9fffa !important;
            background: linear-gradient(180deg, rgba(34,231,202,0.20) 0%, rgba(54,122,255,0.12) 100%);
            border-color: rgba(34,231,202,0.22);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 8px 16px rgba(0,0,0,0.16);
        }
        .fw-mobile-bottom-nav-item:hover {
            border-color: rgba(255,255,255,0.09);
            transform: translateY(-1px);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_mobile_page_header(choice: str) -> None:
    title, subtitle = _mobile_page_metadata(choice)
    logo_inner = (
        f'<img src="{APP_LOGO_DATA_URI}" alt="Finwise AI logo" />'
        if APP_LOGO_DATA_URI else
        "F"
    )
    with st.container(key="mobile_page_header"):
        st.markdown(
            f"""
            <div class="fw-mobile-header-card">
                <div class="fw-mobile-brand-row">
                    <div class="fw-mobile-brand-lockup">
                        <div class="fw-mobile-brand-logo">{logo_inner}</div>
                        <div>
                            <div class="fw-mobile-brand-name">Finwise AI</div>
                            <div class="fw-mobile-brand-tag">Mobile Workspace</div>
                        </div>
                    </div>
                    <div class="fw-mobile-live-pill">Live Feed</div>
                </div>
                <div class="fw-mobile-page-title">{escape(title)}</div>
                <div class="fw-mobile-page-subtitle">{escape(subtitle)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_mobile_bottom_nav(choice: str) -> None:
    with st.container(key="mobile_bottom_nav_shell"):
        render_mobile_bottom_nav_links(
            items=_mobile_nav_items(),
            current_value=choice,
            query_key="mnav",
        )


def _render_mobile_main_app(username: str, premium: bool, choice: str) -> None:
    _render_mobile_shell_styles()
    if choice not in {"Dashboard", "Market Analysis"}:
        _render_mobile_page_header(choice)

    if choice == "Dashboard":
        _render_page_safely("Dashboard", lambda: mobile_dashboard_page(username))
    elif choice == "Market Analysis":
        _render_page_safely("Market Analysis", lambda: ai_page(username, embedded_in_trading_desk=False))
    elif choice == "Trading Desk":
        _render_page_safely("Trading Desk", lambda: mobile_trading_desk_page(username, premium))
    elif choice == "Synthetic Trade":
        st.session_state.trading_desk_view = "Synthetic Trade"
        st.query_params["mdeskmode"] = "Synthetic Trade"
        _render_page_safely("Trading Desk", lambda: mobile_trading_desk_page(username, premium))
    elif choice == "Signal Result":
        _render_page_safely("Signal Result", lambda: signal_result_page(mobile=True))
    elif choice == "Trade Journal":
        _render_page_safely("Trade Journal", lambda: mobile_trade_journal_page(username))
    elif choice == "Upgrade":
        st.markdown(
            """
            <div style="background:linear-gradient(180deg, rgba(14,22,34,0.96), rgba(10,18,28,0.94));
                        border:1px solid rgba(255,255,255,0.06);border-radius:22px;padding:22px 18px;
                        box-shadow:0 22px 48px rgba(0,0,0,0.24);">
                <div style="color:#6d7892;font-size:11px;font-weight:800;letter-spacing:0.12em;text-transform:uppercase;">Premium</div>
                <div style="color:white;font-size:24px;font-weight:900;letter-spacing:-0.04em;margin-top:8px;">Upgrade to Premium</div>
                <div style="color:#8ea6bb;font-size:13px;line-height:1.7;margin-top:10px;">
                    Unlock unlimited AI signals, broker execution, mobile trading workflow, and premium routing tools.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height:0.7rem'></div>", unsafe_allow_html=True)
        if st.button("Upgrade Now", key="mobile_upgrade_now", use_container_width=True, type="primary"):
            _render_page_safely("Checkout", lambda: st.markdown(f"[Complete Payment]({create_checkout_session()})"))
    elif choice == "Account":
        _render_page_safely("Settings", lambda: mobile_account_page(username))

    _render_mobile_bottom_nav(choice)


def main_app():
    username = st.session_state.username
    premium  = is_premium(username)
    _flush_external_redirect()
    if (
        st.session_state.get("awaiting_oauth")
        and st.session_state.get("oauth_returned")
        and str(st.session_state.get("auth_otp_context", "") or "").strip().lower() == "password_change"
    ):
        st.info("Completing Gmail authorization for password verification, please wait...")
        _complete_auth_otp_after_oauth_return()
        return
    _complete_pending_broker_oauth(username)
    layout_mode = _resolve_viewport_mode()
    _render_viewport_debug_panel(layout_mode)
    if layout_mode == "mobile":
        choice = _normalize_nav_choice(
            resolve_query_value(
                "mnav",
                default=st.session_state.get("nav_choice", "Dashboard"),
                allowed={
                    "Dashboard",
                    "Market Analysis",
                    "Trading Desk",
                    "Synthetic Trade",
                    "Trade Journal",
                    "Upgrade",
                    "Account",
                    "Signal Result",
                },
                session_key="nav_choice",
            )
        )
        st.session_state.nav_choice = choice
        if choice == "Signal Result" and "last_signal" not in st.session_state:
            choice = "Trading Desk"
            st.session_state.nav_choice = "Trading Desk"
        if _can_use_standalone_mobile() and choice != "Synthetic Trade":
            _render_mobile_web_redirect(choice)
        else:
            _render_mobile_main_app(username, premium, choice)
        return
    choice = _normalize_nav_choice(st.session_state.get("nav_choice", "Dashboard"))
    if choice == "Synthetic Trade":
        st.session_state.trading_desk_view = "Synthetic Trade"
        st.query_params["mdeskmode"] = "Synthetic Trade"
        choice = "Trading Desk"
        st.session_state.nav_choice = "Trading Desk"
    if st.session_state.get("nav_choice") != choice:
        st.session_state.nav_choice = choice
    _ensure_page_runtime_services(choice)
    if _page_requires_broker_restore(choice):
        _restore_saved_broker_session(username)

    # ── SIDEBAR ──────────────────────────────────────────────
    login_notice = st.session_state.pop("login_notice", "")
    if login_notice:
        st.success(login_notice)

    if premium:
        nav_items = [
            ("Dashboard",       "Dashboard",       ":material/home:"),
            ("Market Analysis", "Market Analysis", ":material/monitoring:"),
            ("Trading Desk",    "Trading Desk",    ":material/track_changes:"),
            ("Trade Journal",   "Trade Journal",   ":material/description:"),
            ("Settings",        "Account",         ":material/settings:"),
        ]
    else:
        nav_items = [
            ("Dashboard",       "Dashboard",       ":material/home:"),
            ("Market Analysis", "Market Analysis", ":material/monitoring:"),
            ("Trading Desk",    "Trading Desk",    ":material/track_changes:"),
            ("Trade Journal",   "Trade Journal",   ":material/description:"),
            ("Upgrade",         "Upgrade",         ":material/diamond:"),
            ("Settings",        "Account",         ":material/settings:"),
        ]

    with st.sidebar:
        sidebar_logo_inner = (
            f'<img src="{APP_LOGO_DATA_URI}" alt="Finwise AI logo" />'
            if APP_LOGO_DATA_URI else
            "F"
        )
        st.markdown(f"""
        <div class="sidebar-logo">
            <div class="sidebar-logo-icon">{sidebar_logo_inner}</div>
            Finwise AI
        </div>
        """, unsafe_allow_html=True)

        if "nav_choice" not in st.session_state:
            st.session_state.nav_choice = "Dashboard"

        # ✅ FIXED: nav buttons are now correctly INSIDE the sidebar block
        for i, (label, key, icon_name) in enumerate(nav_items):
            unique_key = f"nav_{key}_{i}"
            is_active = st.session_state.nav_choice == key
            if st.button(
                label,
                key=unique_key,
                use_container_width=True,
                type="primary" if is_active else "secondary",
                icon=icon_name,
                icon_position="left",
            ):
                st.session_state.nav_choice = key
                st.rerun()

        st.markdown("<hr style='border-color:rgba(0,245,212,0.1);margin:16px 0;'>", unsafe_allow_html=True)

        initials = username[:2].upper()
        tier     = "Premium" if premium else "Free"
        st.markdown(f"""
        <div class="sidebar-user">
            <div class="sidebar-avatar">{initials}</div>
            <div>
                <div style="color:white;font-weight:600;font-size:13px;">{username}</div>
                <div style="font-size:11px;color:#4a7a94;">{tier}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Logout", use_container_width=True, type="primary"):
            _logout_active_session()
            st.session_state.auto_trade_broker = None
            st.session_state.auto_trade_bot = None
            st.session_state.auto_trade_status = ""
            st.session_state.broker_restore_state = {}
            st.session_state.symbol_load_state = {}
            st.session_state.trading_desk_view = "Signal Workspace"
            _clear_connected_broker_profile()
            st.session_state.nav_choice = "Dashboard"
            st.rerun()

    # ── MAIN CONTENT ─────────────────────────────────────────
    choice = _normalize_nav_choice(st.session_state.nav_choice)
    if choice == "Synthetic Trade":
        st.session_state.trading_desk_view = "Synthetic Trade"
        st.query_params["mdeskmode"] = "Synthetic Trade"
        choice = "Trading Desk"
    st.session_state.nav_choice = choice
    if choice == "Signal Result" and "last_signal" not in st.session_state:
        choice = "Trading Desk"
        st.session_state.nav_choice = "Trading Desk"

    if choice == "Dashboard":
        st.markdown(f"""
        <div class="top-bar">
            <div>
                <div class="top-bar-title">Dashboard</div>
                <div class="top-bar-sub">
                    Live market overview across your tracked instruments.
                </div>
            </div>
            <div class="top-bar-right">
                <div class="live-badge">
                    <span class="live-dot"></span> Market Live
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        _render_page_safely("Dashboard", lambda: dashboard_page(username))

    elif choice == "Market Analysis":
        _render_page_safely("Market Analysis", lambda: ai_page(username, embedded_in_trading_desk=False))

    elif choice == "Trading Desk":
        st.markdown(f"""
        <div class="top-bar">
            <div>
                <div class="top-bar-title">Trading Desk</div>
                <div class="top-bar-sub">
                    Live signals, broker connection, and manual execution in one workspace.
                </div>
            </div>
            <div class="top-bar-right">
                <div class="live-badge">
                    <span class="live-dot"></span> Desk Live
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        _render_page_safely(
            "Trading Desk",
            lambda: _render_desktop_trading_desk_page_view(
                username,
                premium,
                render_ai_page_fn=ai_page,
                auto_trade_page=auto_trade_page,
                render_synthetic_trade_page_fn=_render_synthetic_trade_page,
            ),
        )

    elif choice == "Synthetic Trade":
        st.session_state.trading_desk_view = "Synthetic Trade"
        st.session_state.nav_choice = "Trading Desk"
        st.rerun()

    elif choice == "Signal Result":
        _render_page_safely("Signal Result", signal_result_page)

    elif choice == "Trade Journal":
        st.markdown("""
        <div class="top-bar">
            <div>
                <div class="top-bar-title">Trade Journal</div>
                <div class="top-bar-sub">Track every Finwise trade, daily profit and loss, and lifetime performance.</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        _render_page_safely("Trade Journal", lambda: trade_journal_page(username))

    elif choice == "Upgrade":
            st.markdown("""
            <div class="top-bar">
                <div>
                    <div class="top-bar-title">Upgrade to Premium</div>
                    <div class="top-bar-sub">Unlock full AI power and unlimited signals.</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            st.markdown("""
            <div style="background:#0f2639;border:1px solid rgba(0,245,212,0.2);
                        border-radius:14px;padding:28px;max-width:480px;margin-top:8px;">
                <div style="font-size:32px;margin-bottom:12px;">F</div>
                <div style="font-size:20px;font-weight:700;color:white;margin-bottom:8px;">
                    Go Premium
                </div>
                <div style="color:#8ab4c8;font-size:14px;margin-bottom:20px;line-height:1.6;">
                    Unlimited AI signals per day<br>
                    WhatsApp and Telegram trade alerts<br>
                    Broker execution tools<br>
                    Priority support
                </div>
            </div>
            """, unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Upgrade Now — $8/mo"):
                _render_page_safely("Checkout", lambda: st.markdown(f"[Complete Payment]({create_checkout_session()})"))

    elif choice == "Account":
        _render_page_safely("Settings", lambda: account_page(username))

# -----------------------------------
# RUN
# -----------------------------------
try:
    if st.session_state.get("logged_in", False):
        main_app()
    else:
        _render_page_safely("Login", login_page)
except Exception as exc:
    _render_error_boundary("Application", exc)

