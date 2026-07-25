import json
import os
import re
import socket
import hashlib
import hmac
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client

_LOCAL_ENV_PATH = Path(__file__).resolve().with_name(".env")
_LOCAL_ENV_SIGNATURE = None
_TELEGRAM_BOT_PROFILE_CACHE = {"token": "", "profile": None}


def _sync_local_env() -> None:
    global _LOCAL_ENV_SIGNATURE

    try:
        env_stat = _LOCAL_ENV_PATH.stat()
    except OSError:
        return

    env_signature = (env_stat.st_mtime_ns, env_stat.st_size)
    if _LOCAL_ENV_SIGNATURE == env_signature:
        return

    try:
        raw_lines = _LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw_line in raw_lines:
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
        os.environ[key] = value

    _LOCAL_ENV_SIGNATURE = env_signature


def _default_phone_country_prefix() -> str:
    _sync_local_env()
    raw_value = os.getenv("DEFAULT_PHONE_COUNTRY_CODE", "+234").strip()
    digits_only = re.sub(r"\D", "", raw_value)
    return f"+{digits_only}" if digits_only else "+234"


def normalize_phone_number(phone: str) -> str:
    raw_value = str(phone or "").strip()
    if not raw_value:
        return ""

    if raw_value.lower().startswith("whatsapp:"):
        raw_value = raw_value.split(":", 1)[1].strip()

    cleaned_value = re.sub(r"[^\d+]", "", raw_value)
    if not cleaned_value:
        return ""

    if cleaned_value.startswith("00"):
        cleaned_value = f"+{cleaned_value[2:]}"

    if cleaned_value.startswith("+"):
        digits_only = re.sub(r"\D", "", cleaned_value)
        return f"+{digits_only}" if 8 <= len(digits_only) <= 15 else ""

    digits_only = re.sub(r"\D", "", cleaned_value)
    if not digits_only:
        return ""

    if digits_only.startswith("0"):
        country_prefix = _default_phone_country_prefix()
        local_number = digits_only.lstrip("0")
        return f"{country_prefix}{local_number}" if local_number else ""

    return f"+{digits_only}" if 8 <= len(digits_only) <= 15 else ""


def get_whatsapp_sender() -> str:
    _sync_local_env()
    sender = os.getenv("TWILIO_WHATSAPP_FROM", "").strip() or "whatsapp:+14155238886"
    return sender if sender.lower().startswith("whatsapp:") else f"whatsapp:{sender}"


def is_twilio_sandbox_sender() -> bool:
    return get_whatsapp_sender().replace(" ", "") == "whatsapp:+14155238886"


def _telegram_bot_token() -> str:
    _sync_local_env()
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _telegram_connect_secret() -> str:
    _sync_local_env()
    explicit_secret = os.getenv("FINWISE_TELEGRAM_CONNECT_SECRET", "").strip()
    if explicit_secret:
        return explicit_secret
    bot_token = _telegram_bot_token()
    if bot_token:
        return bot_token
    return str(_LOCAL_ENV_PATH)


def _telegram_api_request(
    method: str,
    params: dict | None = None,
    *,
    http_method: str = "POST",
    timeout: int = 8,
) -> tuple[bool, dict]:
    bot_token = _telegram_bot_token()
    if not bot_token:
        return False, {"description": "TELEGRAM_BOT_TOKEN is missing in .env."}

    request_params = {key: value for key, value in (params or {}).items() if value is not None}
    encoded_params = urllib.parse.urlencode(request_params)
    api_url = f"https://api.telegram.org/bot{bot_token}/{method}"
    request_headers = {"Accept": "application/json"}

    if http_method.upper() == "GET":
        if encoded_params:
            api_url = f"{api_url}?{encoded_params}"
        request = urllib.request.Request(api_url, headers=request_headers, method="GET")
    else:
        request = urllib.request.Request(
            api_url,
            data=encoded_params.encode(),
            headers={**request_headers, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

    opener = _build_telegram_opener()
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="ignore")
        payload = json.loads(body) if body else {}
        return bool(payload.get("ok")), payload
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="ignore")
        try:
            payload = json.loads(response_body) if response_body else {}
        except json.JSONDecodeError:
            payload = {}
        if not payload:
            payload = {"description": f"Telegram HTTP {error.code}"}
        return False, payload
    except Exception as error:
        return False, {"description": _format_notification_network_error(error)}


def get_telegram_bot_profile(*, force_refresh: bool = False) -> dict:
    bot_token = _telegram_bot_token()
    if not bot_token:
        return {}

    cached_token = str(_TELEGRAM_BOT_PROFILE_CACHE.get("token") or "")
    cached_profile = _TELEGRAM_BOT_PROFILE_CACHE.get("profile")
    if not force_refresh and cached_token == bot_token and isinstance(cached_profile, dict):
        return cached_profile

    ok, payload = _telegram_api_request("getMe", http_method="GET", timeout=6)
    if not ok:
        return {}

    profile = payload.get("result") or {}
    _TELEGRAM_BOT_PROFILE_CACHE["token"] = bot_token
    _TELEGRAM_BOT_PROFILE_CACHE["profile"] = profile
    return profile if isinstance(profile, dict) else {}


def get_telegram_bot_username() -> str:
    return str(get_telegram_bot_profile().get("username") or "").strip()


def build_telegram_connect_token(username: str) -> str:
    cleaned_username = str(username or "").strip().lower()
    if not cleaned_username:
        return ""
    digest = hmac.new(
        _telegram_connect_secret().encode("utf-8"),
        cleaned_username.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"fw_{digest[:24]}"


def build_telegram_connect_url(username: str) -> str:
    bot_username = get_telegram_bot_username()
    connect_token = build_telegram_connect_token(username)
    if not bot_username or not connect_token:
        return ""
    return f"https://t.me/{bot_username}?start={connect_token}"


def describe_telegram_destination(chat_id: str, *, chat_data: dict | None = None) -> str:
    chat_payload = chat_data or {}
    chat_type = str(chat_payload.get("type") or "").strip().lower()
    username = str(chat_payload.get("username") or "").strip()
    title = str(chat_payload.get("title") or "").strip()
    first_name = str(chat_payload.get("first_name") or "").strip()
    last_name = str(chat_payload.get("last_name") or "").strip()

    if chat_type == "private":
        full_name = " ".join(part for part in (first_name, last_name) if part).strip()
        if full_name:
            return full_name
        if username:
            return f"@{username}"
    if title:
        return title
    if username:
        return f"@{username}"

    cleaned_chat_id = str(chat_id or "").strip()
    if cleaned_chat_id.startswith("@"):
        return cleaned_chat_id
    digits_only = re.sub(r"\D", "", cleaned_chat_id)
    if digits_only:
        return f"chat ending {digits_only[-4:]}"
    return "Telegram chat"


def connect_telegram_chat(username: str) -> tuple[bool, dict | str]:
    bot_token = _telegram_bot_token()
    if not bot_token:
        return False, "Add TELEGRAM_BOT_TOKEN to .env before connecting Telegram."

    connect_token = build_telegram_connect_token(username)
    if not connect_token:
        return False, "Telegram could not build a connection token for this account yet."

    bot_username = get_telegram_bot_username()
    ok, payload = _telegram_api_request("getUpdates", {"limit": 100}, http_method="GET", timeout=8)
    if not ok:
        return False, payload.get("description") or "Telegram could not be reached right now."

    expected_commands = {f"/start {connect_token}"}
    if bot_username:
        expected_commands.add(f"/start@{bot_username} {connect_token}")

    for update in reversed(payload.get("result") or []):
        for update_key in ("message", "channel_post"):
            message = update.get(update_key) or {}
            text = str(message.get("text") or "").strip()
            if text not in expected_commands:
                continue
            chat = message.get("chat") or {}
            chat_id = str(chat.get("id") or "").strip()
            if not chat_id:
                continue
            return True, {
                "chat_id": chat_id,
                "chat": chat,
                "label": describe_telegram_destination(chat_id, chat_data=chat),
            }

    return (
        False,
        "Open the Finwise bot in Telegram, tap Start, then come back here and finish the connection.",
    )


def notification_gateway_status() -> dict:
    _sync_local_env()
    return {
        "twilio_ready": bool(os.getenv("TWILIO_SID", "").strip() and os.getenv("TWILIO_AUTH", "").strip()),
        "telegram_ready": bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip()),
    }


def _notification_proxy_environment() -> dict:
    _sync_local_env()
    proxy_keys = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ]
    return {key: os.getenv(key, "").strip() for key in proxy_keys if os.getenv(key, "").strip()}


def _is_dead_local_proxy(proxy_url: str) -> bool:
    if not proxy_url:
        return False
    parsed = urlparse(proxy_url)
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    return hostname in {"127.0.0.1", "localhost", "::1"} and port == 9


def should_bypass_notification_proxies() -> bool:
    _sync_local_env()
    explicit_setting = os.getenv("FINWISE_BYPASS_NOTIFICATION_PROXIES", "").strip().lower()
    if explicit_setting in {"1", "true", "yes", "on"}:
        return True
    proxy_values = _notification_proxy_environment().values()
    return any(_is_dead_local_proxy(value) for value in proxy_values)


def notification_proxy_warning() -> str:
    proxies = _notification_proxy_environment()
    if not proxies:
        return ""
    if should_bypass_notification_proxies():
        return "Broken proxy variables were detected in this runtime, so Finwise will bypass them for WhatsApp and Telegram delivery."
    return ""


def _build_telegram_opener():
    if should_bypass_notification_proxies():
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _format_notification_network_error(error: Exception) -> str:
    raw_message = str(error)
    lowered = raw_message.lower()
    if "nameresolutionerror" in lowered or "getaddrinfo failed" in lowered:
        if should_bypass_notification_proxies():
            return (
                "DNS lookup for Twilio failed in the current runtime. Finwise is bypassing "
                "the broken proxy variables it found, so this usually points to a temporary "
                "internet or DNS problem. Please try again in a few seconds."
            )
        return "DNS lookup for Twilio failed. Check your internet connection, DNS, VPN, or proxy settings and try again."
    if "connection refused" in lowered and should_bypass_notification_proxies():
        return "A broken local proxy is blocking the notification request. Clear HTTP_PROXY / HTTPS_PROXY or keep the Finwise proxy bypass enabled."
    return raw_message


def _format_twilio_error(error: Exception) -> str:
    raw_message = str(error)
    error_code = str(getattr(error, "code", "") or "").strip()

    if error_code == "63007" or "63007" in raw_message:
        sender = get_whatsapp_sender()
        if is_twilio_sandbox_sender():
            return (
                f"Twilio cannot find a WhatsApp channel for {sender}. "
                "Your app is still using the Twilio WhatsApp sandbox sender, so make sure the sandbox is enabled in "
                "this Twilio account and your phone has joined that sandbox. If you already have an approved WhatsApp "
                "sender, set TWILIO_WHATSAPP_FROM to that sender instead."
            )
        return (
            f"Twilio cannot find a WhatsApp channel for {sender}. "
            "Set TWILIO_WHATSAPP_FROM to a WhatsApp-enabled sender that belongs to this same Account SID, or switch "
            "to the Twilio account that owns that sender."
        )

    return _format_notification_network_error(error)


def _format_socket_error(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        return error.__class__.__name__
    lowered = message.lower()
    if "getaddrinfo failed" in lowered:
        return "DNS lookup failed."
    if "timed out" in lowered:
        return "Connection timed out."
    return message


def _format_proxy_display_value(proxy_url: str) -> str:
    if not proxy_url:
        return ""
    parsed = urlparse(proxy_url)
    if not parsed.scheme and not parsed.hostname:
        return proxy_url
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme or 'http'}://{host}{port}"


def _run_notification_host_diagnostic(host: str, port: int = 443, timeout: float = 3.0) -> dict:
    diagnostic = {
        "host": host,
        "port": port,
        "dns_ok": False,
        "dns_detail": "",
        "tcp_ok": False,
        "tcp_detail": "",
    }
    addresses = []
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        ips = []
        for address_info in addresses:
            socket_address = address_info[4]
            if socket_address:
                ip_address = socket_address[0]
                if ip_address not in ips:
                    ips.append(ip_address)
        diagnostic["dns_ok"] = True
        diagnostic["dns_detail"] = ", ".join(ips[:3]) if ips else "Resolved successfully."
    except Exception as error:
        diagnostic["dns_detail"] = _format_socket_error(error)
        return diagnostic

    target_socket = addresses[0][4] if addresses and len(addresses[0]) > 4 else (host, port)
    try:
        with socket.create_connection((target_socket[0], port), timeout=timeout):
            pass
        diagnostic["tcp_ok"] = True
        diagnostic["tcp_detail"] = f"Connected to {target_socket[0]}:{port}."
    except Exception as error:
        diagnostic["tcp_detail"] = _format_socket_error(error)
    return diagnostic


def build_notification_diagnostics(settings: dict) -> dict:
    proxy_environment = _notification_proxy_environment()
    proxy_keys = sorted(proxy_environment)
    proxy_lines = [
        f"{key}={_format_proxy_display_value(proxy_environment[key])}"
        for key in proxy_keys
    ]
    normalized_phone = normalize_phone_number(settings.get("phone", ""))
    readiness = notification_gateway_status()
    premium_active = bool(int(settings.get("premium", 0) or 0))
    whatsapp_enabled = bool(int(settings.get("notification_whatsapp", 0) or 0))
    telegram_enabled = bool(int(settings.get("notification_telegram", 0) or 0))

    if not proxy_environment:
        proxy_status = "ok"
        proxy_detail = "No proxy variables detected for notifications."
    elif should_bypass_notification_proxies():
        proxy_status = "warn"
        proxy_detail = "Broken proxy variables were found and Finwise will bypass them for notification sends."
    else:
        proxy_status = "ok"
        proxy_detail = "Proxy variables are present and Finwise will honor them."

    whatsapp_items = [
        {
            "label": "Plan access",
            "status": "ok" if premium_active else "warn",
            "detail": (
                "Premium is active for this account."
                if premium_active
                else "Premium is not active for this account, so live routing and test sends stay limited in the current build."
            ),
        },
        {
            "label": "Routing toggle",
            "status": "ok" if whatsapp_enabled else "warn",
            "detail": (
                "WhatsApp routing is enabled in your saved settings."
                if whatsapp_enabled
                else "WhatsApp routing is currently turned off in your saved settings."
            ),
        },
        {
            "label": "Saved number",
            "status": "ok" if normalized_phone else "warn",
            "detail": normalized_phone or "No valid WhatsApp number is saved yet.",
        },
        {
            "label": "Twilio credentials",
            "status": "ok" if readiness["twilio_ready"] else "fail",
            "detail": "TWILIO_SID and TWILIO_AUTH are loaded." if readiness["twilio_ready"] else "TWILIO_SID or TWILIO_AUTH is missing in .env.",
        },
        {
            "label": "Sender",
            "status": "warn" if is_twilio_sandbox_sender() else "ok",
            "detail": (
                f"{get_whatsapp_sender().replace('whatsapp:', '')} (sandbox join required)"
                if is_twilio_sandbox_sender()
                else get_whatsapp_sender().replace("whatsapp:", "")
            ),
        },
    ]

    telegram_items = [
        {
            "label": "Plan access",
            "status": "ok" if premium_active else "warn",
            "detail": (
                "Premium is active for this account."
                if premium_active
                else "Premium is not active for this account, so live routing and test sends stay limited in the current build."
            ),
        },
        {
            "label": "Routing toggle",
            "status": "ok" if telegram_enabled else "warn",
            "detail": (
                "Telegram routing is enabled in your saved settings."
                if telegram_enabled
                else "Telegram routing is currently turned off in your saved settings."
            ),
        },
        {
            "label": "Saved chat ID",
            "status": "ok" if str(settings.get("telegram_chat_id", "")).strip() else "warn",
            "detail": str(settings.get("telegram_chat_id", "")).strip() or "No Telegram chat ID is saved yet.",
        },
        {
            "label": "Bot token",
            "status": "ok" if readiness["telegram_ready"] else "fail",
            "detail": "TELEGRAM_BOT_TOKEN is loaded." if readiness["telegram_ready"] else "TELEGRAM_BOT_TOKEN is missing in .env.",
        },
    ]

    twilio_host = _run_notification_host_diagnostic("api.twilio.com")
    telegram_host = _run_notification_host_diagnostic("api.telegram.org")

    whatsapp_items.extend(
        [
            {
                "label": "Twilio DNS",
                "status": "ok" if twilio_host["dns_ok"] else "fail",
                "detail": twilio_host["dns_detail"],
            },
            {
                "label": "Twilio TCP",
                "status": "ok" if twilio_host["tcp_ok"] else "fail",
                "detail": twilio_host["tcp_detail"] if twilio_host["dns_ok"] else "Skipped because DNS failed.",
            },
        ]
    )

    telegram_items.extend(
        [
            {
                "label": "Telegram DNS",
                "status": "ok" if telegram_host["dns_ok"] else "fail",
                "detail": telegram_host["dns_detail"],
            },
            {
                "label": "Telegram TCP",
                "status": "ok" if telegram_host["tcp_ok"] else "fail",
                "detail": telegram_host["tcp_detail"] if telegram_host["dns_ok"] else "Skipped because DNS failed.",
            },
        ]
    )

    return {
        "ran_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "proxy": {
            "status": proxy_status,
            "detail": proxy_detail,
            "lines": proxy_lines,
        },
        "whatsapp": whatsapp_items,
        "telegram": telegram_items,
    }


def _render_notification_diagnostic_item(item: dict):
    palette = {
        "ok": ("OK", "#19dfd0", "rgba(25,223,208,0.12)", "rgba(25,223,208,0.18)"),
        "warn": ("WARN", "#f7c66b", "rgba(247,198,107,0.12)", "rgba(247,198,107,0.18)"),
        "fail": ("FAIL", "#ff7a8a", "rgba(255,122,138,0.12)", "rgba(255,122,138,0.18)"),
    }
    status_key = item.get("status", "warn")
    badge_text, accent, background, border = palette.get(status_key, palette["warn"])
    st.markdown(
        f"""
        <div style="
            border:1px solid {border};
            background:{background};
            border-radius:14px;
            padding:12px 14px;
            margin-bottom:10px;
        ">
            <div style="display:flex;justify-content:space-between;gap:10px;align-items:center;">
                <div style="color:white;font-size:14px;font-weight:700;">{escape(str(item.get("label", "")))}</div>
                <div style="color:{accent};font-size:11px;font-weight:800;letter-spacing:0.08em;">{badge_text}</div>
            </div>
            <div style="color:#8ab4c8;font-size:12px;line-height:1.55;margin-top:6px;">{escape(str(item.get("detail", "")))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_notification_diagnostics_panel(settings: dict, *, key_prefix: str):
    diagnostics_state_key = f"{key_prefix}_notification_diagnostics"
    with st.expander("Connection Diagnostics", expanded=False):
        st.caption("Run a quick network check from this exact app session before retrying a notification test.")
        if st.button("Run Diagnostics", key=f"{key_prefix}_run_notification_diagnostics", use_container_width=True):
            st.session_state[diagnostics_state_key] = build_notification_diagnostics(settings)

        diagnostics = st.session_state.get(diagnostics_state_key)
        if not diagnostics:
            st.info("No diagnostics run yet. Click the button above to check Twilio and Telegram connectivity.")
            return

        st.caption(f"Last run: {diagnostics['ran_at']}")
        proxy_info = diagnostics["proxy"]
        _render_notification_diagnostic_item(
            {
                "label": "Proxy handling",
                "status": proxy_info["status"],
                "detail": proxy_info["detail"],
            }
        )
        for proxy_line in proxy_info.get("lines", []):
            st.caption(proxy_line)

        left_col, right_col = st.columns(2, gap="large")
        with left_col:
            st.markdown("### WhatsApp Route")
            for item in diagnostics["whatsapp"]:
                _render_notification_diagnostic_item(item)
        with right_col:
            st.markdown("### Telegram Route")
            for item in diagnostics["telegram"]:
                _render_notification_diagnostic_item(item)


def send_whatsapp_message(message, phone):
    _sync_local_env()
    normalized_phone = normalize_phone_number(phone)
    if not normalized_phone:
        return False, "Use a valid WhatsApp number in international format, for example +2348012345678."

    try:
        twilio_sid = os.getenv("TWILIO_SID")
        twilio_auth = os.getenv("TWILIO_AUTH")
        if not twilio_sid or not twilio_auth:
            return False, "TWILIO_SID or TWILIO_AUTH is missing in .env."
        http_client = TwilioHttpClient()
        if http_client.session is not None and should_bypass_notification_proxies():
            http_client.session.trust_env = False
        client = Client(twilio_sid, twilio_auth, http_client=http_client)
        client.messages.create(
            body=message,
            from_=get_whatsapp_sender(),
            to=f"whatsapp:{normalized_phone}",
        )
        return True, ""
    except Exception as error:
        print(f"WhatsApp error: {error}")
        return False, _format_twilio_error(error)


def send_telegram_message(message, chat_id):
    _sync_local_env()
    cleaned_chat_id = str(chat_id or "").strip()
    if not cleaned_chat_id:
        return False, "Add a Telegram chat ID before sending a Telegram test."

    try:
        ok, payload = _telegram_api_request(
            "sendMessage",
            {
                "chat_id": cleaned_chat_id,
                "text": message,
            },
            timeout=10,
        )
        if ok:
            return True, ""
        return False, payload.get("description") or "Telegram rejected the message."
    except Exception as error:
        print(f"Telegram error: {error}")
        return False, _format_notification_network_error(error)
