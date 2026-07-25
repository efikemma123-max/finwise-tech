import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests

from backend.auth.broker_oauth import resolve_broker_oauth_redirect_uri
from backend.market.candle_engine import is_forex_symbol, resolve_market_category


@dataclass(frozen=True)
class TradingConfig:
    max_trade_usd: float = 750.0
    risk_per_trade: float = 0.01
    max_position_size: float = 0.03
    min_order_size: float = 0.001
    slippage_percent: float = 0.15
    default_fee_percent: float = 0.1
    always_execute_signals: bool = False
    min_projected_profit_percent: float = 1.0
    account_growth_goal_percent: float = 90.0
    min_confidence_percent: float = 78.0
    min_risk_reward_ratio: float = 2.0
    max_black_swan_risk: float = 30.0
    min_trend_score: float = 0.35
    min_momentum_score: float = 0.2
    require_robust_signal: bool = True
    require_high_quality_setup: bool = True


@dataclass(frozen=True)
class BrokerAuthConfig:
    broker_name: str
    display_name: str
    logo_path: str = ""
    oauth_supported: bool = False
    api_key_supported: bool = True
    oauth_button_label: str = "Connect with Broker"
    oauth_description: str = "OAuth connection is available for this broker."
    api_fallback_description: str = "OAuth is unavailable for this broker right now, so Finwise will use API credentials."
    oauth_client_id_env: str = ""
    oauth_client_secret_env: str = ""
    oauth_client_secret_required: bool = True
    oauth_authorize_url_env: str = ""
    oauth_token_url_env: str = ""
    oauth_authorize_url: str = ""
    oauth_token_url: str = ""
    oauth_resource_url: str = ""
    oauth_scope: str = ""
    oauth_scope_delimiter: str = " "
    oauth_token_auth_style: str = "client_secret_body"
    oauth_connection_mode: str = "api_key_pair"
    oauth_resource_method: str = "GET"
    oauth_partner_program_required: bool = False
    oauth_state_prefix: str = "broker-oauth"


DISPLAY_ONLY_BROKERS = [
    {
        "broker_name": "binance",
        "display_name": "Binance",
        "logo_path": "",
        "oauth_supported": False,
        "api_key_supported": False,
        "connectable": False,
        "status_label": "Coming Soon",
        "status_tone": "pending",
        "description": "Spot and futures connection is planned next.",
    },
    {
        "broker_name": "kucoin",
        "display_name": "KuCoin",
        "logo_path": "",
        "oauth_supported": False,
        "api_key_supported": False,
        "connectable": False,
        "status_label": "Coming Soon",
        "status_tone": "pending",
        "description": "API trading connector is planned after OKX.",
    },
]


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Broker(ABC):
    def __init__(self, api_key: str, api_secret: str, broker_name: str = "Unknown"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.name = broker_name
        self.last_error = ""

    @classmethod
    def supports_connection_data(cls, connection_data: Dict[str, Any]) -> bool:
        return bool(connection_data.get("api_key") and connection_data.get("api_secret"))

    @classmethod
    def from_connection_data(cls, connection_data: Dict[str, Any], broker_name: str = "") -> "Broker":
        resolved_name = broker_name[:1].upper() + broker_name[1:] if broker_name else "Unknown"
        return cls(
            connection_data.get("api_key", ""),
            connection_data.get("api_secret", ""),
            broker_name=resolved_name,
        )

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        pass

    @abstractmethod
    def get_balance(self, asset: str = "USDT") -> float:
        pass

    @abstractmethod
    def get_market_price(self, symbol: str) -> float:
        pass

    @abstractmethod
    def place_order(self, symbol: str, side: str, quantity: float) -> Dict:
        pass

    @abstractmethod
    def get_order_status(self, symbol: str, order_id: str) -> Dict:
        pass

    @abstractmethod
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        pass

    @abstractmethod
    def get_trading_fees(self, symbol: str) -> float:
        pass


class BybitBroker(Broker):
    def __init__(self, api_key: str, api_secret: str, broker_name: str = "Bybit"):
        super().__init__(api_key, api_secret, broker_name)
        explicit_base_url = str(os.getenv("BYBIT_API_BASE_URL", "")).strip().rstrip("/")
        self.use_testnet = os.getenv("BYBIT_USE_TESTNET", "").lower() in {"1", "true", "yes"}
        if explicit_base_url:
            self.base_urls = [explicit_base_url]
        elif self.use_testnet:
            self.base_urls = ["https://api-testnet.bybit.com"]
        else:
            self.base_urls = [
                "https://api.bybit.com",
                "https://api.bytick.com",
            ]
        self.base_url = self.base_urls[0]
        self.category = os.getenv("BYBIT_BROKER_CATEGORY", "linear")
        self.account_type = os.getenv("BYBIT_ACCOUNT_TYPE", "UNIFIED")
        self.recv_window = os.getenv("BYBIT_RECV_WINDOW", "5000")
        self.session = requests.Session()
        self.session.trust_env = False
        self.connected = False
        self.server_time_offset_ms = 0
        self.server_time_synced_at = 0.0

    def connect(self) -> bool:
        try:
            self._signed_request("GET", "/v5/account/info")
            self.connected = True
            self.last_error = ""
            return True
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)
            return False

    def disconnect(self) -> bool:
        self.connected = False
        try:
            self.session.close()
        except Exception:
            pass
        return True

    def get_balance(self, asset: str = "USDT") -> float:
        payload = self._signed_request(
            "GET",
            "/v5/account/wallet-balance",
            params={"accountType": self.account_type, "coin": asset.upper()},
        )
        accounts = payload.get("result", {}).get("list", [])
        if not accounts:
            return 0.0
        for coin in accounts[0].get("coin", []):
            if coin.get("coin") == asset.upper():
                for key in ("availableToWithdraw", "availableToBorrow", "walletBalance", "equity"):
                    value = coin.get(key)
                    if value not in (None, ""):
                        return float(value)
        return 0.0

    def get_market_price(self, symbol: str) -> float:
        payload = self._public_request(
            "GET",
            "/v5/market/tickers",
            params={"category": self._category_for_symbol(symbol), "symbol": symbol.upper()},
        )
        tickers = payload.get("result", {}).get("list", [])
        if not tickers:
            return 0.0
        return float(tickers[0].get("lastPrice") or 0.0)

    def place_order(self, symbol: str, side: str, quantity: float) -> Dict:
        side_value = "Buy" if side.upper() == "BUY" else "Sell"
        payload = self._signed_request(
            "POST",
            "/v5/order/create",
            body={
                "category": self._category_for_symbol(symbol),
                "symbol": symbol.upper(),
                "side": side_value,
                "orderType": "Market",
                "qty": self._stringify_number(quantity),
                "orderLinkId": f"finwise-{int(time.time() * 1000)}",
            },
        )
        result = payload.get("result", {})
        return {
            "status": "success",
            "order_id": result.get("orderId"),
            "order_link_id": result.get("orderLinkId"),
            "raw": result,
        }

    def get_order_status(self, symbol: str, order_id: str) -> Dict:
        payload = self._signed_request(
            "GET",
            "/v5/order/realtime",
            params={
                "category": self._category_for_symbol(symbol),
                "symbol": symbol.upper(),
                "orderId": order_id,
                "openOnly": 0,
                "limit": 1,
            },
        )
        orders = payload.get("result", {}).get("list", [])
        if not orders:
            return {"order_id": order_id, "status": OrderStatus.FAILED.value}

        order = orders[0]
        status = self._map_order_status(order.get("orderStatus", ""))
        return {
            "order_id": order.get("orderId"),
            "status": status,
            "filled_quantity": float(order.get("cumExecQty") or 0.0),
            "total_quantity": float(order.get("qty") or 0.0),
            "raw": order,
        }

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        payload = self._signed_request(
            "POST",
            "/v5/order/cancel",
            body={
                "category": self._category_for_symbol(symbol),
                "symbol": symbol.upper(),
                "orderId": order_id,
            },
        )
        return bool(payload.get("result", {}).get("orderId"))

    def get_trading_fees(self, symbol: str) -> float:
        try:
            payload = self._signed_request(
                "GET",
                "/v5/account/fee-rate",
                params={"category": self._category_for_symbol(symbol), "symbol": symbol.upper()},
            )
            fee_rows = payload.get("result", {}).get("list", [])
            if fee_rows:
                return float(fee_rows[0].get("takerFeeRate") or 0.001) * 100
        except Exception:
            pass
        return 0.1

    def _public_request(self, method: str, path: str, params: Dict = None) -> Dict:
        return self._request_with_failover(
            method=method,
            path=path,
            params=params,
            timeout=15,
            api_error_message="Bybit request failed",
        )

    def _signed_request(self, method: str, path: str, params: Dict = None, body: Dict = None) -> Dict:
        params = params or {}
        body = body or {}
        body_string = json.dumps(body, separators=(",", ":"))

        for attempt in range(2):
            if attempt == 0:
                self._refresh_server_time_offset(force=False)
            else:
                self._refresh_server_time_offset(force=True)

            timestamp = str(self._current_timestamp_ms())
            query_string = urlencode(sorted(params.items()))
            payload_string = f"{timestamp}{self.api_key}{self.recv_window}{query_string if method.upper() == 'GET' else body_string}"
            signature = hmac.new(self.api_secret.encode("utf-8"), payload_string.encode("utf-8"), hashlib.sha256).hexdigest()

            headers = {
                "X-BAPI-API-KEY": self.api_key,
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-SIGN": signature,
                "X-BAPI-RECV-WINDOW": self.recv_window,
                "Content-Type": "application/json",
            }
            try:
                return self._request_with_failover(
                    method=method,
                    path=path,
                    params=params if method.upper() == "GET" else None,
                    data=body_string if method.upper() != "GET" else None,
                    headers=headers,
                    timeout=20,
                    api_error_message="Bybit signed request failed",
                )
            except RuntimeError as exc:
                self.last_error = str(exc)
                if attempt == 0 and self._is_timestamp_error(exc):
                    continue
                raise

        raise RuntimeError("Bybit signed request failed")

    def _request_with_failover(
        self,
        method: str,
        path: str,
        params: Dict = None,
        data: str = None,
        headers: Dict = None,
        timeout: int = 20,
        api_error_message: str = "Bybit request failed",
    ) -> Dict:
        candidates = [self.base_url] + [url for url in self.base_urls if url != self.base_url]
        last_transport_error = None

        for idx, base_url in enumerate(candidates):
            try:
                response = self.session.request(
                    method=method,
                    url=f"{base_url}{path}",
                    params=params,
                    data=data,
                    headers=headers,
                    timeout=timeout,
                )
                response.raise_for_status()
                payload = response.json()
                ret_code = payload.get("retCode", payload.get("ret_code", 0))
                if ret_code != 0:
                    raise RuntimeError(payload.get("retMsg") or payload.get("ret_msg") or api_error_message)
                self.base_url = base_url
                self.last_error = ""
                return payload
            except RuntimeError:
                raise
            except requests.exceptions.HTTPError as exc:
                response = exc.response
                detail = api_error_message
                if response is not None:
                    try:
                        payload = response.json()
                        detail = payload.get("retMsg") or payload.get("ret_msg") or response.text or detail
                    except Exception:
                        detail = response.text or f"HTTP {response.status_code}"
                raise RuntimeError(str(detail).strip()) from exc
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.SSLError) as exc:
                last_transport_error = exc
                if idx == len(candidates) - 1:
                    raise

        if last_transport_error is not None:
            raise last_transport_error
        raise RuntimeError(api_error_message)

    def _refresh_server_time_offset(self, force: bool = False) -> None:
        if not force and self.server_time_synced_at and (time.time() - self.server_time_synced_at) < 300:
            return

        candidates = [self.base_url] + [url for url in self.base_urls if url != self.base_url]
        last_error = None
        for base_url in candidates:
            started_ms = int(time.time() * 1000)
            try:
                response = self.session.request(
                    method="GET",
                    url=f"{base_url}/v5/market/time",
                    timeout=10,
                )
                response.raise_for_status()
                payload = response.json()
                ret_code = payload.get("retCode", payload.get("ret_code", 0))
                if ret_code != 0:
                    raise RuntimeError(payload.get("retMsg") or payload.get("ret_msg") or "Bybit time sync failed")
                ended_ms = int(time.time() * 1000)
                server_ms = self._extract_server_time_ms(payload)
                midpoint_ms = (started_ms + ended_ms) // 2
                self.server_time_offset_ms = int(server_ms - midpoint_ms)
                self.server_time_synced_at = time.time()
                self.base_url = base_url
                return
            except Exception as exc:
                last_error = exc
        if force and last_error is not None:
            raise RuntimeError(f"Bybit time sync failed: {last_error}") from last_error

    @staticmethod
    def _extract_server_time_ms(payload: Dict) -> int:
        direct_time = payload.get("time")
        if direct_time not in (None, ""):
            return int(float(direct_time))
        result = payload.get("result", {}) or {}
        time_nano = result.get("timeNano")
        if time_nano not in (None, ""):
            return int(int(time_nano) / 1_000_000)
        time_second = result.get("timeSecond")
        if time_second not in (None, ""):
            return int(float(time_second) * 1000)
        raise RuntimeError("Bybit time sync payload did not include a server timestamp.")

    def _current_timestamp_ms(self) -> int:
        return int(time.time() * 1000) + int(self.server_time_offset_ms or 0)

    @staticmethod
    def _is_timestamp_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return "server timestamp" in message or "recv_window" in message or "req_timestamp" in message

    @staticmethod
    def _map_order_status(status: str) -> str:
        mapping = {
            "New": OrderStatus.PENDING.value,
            "Created": OrderStatus.PENDING.value,
            "PartiallyFilled": OrderStatus.PARTIAL.value,
            "Filled": OrderStatus.FILLED.value,
            "Cancelled": OrderStatus.CANCELLED.value,
            "Rejected": OrderStatus.FAILED.value,
            "Deactivated": OrderStatus.CANCELLED.value,
        }
        return mapping.get(status, status.lower() if status else OrderStatus.FAILED.value)

    @staticmethod
    def _stringify_number(value: float) -> str:
        text = f"{value:.8f}".rstrip("0").rstrip(".")
        return text or "0"

    def _category_for_symbol(self, symbol: str) -> str:
        explicit_category = os.getenv("BYBIT_BROKER_CATEGORY", "").strip().lower()
        return explicit_category or resolve_market_category(symbol)


class CoinbaseBroker(Broker):
    def __init__(
        self,
        access_token: str,
        refresh_token: str = "",
        token_expires_at: Optional[float] = None,
        broker_name: str = "Coinbase",
    ):
        super().__init__(access_token, refresh_token, broker_name)
        self.access_token = access_token
        self.refresh_token = refresh_token or ""
        self.token_expires_at = float(token_expires_at or 0.0)
        self.base_url = "https://api.coinbase.com"
        self.session = requests.Session()
        self.session.trust_env = False
        self.connected = False
        self._accounts_cache: list = []
        self._accounts_cached_at = 0.0

    @classmethod
    def supports_connection_data(cls, connection_data: Dict[str, Any]) -> bool:
        return bool(connection_data.get("access_token"))

    @classmethod
    def from_connection_data(cls, connection_data: Dict[str, Any], broker_name: str = "") -> "CoinbaseBroker":
        resolved_name = broker_name[:1].upper() + broker_name[1:] if broker_name else "Coinbase"
        return cls(
            connection_data.get("access_token", ""),
            connection_data.get("refresh_token", ""),
            connection_data.get("token_expires_at"),
            broker_name=resolved_name,
        )

    def connect(self) -> bool:
        try:
            self._request("GET", "/v2/user")
            self.connected = True
            self.last_error = ""
            return True
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)
            return False

    def disconnect(self) -> bool:
        self.connected = False
        try:
            self.session.close()
        except Exception:
            pass
        return True

    def get_balance(self, asset: str = "USDT") -> float:
        desired = asset.upper()
        stable_aliases = {"USD", "USDC", "USDT"}
        for account in self._list_accounts():
            currency = str(account.get("currency", "")).upper()
            if currency == desired or (desired in stable_aliases and currency in stable_aliases):
                available = (account.get("available_balance") or {}).get("value")
                if available not in (None, ""):
                    return float(available)
        return 0.0

    def get_market_price(self, symbol: str) -> float:
        for product_id in self._candidate_product_ids(symbol):
            try:
                payload = self._request("GET", f"/api/v3/brokerage/market/products/{product_id}", auth_required=False)
            except RuntimeError:
                continue
            price = payload.get("price") or payload.get("mid_market_price")
            if price not in (None, ""):
                return float(price)
        return 0.0

    def place_order(self, symbol: str, side: str, quantity: float) -> Dict:
        product_id = self._resolve_product_id(symbol)
        payload = {
            "client_order_id": f"finwise-{int(time.time() * 1000)}",
            "product_id": product_id,
            "side": "BUY" if side.upper() == "BUY" else "SELL",
            "order_configuration": {
                "market_market_ioc": {
                    "base_size": self._stringify_number(quantity),
                }
            },
        }
        portfolio_id = self._primary_portfolio_id()
        if portfolio_id:
            payload["retail_portfolio_id"] = portfolio_id
        response = self._request("POST", "/api/v3/brokerage/orders", body=payload)
        if response.get("success") is False:
            error_payload = response.get("error_response", {}) or {}
            message = (
                error_payload.get("message")
                or error_payload.get("error")
                or response.get("message")
                or "Coinbase order was rejected."
            )
            raise RuntimeError(str(message))
        result = response.get("success_response", {}) or response
        return {
            "status": "success",
            "order_id": result.get("order_id"),
            "client_order_id": payload["client_order_id"],
            "raw": response,
        }

    def get_order_status(self, symbol: str, order_id: str) -> Dict:
        payload = self._request("GET", f"/api/v3/brokerage/orders/historical/{order_id}")
        order = payload.get("order", {}) or {}
        status = str(order.get("status", "")).upper()
        mapping = {
            "OPEN": OrderStatus.PENDING.value,
            "PENDING": OrderStatus.PENDING.value,
            "FILLED": OrderStatus.FILLED.value,
            "CANCELLED": OrderStatus.CANCELLED.value,
            "EXPIRED": OrderStatus.CANCELLED.value,
            "FAILED": OrderStatus.FAILED.value,
            "REJECTED": OrderStatus.FAILED.value,
        }
        return {
            "status": mapping.get(status, status.lower() if status else OrderStatus.FAILED.value),
            "raw": order,
        }

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        payload = self._request(
            "POST",
            "/api/v3/brokerage/orders/batch_cancel",
            body={"order_ids": [order_id]},
        )
        results = payload.get("results") or payload.get("success_results") or []
        if not results:
            return bool(payload.get("success"))
        return any(str(item.get("success", "")).lower() == "true" or item.get("success") is True for item in results)

    def get_trading_fees(self, symbol: str) -> float:
        payload = self._request("GET", "/api/v3/brokerage/transaction_summary")
        fee_tier = payload.get("fee_tier", {}) or {}
        taker_rate = fee_tier.get("taker_fee_rate")
        if taker_rate in (None, ""):
            return 0.0
        return float(taker_rate) * 100

    def _request(
        self,
        method: str,
        path: str,
        params: Dict = None,
        body: Dict = None,
        auth_required: bool = True,
        allow_refresh: bool = True,
    ) -> Dict:
        headers = {"Accept": "application/json", "User-Agent": "FinwiseAI/1.0"}
        if auth_required:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        response = self.session.request(
            method=method,
            url=f"{self.base_url}{path}",
            params=params,
            json=body,
            headers=headers,
            timeout=20,
        )
        if response.status_code == 401 and auth_required and allow_refresh and self._refresh_access_token():
            return self._request(method, path, params=params, body=body, auth_required=auth_required, allow_refresh=False)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = "Coinbase request failed."
            try:
                payload = response.json()
                detail = (
                    payload.get("message")
                    or payload.get("error_details")
                    or payload.get("error")
                    or detail
                )
            except Exception:
                detail = response.text or detail
            raise RuntimeError(str(detail).strip()) from exc
        payload = response.json()
        self.last_error = ""
        return payload

    def _refresh_access_token(self) -> bool:
        if not self.refresh_token:
            return False
        client_id = os.getenv("COINBASE_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.getenv("COINBASE_OAUTH_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return False
        response = self.session.post(
            "https://login.coinbase.com/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "FinwiseAI/1.0",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=20,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError:
            return False
        payload = response.json()
        access_token = payload.get("access_token", "")
        if not access_token:
            return False
        self.access_token = access_token
        self.api_key = access_token
        new_refresh = payload.get("refresh_token")
        if new_refresh:
            self.refresh_token = new_refresh
            self.api_secret = new_refresh
        expires_in = float(payload.get("expires_in") or 0)
        self.token_expires_at = time.time() + expires_in if expires_in > 0 else 0.0
        return True

    def _list_accounts(self) -> list:
        if self._accounts_cache and (time.time() - self._accounts_cached_at) < 20:
            return list(self._accounts_cache)
        payload = self._request("GET", "/api/v3/brokerage/accounts")
        accounts = payload.get("accounts", []) or []
        self._accounts_cache = list(accounts)
        self._accounts_cached_at = time.time()
        return list(accounts)

    def _primary_portfolio_id(self) -> str:
        for account in self._list_accounts():
            portfolio_id = str(account.get("retail_portfolio_id", "")).strip()
            if portfolio_id:
                return portfolio_id
        return ""

    def _resolve_product_id(self, symbol: str) -> str:
        for product_id in self._candidate_product_ids(symbol):
            try:
                payload = self._request("GET", f"/api/v3/brokerage/market/products/{product_id}", auth_required=False)
            except RuntimeError:
                continue
            if str(payload.get("product_id", "")).upper() == product_id:
                return product_id
        return self._candidate_product_ids(symbol)[0]

    @staticmethod
    def _candidate_product_ids(symbol: str) -> list:
        clean = str(symbol or "").upper().replace("-", "").replace("/", "")
        quotes = ("USDT", "USDC", "USD", "EUR", "GBP")
        base = clean
        quote = "USD"
        for candidate in quotes:
            if clean.endswith(candidate) and len(clean) > len(candidate):
                base = clean[: -len(candidate)]
                quote = candidate
                break
        mapped_quote = "USD" if quote == "USDT" else quote
        candidates = [f"{base}-{mapped_quote}"]
        if quote != "USDC":
            candidates.append(f"{base}-USDC")
        if quote != "USD":
            candidates.append(f"{base}-USD")
        deduped = []
        for item in candidates:
            if item not in deduped:
                deduped.append(item)
        return deduped

    @staticmethod
    def _stringify_number(value: float) -> str:
        text = f"{value:.8f}".rstrip("0").rstrip(".")
        return text or "0"


class KrakenBroker(Broker):
    def __init__(self, api_key: str, api_secret: str, broker_name: str = "Kraken"):
        super().__init__(api_key, api_secret, broker_name)
        self.base_url = "https://api.kraken.com"
        self.session = requests.Session()
        self.session.trust_env = False
        self.connected = False

    def connect(self) -> bool:
        try:
            self._private_request("/0/private/Balance")
            self.connected = True
            self.last_error = ""
            return True
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)
            return False

    def disconnect(self) -> bool:
        self.connected = False
        try:
            self.session.close()
        except Exception:
            pass
        return True

    def get_balance(self, asset: str = "USDT") -> float:
        payload = self._private_request("/0/private/Balance")
        balances = payload.get("result", {}) or {}
        desired = asset.upper()
        aliases = [desired]
        if desired == "USD":
            aliases.extend(["ZUSD", "USD"])
        elif desired == "BTC":
            aliases.extend(["XXBT", "XBT"])
        for key, value in balances.items():
            normalized = str(key).upper()
            if normalized in aliases or normalized.startswith(desired):
                try:
                    return float(value)
                except Exception:
                    continue
        return 0.0

    def get_market_price(self, symbol: str) -> float:
        pair = self._pair_for_symbol(symbol)
        payload = self._public_request("/0/public/Ticker", params={"pair": pair})
        result = payload.get("result", {}) or {}
        if not result:
            return 0.0
        first_market = next(iter(result.values()), {})
        close_values = first_market.get("c", [])
        if close_values:
            return float(close_values[0])
        return 0.0

    def place_order(self, symbol: str, side: str, quantity: float) -> Dict:
        payload = self._private_request(
            "/0/private/AddOrder",
            body={
                "pair": self._pair_for_symbol(symbol),
                "type": "buy" if side.upper() == "BUY" else "sell",
                "ordertype": "market",
                "volume": self._stringify_number(quantity),
            },
        )
        result = payload.get("result", {}) or {}
        txids = result.get("txid") or []
        order_id = txids[0] if txids else None
        return {
            "status": "success",
            "order_id": order_id,
            "raw": result,
        }

    def get_order_status(self, symbol: str, order_id: str) -> Dict:
        payload = self._private_request("/0/private/QueryOrders", body={"txid": order_id})
        order = (payload.get("result", {}) or {}).get(order_id, {}) or {}
        status = str(order.get("status", "")).lower()
        mapping = {
            "pending": OrderStatus.PENDING.value,
            "open": OrderStatus.PENDING.value,
            "closed": OrderStatus.FILLED.value,
            "canceled": OrderStatus.CANCELLED.value,
            "expired": OrderStatus.CANCELLED.value,
        }
        return {
            "status": mapping.get(status, status or OrderStatus.FAILED.value),
            "raw": order,
        }

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        payload = self._private_request("/0/private/CancelOrder", body={"txid": order_id})
        result = payload.get("result", {}) or {}
        count = result.get("count")
        try:
            return int(count or 0) > 0
        except Exception:
            return bool(count)

    def get_trading_fees(self, symbol: str) -> float:
        payload = self._private_request(
            "/0/private/TradeVolume",
            body={"pair": self._pair_for_symbol(symbol)},
        )
        fees = (payload.get("result", {}) or {}).get("fees", {}) or {}
        if not fees:
            return 0.0
        first_market = next(iter(fees.values()), {}) or {}
        fee = first_market.get("fee")
        if fee in (None, ""):
            return 0.0
        return float(fee)

    def _public_request(self, path: str, params: Dict = None) -> Dict:
        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            headers={"User-Agent": "FinwiseAI/1.0"},
            timeout=20,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(response.text or "Kraken public request failed.") from exc
        payload = response.json()
        error_items = payload.get("error", []) or []
        if error_items:
            raise RuntimeError(", ".join(str(item) for item in error_items))
        return payload

    def _private_request(self, path: str, body: Dict = None) -> Dict:
        body = dict(body or {})
        nonce = str(int(time.time() * 1000))
        body["nonce"] = nonce
        post_data = urlencode(body)
        signature = self._build_signature(path, nonce, post_data)
        response = self.session.post(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "API-Key": self.api_key,
                "API-Sign": signature,
                "User-Agent": "FinwiseAI/1.0",
            },
            timeout=20,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(response.text or "Kraken private request failed.") from exc
        payload = response.json()
        error_items = payload.get("error", []) or []
        if error_items:
            raise RuntimeError(", ".join(str(item) for item in error_items))
        self.last_error = ""
        return payload

    def _build_signature(self, path: str, nonce: str, post_data: str) -> str:
        encoded = (nonce + post_data).encode("utf-8")
        message = path.encode("utf-8") + hashlib.sha256(encoded).digest()
        secret = base64.b64decode(self.api_secret)
        digest = hmac.new(secret, message, hashlib.sha512).digest()
        return base64.b64encode(digest).decode("utf-8")

    @staticmethod
    def _pair_for_symbol(symbol: str) -> str:
        clean = str(symbol or "").upper().replace("-", "").replace("/", "")
        quotes = ("USDT", "USDC", "USD", "EUR", "GBP", "BTC")
        base = clean
        quote = "USD"
        for candidate in quotes:
            if clean.endswith(candidate) and len(clean) > len(candidate):
                base = clean[: -len(candidate)]
                quote = candidate
                break
        if base == "BTC":
            base = "XBT"
        return f"{base}/{quote}"

    @staticmethod
    def _stringify_number(value: float) -> str:
        text = f"{value:.8f}".rstrip("0").rstrip(".")
        return text or "0"


class OKXBroker(Broker):
    def __init__(
        self,
        access_token: str,
        refresh_token: str = "",
        token_expires_at: Optional[float] = None,
        broker_name: str = "OKX",
    ):
        super().__init__(access_token, refresh_token, broker_name)
        self.access_token = access_token
        self.refresh_token = refresh_token or ""
        self.token_expires_at = float(token_expires_at or 0.0)
        explicit_base = str(os.getenv("OKX_API_BASE_URL", "")).strip().rstrip("/")
        self.base_url = explicit_base or "https://www.okx.com"
        self.session = requests.Session()
        self.session.trust_env = False
        self.connected = False

    @classmethod
    def supports_connection_data(cls, connection_data: Dict[str, Any]) -> bool:
        return bool(connection_data.get("access_token"))

    @classmethod
    def from_connection_data(cls, connection_data: Dict[str, Any], broker_name: str = "") -> "OKXBroker":
        resolved_name = broker_name[:1].upper() + broker_name[1:] if broker_name else "OKX"
        return cls(
            connection_data.get("access_token", ""),
            connection_data.get("refresh_token", ""),
            connection_data.get("token_expires_at"),
            broker_name=resolved_name,
        )

    def connect(self) -> bool:
        try:
            self._request("GET", "/api/v5/account/balance")
            self.connected = True
            self.last_error = ""
            return True
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)
            return False

    def disconnect(self) -> bool:
        self.connected = False
        try:
            self.session.close()
        except Exception:
            pass
        return True

    def get_balance(self, asset: str = "USDT") -> float:
        payload = self._request("GET", "/api/v5/account/balance", params={"ccy": asset.upper()})
        accounts = payload.get("data", []) or []
        if not accounts:
            return 0.0
        for detail in accounts[0].get("details", []) or []:
            if str(detail.get("ccy", "")).upper() != asset.upper():
                continue
            for key in ("availBal", "cashBal", "eq", "availEq"):
                value = detail.get(key)
                if value not in (None, ""):
                    return float(value)
        return 0.0

    def get_market_price(self, symbol: str) -> float:
        payload = self._request(
            "GET",
            "/api/v5/market/ticker",
            params={"instId": self._instrument_for_symbol(symbol)},
            auth_required=False,
        )
        tickers = payload.get("data", []) or []
        if not tickers:
            return 0.0
        return float(tickers[0].get("last") or 0.0)

    def place_order(self, symbol: str, side: str, quantity: float) -> Dict:
        payload = self._request(
            "POST",
            "/api/v5/trade/order",
            body={
                "instId": self._instrument_for_symbol(symbol),
                "tdMode": "cash",
                "side": "buy" if side.upper() == "BUY" else "sell",
                "ordType": "market",
                "sz": self._stringify_number(quantity),
                "tgtCcy": "base_ccy",
            },
        )
        result = (payload.get("data", []) or [{}])[0]
        code = str(result.get("sCode", result.get("code", "0")))
        if code not in {"0", ""}:
            raise RuntimeError(result.get("sMsg") or result.get("msg") or "OKX order was rejected.")
        return {
            "status": "success",
            "order_id": result.get("ordId"),
            "raw": result,
        }

    def get_order_status(self, symbol: str, order_id: str) -> Dict:
        payload = self._request(
            "GET",
            "/api/v5/trade/order",
            params={"instId": self._instrument_for_symbol(symbol), "ordId": order_id},
        )
        order = (payload.get("data", []) or [{}])[0]
        state = str(order.get("state", "")).lower()
        mapping = {
            "live": OrderStatus.PENDING.value,
            "partially_filled": OrderStatus.PARTIAL.value,
            "filled": OrderStatus.FILLED.value,
            "canceled": OrderStatus.CANCELLED.value,
            "mmp_canceled": OrderStatus.CANCELLED.value,
        }
        return {
            "status": mapping.get(state, state or OrderStatus.FAILED.value),
            "raw": order,
        }

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        payload = self._request(
            "POST",
            "/api/v5/trade/cancel-order",
            body={"instId": self._instrument_for_symbol(symbol), "ordId": order_id},
        )
        result = (payload.get("data", []) or [{}])[0]
        code = str(result.get("sCode", result.get("code", "0")))
        return code in {"0", ""}

    def get_trading_fees(self, symbol: str) -> float:
        payload = self._request(
            "GET",
            "/api/v5/account/trade-fee",
            params={"instType": "SPOT", "instId": self._instrument_for_symbol(symbol)},
        )
        result = (payload.get("data", []) or [{}])[0]
        fee = result.get("taker")
        if fee in (None, ""):
            return 0.0
        return abs(float(fee)) * 100

    def _request(
        self,
        method: str,
        path: str,
        params: Dict = None,
        body: Dict = None,
        auth_required: bool = True,
        allow_refresh: bool = True,
    ) -> Dict:
        headers = {"User-Agent": "FinwiseAI/1.0"}
        if auth_required:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        response = self.session.request(
            method=method,
            url=f"{self.base_url}{path}",
            params=params,
            json=body,
            headers=headers,
            timeout=20,
        )
        if response.status_code == 401 and auth_required and allow_refresh and self._refresh_access_token():
            return self._request(method, path, params=params, body=body, auth_required=auth_required, allow_refresh=False)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = response.text or "OKX request failed."
            try:
                payload = response.json()
                detail = payload.get("msg") or payload.get("message") or detail
            except Exception:
                pass
            raise RuntimeError(str(detail).strip()) from exc
        payload = response.json()
        code = str(payload.get("code", "0"))
        if code not in {"0", ""}:
            raise RuntimeError(payload.get("msg") or "OKX request failed.")
        self.last_error = ""
        return payload

    def _refresh_access_token(self) -> bool:
        if not self.refresh_token:
            return False
        client_id = os.getenv("OKX_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.getenv("OKX_OAUTH_CLIENT_SECRET", "").strip()
        token_url = os.getenv("OKX_OAUTH_TOKEN_URL", "").strip()
        if not client_id or not client_secret or not token_url:
            return False
        response = self.session.post(
            token_url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "FinwiseAI/1.0",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=20,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError:
            return False
        payload = response.json()
        access_token = payload.get("access_token") or (payload.get("data", {}) or {}).get("access_token")
        if not access_token:
            return False
        self.access_token = access_token
        self.api_key = access_token
        new_refresh = payload.get("refresh_token") or (payload.get("data", {}) or {}).get("refresh_token")
        if new_refresh:
            self.refresh_token = new_refresh
            self.api_secret = new_refresh
        expires_in = payload.get("expires_in") or (payload.get("data", {}) or {}).get("expires_in", 0)
        try:
            self.token_expires_at = time.time() + float(expires_in or 0)
        except Exception:
            self.token_expires_at = 0.0
        return True

    @staticmethod
    def _instrument_for_symbol(symbol: str) -> str:
        clean = str(symbol or "").upper().replace("-", "").replace("/", "")
        quotes = ("USDT", "USDC", "USD", "EUR", "GBP")
        base = clean
        quote = "USDT"
        for candidate in quotes:
            if clean.endswith(candidate) and len(clean) > len(candidate):
                base = clean[: -len(candidate)]
                quote = candidate
                break
        return f"{base}-{quote}"

    @staticmethod
    def _stringify_number(value: float) -> str:
        text = f"{value:.8f}".rstrip("0").rstrip(".")
        return text or "0"


class BrokerFactory:
    _brokers: Dict[str, type] = {}
    _auth_configs: Dict[str, BrokerAuthConfig] = {}
    _last_connection_error: str = ""

    @staticmethod
    def create_broker(broker_name: str, api_key: str, api_secret: str) -> Optional[Broker]:
        broker_class = BrokerFactory._brokers.get(broker_name.lower())
        if broker_class is None:
            BrokerFactory._last_connection_error = f"{broker_name} is not registered in Finwise."
            return None

        broker = broker_class(api_key, api_secret)
        if not broker.connect():
            broker_error = getattr(broker, "last_error", "") or "Broker connection failed."
            BrokerFactory._last_connection_error = BrokerFactory._format_connection_error(
                broker_name.lower(),
                broker_error,
                broker,
            )
            return None
        BrokerFactory._last_connection_error = ""
        return broker

    @staticmethod
    def connect_broker_with_api(broker_name: str, api_key: str, api_secret: str) -> Optional[Broker]:
        return BrokerFactory.create_broker(broker_name, api_key, api_secret)

    @staticmethod
    def get_last_connection_error() -> str:
        return BrokerFactory._last_connection_error

    @staticmethod
    def run_connector_test(broker: Broker, symbol: str = "BTCUSDT", asset: str = "USDT") -> Dict[str, Any]:
        report: Dict[str, Any] = {
            "broker": getattr(broker, "name", "Broker"),
            "symbol": str(symbol or "BTCUSDT").upper(),
            "asset": str(asset or "USDT").upper(),
            "tested_at": datetime.utcnow().isoformat() + "Z",
            "checks": [],
            "passed": 0,
            "total": 0,
            "summary": "",
        }

        if is_forex_symbol(report["symbol"]):
            report["checks"].append(
                {
                    "name": "Market support",
                    "ok": False,
                    "detail": "Forex analysis is supported, but live API execution is currently limited to crypto exchange brokers.",
                }
            )
            report["total"] = 1
            report["status"] = "failed"
            report["summary"] = "Connector test blocked: forex live execution is not available for this broker adapter."
            return report

        def add_check(name: str, fn) -> None:
            try:
                detail = fn()
                report["checks"].append({"name": name, "ok": True, "detail": str(detail)})
                report["passed"] += 1
            except Exception as exc:
                report["checks"].append({"name": name, "ok": False, "detail": str(exc)})
            report["total"] += 1

        def auth_check() -> str:
            if broker.connect():
                endpoint = getattr(broker, "base_url", "")
                mode = "testnet" if "testnet" in endpoint else "mainnet" if endpoint else "live"
                return f"Authenticated successfully ({mode})."
            error = getattr(broker, "last_error", "") or "Authentication failed."
            raise RuntimeError(error)

        def balance_check() -> str:
            balance_value = float(broker.get_balance(report["asset"]))
            return f"{report['asset']} balance available: {balance_value:,.8f}".rstrip("0").rstrip(".")

        def price_check() -> str:
            last_price = float(broker.get_market_price(report["symbol"]))
            if last_price <= 0:
                raise RuntimeError("Market price returned 0.")
            return f"{report['symbol']} last price: {last_price:,.6f}".rstrip("0").rstrip(".")

        def fee_check() -> str:
            fee_value = float(broker.get_trading_fees(report["symbol"]))
            return f"Taker fee estimate: {fee_value:.6f}%".rstrip("0").rstrip(".")

        add_check("Authentication", auth_check)
        add_check("Balance Access", balance_check)
        add_check("Market Data", price_check)
        add_check("Trading Fees", fee_check)

        failures = [item for item in report["checks"] if not item["ok"]]
        if not failures:
            report["summary"] = "Connector test passed. Broker auth, balance, price, and fee access are working."
        else:
            first_failure = failures[0]
            report["summary"] = f"Connector test found an issue in {first_failure['name']}: {first_failure['detail']}"
        return report

    @staticmethod
    def get_auth_config(broker_name: str) -> BrokerAuthConfig:
        key = broker_name.lower()
        config = BrokerFactory._auth_configs.get(key)
        if config is not None:
            return config
        display_name = broker_name[:1].upper() + broker_name[1:]
        return BrokerAuthConfig(
            broker_name=key,
            display_name=display_name,
        )

    @staticmethod
    def get_broker_catalog() -> list:
        catalog = []
        seen = set()
        known_brokers = sorted(set(BrokerFactory.get_available_brokers()) | set(BrokerFactory._auth_configs.keys()))
        for broker_name in known_brokers:
            config = BrokerFactory.get_auth_config(broker_name)
            oauth_request = BrokerFactory.get_oauth_connection_request(broker_name)
            adapter_ready = broker_name in BrokerFactory._brokers
            connectable = bool(adapter_ready and (oauth_request.get("ready") or config.api_key_supported))
            if connectable:
                status_label = "Live Now"
                status_tone = "live"
            elif config.oauth_supported and config.oauth_partner_program_required:
                status_label = "Partner Setup"
                status_tone = "pending"
            elif config.oauth_supported:
                status_label = "App Setup"
                status_tone = "setup"
            elif config.api_key_supported and adapter_ready:
                status_label = "API Key"
                status_tone = "setup"
            else:
                status_label = "Planned"
                status_tone = "planned"
            description = config.oauth_description if config.oauth_supported else config.api_fallback_description
            catalog.append(
                {
                    "broker_name": config.broker_name,
                    "display_name": config.display_name,
                    "logo_path": config.logo_path,
                    "oauth_supported": config.oauth_supported,
                    "oauth_ready": oauth_request.get("ready", False),
                    "api_key_supported": config.api_key_supported,
                    "oauth_button_label": config.oauth_button_label,
                    "oauth_description": config.oauth_description,
                    "api_fallback_description": config.api_fallback_description,
                    "connectable": connectable,
                    "adapter_ready": adapter_ready,
                    "status_label": status_label,
                    "status_tone": status_tone,
                    "description": description,
                }
            )
            seen.add(config.broker_name)
        for item in DISPLAY_ONLY_BROKERS:
            if item["broker_name"] in seen:
                continue
            catalog.append(dict(item))
        return catalog

    @staticmethod
    def get_oauth_connection_request(broker_name: str) -> Dict:
        config = BrokerFactory.get_auth_config(broker_name)
        if not config.oauth_supported:
            return {
                "supported": False,
                "ready": False,
                "reason": "oauth_unavailable",
                "message": f"OAuth is not available for {config.display_name} yet.",
            }
        client_id = os.getenv(config.oauth_client_id_env, "").strip() if config.oauth_client_id_env else ""
        client_secret = os.getenv(config.oauth_client_secret_env, "").strip() if config.oauth_client_secret_env else ""
        authorize_url = BrokerFactory._resolve_oauth_authorize_url(config)
        token_url = BrokerFactory._resolve_oauth_token_url(config)
        client_secret_ok = client_secret or not config.oauth_client_secret_required
        if not client_id or not client_secret_ok or not authorize_url or not token_url:
            missing_items = []
            if not client_id and config.oauth_client_id_env:
                missing_items.append(config.oauth_client_id_env)
            if not client_secret_ok and config.oauth_client_secret_env:
                missing_items.append(config.oauth_client_secret_env)
            if not authorize_url:
                missing_items.append(config.oauth_authorize_url_env or "authorization URL")
            if not token_url:
                missing_items.append(config.oauth_token_url_env or "token URL")
            missing_suffix = f" Missing: {', '.join(missing_items)}." if missing_items else ""
            return {
                "supported": True,
                "ready": False,
                "reason": "oauth_not_configured",
                "message": (
                    f"{config.display_name} supports OAuth, but Finwise is missing the required "
                    f"broker OAuth credentials or URLs.{missing_suffix}"
                ),
            }
        try:
            resolve_broker_oauth_redirect_uri(broker_name=broker_name)
        except RuntimeError as exc:
            return {
                "supported": True,
                "ready": False,
                "reason": "oauth_redirect_invalid",
                "message": str(exc),
            }
        return {
            "supported": True,
            "ready": True,
            "reason": "oauth_ready",
            "message": f"OAuth flow is ready for {config.display_name}.",
        }

    @staticmethod
    def generate_oauth_state(broker_name: str) -> str:
        config = BrokerFactory.get_auth_config(broker_name)
        return f"{config.oauth_state_prefix}:{broker_name.lower()}:{secrets.token_urlsafe(24)}"

    @staticmethod
    def build_oauth_authorization_url(broker_name: str, redirect_uri: str, state: str) -> str:
        config = BrokerFactory.get_auth_config(broker_name)
        oauth_request = BrokerFactory.get_oauth_connection_request(broker_name)
        if not oauth_request.get("ready"):
            raise RuntimeError(oauth_request.get("message", "OAuth is not ready for this broker."))

        params = {
            "client_id": os.getenv(config.oauth_client_id_env, "").strip(),
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
        if config.oauth_scope:
            scope_tokens = [item for item in str(config.oauth_scope).split() if item]
            params["scope"] = config.oauth_scope_delimiter.join(scope_tokens) if scope_tokens else config.oauth_scope
        authorize_url = BrokerFactory._resolve_oauth_authorize_url(config)
        return f"{authorize_url}?{urlencode(params)}"

    @staticmethod
    def exchange_oauth_code_for_connection(broker_name: str, code: str, redirect_uri: str) -> Dict:
        config = BrokerFactory.get_auth_config(broker_name)
        oauth_request = BrokerFactory.get_oauth_connection_request(broker_name)
        if not oauth_request.get("ready"):
            raise RuntimeError(oauth_request.get("message", "OAuth is not ready for this broker."))

        client_id = os.getenv(config.oauth_client_id_env, "").strip()
        client_secret = os.getenv(config.oauth_client_secret_env, "").strip()
        session = requests.Session()
        session.trust_env = False
        token_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "FinwiseAI/1.0",
        }
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
        }
        if redirect_uri:
            token_data["redirect_uri"] = redirect_uri
        if config.oauth_token_auth_style == "basic":
            credentials = f"{client_id}:{client_secret}".encode("utf-8")
            token_headers["Authorization"] = "Basic " + base64.b64encode(credentials).decode("utf-8")
            token_data["client_id"] = client_id
        else:
            token_data["client_id"] = client_id
            if client_secret:
                token_data["client_secret"] = client_secret
        token_response = session.post(
            BrokerFactory._resolve_oauth_token_url(config),
            headers=token_headers,
            data=token_data,
            timeout=20,
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        token_result = token_payload.get("result", {}) if isinstance(token_payload.get("result"), dict) else {}
        token_data_payload = token_payload.get("data", {}) if isinstance(token_payload.get("data"), dict) else {}
        access_token = (
            token_payload.get("access_token")
            or token_result.get("access_token")
            or token_data_payload.get("access_token")
        )
        refresh_token = (
            token_payload.get("refresh_token")
            or token_result.get("refresh_token", "")
            or token_data_payload.get("refresh_token", "")
        )
        expires_in = (
            token_payload.get("expires_in")
            or token_result.get("expires_in", 0)
            or token_data_payload.get("expires_in", 0)
        )
        if not access_token:
            raise RuntimeError("OAuth token exchange did not return an access token.")
        expires_at = time.time() + float(expires_in or 0)
        connection_data = {
            "broker_name": broker_name.lower(),
            "auth_method": "oauth",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_expires_at": expires_at,
            "metadata": {
                "token_payload": token_payload,
            },
        }
        mode = config.oauth_connection_mode
        if mode == "bearer_token":
            connection_data["metadata"]["connection_mode"] = mode
            return connection_data
        if not config.oauth_resource_url:
            raise RuntimeError("OAuth resource endpoint is not configured for this broker.")
        resource_headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "FinwiseAI/1.0",
        }
        resource_method = (config.oauth_resource_method or "GET").upper()
        resource_response = session.request(
            method=resource_method,
            url=config.oauth_resource_url,
            headers=resource_headers,
            json={} if resource_method in {"POST", "PUT", "PATCH"} else None,
            timeout=20,
        )
        resource_response.raise_for_status()
        resource_payload = resource_response.json()
        result = resource_payload.get("result", resource_payload)
        if isinstance(result, list):
            result = result[0] if result else {}
        ret_code = resource_payload.get("retCode", resource_payload.get("ret_code", resource_payload.get("code", 0)))
        if str(ret_code) not in {"0", "", "None"} and ret_code is not None:
            raise RuntimeError(
                resource_payload.get("retMsg")
                or resource_payload.get("ret_msg")
                or resource_payload.get("msg")
                or "Broker OAuth resource request failed."
            )
        api_key = (
            result.get("api_key")
            or result.get("apiKey")
            or result.get("key")
            or result.get("public_key")
            or result.get("publicKey")
            or ""
        )
        api_secret = (
            result.get("api_secret")
            or result.get("apiSecret")
            or result.get("secret")
            or result.get("private_key")
            or result.get("privateKey")
            or ""
        )
        if not api_key or not api_secret:
            raise RuntimeError("OAuth resource exchange did not return broker API credentials.")
        connection_data["api_key"] = api_key
        connection_data["api_secret"] = api_secret
        connection_data["metadata"]["resource_payload"] = resource_payload
        connection_data["metadata"]["connection_mode"] = mode
        return connection_data

    @staticmethod
    def create_broker_from_connection_data(broker_name: str, connection_data: Dict) -> Optional[Broker]:
        broker_key = broker_name.lower()
        broker_class = BrokerFactory._brokers.get(broker_key)
        if broker_class is None:
            BrokerFactory._last_connection_error = f"{broker_name} is not registered in Finwise."
            return None
        if not BrokerFactory.connection_data_is_bootable(broker_key, connection_data):
            BrokerFactory._last_connection_error = f"{broker_name.title()} does not have enough saved credentials to reconnect."
            return None
        try:
            broker = broker_class.from_connection_data(connection_data, broker_name=broker_key)
        except Exception as exc:
            BrokerFactory._last_connection_error = str(exc)
            return None
        if not broker.connect():
            broker_error = getattr(broker, "last_error", "") or "Broker connection failed."
            BrokerFactory._last_connection_error = BrokerFactory._format_connection_error(
                broker_key,
                broker_error,
                broker,
            )
            return None
        BrokerFactory._last_connection_error = ""
        return broker

    @staticmethod
    def register_broker(broker_name: str, broker_class: type, auth_config: BrokerAuthConfig = None) -> None:
        if not issubclass(broker_class, Broker):
            raise TypeError("broker_class must inherit from Broker")
        key = broker_name.lower()
        BrokerFactory._brokers[key] = broker_class
        BrokerFactory._auth_configs[key] = auth_config or BrokerAuthConfig(
            broker_name=key,
            display_name=broker_name[:1].upper() + broker_name[1:],
        )

    @staticmethod
    def register_auth_config(auth_config: BrokerAuthConfig) -> None:
        BrokerFactory._auth_configs[auth_config.broker_name.lower()] = auth_config

    @staticmethod
    def connection_data_is_bootable(broker_name: str, connection_data: Dict[str, Any]) -> bool:
        broker_class = BrokerFactory._brokers.get(broker_name.lower())
        if broker_class is None:
            return False
        return bool(broker_class.supports_connection_data(connection_data))

    @staticmethod
    def get_available_brokers() -> list:
        return sorted(BrokerFactory._brokers.keys())

    @staticmethod
    def _resolve_oauth_authorize_url(config: BrokerAuthConfig) -> str:
        if config.oauth_authorize_url_env:
            override = os.getenv(config.oauth_authorize_url_env, "").strip()
            if override:
                return override
        return str(config.oauth_authorize_url or "").strip()

    @staticmethod
    def _resolve_oauth_token_url(config: BrokerAuthConfig) -> str:
        if config.oauth_token_url_env:
            override = os.getenv(config.oauth_token_url_env, "").strip()
            if override:
                return override
        return str(config.oauth_token_url or "").strip()

    @staticmethod
    def _format_connection_error(broker_name: str, broker_error: str, broker: Broker) -> str:
        if broker_name == "bybit":
            endpoint_label = "testnet" if "api-testnet" in getattr(broker, "base_url", "") else "mainnet"
            return (
                f"{broker_error} "
                f"(Current Finwise Bybit target: {endpoint_label}, endpoint: {getattr(broker, 'base_url', 'unknown')}, "
                f"account type: {getattr(broker, 'account_type', 'UNKNOWN')})"
            ).strip()
        if broker_name == "coinbase":
            return f"{broker_error} (Current Finwise Coinbase endpoint: {getattr(broker, 'base_url', 'unknown')})".strip()
        if broker_name == "kraken":
            return f"{broker_error} (Current Finwise Kraken endpoint: {getattr(broker, 'base_url', 'unknown')})".strip()
        if broker_name == "okx":
            return f"{broker_error} (Current Finwise OKX endpoint: {getattr(broker, 'base_url', 'unknown')})".strip()
        return broker_error


class TradingBot:
    def __init__(self, broker: Broker, max_drawdown: float = 10.0, config: TradingConfig = None):
        if not isinstance(broker, Broker):
            raise ValueError("broker must be an instance of Broker")
        self.broker = broker
        self.max_drawdown = max_drawdown
        self.config = config or TradingConfig()
        self.trades = []
        self.initial_balance = 0.0
        self.current_balance = 0.0

    def _current_drawdown(self) -> float:
        if not self.trades:
            return 0.0
        peak = max([trade["balance_after"] for trade in self.trades] + [self.initial_balance or self.current_balance])
        if peak <= 0:
            return 0.0
        return ((peak - self.current_balance) / peak) * 100

    def _projected_profit_percent(self, ai_worker_analysis: Dict) -> float:
        entry_exit = ai_worker_analysis.get("entry_exit", {})
        entry_price = float(entry_exit.get("actual_entry") or entry_exit.get("entry_price") or 0)
        reward_amount = float(entry_exit.get("reward_amount") or 0)
        if entry_price <= 0 or reward_amount <= 0:
            return 0.0

        # reward_amount already reflects the modeled move after exit-fee impact,
        # so this is the cleanest estimate of the setup's net upside.
        projected_profit_percent = reward_amount / entry_price * 100
        return round(max(projected_profit_percent, 0.0), 2)

    def _target_profit_price(self, ai_worker_analysis: Dict, signal_type: str, entry_price: float) -> float:
        entry_exit = ai_worker_analysis.get("entry_exit", {})
        take_profit = float(entry_exit.get("take_profit") or 0)
        if take_profit > 0:
            return round(take_profit, 8)
        if entry_price <= 0:
            return 0.0
        fallback_multiplier = self.config.min_projected_profit_percent / 100
        if signal_type.upper() == "BUY":
            return round(entry_price * (1 + fallback_multiplier), 8)
        return round(max(entry_price * (1 - fallback_multiplier), 0.00000001), 8)

    def build_profit_guard_report(self, ai_worker_analysis: Dict) -> Dict:
        entry_exit = ai_worker_analysis.get("entry_exit", {})
        summary = ai_worker_analysis.get("summary", {})
        black_swan = ai_worker_analysis.get("black_swan_risk", {})
        robustness = ai_worker_analysis.get("robustness", {})
        regime = ai_worker_analysis.get("regime", {})

        confidence = float(ai_worker_analysis.get("confidence", 0) or 0)
        rr_ratio = float(entry_exit.get("risk_reward_ratio", 0) or 0)
        projected_profit_percent = self._projected_profit_percent(ai_worker_analysis)
        black_swan_risk = float(black_swan.get("risk_level", 0) or 0)
        trend_score = abs(float(summary.get("trend_score", 0) or 0))
        momentum_score = abs(float(summary.get("momentum_score", 0) or 0))
        setup_quality = str(summary.get("setup_quality", "unknown")).lower()
        robust = bool(robustness.get("robust", False))
        regime_name = regime.get("regime", "unknown") if isinstance(regime, dict) else str(regime)

        failed_checks = []
        passed_checks = []

        def check(condition: bool, passed_message: str, failed_message: str) -> None:
            if condition:
                passed_checks.append(passed_message)
            else:
                failed_checks.append(failed_message)

        check(
            confidence >= self.config.min_confidence_percent,
            f"Confidence {confidence:.0f}% meets minimum threshold",
            f"Confidence {confidence:.0f}% is below the {self.config.min_confidence_percent:.0f}% auto-trade threshold",
        )
        check(
            rr_ratio >= self.config.min_risk_reward_ratio,
            f"Reward/risk {rr_ratio:.2f} meets minimum threshold",
            f"Reward/risk {rr_ratio:.2f} is below the {self.config.min_risk_reward_ratio:.2f} requirement",
        )
        check(
            projected_profit_percent >= self.config.min_projected_profit_percent,
            f"Projected profit {projected_profit_percent:.2f}% clears the minimum edge requirement",
            f"Projected profit {projected_profit_percent:.2f}% is below the {self.config.min_projected_profit_percent:.2f}% minimum edge",
        )
        check(
            black_swan_risk <= self.config.max_black_swan_risk,
            f"Black swan risk {black_swan_risk:.1f} is within limits",
            f"Black swan risk {black_swan_risk:.1f} exceeds the {self.config.max_black_swan_risk:.0f} limit",
        )
        check(
            trend_score >= self.config.min_trend_score,
            f"Trend score {trend_score:.2f} confirms directional structure",
            f"Trend score {trend_score:.2f} is below the {self.config.min_trend_score:.2f} minimum",
        )
        check(
            momentum_score >= self.config.min_momentum_score,
            f"Momentum score {momentum_score:.2f} confirms follow-through",
            f"Momentum score {momentum_score:.2f} is below the {self.config.min_momentum_score:.2f} minimum",
        )

        if self.config.require_robust_signal:
            check(
                robust,
                "Signal robustness check passed",
                "Signal robustness check failed",
            )
        else:
            passed_checks.append("Robustness gate disabled")

        if self.config.require_high_quality_setup:
            check(
                setup_quality == "high",
                f"Setup quality is {setup_quality}",
                f"Setup quality is {setup_quality}; only high-quality setups can auto-execute",
            )
        else:
            passed_checks.append(f"Setup quality gate disabled ({setup_quality})")

        if regime_name == "volatile":
            failed_checks.append("Market regime is volatile, so auto-trade is standing aside")

        quality_score = len(passed_checks)
        total_checks = quality_score + len(failed_checks)

        return {
            "passed": len(failed_checks) == 0,
            "reason": failed_checks[0] if failed_checks else "Profit guard approved the setup",
            "min_projected_profit_percent": self.config.min_projected_profit_percent,
            "account_growth_goal_percent": self.config.account_growth_goal_percent,
            "projected_profit_percent": projected_profit_percent,
            "confidence_percent": round(confidence, 2),
            "risk_reward_ratio": round(rr_ratio, 2),
            "black_swan_risk": round(black_swan_risk, 2),
            "trend_score": round(trend_score, 2),
            "momentum_score": round(momentum_score, 2),
            "setup_quality": setup_quality,
            "regime": regime_name,
            "quality_score": quality_score,
            "total_checks": total_checks,
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
        }

    def validate_ai_worker_signal(self, ai_worker_analysis: Dict) -> Tuple[bool, str, Dict]:
        if not ai_worker_analysis.get("trade_allowed", False):
            return False, ai_worker_analysis.get("reason", "Signal blocked"), {}

        signal = ai_worker_analysis.get("signal", "HOLD")
        if signal not in {"BUY", "SELL"}:
            return False, f"Unsupported signal: {signal}", {}

        current_drawdown = self._current_drawdown()
        if current_drawdown > self.max_drawdown:
            return False, f"Drawdown exceeded: {current_drawdown:.2f}%", {}

        profit_guard = self.build_profit_guard_report(ai_worker_analysis)
        if not profit_guard["passed"]:
            if self.config.always_execute_signals:
                failed_checks = list(profit_guard.get("failed_checks", []))
                failed_checks.append("Legacy execute override is enabled, but Finwise now enforces the hard risk gates.")
                profit_guard["failed_checks"] = failed_checks
            return False, profit_guard["reason"], profit_guard

        if self.config.always_execute_signals:
            return True, "Signal validated; hard risk gates remain enforced", profit_guard
        return True, "Signal validated", profit_guard

    def _resolve_trade_amount(self, balance: float, ai_worker_analysis: Dict) -> float:
        position_size = ai_worker_analysis.get("position_size", {})
        model_usd = float(position_size.get("position_size_usd", 0) or 0)
        risk_cap = balance * self.config.risk_per_trade
        balance_cap = balance * self.config.max_position_size
        trade_amount = model_usd if model_usd > 0 else risk_cap
        return min(self.config.max_trade_usd, risk_cap, balance_cap, trade_amount, balance)

    def execute_trade_from_ai_worker(self, ai_worker_analysis: Dict, symbol: str) -> Dict:
        try:
            symbol = str(symbol or "").upper()
            if is_forex_symbol(symbol):
                return {
                    "status": "blocked",
                    "reason": "Forex analysis is supported, but live API execution is currently limited to crypto exchange brokers.",
                    "timestamp": datetime.utcnow().isoformat(),
                    "profit_guard": {},
                }

            is_valid, reason, profit_guard = self.validate_ai_worker_signal(ai_worker_analysis)
            if not is_valid:
                return {
                    "status": "blocked",
                    "reason": reason,
                    "timestamp": datetime.utcnow().isoformat(),
                    "profit_guard": profit_guard,
                }

            balance = float(self.broker.get_balance("USDT"))
            if balance <= 0:
                return {"status": "failed", "reason": "insufficient_balance"}

            if self.initial_balance == 0:
                self.initial_balance = balance
            self.current_balance = balance

            signal_type = ai_worker_analysis["signal"]
            market_price = float(self.broker.get_market_price(symbol))
            if market_price <= 0:
                return {"status": "failed", "reason": "price_fetch_error"}

            entry_exit = ai_worker_analysis.get("entry_exit", {})
            entry_price = float(entry_exit.get("actual_entry") or 0)
            if entry_price <= 0:
                price_multiplier = 1 + self.config.slippage_percent / 100 if signal_type == "BUY" else 1 - self.config.slippage_percent / 100
                entry_price = market_price * price_multiplier

            trade_amount = self._resolve_trade_amount(balance, ai_worker_analysis)
            if trade_amount <= 0:
                return {"status": "failed", "reason": "trade_amount_zero"}

            quantity = round(trade_amount / entry_price, 8)
            if quantity < self.config.min_order_size:
                return {"status": "failed", "reason": "quantity_too_small"}

            order_result = self.broker.place_order(symbol, signal_type, quantity)
            if order_result.get("status") != "success":
                return order_result

            fee_percent = float(self.broker.get_trading_fees(symbol) or self.config.default_fee_percent)
            fee_paid = trade_amount * fee_percent / 100
            regime = ai_worker_analysis.get("regime", {})
            summary = ai_worker_analysis.get("summary", {})
            target_profit_price = self._target_profit_price(ai_worker_analysis, signal_type, entry_price)
            account_growth_goal_balance = balance * (1 + self.config.account_growth_goal_percent / 100)

            trade_log = {
                "broker": self.broker.name,
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "signal": signal_type,
                "confidence": float(ai_worker_analysis.get("confidence", 0)),
                "quantity": quantity,
                "notional_usd": round(trade_amount, 2),
                "entry_price": round(entry_price, 8),
                "market_price": round(market_price, 8),
                "balance_before": round(balance, 2),
                "balance_after": round(balance - trade_amount - fee_paid, 2),
                "fee_paid": round(fee_paid, 4),
                "order_id": order_result.get("order_id"),
                "risk_reward_ratio": float(entry_exit.get("risk_reward_ratio", 0)),
                "projected_profit_percent": float(profit_guard.get("projected_profit_percent", 0)),
                "min_projected_profit_percent": float(
                    profit_guard.get("min_projected_profit_percent", self.config.min_projected_profit_percent)
                ),
                "account_growth_goal_percent": float(
                    profit_guard.get("account_growth_goal_percent", self.config.account_growth_goal_percent)
                ),
                "account_growth_goal_balance": round(account_growth_goal_balance, 2),
                "target_profit_price": float(target_profit_price),
                "stop_loss": float(entry_exit.get("stop_loss", 0)),
                "take_profit": float(entry_exit.get("take_profit", 0)),
                "regime": regime.get("regime", "unknown") if isinstance(regime, dict) else str(regime),
                "setup_quality": summary.get("setup_quality", "unknown") if isinstance(summary, dict) else "unknown",
            }

            self.trades.append(trade_log)
            self.current_balance = trade_log["balance_after"]

            return {
                "status": "success",
                "broker": self.broker.name,
                "trade": trade_log,
                "order_id": order_result.get("order_id"),
                "profit_guard": profit_guard,
                "message": f"Executed {signal_type} {quantity:.8f} {symbol} at {entry_price:.8f}",
            }
        except Exception as exc:
            return {"status": "failed", "reason": str(exc)}

    def preview_trade_from_ai_worker(self, ai_worker_analysis: Dict, symbol: str) -> Dict:
        try:
            symbol = str(symbol or "").upper()
            if is_forex_symbol(symbol):
                return {
                    "status": "blocked",
                    "reason": "Forex analysis is supported, but live API execution is currently limited to crypto exchange brokers.",
                    "symbol": symbol,
                    "profit_guard": {},
                }

            is_valid, reason, profit_guard = self.validate_ai_worker_signal(ai_worker_analysis)

            try:
                balance = float(self.broker.get_balance("USDT"))
            except Exception as exc:
                return {
                    "status": "failed",
                    "reason": f"Balance check failed: {exc}",
                    "profit_guard": profit_guard,
                }

            try:
                market_price = float(self.broker.get_market_price(symbol))
            except Exception as exc:
                return {
                    "status": "failed",
                    "reason": f"Market price check failed: {exc}",
                    "balance": balance,
                    "profit_guard": profit_guard,
                }

            signal_type = ai_worker_analysis.get("signal", "HOLD")
            entry_exit = ai_worker_analysis.get("entry_exit", {})
            entry_price = float(entry_exit.get("actual_entry") or 0)
            if entry_price <= 0 and market_price > 0:
                price_multiplier = 1 + self.config.slippage_percent / 100 if signal_type == "BUY" else 1 - self.config.slippage_percent / 100
                entry_price = market_price * price_multiplier

            trade_amount = self._resolve_trade_amount(balance, ai_worker_analysis) if balance > 0 else 0.0
            quantity = round(trade_amount / entry_price, 8) if entry_price > 0 else 0.0

            preview = {
                "status": "ready" if is_valid and quantity >= self.config.min_order_size else "blocked" if not is_valid else "failed",
                "reason": reason if not is_valid else "Trade route is ready for execution." if quantity >= self.config.min_order_size else "Quantity would be below the minimum order size.",
                "signal": signal_type,
                "symbol": symbol,
                "balance": round(balance, 8),
                "market_price": round(market_price, 8),
                "entry_price": round(entry_price, 8),
                "trade_amount": round(trade_amount, 8),
                "quantity": round(quantity, 8),
                "min_order_size": self.config.min_order_size,
                "profit_guard": profit_guard,
            }
            return preview
        except Exception as exc:
            return {"status": "failed", "reason": str(exc), "profit_guard": {}}

    def get_performance(self) -> Dict:
        if not self.trades:
            return {
                "broker": self.broker.name,
                "total_trades": 0,
                "message": "No trades yet",
            }

        total_trades = len(self.trades)
        buy_trades = [trade for trade in self.trades if trade["signal"] == "BUY"]
        sell_trades = [trade for trade in self.trades if trade["signal"] == "SELL"]
        avg_confidence = sum(trade["confidence"] for trade in self.trades) / total_trades
        avg_rr = sum(trade.get("risk_reward_ratio", 0) for trade in self.trades) / total_trades
        total_notional = sum(trade.get("notional_usd", 0) for trade in self.trades)

        return {
            "broker": self.broker.name,
            "total_trades": total_trades,
            "buy_trades": len(buy_trades),
            "sell_trades": len(sell_trades),
            "avg_confidence": round(avg_confidence, 2),
            "avg_risk_reward": round(avg_rr, 2),
            "total_notional_usd": round(total_notional, 2),
            "current_drawdown": round(self._current_drawdown(), 2),
            "last_trade": self.trades[-1]["timestamp"],
            "guard_mode": "legacy_override" if self.config.always_execute_signals else "strict",
            "min_confidence_percent": self.config.min_confidence_percent,
            "min_risk_reward_ratio": self.config.min_risk_reward_ratio,
            "min_projected_profit_percent": self.config.min_projected_profit_percent,
            "account_growth_goal_percent": self.config.account_growth_goal_percent,
        }


BrokerFactory.register_broker(
    "bybit",
    BybitBroker,
    BrokerAuthConfig(
        broker_name="bybit",
        display_name="Bybit",
        logo_path="https://upload.wikimedia.org/wikipedia/commons/thumb/1/14/Bybit_Logo.svg/500px-Bybit_Logo.svg.png",
        oauth_supported=True,
        api_key_supported=True,
        oauth_button_label="Connect with Broker",
        oauth_description="OAuth connection is available for Bybit once Finwise is configured with broker OAuth credentials.",
        api_fallback_description="If Bybit OAuth is not configured yet, Finwise will ask for API credentials as the fallback connection method.",
        oauth_client_id_env="BYBIT_OAUTH_CLIENT_ID",
        oauth_client_secret_env="BYBIT_OAUTH_CLIENT_SECRET",
        oauth_authorize_url="https://www.bybit.com/en/oauth",
        oauth_token_url="https://api2.bybit.com/oauth/v1/public/access_token",
        oauth_resource_url="https://api2.bybit.com/oauth/v1/resource/restrict/openapi",
        oauth_scope="openapi",
        oauth_connection_mode="api_key_pair",
        oauth_state_prefix="broker-oauth",
    ),
)

BrokerFactory.register_broker(
    "coinbase",
    CoinbaseBroker,
    BrokerAuthConfig(
        broker_name="coinbase",
        display_name="Coinbase",
        logo_path="https://images.ctfassets.net/c5bd0wqjc7v0/1J1wT0W5EydfK8s1A0Kzr2/4e4dbf6f0c2c91fda591d61d848ca8f7/Coinbase_C_Blu_432x432.png",
        oauth_supported=True,
        api_key_supported=False,
        oauth_button_label="Connect with Coinbase",
        oauth_description="Coinbase App OAuth can return users straight into Finwise for balance, account, and Advanced Trade access.",
        api_fallback_description="Coinbase consumer trading should use OAuth instead of asking users to copy credentials.",
        oauth_client_id_env="COINBASE_OAUTH_CLIENT_ID",
        oauth_client_secret_env="COINBASE_OAUTH_CLIENT_SECRET",
        oauth_authorize_url="https://login.coinbase.com/oauth2/auth",
        oauth_token_url="https://login.coinbase.com/oauth2/token",
        oauth_scope="wallet:user:read wallet:accounts:read offline_access",
        oauth_scope_delimiter=",",
        oauth_token_auth_style="client_secret_body",
        oauth_connection_mode="bearer_token",
        oauth_partner_program_required=True,
        oauth_state_prefix="broker-oauth",
    ),
)

BrokerFactory.register_broker(
    "kraken",
    KrakenBroker,
    BrokerAuthConfig(
        broker_name="kraken",
        display_name="Kraken",
        logo_path="https://upload.wikimedia.org/wikipedia/commons/thumb/2/29/Kraken-logo.svg/512px-Kraken-logo.svg.png",
        oauth_supported=True,
        api_key_supported=True,
        oauth_button_label="Connect with Kraken",
        oauth_description="Kraken Connect supports OAuth 2.0 and Fast API keys for approved third-party apps.",
        api_fallback_description="If Kraken OAuth is not set up yet, Finwise can still connect with a normal Kraken API key and secret.",
        oauth_client_id_env="KRAKEN_OAUTH_CLIENT_ID",
        oauth_client_secret_env="KRAKEN_OAUTH_CLIENT_SECRET",
        oauth_authorize_url="https://id.kraken.com/oauth/authorize",
        oauth_token_url="https://api.kraken.com/oauth/token",
        oauth_resource_url="https://api.kraken.com/fast-api-key",
        oauth_scope=(
            "account.fast-api-key:funds-query "
            "account.fast-api-key:trades-query-open "
            "account.fast-api-key:trades-query-closed "
            "account.fast-api-key:trades-modify "
            "account.fast-api-key:trades-close "
            "account.fast-api-key:write"
        ),
        oauth_token_auth_style="basic",
        oauth_connection_mode="api_key_pair",
        oauth_resource_method="POST",
        oauth_partner_program_required=True,
        oauth_state_prefix="broker-oauth",
    ),
)

BrokerFactory.register_broker(
    "okx",
    OKXBroker,
    BrokerAuthConfig(
        broker_name="okx",
        display_name="OKX",
        logo_path="https://static.okx.com/cdn/assets/imgs/2211/5D79824F98D32028.png",
        oauth_supported=True,
        api_key_supported=False,
        oauth_button_label="Connect with OKX",
        oauth_description="OKX broker OAuth can hand Finwise a bearer session for account and trade calls once your broker app is approved.",
        api_fallback_description="OKX manual API keys need extra passphrase handling, so Finwise prefers OAuth for this exchange.",
        oauth_client_id_env="OKX_OAUTH_CLIENT_ID",
        oauth_client_secret_env="OKX_OAUTH_CLIENT_SECRET",
        oauth_authorize_url_env="OKX_OAUTH_AUTHORIZE_URL",
        oauth_token_url_env="OKX_OAUTH_TOKEN_URL",
        oauth_scope="read_only trade",
        oauth_connection_mode="bearer_token",
        oauth_partner_program_required=True,
        oauth_state_prefix="broker-oauth",
    ),
)
