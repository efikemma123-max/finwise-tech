"""Broker execution workspace and auto-trade routing UI."""

import logging
import time
from html import escape

import streamlit as st

from ai_worker import (
    _log_trade_history,
    _render_pair_picker,
    ai_signal_for_user,
    backtest_ai_worker_strategy,
    fetch_bybit_klines,
)
from backend.ai.broker_ai_copilot import render_copilot_drawer
from backend.ai.manual_trade_assistant import (
    build_manual_trade_guide,
    manual_profile_connected,
    render_manual_trade_guide,
)
from backend.auth.broker_oauth import (
    deactivate_broker_connection,
    resolve_broker_oauth_redirect_uri,
    save_broker_connection,
    save_broker_oauth_state,
)
from backend.market.candle_engine import is_forex_symbol
from backend.trading.trade_engine import BrokerFactory, TradingBot
from finwise_model.live_data import log_model_event


LOGGER = logging.getLogger("finwise.ai_worker_auto_trade")
BROKER_BALANCE_CACHE_TTL_SECONDS = 20.0


def _broker_oauth_redirect_uri(broker_name: str = "") -> str:
    try:
        actual_port = st.get_option("server.port") or 8501
    except Exception:
        actual_port = 8501
    return resolve_broker_oauth_redirect_uri(default_port=int(actual_port), broker_name=broker_name)


def _launch_broker_oauth(username: str, broker_name: str, state_key: str, metadata: dict = None):
    state = BrokerFactory.generate_oauth_state(broker_name)
    redirect_uri = _broker_oauth_redirect_uri(broker_name)
    auth_url = BrokerFactory.build_oauth_authorization_url(broker_name, redirect_uri, state)
    save_broker_oauth_state(
        username=username,
        broker_name=broker_name,
        state=state,
        redirect_uri=redirect_uri,
        metadata=metadata or {},
    )
    st.session_state[state_key] = auth_url
    st.session_state.pending_external_redirect = auth_url
    st.session_state.auto_trade_status = f"{broker_name.title()} authorization is ready. Continue to the broker approval screen."


def _sync_connected_broker_profile(username: str, broker):
    balance_value = 0.0
    try:
        cache = st.session_state.get("broker_balance_cache", {})
        session_scope = st.session_state.get("auth_session_id") or st.session_state.get("username") or "guest"
        cache_key = f"{session_scope}:{getattr(broker, 'name', 'broker')}:USDT"
        entry = cache.get(cache_key, {})
        last_sync = float(entry.get("synced_at", 0.0) or 0.0)
        now = time.time()
        if last_sync and (now - last_sync) < BROKER_BALANCE_CACHE_TTL_SECONDS:
            balance_value = float(entry.get("value", 0.0) or 0.0)
        else:
            balance_value = float(broker.get_balance("USDT"))
            cache[cache_key] = {"value": balance_value, "synced_at": now}
            st.session_state.broker_balance_cache = cache
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


def _render_connector_test_report(report: dict):
    if not report:
        return

    summary = str(report.get("summary", "") or "").strip()
    status = str(report.get("status", "") or "").strip().lower()
    if status == "ready" or report.get("passed") == report.get("total"):
        st.success(summary or "Connector test passed.")
    elif summary:
        st.warning(summary)

    top_cols = st.columns(4)
    top_cols[0].metric("Broker", report.get("broker", "--"))
    top_cols[1].metric("Checks Passed", f"{report.get('passed', 0)}/{report.get('total', 0)}")
    top_cols[2].metric("Test Symbol", report.get("symbol", "--"))
    top_cols[3].metric("Asset", report.get("asset", "--"))

    for item in report.get("checks", []):
        label = item.get("name", "Check")
        detail = item.get("detail", "")
        if item.get("ok"):
            st.markdown(f"**{label}:** {detail}")
        else:
            st.error(f"{label}: {detail}")


def _render_trade_preview_report(preview: dict):
    if not preview:
        return

    status = str(preview.get("status", "") or "").lower()
    reason = str(preview.get("reason", "") or "").strip()
    if status == "ready":
        st.success(reason or "Auto-trade route is ready.")
    elif status == "blocked":
        st.warning(reason or "Auto-trade route is blocked by the current risk gates.")
    else:
        st.error(reason or "Auto-trade route test failed.")

    metric_cols = st.columns(5)
    metric_cols[0].metric("Signal", preview.get("signal", "--"))
    metric_cols[1].metric("Balance", f"${float(preview.get('balance', 0) or 0):,.2f}")
    metric_cols[2].metric("Entry Price", f"${float(preview.get('entry_price', 0) or 0):,.4f}")
    metric_cols[3].metric("Trade Amount", f"${float(preview.get('trade_amount', 0) or 0):,.2f}")
    metric_cols[4].metric("Quantity", f"{float(preview.get('quantity', 0) or 0):.8f}")

    profit_guard = preview.get("profit_guard") or {}
    if profit_guard:
        guard_cols = st.columns(4)
        guard_cols[0].metric("Projected Profit", f"{float(profit_guard.get('projected_profit_percent', 0) or 0):.2f}%")
        guard_cols[1].metric("Confidence", f"{float(profit_guard.get('confidence_percent', 0) or 0):.0f}%")
        guard_cols[2].metric("Reward / Risk", f"{float(profit_guard.get('risk_reward_ratio', 0) or 0):.2f}")
        guard_cols[3].metric("Passed Checks", f"{int(profit_guard.get('quality_score', 0) or 0)}/{int(profit_guard.get('total_checks', 0) or 0)}")
        failed_checks = profit_guard.get("failed_checks", []) or []
        if failed_checks:
            st.markdown("**Blocked by:**")
            for item in failed_checks:
                st.markdown(f"- {item}")


def _render_adaptive_profile_summary(profile: dict, *, compact: bool = False):
    if not profile:
        return

    stats = profile.get("stats") or {}
    recent = profile.get("recent") or {}
    daily_guard = profile.get("daily_guard") or {}
    effective_thresholds = (profile.get("thresholds") or {}).get("effective", {})
    notes = [str(item).strip() for item in (profile.get("notes") or []) if str(item).strip()]
    if compact:
        with st.expander("Adaptive Coach", expanded=False):
            if not profile.get("ready"):
                st.caption("Adaptive tuning activates after at least 5 closed trades are recorded in your journal.")
            else:
                top_a, top_b = st.columns(2)
                top_a.metric("Win Rate", f"{float(stats.get('win_rate', 0) or 0):.1f}%")
                top_b.metric("Profit Factor", f"{float(stats.get('profit_factor', 0) or 0):.2f}")
                mid_a, mid_b = st.columns(2)
                mid_a.metric("Adaptive Size", f"{float(profile.get('size_multiplier', 1.0) or 1.0):.2f}x")
                mid_b.metric("Min Confidence", f"{int(profile.get('min_confidence', 55) or 55)}%")
                st.caption(str(profile.get("suggestion", "") or "").strip())
                if float(effective_thresholds.get("min_rr_ratio", 0) or 0) > 0:
                    st.caption(
                        f"Effective gate: {int(effective_thresholds.get('min_confidence', 55) or 55)}% confidence "
                        f"and {float(effective_thresholds.get('min_rr_ratio', 1.5) or 1.5):.2f}R."
                    )
                if recent.get("count"):
                    st.caption(
                        f"Recent closed trades: {recent.get('count', 0)} | "
                        f"Net P&L: {float(recent.get('net_pnl_pct', 0) or 0):.2f}%"
                    )
                if float(daily_guard.get("cap_usd", 0) or 0) > 0:
                    st.caption(
                        f"Daily guard: ${float(daily_guard.get('today_net_usd', 0) or 0):,.2f} "
                        f"/ -${float(daily_guard.get('cap_usd', 0) or 0):,.2f}"
                    )
                for note in notes[:3]:
                    st.markdown(f"- {note}")
    else:
        st.markdown("**Adaptive Coach**")
        if not profile.get("ready"):
            st.caption("Adaptive tuning activates after at least 5 closed trades are recorded in your journal.")
            return
        cols = st.columns(4)
        cols[0].metric("Win Rate", f"{float(stats.get('win_rate', 0) or 0):.1f}%")
        cols[1].metric("Profit Factor", f"{float(stats.get('profit_factor', 0) or 0):.2f}")
        cols[2].metric("Adaptive Size", f"{float(profile.get('size_multiplier', 1.0) or 1.0):.2f}x")
        cols[3].metric("Min Confidence", f"{int(profile.get('min_confidence', 55) or 55)}%")
        st.caption(str(profile.get("suggestion", "") or "").strip())
        if float(effective_thresholds.get("min_rr_ratio", 0) or 0) > 0:
            st.caption(
                f"Effective gate: {int(effective_thresholds.get('min_confidence', 55) or 55)}% confidence "
                f"and {float(effective_thresholds.get('min_rr_ratio', 1.5) or 1.5):.2f}R."
            )
        if float(daily_guard.get("cap_usd", 0) or 0) > 0:
            st.caption(
                f"Daily guard: today's closed-trade net is ${float(daily_guard.get('today_net_usd', 0) or 0):,.2f} "
                f"against a learned cap of -${float(daily_guard.get('cap_usd', 0) or 0):,.2f}."
            )
        for note in notes[:3]:
            st.markdown(f"- {note}")


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
                    st.session_state.auto_trade_status = f"{broker['display_name']} is already connected. Opening Broker & Execution."
                    st.session_state.trading_desk_view = "Broker & Execution"
                    st.session_state.open_broker_execution = True
                    st.session_state.nav_choice = "Trading Desk"
                st.rerun()
    if selected:
        chosen = next((item for item in catalog if item["broker_name"] == selected), None)
        if chosen:
            st.success(f"Selected broker: {chosen['display_name']}")
            if not chosen.get("connectable", True):
                st.info(f"{chosen['display_name']} is visible in the catalog, but live connection is not enabled yet in this build.")
    return selected


@st.dialog("Connect Broker", width="large")
def _render_live_broker_connect_dialog(username: str):
    broker_catalog = BrokerFactory.get_broker_catalog()
    broker_name = _render_broker_logo_picker("auto_trade_dialog", broker_catalog)
    if not broker_name:
        return

    broker_map = {item["broker_name"]: item for item in broker_catalog}
    broker_config = broker_map[broker_name]
    st.markdown(f"##### {escape(broker_config['display_name'])} Connection")
    st.caption(broker_config.get("description", "Choose your broker and continue with the secure connection flow."))
    if not broker_config.get("connectable", True):
        st.info(
            f"{broker_config['display_name']} is a real broker entry, but this connection still needs the remaining app-side setup before users can finish it here."
        )
        return
    oauth_request = BrokerFactory.get_oauth_connection_request(broker_name)

    st.caption("Choose how you want Finwise to connect to this broker.")

    if oauth_request.get("ready"):
        oauth_link_key = f"auto_trade_oauth_link_{broker_name}"
        if st.button("Connect with Broker", use_container_width=True, key="auto_trade_connect_oauth"):
            _launch_broker_oauth(
                username=username,
                broker_name=broker_name,
                state_key=oauth_link_key,
                metadata={"origin": "auto_trade"},
            )
            st.rerun()
        oauth_link = st.session_state.get(oauth_link_key)
        if oauth_link:
            st.link_button(
                f"Continue with {broker_config['display_name']}",
                oauth_link,
                use_container_width=True,
            )
        return
    elif oauth_request.get("message"):
        oauth_message = oauth_request["message"]
        if oauth_request.get("reason") == "oauth_not_configured":
            oauth_message += (
                f" This is app-side setup, so being logged into {broker_config['display_name']} on the web "
                "will not turn OAuth on by itself."
            )
        st.warning(f"OAuth unavailable: {oauth_message}")

    if broker_config["api_key_supported"]:
        st.caption("Secure instant connection is unavailable right now. Use your broker credentials to continue.")
        api_key = st.text_input("API Key", type="password", key="auto_trade_api_key")
        api_secret = st.text_input("API Secret", type="password", key="auto_trade_api_secret")
        if st.button("Connect with Broker", use_container_width=True, key="auto_trade_connect_broker"):
            if not api_key or not api_secret:
                st.error("Enter both API key and API secret to connect this broker.")
                return

            broker = BrokerFactory.connect_broker_with_api(broker_name, api_key, api_secret)
            if broker is None:
                last_error = BrokerFactory.get_last_connection_error() or "Check your credentials and try again."
                LOGGER.warning("Broker API connection failed: %s", last_error)
                st.session_state.auto_trade_status = "Could not connect the selected broker right now. Check your credentials and try again."
                st.error(st.session_state.auto_trade_status)
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
                metadata={"origin": "auto_trade_fallback"},
            )
            st.session_state.auto_trade_status = f"{broker.name} connected successfully."
            st.session_state.trading_desk_view = "Broker & Execution"
            st.session_state.open_broker_execution = True
            st.session_state.nav_choice = "Trading Desk"
            st.rerun()
        return

    st.info("This broker is not available for connection right now.")


def _legacy_auto_trade_page(username, is_premium_user=False):
    st.subheader("Broker & Execution")
    st.caption("Auto trade is optional. Connect a broker profile, get the AI signal, and place the trade yourself.")

    if "manual_broker_profile" not in st.session_state:
        st.session_state.manual_broker_profile = None
    if "manual_trade_signal" not in st.session_state:
        st.session_state.manual_trade_signal = None
    if "manual_trade_meta" not in st.session_state:
        st.session_state.manual_trade_meta = {}
    if "auto_trade_broker" not in st.session_state:
        st.session_state.auto_trade_broker = None
    if "auto_trade_bot" not in st.session_state:
        st.session_state.auto_trade_bot = None
    if "auto_trade_status" not in st.session_state:
        st.session_state.auto_trade_status = ""
    if "last_auto_trade_execution" not in st.session_state:
        st.session_state.last_auto_trade_execution = {}

    if st.session_state.auto_trade_status:
        st.info(st.session_state.auto_trade_status)

    if is_premium_user:
        st.caption("Premium account detected. You can still trade manually; live API auto-routing can be enabled later.")
    else:
        st.caption("Manual broker-assisted trading is available now. Automatic execution can stay optional.")

    manual_tab, api_tab = st.tabs(["Broker Profile", "Connect Broker"])

    with manual_tab:
        profile = st.session_state.manual_broker_profile

        if profile is None:
            st.markdown(
                """
                <div style="background:#0f2639;border:1px solid rgba(0,245,212,0.16);
                            border-radius:16px;padding:18px;margin-top:10px;">
                    <div style="color:white;font-size:18px;font-weight:700;">Connect Broker Profile</div>
                    <div style="color:#8ab4c8;font-size:13px;margin-top:6px;">
                        Save the broker you trade on so Finwise can build manual trade plans around your account size.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            broker_col, alias_col, balance_col = st.columns(3)
            with broker_col:
                broker_choice = st.selectbox("Broker", ["Binance", "Bybit", "OKX", "KuCoin", "MetaTrader", "Other"], key="manual_profile_broker")
            with alias_col:
                account_alias = st.text_input("Account Alias", value=username, key="manual_profile_alias")
            with balance_col:
                account_balance = st.number_input("Trading Balance (USD)", min_value=50.0, value=1000.0, step=50.0, key="manual_profile_balance")

            custom_broker = ""
            if broker_choice == "Other":
                custom_broker = st.text_input("Custom Broker Name", key="manual_profile_custom_broker").strip()

            if st.button("Save Broker Profile", use_container_width=True):
                broker_name = custom_broker or broker_choice
                if not broker_name:
                    st.error("Enter a broker name to continue.")
                    return

                st.session_state.manual_broker_profile = {
                    "broker_name": broker_name,
                    "account_alias": account_alias or username,
                    "balance": float(account_balance),
                }
                st.session_state.auto_trade_status = f"{broker_name} profile connected."
                st.rerun()
        else:
            st.success(f"Connected broker profile: {profile['broker_name']}")
            if manual_profile_connected(st.session_state):
                st.caption("Manual profile detected. Finwise Assistant will use this balance profile to guide your next trade.")
            st.markdown(
                f"""
                <div style="background:#0f2639;border:1px solid rgba(0,245,212,0.14);
                            border-radius:16px;padding:16px;margin-top:10px;">
                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;">
                        <div style="background:#0b1e2d;border-radius:12px;padding:10px;">
                            <div style="color:#4a7a94;font-size:10px;">Broker</div>
                            <div style="color:white;font-size:15px;font-weight:700;">{profile['broker_name']}</div>
                        </div>
                        <div style="background:#0b1e2d;border-radius:12px;padding:10px;">
                            <div style="color:#4a7a94;font-size:10px;">Account</div>
                            <div style="color:white;font-size:15px;font-weight:700;">{profile['account_alias']}</div>
                        </div>
                        <div style="background:#0b1e2d;border-radius:12px;padding:10px;">
                            <div style="color:#4a7a94;font-size:10px;">Balance Basis</div>
                            <div style="color:white;font-size:15px;font-weight:700;">${profile['balance']:,.2f}</div>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if st.button("Disconnect Broker Profile", use_container_width=True):
                st.session_state.manual_broker_profile = None
                st.session_state.manual_trade_signal = None
                st.session_state.manual_trade_meta = {}
                st.session_state.auto_trade_status = "Broker profile disconnected."
                st.rerun()

            st.markdown("---")
            st.markdown("**Manual Signal Workspace**")
            signal_symbol_col, signal_tf_col, signal_balance_col = st.columns(3)
            with signal_symbol_col:
                symbol = _render_pair_picker(
                    "Symbol",
                    "manual_signal_symbol",
                    default_symbol=st.session_state.get("manual_signal_symbol_select", "BTCUSDT"),
                )
            with signal_tf_col:
                tf_label = st.selectbox("Timeframe", ["1m", "5m", "15m", "1h"], key="manual_signal_tf")
            with signal_balance_col:
                balance = st.number_input("Balance For Sizing", min_value=50.0, value=float(profile["balance"]), step=50.0, key="manual_signal_balance")

            st.caption("Search any supported market and build the manual trade guide around your saved balance profile.")
            tf_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60"}
            if st.button("Get Signal For Manual Trade", use_container_width=True):
                df = fetch_bybit_klines(symbol=symbol, interval=tf_map[tf_label], limit=220)
                if df.empty or len(df) < 50:
                    st.error("Not enough market data to build the trade plan right now.")
                else:
                    result = ai_signal_for_user(
                        username,
                        df,
                        symbol=symbol,
                        current_balance=balance,
                        timeframe=tf_label,
                    )
                    st.session_state.manual_trade_signal = result
                    st.session_state.manual_trade_meta = {
                        "symbol": symbol,
                        "tf_label": tf_label,
                        "balance": float(balance),
                        "broker_name": profile["broker_name"],
                    }
                    st.rerun()

            result = st.session_state.manual_trade_signal
            meta = st.session_state.manual_trade_meta
            if result and meta:
                _render_adaptive_profile_summary(result.get("adaptive_profile") or {}, compact=False)
                guide = build_manual_trade_guide(
                    profile,
                    result,
                    {
                        "broker_name": meta.get("broker_name", profile["broker_name"]),
                        "symbol": meta.get("symbol", symbol),
                        "tf_label": meta.get("tf_label", tf_label),
                        "balance": meta.get("balance", float(balance)),
                    },
                )
                render_manual_trade_guide(guide)
                action_col1, action_col2 = st.columns(2)
                with action_col1:
                    if st.button(
                        "Record As Open Trade",
                        use_container_width=True,
                        key="record_manual_trade",
                        disabled=guide["signal"] not in {"BUY", "SELL"},
                    ):
                        _log_trade_history(
                            username=username,
                            broker_name=guide["broker_name"],
                            account_alias=profile.get("account_alias", username),
                            source="manual",
                            status="open",
                            symbol=guide["symbol"],
                            timeframe=guide["tf_label"],
                            side=guide["signal"],
                            confidence=guide["confidence"],
                            quantity=guide["quantity"],
                            notional_usd=guide["suggested_notional"],
                            entry_price=guide["entry_price"],
                            stop_loss=guide["stop_loss"],
                            take_profit=guide["take_profit"],
                            regime=guide["regime"],
                            setup_quality=guide["setup_quality"],
                            risk_reward_ratio=guide["risk_reward_ratio"],
                            notes="Recorded from manual execution guide",
                        )
                        st.success("Trade saved to Finwise journal as an open trade.")
                with action_col2:
                    st.caption("You can close the trade later from the Trade Journal page once the result is known.")

    with api_tab:
        broker_catalog = BrokerFactory.get_broker_catalog()
        connected_broker = st.session_state.auto_trade_broker
        connected_bot = st.session_state.auto_trade_bot

        if not broker_catalog:
            st.info("No live broker adapter is installed yet. Use the Broker Profile tab above to trade manually with Finwise signals.")
            return

        if not is_premium_user:
            st.warning("Live API broker routing is optional and can be enabled later. For now, use the Broker Profile tab to place trades yourself.")
            return

        if connected_broker is not None:
            perf = connected_bot.get_performance() if connected_bot is not None else {"message": "Broker connected"}
            st.success(f"Broker connected: {connected_broker.name}")
            connection_method = st.session_state.get("auto_trade_connection_method", "unknown")
            st.write(
                {
                    "broker": connected_broker.name,
                    "connection_method": connection_method,
                    "total_trades": perf.get("total_trades", 0),
                    "current_drawdown": perf.get("current_drawdown", 0),
                }
            )
            if connected_bot is not None:
                st.caption(
                    f"Always-execute mode is active. Every BUY/SELL signal will be routed, "
                    f"and Finwise will track a {connected_bot.config.target_profit_percent:.0f}% "
                    "profit objective for the trade."
                )
                st.caption(
                    "Important: the profit objective is a target, not a guaranteed realized market outcome."
                )

            api_result = st.session_state.get("manual_trade_signal")
            api_meta = st.session_state.get("manual_trade_meta", {})
            if api_result and api_meta:
                api_symbol = str(api_meta.get("symbol", "BTCUSDT") or "BTCUSDT").upper()
                forex_signal = is_forex_symbol(api_symbol)
                st.markdown("---")
                st.markdown("**Execute Latest Finwise Signal**")
                if forex_signal:
                    st.info("Forex signals are available for analysis and manual trading. Live API execution is currently limited to crypto exchange brokers.")
                else:
                    st.caption(f"{api_symbol} on {api_meta.get('tf_label', '1m')} is ready for broker-assisted execution.")
                if st.button("Execute Signal With Connected Broker", use_container_width=True, disabled=forex_signal):
                    execution = connected_bot.execute_trade_from_ai_worker(api_result, api_symbol)
                    st.session_state.last_auto_trade_execution = {
                        **execution,
                        "broker_key": connected_broker.name,
                    }
                    if execution.get("status") != "success":
                        st.error(execution.get("reason", "Execution failed"))
                        profit_guard = execution.get("profit_guard") or {}
                        if profit_guard:
                            metric_cols = st.columns(3)
                            metric_cols[0].metric("Projected Profit", f"{profit_guard.get('projected_profit_percent', 0):.2f}%")
                            metric_cols[1].metric("Target", f"{profit_guard.get('target_profit_percent', 0):.0f}%")
                            metric_cols[2].metric(
                                "Passed Checks",
                                f"{profit_guard.get('quality_score', 0)}/{profit_guard.get('total_checks', 0)}",
                            )
                            failed_checks = profit_guard.get("failed_checks", [])
                            if failed_checks:
                                st.markdown(
                                    "**Profit guard blocked execution:**\n"
                                    + "\n".join(f"- {item}" for item in failed_checks)
                                )
                    else:
                        trade = execution.get("trade", {})
                        _log_trade_history(
                            username=username,
                            broker_name=trade.get("broker", connected_broker.name),
                            account_alias=username,
                            source="live_api",
                            status="executed",
                            symbol=trade.get("symbol", api_meta.get("symbol", "BTCUSDT")),
                            timeframe=api_meta.get("tf_label", "1m"),
                            side=trade.get("signal", api_result.get("signal", "HOLD")),
                            confidence=trade.get("confidence", api_result.get("confidence", 0)),
                            quantity=trade.get("quantity", 0),
                            notional_usd=trade.get("notional_usd", 0),
                            entry_price=trade.get("entry_price", 0),
                            stop_loss=trade.get("stop_loss", 0),
                            take_profit=trade.get("take_profit", 0),
                            fee_paid=trade.get("fee_paid", 0),
                            regime=trade.get("regime", ""),
                            setup_quality=trade.get("setup_quality", ""),
                            risk_reward_ratio=trade.get("risk_reward_ratio", 0),
                            notes=f"Order ID: {trade.get('order_id', '')}",
                        )
                        st.success(execution.get("message", "Trade executed and logged."))
                        target_cols = st.columns(3)
                        target_cols[0].metric("Profit Objective", f"{trade.get('target_profit_percent', 0):.0f}%")
                        target_cols[1].metric("Target Price", f"${trade.get('target_profit_price', 0):,.4f}")
                        target_cols[2].metric("Projected Setup Profit", f"{trade.get('projected_profit_percent', 0):.2f}%")

            if st.button("Disconnect Broker", use_container_width=True):
                try:
                    connected_broker.disconnect()
                except Exception:
                    pass
                deactivate_broker_connection(username, connected_broker.name.lower())
                st.session_state.auto_trade_broker = None
                st.session_state.auto_trade_bot = None
                st.session_state.last_auto_trade_execution = {}
                st.session_state.trading_desk_view = "Signal Workspace"
                st.session_state.auto_trade_status = "Broker disconnected."
                st.rerun()
        else:
            st.markdown(
                """
                <div style="background:#0f2639;border:1px solid rgba(0,245,212,0.14);
                            border-radius:16px;padding:16px;margin-top:10px;">
                    <div style="color:white;font-size:18px;font-weight:700;">Secure Broker Connection</div>
                    <div style="color:#8ab4c8;font-size:13px;margin-top:6px;">
                        Choose a supported broker and continue with the secure connection flow.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Connect Broker", use_container_width=True, key="open_auto_trade_connect_dialog"):
                _render_live_broker_connect_dialog(username)


def auto_trade_page(username, is_premium_user=False):
    st.subheader("Broker & Execution")
    st.caption("Connect your broker once and Finwise will use the live account balance in your trading workspace.")

    if "manual_broker_profile" not in st.session_state:
        st.session_state.manual_broker_profile = None
    if "manual_trade_signal" not in st.session_state:
        st.session_state.manual_trade_signal = None
    if "manual_trade_meta" not in st.session_state:
        st.session_state.manual_trade_meta = {}
    if "manual_signal_backtest" not in st.session_state:
        st.session_state.manual_signal_backtest = None
    if "auto_trade_broker" not in st.session_state:
        st.session_state.auto_trade_broker = None
    if "auto_trade_bot" not in st.session_state:
        st.session_state.auto_trade_bot = None
    if "auto_trade_status" not in st.session_state:
        st.session_state.auto_trade_status = ""

    if st.session_state.auto_trade_status:
        st.info(st.session_state.auto_trade_status)

    broker_catalog = BrokerFactory.get_broker_catalog()
    connected_broker = st.session_state.auto_trade_broker
    connected_bot = st.session_state.auto_trade_bot

    if not broker_catalog:
        st.info("No supported broker is available right now.")
        return

    if not is_premium_user:
        st.warning("Broker execution becomes available with Premium.")
        return

    if connected_broker is None:
        st.markdown(
            """
            <div style="background:#0f2639;border:1px solid rgba(0,245,212,0.14);
                        border-radius:16px;padding:16px;margin-top:10px;">
                <div style="color:white;font-size:18px;font-weight:700;">Secure Broker Connection</div>
                <div style="color:#8ab4c8;font-size:13px;margin-top:6px;">
                    Connect your broker first. Once connected, Finwise will sync the balance to your dashboard automatically.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Connect Broker", use_container_width=True, key="open_auto_trade_connect_dialog_new"):
            _render_live_broker_connect_dialog(username)
        return

    profile = _sync_connected_broker_profile(username, connected_broker)
    perf = connected_bot.get_performance() if connected_bot is not None else {"message": "Broker connected"}
    connection_method = st.session_state.get("auto_trade_connection_method", "unknown")

    st.success(f"Broker connected: {connected_broker.name}")
    info_cols = st.columns(3)
    info_cols[0].metric("Connection", connection_method.replace("_", " ").title())
    info_cols[1].metric("Total Trades", perf.get("total_trades", 0))
    info_cols[2].metric("Drawdown", f"{perf.get('current_drawdown', 0):.2f}%")

    if connected_bot is not None:
        st.caption(
            f"Strict guard mode is active. Finwise is working toward a "
            f"{connected_bot.config.account_growth_goal_percent:.0f}% account-growth goal, "
            f"but each routed setup still needs at least "
            f"{connected_bot.config.min_confidence_percent:.0f}% confidence, "
            f"{connected_bot.config.min_risk_reward_ratio:.2f}R, and a projected "
            f"{connected_bot.config.min_projected_profit_percent:.2f}% edge."
        )

    signal_result = st.session_state.get("manual_trade_signal") or {}
    signal_meta = st.session_state.get("manual_trade_meta", {}) or {}
    backtest_report = st.session_state.get("manual_signal_backtest") or {}
    connector_report = st.session_state.get("broker_connector_test_report") or {}
    if connector_report.get("broker_key") != connected_broker.name:
        connector_report = {}
    preview_report = st.session_state.get("auto_trade_preview_report") or {}
    if preview_report.get("broker_key") != connected_broker.name:
        preview_report = {}
    last_execution = st.session_state.get("last_auto_trade_execution") or {}
    if last_execution.get("broker_key") != connected_broker.name:
        last_execution = {}

    copilot_context = {
        "broker_name": connected_broker.name,
        "connection_method": connection_method,
        "balance": profile.get("balance", 0.0),
        "total_trades": perf.get("total_trades", 0),
        "drawdown": perf.get("current_drawdown", 0),
        "status_text": st.session_state.get("auto_trade_status", ""),
        "signal": signal_result,
        "signal_meta": signal_meta,
        "backtest": backtest_report,
        "preview": preview_report,
        "connector": connector_report,
        "execution": last_execution,
        "bot_thresholds": {
            "min_confidence": getattr(connected_bot.config, "min_confidence_percent", 0) if connected_bot is not None else 0,
            "min_rr": getattr(connected_bot.config, "min_risk_reward_ratio", 0) if connected_bot is not None else 0,
            "min_edge": getattr(connected_bot.config, "min_projected_profit_percent", 0) if connected_bot is not None else 0,
            "growth_goal": getattr(connected_bot.config, "account_growth_goal_percent", 0) if connected_bot is not None else 0,
        },
    }

    render_copilot_drawer(
        username=username,
        context=copilot_context,
        scope="broker",
        state_key="broker_execution_copilot_open",
    )

    st.markdown("---")
    st.markdown("**Connector Test**")
    st.caption("Run a safe broker diagnostic first. This checks auth, balance access, live price access, and fee access without placing any order.")
    test_cols = st.columns([1.25, 0.9, 0.9])
    with test_cols[0]:
        connector_test_symbol = st.text_input(
            "Test Symbol",
            value=st.session_state.get("connector_test_symbol", "BTCUSDT"),
            key="connector_test_symbol",
        ).strip().upper() or "BTCUSDT"
    with test_cols[1]:
        connector_test_asset = st.selectbox(
            "Balance Asset",
            ["USDT", "USD", "USDC", "BTC"],
            index=0,
            key="connector_test_asset",
        )
    with test_cols[2]:
        st.write("")
        st.write("")
        if st.button("Run Connector Test", use_container_width=True, key="run_broker_connector_test"):
            report = BrokerFactory.run_connector_test(
                connected_broker,
                symbol=connector_test_symbol,
                asset=connector_test_asset,
            )
            report["broker_key"] = connected_broker.name
            st.session_state.broker_connector_test_report = report
            st.session_state.auto_trade_status = report.get("summary", "Connector test completed.")
            log_model_event(
                username=username,
                broker_name=connected_broker.name,
                event_type="connector_test",
                event_status=str(report.get("status") or ""),
                symbol=connector_test_symbol,
                payload=report,
            )
            st.rerun()

    connector_report = st.session_state.get("broker_connector_test_report") or {}
    if connector_report and connector_report.get("broker_key") == connected_broker.name:
        _render_connector_test_report(connector_report)

    st.markdown("---")
    st.markdown("**Signal Workspace**")
    signal_symbol_col, signal_tf_col, signal_balance_col = st.columns(3)
    with signal_symbol_col:
        symbol = _render_pair_picker(
            "Symbol",
            "manual_signal_symbol",
            default_symbol=st.session_state.get("manual_signal_symbol_select", "BTCUSDT"),
        )
    with signal_tf_col:
        tf_label = st.selectbox("Timeframe", ["1m", "5m", "15m", "1h"], key="manual_signal_tf")
    with signal_balance_col:
        balance = st.number_input(
            "Balance For Sizing",
            min_value=0.0,
            value=float(profile.get("balance", 0.0)),
            step=50.0,
            key="manual_signal_balance",
            disabled=True,
        )

    st.caption("Balance is synced from your connected broker and shown on the dashboard.")
    tf_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60"}
    if st.button("Get Signal For Manual Trade", use_container_width=True):
        df = fetch_bybit_klines(symbol=symbol, interval=tf_map[tf_label], limit=320)
        if df.empty or len(df) < 50:
            st.error("Not enough market data to build the trade plan right now.")
        else:
            result = ai_signal_for_user(
                username,
                df,
                symbol=symbol,
                current_balance=balance,
                timeframe=tf_label,
            )
            report = backtest_ai_worker_strategy(
                df,
                symbol=symbol,
                current_balance=balance,
                warmup_bars=120,
                lookahead_bars=12,
                username=username,
                timeframe=tf_label,
            )
            st.session_state.manual_trade_signal = result
            st.session_state.manual_signal_backtest = report
            st.session_state.manual_trade_meta = {
                "symbol": symbol,
                "tf_label": tf_label,
                "balance": float(balance),
                "broker_name": profile["broker_name"],
            }
            st.rerun()

    result = st.session_state.manual_trade_signal
    meta = st.session_state.manual_trade_meta
    backtest_report = st.session_state.get("manual_signal_backtest") or {}
    if result and meta:
        _render_adaptive_profile_summary(result.get("adaptive_profile") or {}, compact=False)
        guide = build_manual_trade_guide(
            profile,
            result,
            {
                "broker_name": meta.get("broker_name", profile["broker_name"]),
                "symbol": meta.get("symbol", symbol),
                "tf_label": meta.get("tf_label", tf_label),
                "balance": meta.get("balance", float(balance)),
            },
        )
        render_manual_trade_guide(guide)
        if backtest_report.get("ready"):
            rating = backtest_report.get("rating", {})
            st.markdown("**Strategy Snapshot**")
            snapshot_cols = st.columns(5)
            snapshot_cols[0].metric("Report Card", f"{rating.get('score', 0):.1f}/10")
            snapshot_cols[1].metric("Win Rate", f"{backtest_report.get('win_rate', 0):.1f}%")
            snapshot_cols[2].metric("Profit Factor", f"{backtest_report.get('profit_factor', 0):.2f}")
            snapshot_cols[3].metric("Max Drawdown", f"{backtest_report.get('max_drawdown_percent', 0):.2f}%")
            snapshot_cols[4].metric("Sim Trades", backtest_report.get("total_trades", 0))
            st.caption(
                f"{rating.get('label', 'Unknown')} snapshot from {backtest_report.get('sample_size_bars', 0)} bars "
                f"with a {backtest_report.get('lookahead_bars', 0)}-bar outcome window."
            )
        elif backtest_report:
            st.caption(backtest_report.get("reason", "Strategy snapshot unavailable."))

        action_col1, action_col2 = st.columns(2)
        with action_col1:
            if st.button(
                "Record As Open Trade",
                use_container_width=True,
                key="record_manual_trade_new",
                disabled=guide["signal"] not in {"BUY", "SELL"},
            ):
                _log_trade_history(
                    username=username,
                    broker_name=guide["broker_name"],
                    account_alias=profile.get("account_alias", username),
                    source="manual",
                    status="open",
                    symbol=guide["symbol"],
                    timeframe=guide["tf_label"],
                    side=guide["signal"],
                    confidence=guide["confidence"],
                    quantity=guide["quantity"],
                    notional_usd=guide["suggested_notional"],
                    entry_price=guide["entry_price"],
                    stop_loss=guide["stop_loss"],
                    take_profit=guide["take_profit"],
                    regime=guide["regime"],
                    setup_quality=guide["setup_quality"],
                    risk_reward_ratio=guide["risk_reward_ratio"],
                    notes="Recorded from manual execution guide",
                )
                st.success("Trade saved to Finwise journal as an open trade.")
        with action_col2:
            st.caption("You can close the trade later from the Trade Journal page once the result is known.")

    api_result = st.session_state.get("manual_trade_signal")
    api_meta = st.session_state.get("manual_trade_meta", {})
    if api_result and api_meta:
        api_symbol = str(api_meta.get("symbol", "BTCUSDT") or "BTCUSDT").upper()
        forex_signal = is_forex_symbol(api_symbol)
        st.markdown("---")
        st.markdown("**Execute Latest Finwise Signal**")
        if forex_signal:
            st.info("Forex signals are available for analysis and manual trading. Live API execution is currently limited to crypto exchange brokers.")
        else:
            st.caption(f"{api_symbol} on {api_meta.get('tf_label', '1m')} is ready for broker-assisted execution.")
        preview_col, execute_col = st.columns(2)
        with preview_col:
            if st.button("Test Auto Trade Route", use_container_width=True, disabled=forex_signal):
                preview = connected_bot.preview_trade_from_ai_worker(
                    api_result,
                    api_symbol,
                )
                preview["broker_key"] = connected_broker.name
                st.session_state.auto_trade_preview_report = preview
                log_model_event(
                    username=username,
                    broker_name=connected_broker.name,
                    event_type="route_preview",
                    event_status=str(preview.get("status") or ""),
                    symbol=api_symbol,
                    timeframe=str(api_meta.get("tf_label", "") or ""),
                    payload=preview,
                )
                st.rerun()

        preview_report = st.session_state.get("auto_trade_preview_report") or {}
        if preview_report and preview_report.get("broker_key") == connected_broker.name:
            _render_trade_preview_report(preview_report)

        with execute_col:
            if st.button("Execute Signal With Connected Broker", use_container_width=True, disabled=forex_signal):
                execution = connected_bot.execute_trade_from_ai_worker(api_result, api_symbol)
                st.session_state.last_auto_trade_execution = {
                    **execution,
                    "broker_key": connected_broker.name,
                }
                log_model_event(
                    username=username,
                    broker_name=connected_broker.name,
                    event_type="trade_execution",
                    event_status=str(execution.get("status") or ""),
                    symbol=api_symbol,
                    timeframe=str(api_meta.get("tf_label", "") or ""),
                    payload=st.session_state.last_auto_trade_execution,
                )
                if execution.get("status") != "success":
                    st.error(execution.get("reason", "Execution failed"))
                    profit_guard = execution.get("profit_guard") or {}
                    if profit_guard:
                        metric_cols = st.columns(4)
                        metric_cols[0].metric("Projected Profit", f"{profit_guard.get('projected_profit_percent', 0):.2f}%")
                        metric_cols[1].metric("Min Edge", f"{profit_guard.get('min_projected_profit_percent', 0):.2f}%")
                        metric_cols[2].metric("Growth Goal", f"{profit_guard.get('account_growth_goal_percent', 0):.0f}%")
                        metric_cols[3].metric(
                            "Passed Checks",
                            f"{profit_guard.get('quality_score', 0)}/{profit_guard.get('total_checks', 0)}",
                        )
                        failed_checks = profit_guard.get("failed_checks", [])
                        if failed_checks:
                            st.markdown(
                                "**Profit guard blocked execution:**\n"
                                + "\n".join(f"- {item}" for item in failed_checks)
                            )
                else:
                    trade = execution.get("trade", {})
                    _log_trade_history(
                        username=username,
                        broker_name=trade.get("broker", connected_broker.name),
                        account_alias=username,
                        source="live_api",
                        status="executed",
                        symbol=trade.get("symbol", api_meta.get("symbol", "BTCUSDT")),
                        timeframe=api_meta.get("tf_label", "1m"),
                        side=trade.get("signal", api_result.get("signal", "HOLD")),
                        confidence=trade.get("confidence", api_result.get("confidence", 0)),
                        quantity=trade.get("quantity", 0),
                        notional_usd=trade.get("notional_usd", 0),
                        entry_price=trade.get("entry_price", 0),
                        stop_loss=trade.get("stop_loss", 0),
                        take_profit=trade.get("take_profit", 0),
                        fee_paid=trade.get("fee_paid", 0),
                        regime=trade.get("regime", ""),
                        setup_quality=trade.get("setup_quality", ""),
                        risk_reward_ratio=trade.get("risk_reward_ratio", 0),
                        notes=f"Order ID: {trade.get('order_id', '')}",
                    )
                    st.success(execution.get("message", "Trade executed and logged."))
                    target_cols = st.columns(4)
                    target_cols[0].metric("Growth Goal", f"{trade.get('account_growth_goal_percent', 0):.0f}%")
                    target_cols[1].metric("Goal Balance", f"${trade.get('account_growth_goal_balance', 0):,.2f}")
                    target_cols[2].metric("Take Profit", f"${trade.get('target_profit_price', 0):,.4f}")
                    target_cols[3].metric("Projected Setup Profit", f"{trade.get('projected_profit_percent', 0):.2f}%")

    if st.button("Disconnect Broker", use_container_width=True, key="disconnect_broker_new"):
        try:
            connected_broker.disconnect()
        except Exception:
            pass
        deactivate_broker_connection(username, connected_broker.name.lower())
        _clear_connected_broker_profile()
        st.session_state.auto_trade_broker = None
        st.session_state.auto_trade_bot = None
        st.session_state.broker_connector_test_report = {}
        st.session_state.auto_trade_preview_report = {}
        st.session_state.last_auto_trade_execution = {}
        st.session_state.trading_desk_view = "Signal Workspace"
        st.session_state.auto_trade_status = "Broker disconnected."
        st.rerun()


__all__ = ["auto_trade_page"]
