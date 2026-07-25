import json
import asyncio
import os
import threading
import time
from datetime import datetime

import certifi
import pandas as pd
import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import websockets
except ImportError:
    websockets = None

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def make_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = True
    retry = Retry(
        total=1,
        backoff_factor=0.25,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _bybit_rest_base_urls() -> list[str]:
    explicit_base = str(os.getenv("BYBIT_API_BASE_URL", "")).strip().rstrip("/")
    if explicit_base:
        return [explicit_base]
    return ["https://api.bybit.com", "https://api.bytick.com"]


def _bybit_url(path: str, base_url: str | None = None) -> str:
    base = (base_url or _bybit_rest_base_urls()[0]).rstrip("/")
    return f"{base}{path}"


REST_KLINE_PATH = "/v5/market/kline"
REST_TICKER_PATH = "/v5/market/tickers"
REST_ORDERBOOK_PATH = "/v5/market/orderbook"
REST_INSTRUMENTS_PATH = "/v5/market/instruments-info"
REST_KLINE_URL = _bybit_url(REST_KLINE_PATH)
REST_TICKER_URL = _bybit_url(REST_TICKER_PATH)
REST_ORDERBOOK_URL = _bybit_url(REST_ORDERBOOK_PATH)
REST_INSTRUMENTS_URL = _bybit_url(REST_INSTRUMENTS_PATH)
BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
WS_URL = "wss://stream.bybit.com/v5/public/linear"
KLINE_COLUMNS = ["time", "open", "high", "low", "close", "volume", "turnover"]
CRYPTO_SYMBOL_FALLBACK = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
    "LTCUSDT",
    "BNBUSDT",
    "TRXUSDT",
    "TONUSDT",
    "SUIUSDT",
    "APTUSDT",
    "ARBUSDT",
    "OPUSDT",
    "BTCUSDC",
    "ETHUSDC",
    "SOLUSDC",
    "XRPUSDC",
    "BTCUSD",
    "ETHUSD",
    "SOLUSD",
    "XRPUSD",
]
FOREX_CURRENCIES = {
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "CHF",
    "CAD",
    "AUD",
    "NZD",
}
FOREX_SYMBOL_FALLBACK = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "USDCAD",
    "NZDUSD",
    "EURJPY",
    "GBPJPY",
    "EURGBP",
    "EURAUD",
    "EURCAD",
    "EURCHF",
    "AUDJPY",
    "CADJPY",
    "CHFJPY",
    "GBPAUD",
    "GBPCAD",
    "GBPCHF",
    "AUDCAD",
    "AUDCHF",
    "AUDNZD",
    "NZDJPY",
]
POPULAR_SYMBOL_FALLBACK = CRYPTO_SYMBOL_FALLBACK + FOREX_SYMBOL_FALLBACK
INTERVAL_MAP = {
    "1": "1",
    "1m": "1",
    "3": "3",
    "3m": "3",
    "5": "5",
    "5m": "5",
    "15": "15",
    "15m": "15",
    "30": "30",
    "30m": "30",
    "60": "60",
    "1h": "60",
    "120": "120",
    "2h": "120",
    "240": "240",
    "4h": "240",
    "360": "360",
    "6h": "360",
    "720": "720",
    "12h": "720",
    "D": "D",
    "1d": "D",
}
PANDAS_RULES = {
    "1m": "1min",
    "3m": "3min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1H",
    "2h": "2H",
    "4h": "4H",
    "6h": "6H",
    "12h": "12H",
    "1d": "1D",
}
NORMALIZED_INTERVALS = {
    "1": "1m",
    "3": "3m",
    "5": "5m",
    "15": "15m",
    "30": "30m",
    "60": "1h",
    "120": "2h",
    "240": "4h",
    "360": "6h",
    "720": "12h",
    "D": "1d",
}
YAHOO_INTERVAL_MAP = {
    "1m": "1m",
    "3m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "2h": "60m",
    "4h": "60m",
    "6h": "60m",
    "12h": "60m",
    "1d": "1d",
}
BINANCE_INTERVAL_MAP = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "12h": "12h",
    "1d": "1d",
}
YAHOO_RANGE_BY_INTERVAL = {
    "1m": "7d",
    "3m": "7d",
    "5m": "1mo",
    "15m": "1mo",
    "30m": "2mo",
    "1h": "6mo",
    "2h": "1y",
    "4h": "1y",
    "6h": "1y",
    "12h": "2y",
    "1d": "5y",
}
YAHOO_RESAMPLE_RULES = {
    "3m": "3min",
    "2h": "2H",
    "4h": "4H",
    "6h": "6H",
    "12h": "12H",
}
INTERVAL_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
}
MAX_KLINE_PAGE_SIZE = 1000
REST_TIMEOUT_SECONDS = 5
WS_PING_TIMEOUT_SECONDS = 8
_DEFAULT_HISTORY_LIMIT = object()


def normalize_market_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "").replace("-", "").replace(" ", "")


def normalize_market_interval(interval: str) -> str:
    value = str(interval or "").strip()
    return NORMALIZED_INTERVALS.get(INTERVAL_MAP.get(value, value), "1m")


def is_forex_symbol(symbol: str) -> bool:
    symbol = normalize_market_symbol(symbol)
    if len(symbol) != 6:
        return False
    base = symbol[:3]
    quote = symbol[3:]
    return base in FOREX_CURRENCIES and quote in FOREX_CURRENCIES and base != quote


def get_market_asset_class(symbol: str) -> str:
    return "forex" if is_forex_symbol(symbol) else "crypto"


def split_market_symbol(symbol: str) -> tuple[str, str]:
    symbol = normalize_market_symbol(symbol)
    if is_forex_symbol(symbol):
        return symbol[:3], symbol[3:]
    for quote in ("USDT", "USDC", "USD", "BTC", "ETH", "EUR", "GBP"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)], quote
    return symbol, ""


def _empty_kline_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=KLINE_COLUMNS)


def resolve_market_category(symbol: str) -> str:
    symbol = normalize_market_symbol(symbol)
    if symbol.endswith("USDT") or symbol.endswith("USDC"):
        return "linear"
    if symbol.endswith("USD"):
        return "inverse"
    return "linear"


def sort_symbols(symbols) -> list:
    quote_priority = {"USDT": 0, "USDC": 1, "USD": 2}
    fallback_rank = {symbol: index for index, symbol in enumerate(POPULAR_SYMBOL_FALLBACK)}

    def _quote(symbol: str) -> str:
        for quote in ("USDT", "USDC", "USD"):
            if symbol.endswith(quote):
                return quote
        return ""

    def _sort_key(symbol: str):
        symbol = normalize_market_symbol(symbol)
        if is_forex_symbol(symbol):
            base, quote = split_market_symbol(symbol)
            return (1, fallback_rank.get(symbol, 999), quote, base, symbol)
        quote = _quote(symbol)
        base = symbol[: -len(quote)] if quote else symbol
        return (0, quote_priority.get(quote, 99), base, symbol)

    cleaned = {normalize_market_symbol(symbol) for symbol in symbols if symbol}
    return sorted(cleaned, key=_sort_key)


def _yahoo_symbol_for_forex(symbol: str) -> str:
    symbol = normalize_market_symbol(symbol)
    return f"{symbol}=X"


def _forex_request_params(interval: str, limit: int, start_ms: int | None, end_ms: int | None) -> dict:
    interval = normalize_market_interval(interval)
    yahoo_interval = YAHOO_INTERVAL_MAP.get(interval, "1m")
    params = {
        "interval": yahoo_interval,
        "includePrePost": "true",
        "events": "history",
    }
    if start_ms is not None or end_ms is not None:
        interval_seconds = INTERVAL_SECONDS.get(interval, 60)
        period2 = int((end_ms if end_ms is not None else time.time() * 1000) / 1000)
        if start_ms is not None:
            period1 = int(start_ms / 1000)
        else:
            lookback_seconds = max(limit * interval_seconds * 4, 5 * 86400)
            period1 = max(0, period2 - lookback_seconds)
        params["period1"] = period1
        params["period2"] = period2
    else:
        params["range"] = YAHOO_RANGE_BY_INTERVAL.get(interval, "1mo")
    return params


def _coerce_yahoo_forex_history(payload: dict, interval: str, limit: int) -> pd.DataFrame:
    result_items = (payload.get("chart", {}) or {}).get("result") or []
    if not result_items:
        return _empty_kline_frame()

    result = result_items[0] or {}
    timestamps = result.get("timestamp") or []
    quote_payloads = ((result.get("indicators", {}) or {}).get("quote") or [{}])
    quote = quote_payloads[0] if quote_payloads else {}
    rows = []
    for index, ts in enumerate(timestamps):
        try:
            open_value = quote.get("open", [])[index]
            high_value = quote.get("high", [])[index]
            low_value = quote.get("low", [])[index]
            close_value = quote.get("close", [])[index]
        except (IndexError, TypeError):
            continue
        if any(value is None for value in (open_value, high_value, low_value, close_value)):
            continue
        try:
            volume_value = quote.get("volume", [])[index]
        except (IndexError, TypeError):
            volume_value = 0.0
        rows.append(
            {
                "time": pd.to_datetime(int(ts), unit="s", utc=True).tz_localize(None),
                "open": float(open_value),
                "high": float(high_value),
                "low": float(low_value),
                "close": float(close_value),
                "volume": float(volume_value or 0.0),
                "turnover": 0.0,
            }
        )

    if not rows:
        return _empty_kline_frame()

    df = pd.DataFrame(rows, columns=KLINE_COLUMNS)
    df = df.dropna(subset=["time", "open", "high", "low", "close"])
    df = df.sort_values("time").drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)

    interval = normalize_market_interval(interval)
    resample_rule = YAHOO_RESAMPLE_RULES.get(interval)
    if resample_rule and not df.empty:
        df = (
            df.set_index("time")
            .resample(resample_rule)
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                    "turnover": "sum",
                }
            )
            .dropna(subset=["open", "high", "low", "close"])
            .reset_index()
        )

    if limit is not None and limit > 0 and len(df) > limit:
        df = df.tail(int(limit)).reset_index(drop=True)
    return df


def fetch_forex_history(
    symbol: str,
    interval: str = "1m",
    limit: int = 500,
    session: requests.Session = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> pd.DataFrame:
    symbol = normalize_market_symbol(symbol)
    if not is_forex_symbol(symbol):
        return _empty_kline_frame()

    active_session = session or make_session()
    should_close = session is None
    try:
        response = active_session.get(
            YAHOO_CHART_URL.format(symbol=_yahoo_symbol_for_forex(symbol)),
            params=_forex_request_params(interval, int(limit or 500), start_ms, end_ms),
            headers={"User-Agent": "FinwiseAI/1.0"},
            verify=certifi.where(),
            timeout=REST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        return _coerce_yahoo_forex_history(payload, interval, int(limit or 500))
    except Exception:
        return _empty_kline_frame()
    finally:
        if should_close:
            active_session.close()


def fetch_binance_crypto_history(
    symbol: str,
    interval: str = "1m",
    limit: int = 500,
    session: requests.Session = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> pd.DataFrame:
    symbol = normalize_market_symbol(symbol)
    if not symbol or is_forex_symbol(symbol):
        return _empty_kline_frame()

    interval = normalize_market_interval(interval)
    binance_interval = BINANCE_INTERVAL_MAP.get(interval)
    if not binance_interval:
        return _empty_kline_frame()

    try:
        limit = max(1, min(int(limit or 500), MAX_KLINE_PAGE_SIZE))
    except (TypeError, ValueError):
        limit = 500

    params = {
        "symbol": symbol,
        "interval": binance_interval,
        "limit": limit,
    }
    if start_ms is not None:
        params["startTime"] = int(start_ms)
    if end_ms is not None:
        params["endTime"] = int(end_ms)

    active_session = session or make_session()
    should_close = session is None
    try:
        response = active_session.get(
            BINANCE_KLINE_URL,
            params=params,
            headers={"User-Agent": "FinwiseAI/1.0"},
            verify=certifi.where(),
            timeout=REST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        rows = response.json()
        if not rows:
            return _empty_kline_frame()

        parsed_rows = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            parsed_rows.append(
                {
                    "time": pd.to_datetime(float(row[0]), unit="ms", utc=True).tz_localize(None),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "turnover": float(row[7]) if len(row) > 7 else 0.0,
                }
            )

        if not parsed_rows:
            return _empty_kline_frame()

        df = pd.DataFrame(parsed_rows, columns=KLINE_COLUMNS)
        df = df.dropna(subset=["time", "open", "high", "low", "close"])
        return df.sort_values("time").drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)
    except Exception:
        return _empty_kline_frame()
    finally:
        if should_close:
            active_session.close()


def _bybit_get_json(
    session: requests.Session,
    path: str,
    params: dict | None = None,
    timeout: int = REST_TIMEOUT_SECONDS,
) -> dict:
    last_error = None
    for base_url in _bybit_rest_base_urls():
        try:
            response = session.get(
                _bybit_url(path, base_url),
                params=params,
                verify=certifi.where(),
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("retCode") != 0:
                raise RuntimeError(payload.get("retMsg", "Bybit request failed"))
            return payload
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Bybit request failed: {last_error}")


def fetch_market_klines(symbol="BTCUSDT", interval="1", limit=200, session: requests.Session = None) -> pd.DataFrame:
    symbol = normalize_market_symbol(symbol)
    interval = normalize_market_interval(interval)
    try:
        limit = max(1, min(int(limit or 200), MAX_KLINE_PAGE_SIZE))
    except (TypeError, ValueError):
        limit = 200

    if is_forex_symbol(symbol):
        df = fetch_forex_history(symbol, interval=interval, limit=limit, session=session)
        if df.empty:
            return pd.DataFrame()
        return df.rename(columns={"time": "timestamp"}).sort_values("timestamp").reset_index(drop=True)

    active_session = session or make_session()
    should_close = session is None
    try:
        payload = _bybit_get_json(
            active_session,
            REST_KLINE_PATH,
            {
                "category": resolve_market_category(symbol),
                "symbol": symbol,
                "interval": INTERVAL_MAP.get(str(interval).strip(), "1"),
                "limit": limit,
            },
        )
        rows = payload.get("result", {}).get("list", [])
        if not rows:
            fallback_df = fetch_binance_crypto_history(symbol, interval=interval, limit=limit, session=active_session)
            return fallback_df.rename(columns={"time": "timestamp"}).sort_values("timestamp").reset_index(drop=True)

        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
        df["timestamp"] = pd.to_datetime(df["timestamp"].astype(float), unit="ms", utc=True).dt.tz_localize(None)
        numeric_cols = ["open", "high", "low", "close", "volume", "turnover"]
        df[numeric_cols] = df[numeric_cols].astype(float)
        return df.sort_values("timestamp").reset_index(drop=True)
    except Exception:
        fallback_df = fetch_binance_crypto_history(symbol, interval=interval, limit=limit, session=active_session)
        return fallback_df.rename(columns={"time": "timestamp"}).sort_values("timestamp").reset_index(drop=True)
    finally:
        if should_close:
            active_session.close()


def discover_tradable_symbols(session: requests.Session = None, categories=("linear", "inverse"), include_forex: bool = True) -> list:
    active_session = session or make_session()
    should_close = session is None
    discovered = []
    forex_symbols = list(FOREX_SYMBOL_FALLBACK) if include_forex else []

    try:
        for category in categories:
            cursor = None
            while True:
                params = {"category": category, "status": "Trading", "limit": 1000}
                if cursor:
                    params["cursor"] = cursor

                payload = _bybit_get_json(active_session, REST_INSTRUMENTS_PATH, params)

                result = payload.get("result", {})
                rows = result.get("list", [])
                for item in rows:
                    symbol = str(item.get("symbol", "")).upper()
                    if symbol.endswith(("USDT", "USDC", "USD")):
                        discovered.append(symbol)

                cursor = result.get("nextPageCursor")
                if not cursor:
                    break
    except Exception:
        crypto_symbols = list(CRYPTO_SYMBOL_FALLBACK)
        return sort_symbols(crypto_symbols + forex_symbols)
    finally:
        if should_close:
            active_session.close()

    if discovered:
        return sort_symbols(discovered + forex_symbols)
    return sort_symbols(list(CRYPTO_SYMBOL_FALLBACK) + forex_symbols)


class Multicandleengine:
    WS_URL = WS_URL

    def __init__(self, symbols=None, interval="1m", limit=500):
        self.symbols = sort_symbols(symbols or ["BTCUSDT", "ETHUSDT"])
        self.interval = self._normalize_interval(interval)
        self.limit = limit
        self._session = make_session()
        self._lock = threading.RLock()
        self._history_limit = max(limit * 4, 3000)
        self._rest_poll_seconds = 5
        self.history = {}
        self.market_state = {}
        self.orderbooks = {}
        self.metric_history = {}
        self.interval_history_cache = {}
        self._interval_fetching = set()
        self._symbol_directory = []

        for symbol in self.symbols:
            self._register_symbol(symbol)

    def _normalize_interval(self, interval: str) -> str:
        return normalize_market_interval(interval)

    def _interval_to_rest(self, interval: str) -> str:
        return INTERVAL_MAP.get(str(interval).strip(), INTERVAL_MAP.get(self.interval, "1"))

    def _empty_market_state(self, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "asset_class": get_market_asset_class(symbol),
            "feed_source": "Yahoo Finance FX" if is_forex_symbol(symbol) else "Bybit",
            "last_price": None,
            "mark_price": None,
            "index_price": None,
            "open_interest": None,
            "volume_24h": None,
            "turnover_24h": None,
            "funding_rate": None,
            "price_24h_pcnt": None,
            "high_24h": None,
            "low_24h": None,
            "updated_at": None,
        }

    def _register_symbol(self, symbol: str):
        symbol = normalize_market_symbol(symbol)
        if symbol not in self.symbols:
            self.symbols.append(symbol)
            self.symbols = sort_symbols(self.symbols)
        if symbol not in self.history:
            self.history[symbol] = pd.DataFrame(columns=KLINE_COLUMNS)
        if symbol not in self.market_state:
            self.market_state[symbol] = self._empty_market_state(symbol)
        if symbol not in self.orderbooks:
            self.orderbooks[symbol] = {"bids": [], "asks": [], "updated_at": None}
        if symbol not in self.metric_history:
            self.metric_history[symbol] = {
                "last_price": [],
                "mark_price": [],
                "index_price": [],
                "open_interest": [],
                "volume_24h": [],
                "turnover_24h": [],
                "funding_rate": [],
                "price_24h_pcnt": [],
                "high_24h": [],
                "low_24h": [],
            }

    def _interval_cache_key(self, symbol: str, interval: str) -> tuple[str, str]:
        return (str(symbol or "").upper(), self._normalize_interval(interval))

    def _interval_cache_ttl(self, interval: str) -> float:
        interval = self._normalize_interval(interval)
        if interval in {"1m", "3m"}:
            return 6.0
        if interval in {"5m", "15m"}:
            return 15.0
        if interval in {"30m", "1h"}:
            return 30.0
        return 90.0

    def _store_interval_history(self, symbol: str, interval: str, df: pd.DataFrame, source: str = "remote") -> None:
        cache_key = self._interval_cache_key(symbol, interval)
        cached_df = pd.DataFrame(columns=KLINE_COLUMNS) if df is None else df.copy()
        with self._lock:
            self.interval_history_cache[cache_key] = {
                "df": cached_df,
                "fetched_at": time.time(),
                "source": source,
            }

    def _get_interval_history_entry(self, symbol: str, interval: str) -> dict | None:
        cache_key = self._interval_cache_key(symbol, interval)
        with self._lock:
            entry = self.interval_history_cache.get(cache_key)
            if not entry:
                return None
            return {
                "df": entry.get("df", pd.DataFrame(columns=KLINE_COLUMNS)).copy(),
                "fetched_at": float(entry.get("fetched_at", 0.0) or 0.0),
                "source": entry.get("source", "remote"),
            }

    def _invalidate_interval_history(self, symbol: str):
        symbol = self.ensure_symbol(symbol)
        with self._lock:
            stale_keys = [key for key in self.interval_history_cache if key[0] == symbol]
            for key in stale_keys:
                self.interval_history_cache.pop(key, None)

    def _prefetch_interval_history(self, symbol: str, interval: str):
        symbol = self.ensure_symbol(symbol)
        interval = self._normalize_interval(interval)
        if interval == self.interval:
            return

        cache_key = self._interval_cache_key(symbol, interval)
        with self._lock:
            if cache_key in self._interval_fetching:
                return
            self._interval_fetching.add(cache_key)

        def _worker():
            try:
                df = self.fetch_history(symbol, interval=interval, limit=self.limit, store=False)
                if df is not None and not df.empty:
                    cache_entry = self._get_interval_history_entry(symbol, interval)
                    cached_remote = cache_entry["df"] if cache_entry else pd.DataFrame(columns=KLINE_COLUMNS)
                    merged_remote = self._merge_history_frames(cached_remote, df, max_rows=self._history_limit)
                    self._store_interval_history(symbol, interval, merged_remote, source="remote")
            except Exception:
                pass
            finally:
                with self._lock:
                    self._interval_fetching.discard(cache_key)

        threading.Thread(target=_worker, daemon=True).start()

    def ensure_symbol(self, symbol: str) -> str:
        symbol = normalize_market_symbol(symbol)
        with self._lock:
            self._register_symbol(symbol)
        return symbol

    def _request_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list:
        symbol = self.ensure_symbol(symbol)
        params = {
            "category": resolve_market_category(symbol),
            "symbol": symbol,
            "interval": self._interval_to_rest(interval),
            "limit": limit,
        }
        if start_ms is not None:
            params["start"] = int(start_ms)
        if end_ms is not None:
            params["end"] = int(end_ms)
        payload = _bybit_get_json(self._session, REST_KLINE_PATH, params)
        return payload.get("result", {}).get("list", [])

    def _get_json(self, path: str, params: dict) -> dict:
        return _bybit_get_json(self._session, path, params)

    def _coerce_history(self, raw_data: list) -> pd.DataFrame:
        if not raw_data:
            return pd.DataFrame(columns=KLINE_COLUMNS)
        df = pd.DataFrame(raw_data, columns=KLINE_COLUMNS)
        df["time"] = pd.to_datetime(df["time"].astype(float), unit="ms", utc=True).dt.tz_localize(None)
        numeric_cols = ["open", "high", "low", "close", "volume", "turnover"]
        df[numeric_cols] = df[numeric_cols].astype(float)
        df = df.dropna(subset=["time", "open", "high", "low", "close"])
        df = df.sort_values("time").drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)
        return df

    def _merge_history_frames(self, *frames: pd.DataFrame, max_rows: int | None = None) -> pd.DataFrame:
        usable_frames = [frame.copy() for frame in frames if frame is not None and not frame.empty]
        if not usable_frames:
            return pd.DataFrame(columns=KLINE_COLUMNS)

        merged = pd.concat(usable_frames, ignore_index=True)
        merged = merged.sort_values("time").drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)
        if max_rows is not None and max_rows > 0 and len(merged) > max_rows:
            merged = merged.tail(max_rows).reset_index(drop=True)
        return merged

    def _history_to_chart_df(self, df: pd.DataFrame, limit=_DEFAULT_HISTORY_LIMIT) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        chart_df = df.rename(columns={"time": "timestamp"})
        chart_df = chart_df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
        chart_df["timestamp"] = pd.to_datetime(chart_df["timestamp"], errors="coerce")
        numeric_cols = ["open", "high", "low", "close", "volume"]
        chart_df[numeric_cols] = chart_df[numeric_cols].apply(pd.to_numeric, errors="coerce")
        chart_df = chart_df.dropna(subset=["timestamp", "open", "high", "low", "close"])

        if limit is _DEFAULT_HISTORY_LIMIT:
            limit = self.limit
        if limit is not None and limit > 0 and len(chart_df) > limit:
            chart_df = chart_df.tail(int(limit)).reset_index(drop=True)

        return chart_df.sort_values("timestamp").reset_index(drop=True)

    def fetch_history(
        self,
        symbol: str,
        interval: str = None,
        limit: int = None,
        store: bool = True,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> pd.DataFrame:
        symbol = self.ensure_symbol(symbol)
        interval = self._normalize_interval(interval or self.interval)
        try:
            limit = int(limit or self.limit)
        except (TypeError, ValueError):
            limit = self.limit
        limit = max(1, min(limit, MAX_KLINE_PAGE_SIZE))
        if is_forex_symbol(symbol):
            df = fetch_forex_history(
                symbol,
                interval=interval,
                limit=limit,
                session=self._session,
                start_ms=start_ms,
                end_ms=end_ms,
            )
        else:
            try:
                df = self._coerce_history(self._request_klines(symbol, interval, limit, start_ms=start_ms, end_ms=end_ms))
            except Exception:
                df = _empty_kline_frame()
            if df.empty:
                df = fetch_binance_crypto_history(
                    symbol,
                    interval=interval,
                    limit=limit,
                    session=self._session,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
        if store and interval == self.interval:
            with self._lock:
                self.history[symbol] = df.tail(self._history_limit).reset_index(drop=True)
            self._invalidate_interval_history(symbol)
        elif store and interval != self.interval:
            self._store_interval_history(symbol, interval, df, source="remote")
        return df

    def fetch_all_history(self) -> dict:
        for symbol in list(self.symbols):
            try:
                self.fetch_history(symbol)
                self.refresh_symbol(symbol)
                print(f"[OK] Fetched history for {symbol}")
            except Exception as exc:
                print(f"[ERROR] Could not fetch history for {symbol}: {exc}")
        return self.history

    def fetch_ticker(self, symbol: str) -> dict:
        symbol = self.ensure_symbol(symbol)
        if is_forex_symbol(symbol):
            history = self.get_history(symbol, self.interval, limit=None)
            if history is None or history.empty:
                history = self.fetch_history(symbol, interval=self.interval, limit=self.limit, store=False)
                history = self._history_to_chart_df(history, limit=None)
            if history is None or history.empty:
                return {}
            latest = history.iloc[-1]
            return {
                "lastPrice": latest.get("close"),
                "markPrice": latest.get("close"),
                "indexPrice": latest.get("close"),
            }
        payload = self._get_json(
            REST_TICKER_PATH,
            {"category": resolve_market_category(symbol), "symbol": symbol},
        )
        items = payload.get("result", {}).get("list", [])
        return items[0] if items else {}

    def fetch_orderbook(self, symbol: str, depth: int = 12) -> dict:
        symbol = self.ensure_symbol(symbol)
        if is_forex_symbol(symbol):
            return {"bids": [], "asks": [], "updated_at": datetime.utcnow().isoformat(), "source": "forex_quote"}
        payload = self._get_json(
            REST_ORDERBOOK_PATH,
            {"category": resolve_market_category(symbol), "symbol": symbol, "limit": depth},
        )
        result = payload.get("result", {})
        return {
            "bids": [
                {"price": float(price), "size": float(size)}
                for price, size in result.get("b", [])[:depth]
            ],
            "asks": [
                {"price": float(price), "size": float(size)}
                for price, size in result.get("a", [])[:depth]
            ],
            "updated_at": datetime.utcnow().isoformat(),
        }

    def refresh_symbol(self, symbol: str):
        symbol = self.ensure_symbol(symbol)
        if is_forex_symbol(symbol):
            with self._lock:
                history = self.history.get(symbol, pd.DataFrame(columns=KLINE_COLUMNS)).copy()
            if history.empty:
                history = self.fetch_history(symbol, interval=self.interval, limit=self.limit, store=True)
            self._update_forex_market_state(symbol, history)
            with self._lock:
                self.orderbooks[symbol] = {
                    "bids": [],
                    "asks": [],
                    "updated_at": datetime.utcnow().isoformat(),
                    "source": "forex_quote",
                }
            return

        try:
            ticker = self.fetch_ticker(symbol)
            self._update_ticker(symbol, ticker)
        except Exception:
            pass

        try:
            orderbook = self.fetch_orderbook(symbol)
            with self._lock:
                self.orderbooks[symbol] = orderbook
        except Exception:
            pass

    def refresh_market_state(self):
        for symbol in list(self.symbols):
            try:
                self.fetch_history(symbol)
            except Exception:
                pass
            self.refresh_symbol(symbol)

    def _upsert_candle(self, symbol: str, candle: dict):
        symbol = self.ensure_symbol(symbol)
        row = {
            "time": pd.to_datetime(int(candle["start"]), unit="ms", utc=True).tz_localize(None),
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
            "volume": float(candle.get("volume", 0.0)),
            "turnover": float(candle.get("turnover", 0.0)),
        }
        new_row = pd.DataFrame([row], columns=KLINE_COLUMNS)

        with self._lock:
            current = self.history[symbol]
            if current.empty:
                updated = new_row
            else:
                updated = pd.concat([current, new_row], ignore_index=True)
                updated = updated.sort_values("time").drop_duplicates(subset=["time"], keep="last")
            self.history[symbol] = updated.tail(self._history_limit).reset_index(drop=True)
            stale_cache_keys = [key for key in self.interval_history_cache if key[0] == symbol]
            for key in stale_cache_keys:
                self.interval_history_cache.pop(key, None)

            state = self.market_state[symbol]
            state["last_price"] = row["close"]
            state["updated_at"] = datetime.utcnow().isoformat()

    def _update_ticker(self, symbol: str, ticker: dict):
        symbol = self.ensure_symbol(symbol)
        with self._lock:
            state = self.market_state[symbol]
            state["asset_class"] = get_market_asset_class(symbol)
            state["feed_source"] = "Bybit"
            state["last_price"] = self._to_float(ticker.get("lastPrice"), state["last_price"])
            state["mark_price"] = self._to_float(ticker.get("markPrice"), state["mark_price"])
            state["index_price"] = self._to_float(ticker.get("indexPrice"), state["index_price"])
            state["open_interest"] = self._to_float(ticker.get("openInterest"), state["open_interest"])
            state["volume_24h"] = self._to_float(ticker.get("volume24h"), state["volume_24h"])
            state["turnover_24h"] = self._to_float(ticker.get("turnover24h"), state["turnover_24h"])
            state["funding_rate"] = self._to_float(ticker.get("fundingRate"), state["funding_rate"])
            state["price_24h_pcnt"] = self._to_float(ticker.get("price24hPcnt"), state["price_24h_pcnt"])
            state["high_24h"] = self._to_float(ticker.get("highPrice24h"), state["high_24h"])
            state["low_24h"] = self._to_float(ticker.get("lowPrice24h"), state["low_24h"])
            state["updated_at"] = datetime.utcnow().isoformat()
            metric_store = self.metric_history[symbol]
            for field in (
                "last_price",
                "mark_price",
                "index_price",
                "open_interest",
                "volume_24h",
                "turnover_24h",
                "funding_rate",
                "price_24h_pcnt",
                "high_24h",
                "low_24h",
            ):
                value = state.get(field)
                if value in (None, ""):
                    continue
                history = metric_store.setdefault(field, [])
                try:
                    numeric_value = float(value)
                except (TypeError, ValueError):
                    continue
                history.append(numeric_value)
                if len(history) > self._history_limit:
                    del history[:-self._history_limit]

    def _update_forex_market_state(self, symbol: str, history: pd.DataFrame):
        symbol = self.ensure_symbol(symbol)
        if history is None or history.empty:
            return

        working = history.copy()
        working["time"] = pd.to_datetime(working["time"], errors="coerce")
        for column in ["open", "high", "low", "close", "volume"]:
            working[column] = pd.to_numeric(working[column], errors="coerce")
        working = working.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time")
        if working.empty:
            return

        latest = working.iloc[-1]
        latest_time = latest["time"]
        window = working[working["time"] >= latest_time - pd.Timedelta(hours=24)]
        if window.empty:
            window = working.tail(min(len(working), 24))

        open_ref = float(window.iloc[0]["open"]) if not window.empty else float(latest["open"])
        last_price = float(latest["close"])
        change_fraction = ((last_price - open_ref) / open_ref) if open_ref else None
        state_values = {
            "last_price": last_price,
            "mark_price": last_price,
            "index_price": last_price,
            "open_interest": None,
            "volume_24h": float(window["volume"].sum()) if "volume" in window else 0.0,
            "turnover_24h": 0.0,
            "funding_rate": None,
            "price_24h_pcnt": change_fraction,
            "high_24h": float(window["high"].max()) if not window.empty else float(latest["high"]),
            "low_24h": float(window["low"].min()) if not window.empty else float(latest["low"]),
            "updated_at": datetime.utcnow().isoformat(),
            "asset_class": "forex",
            "feed_source": "Yahoo Finance FX",
        }

        with self._lock:
            state = self.market_state[symbol]
            state.update(state_values)
            metric_store = self.metric_history[symbol]
            for field in (
                "last_price",
                "mark_price",
                "index_price",
                "volume_24h",
                "turnover_24h",
                "price_24h_pcnt",
                "high_24h",
                "low_24h",
            ):
                value = state.get(field)
                if value in (None, ""):
                    continue
                history_values = metric_store.setdefault(field, [])
                try:
                    numeric_value = float(value)
                except (TypeError, ValueError):
                    continue
                history_values.append(numeric_value)
                if len(history_values) > self._history_limit:
                    del history_values[:-self._history_limit]

    def _update_orderbook(self, symbol: str, payload: dict):
        symbol = self.ensure_symbol(symbol)
        bids = [
            {"price": float(price), "size": float(size)}
            for price, size in payload.get("b", [])[:12]
        ]
        asks = [
            {"price": float(price), "size": float(size)}
            for price, size in payload.get("a", [])[:12]
        ]
        with self._lock:
            self.orderbooks[symbol] = {
                "bids": bids,
                "asks": asks,
                "updated_at": datetime.utcnow().isoformat(),
            }

    def _handle_message(self, message: dict):
        topic = message.get("topic", "")
        data = message.get("data")
        if not topic or data is None:
            return

        parts = topic.split(".")
        if topic.startswith("kline.") and len(parts) >= 3:
            symbol = parts[-1].upper()
            items = data if isinstance(data, list) else [data]
            for candle in items:
                self._upsert_candle(symbol, candle)
        elif topic.startswith("tickers.") and len(parts) >= 2:
            symbol = parts[-1].upper()
            ticker = data if isinstance(data, dict) else {}
            self._update_ticker(symbol, ticker)
        elif topic.startswith("orderbook.") and len(parts) >= 3:
            symbol = parts[-1].upper()
            payload = data if isinstance(data, dict) else {}
            self._update_orderbook(symbol, payload)

    async def stream(self):
        if websockets is None:
            print("[WS] websockets package not installed, using REST polling fallback.")
            return

        while True:
            try:
                async with websockets.connect(self.WS_URL, ping_interval=20, ping_timeout=WS_PING_TIMEOUT_SECONDS) as ws:
                    args = []
                    for symbol in list(self.symbols):
                        if is_forex_symbol(symbol):
                            continue
                        if resolve_market_category(symbol) != "linear":
                            continue
                        args.extend(
                            [
                                f"kline.1.{symbol}",
                                f"tickers.{symbol}",
                                f"orderbook.50.{symbol}",
                            ]
                        )
                    if not args:
                        await asyncio.sleep(self._rest_poll_seconds)
                        continue
                    await ws.send(json.dumps({"op": "subscribe", "args": args}))
                    print(f"[WS] Connected and subscribed to {self.symbols}")

                    while True:
                        raw_message = await ws.recv()
                        message = json.loads(raw_message)
                        if message.get("op") == "pong":
                            continue
                        self._handle_message(message)
            except Exception as exc:
                print(f"[WS] Disconnected: {exc} | reconnecting in 5s...")
                await asyncio.sleep(5)

    async def run(self, interval_seconds: int = 60):
        if websockets is None:
            while True:
                self.refresh_market_state()
                await asyncio.sleep(self._rest_poll_seconds)
        else:
            poll_task = asyncio.create_task(self._poll_market_state_loop())
            try:
                await self.stream()
            finally:
                poll_task.cancel()

    async def _poll_market_state_loop(self):
        while True:
            try:
                self.refresh_market_state()
            except Exception:
                pass
            await asyncio.sleep(self._rest_poll_seconds)

    def _resample_history(self, df: pd.DataFrame, interval: str) -> pd.DataFrame:
        rule = PANDAS_RULES.get(interval)
        if df.empty or not rule or interval == self.interval:
            return df

        resampled = (
            df.set_index("time")
            .resample(rule)
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                    "turnover": "sum",
                }
            )
            .dropna(subset=["open", "high", "low", "close"])
            .reset_index()
        )
        return resampled

    def _compose_history_frame(self, symbol: str, interval: str) -> pd.DataFrame:
        symbol = self.ensure_symbol(symbol)
        interval = self._normalize_interval(interval)

        with self._lock:
            base_df = self.history.get(symbol, pd.DataFrame(columns=KLINE_COLUMNS)).copy()

        if interval == self.interval:
            df = base_df
        else:
            live_df = self._resample_history(base_df, interval)
            cache_entry = self._get_interval_history_entry(symbol, interval)
            remote_df = pd.DataFrame(columns=KLINE_COLUMNS)
            if cache_entry:
                remote_df = cache_entry["df"]
                if (
                    cache_entry.get("source") == "resampled"
                    or (time.time() - cache_entry.get("fetched_at", 0.0)) > self._interval_cache_ttl(interval)
                ):
                    self._prefetch_interval_history(symbol, interval)
            else:
                if not live_df.empty:
                    self._store_interval_history(symbol, interval, live_df, source="resampled")
                if live_df.empty or len(live_df) < 50:
                    self._prefetch_interval_history(symbol, interval)

            frames = [frame for frame in (remote_df, live_df) if frame is not None and not frame.empty]
            if frames:
                df = self._merge_history_frames(*frames)
            else:
                df = pd.DataFrame(columns=KLINE_COLUMNS)

        return df

    def get_history(self, symbol: str, interval: str = None, limit=_DEFAULT_HISTORY_LIMIT) -> pd.DataFrame:
        symbol = self.ensure_symbol(symbol)
        interval = self._normalize_interval(interval or self.interval)
        return self._history_to_chart_df(self._compose_history_frame(symbol, interval), limit=limit)

    def ensure_history_depth(self, symbol: str, interval: str = None, min_candles: int = 720) -> pd.DataFrame:
        symbol = self.ensure_symbol(symbol)
        interval = self._normalize_interval(interval or self.interval)
        try:
            min_candles = int(min_candles)
        except (TypeError, ValueError):
            min_candles = self.limit
        min_candles = max(self.limit, min(min_candles, MAX_KLINE_PAGE_SIZE))

        current = self.get_history(symbol, interval, limit=None)
        if len(current) >= min_candles:
            return current

        try:
            fetched = self.fetch_history(symbol, interval=interval, limit=min_candles, store=False)
        except Exception:
            return current

        if fetched is None or fetched.empty:
            return current

        if interval == self.interval:
            with self._lock:
                existing = self.history.get(symbol, pd.DataFrame(columns=KLINE_COLUMNS)).copy()
                self.history[symbol] = self._merge_history_frames(existing, fetched, max_rows=self._history_limit)
            self._invalidate_interval_history(symbol)
        else:
            cache_entry = self._get_interval_history_entry(symbol, interval)
            cached_remote = cache_entry["df"] if cache_entry else pd.DataFrame(columns=KLINE_COLUMNS)
            merged_remote = self._merge_history_frames(cached_remote, fetched, max_rows=self._history_limit)
            self._store_interval_history(symbol, interval, merged_remote, source="remote")

        return self.get_history(symbol, interval, limit=None)

    def load_older_history(self, symbol: str, interval: str = None, before_time=None, limit: int = 500) -> pd.DataFrame:
        symbol = self.ensure_symbol(symbol)
        interval = self._normalize_interval(interval or self.interval)
        try:
            limit = int(limit or self.limit)
        except (TypeError, ValueError):
            limit = self.limit
        limit = max(1, min(limit, MAX_KLINE_PAGE_SIZE))

        if before_time is None:
            current = self.get_history(symbol, interval, limit=None)
            if current.empty:
                return current
            before_dt = pd.to_datetime(current["timestamp"].min(), errors="coerce")
        else:
            before_dt = pd.to_datetime(float(before_time), unit="s", utc=True).tz_localize(None)

        if pd.isna(before_dt):
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        end_ms = int(before_dt.timestamp() * 1000) - 1
        if end_ms <= 0:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        older_df = self.fetch_history(symbol, interval=interval, limit=limit, store=False, end_ms=end_ms)
        if older_df is None or older_df.empty:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        if interval == self.interval:
            with self._lock:
                existing = self.history.get(symbol, pd.DataFrame(columns=KLINE_COLUMNS)).copy()
                self.history[symbol] = self._merge_history_frames(existing, older_df, max_rows=self._history_limit)
            self._invalidate_interval_history(symbol)
        else:
            cache_entry = self._get_interval_history_entry(symbol, interval)
            cached_remote = cache_entry["df"] if cache_entry else pd.DataFrame(columns=KLINE_COLUMNS)
            merged_remote = self._merge_history_frames(cached_remote, older_df, max_rows=self._history_limit)
            self._store_interval_history(symbol, interval, merged_remote, source="remote")

        return self._history_to_chart_df(older_df, limit=None)

    def get_market_snapshot(self, symbol: str) -> dict:
        symbol = self.ensure_symbol(symbol)
        with self._lock:
            state = dict(self.market_state.get(symbol, self._empty_market_state(symbol)))
            history = self.history.get(symbol, pd.DataFrame(columns=KLINE_COLUMNS)).copy()

        if not history.empty:
            latest = history.iloc[-1]
            previous_close = history.iloc[-2]["close"] if len(history) > 1 else latest["open"]
            if state.get("last_price") is None:
                state["last_price"] = float(latest["close"])
            state["candle_open"] = float(latest["open"])
            state["candle_high"] = float(latest["high"])
            state["candle_low"] = float(latest["low"])
            state["candle_volume"] = float(latest["volume"])
            state["candle_change"] = float(latest["close"] - previous_close)
            state["candle_change_pct"] = float(((latest["close"] - previous_close) / previous_close) * 100) if previous_close else 0.0
        else:
            state["candle_open"] = None
            state["candle_high"] = None
            state["candle_low"] = None
            state["candle_volume"] = None
            state["candle_change"] = None
            state["candle_change_pct"] = None

        return state

    def get_orderbook(self, symbol: str, depth: int = 10) -> dict:
        symbol = self.ensure_symbol(symbol)
        with self._lock:
            orderbook = self.orderbooks.get(symbol, {"bids": [], "asks": [], "updated_at": None})
            bids = list(orderbook["bids"][:depth])
            asks = list(orderbook["asks"][:depth])
        return {
            "bids": bids,
            "asks": asks,
            "updated_at": orderbook.get("updated_at"),
            "source": orderbook.get("source"),
        }

    def get_metric_series(self, symbol: str, field: str, limit: int = 30) -> list[float]:
        symbol = self.ensure_symbol(symbol)
        field_key = str(field or "").strip()
        with self._lock:
            values = list((self.metric_history.get(symbol, {}) or {}).get(field_key, []))
        if limit is not None and limit > 0:
            values = values[-limit:]
        return [float(value) for value in values if value is not None]

    def get_available_symbols(self, refresh: bool = False, max_symbols: int = None) -> list:
        if refresh or not self._symbol_directory:
            symbols = discover_tradable_symbols(self._session)
            with self._lock:
                self._symbol_directory = sort_symbols(list(self.symbols) + list(symbols))

        available = list(self._symbol_directory) if self._symbol_directory else sort_symbols(self.symbols)
        if max_symbols is not None:
            return available[:max_symbols]
        return available

    def get_latest_tick(self, symbol: str) -> dict:
        """Get the latest tick/price data for real-time candle building."""
        symbol = self.ensure_symbol(symbol)
        with self._lock:
            state = self.market_state.get(symbol, {})
            return {
                "symbol": symbol,
                "last_price": state.get("last_price"),
                "mark_price": state.get("mark_price"),
                "volume_24h": state.get("volume_24h"),
                "updated_at": state.get("updated_at"),
            }

    def get_current_candle(self, symbol: str, interval: str = None) -> dict:
        """Get the current candle being built (last row of history)."""
        symbol = self.ensure_symbol(symbol)
        interval = self._normalize_interval(interval or self.interval)
        
        with self._lock:
            df = self.get_history(symbol, interval=interval)
        
        if df.empty:
            return {}
        
        last = df.iloc[-1]
        return {
            "timestamp": last.get("timestamp"),
            "open": last.get("open"),
            "high": last.get("high"),
            "low": last.get("low"),
            "close": last.get("close"),
            "volume": last.get("volume"),
        }

    @staticmethod
    def _to_float(value, fallback=None):
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback
