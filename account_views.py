from html import escape
from textwrap import dedent

import streamlit as st
from mobile_ui_helpers import render_mobile_link_tabs, resolve_query_value

from backend.core.notification_service import (
    build_telegram_connect_url,
    connect_telegram_chat,
    describe_telegram_destination,
    is_twilio_sandbox_sender,
    normalize_phone_number,
    notification_gateway_status,
)


STATE_KEYS = {
    "view": "account_settings_view",
    "phone": "account_settings_phone_input",
    "telegram_chat_id": "account_settings_telegram_chat_id_input",
    "notification_whatsapp": "account_settings_whatsapp_enabled",
    "notification_telegram": "account_settings_telegram_enabled",
    "notify_buy_signals": "account_settings_notify_buy_signals",
    "notify_sell_signals": "account_settings_notify_sell_signals",
    "notify_signal_updates": "account_settings_notify_signal_updates",
    "notify_high_confidence_only": "account_settings_notify_high_confidence_only",
    "notify_market_digest": "account_settings_notify_market_digest",
    "security_authenticator_2fa": "account_settings_security_authenticator_2fa",
    "security_sms_verification": "account_settings_security_sms_verification",
    "security_login_alerts": "account_settings_security_login_alerts",
    "tab": "account_settings_tab",
    "password_change_code": "account_settings_password_change_code",
    "password_change_new_password": "account_settings_password_change_new_password",
    "password_change_confirm_password": "account_settings_password_change_confirm_password",
    "loaded_signature": "_account_settings_loaded_signature",
}


def _status_badge(label: str, ready: bool, status_text: str | None = None) -> str:
    badge_class = "ready" if ready else "warning"
    badge_text = status_text or ("Ready" if ready else "Needs Setup")
    return (
        f'<div class="channel-badge {badge_class}">'
        f'<div class="dot"></div>{escape(label)} | {badge_text}'
        f"</div>"
    )


def _whatsapp_setup_status(phone: str, *, twilio_ready: bool) -> tuple[str, bool]:
    normalized_phone = normalize_phone_number(phone)
    if not twilio_ready:
        return "Needs Setup", False
    if not normalized_phone:
        return "Add Number", False
    if is_twilio_sandbox_sender():
        return "Needs Setup", False
    return "Ready", True


def _telegram_setup_status(chat_id: str, *, telegram_ready: bool) -> tuple[str, bool]:
    cleaned_chat_id = str(chat_id or "").strip()
    if not telegram_ready:
        return "Needs Setup", False
    if not cleaned_chat_id:
        return "Connect Bot", False
    return "Ready", True


def _build_loaded_signature(username: str, settings: dict, preferences: dict) -> tuple:
    return (
        username,
        settings.get("email", ""),
        settings.get("phone", ""),
        int(settings.get("premium", 0) or 0),
        int(settings.get("notification_whatsapp", 0) or 0),
        int(settings.get("notification_telegram", 0) or 0),
        settings.get("telegram_chat_id", ""),
        int(preferences.get("notify_buy_signals", 1) or 0),
        int(preferences.get("notify_sell_signals", 1) or 0),
        int(preferences.get("notify_signal_updates", 0) or 0),
        int(preferences.get("notify_high_confidence_only", 0) or 0),
        int(preferences.get("notify_market_digest", 1) or 0),
        int(preferences.get("security_authenticator_2fa", 0) or 0),
        int(preferences.get("security_sms_verification", 1) or 0),
        int(preferences.get("security_login_alerts", 1) or 0),
    )


def _seed_settings_state(username: str, settings: dict, preferences: dict, *, force: bool = False) -> None:
    signature = _build_loaded_signature(username, settings, preferences)
    if force or st.session_state.get(STATE_KEYS["loaded_signature"]) != signature:
        st.session_state[STATE_KEYS["phone"]] = settings.get("phone", "") or ""
        st.session_state[STATE_KEYS["telegram_chat_id"]] = settings.get("telegram_chat_id", "") or ""
        st.session_state[STATE_KEYS["notification_whatsapp"]] = bool(settings.get("notification_whatsapp", 0))
        st.session_state[STATE_KEYS["notification_telegram"]] = bool(settings.get("notification_telegram", 0))
        st.session_state[STATE_KEYS["notify_buy_signals"]] = bool(preferences.get("notify_buy_signals", 1))
        st.session_state[STATE_KEYS["notify_sell_signals"]] = bool(preferences.get("notify_sell_signals", 1))
        st.session_state[STATE_KEYS["notify_signal_updates"]] = bool(preferences.get("notify_signal_updates", 0))
        st.session_state[STATE_KEYS["notify_high_confidence_only"]] = bool(preferences.get("notify_high_confidence_only", 0))
        st.session_state[STATE_KEYS["notify_market_digest"]] = bool(preferences.get("notify_market_digest", 1))
        st.session_state[STATE_KEYS["security_authenticator_2fa"]] = bool(preferences.get("security_authenticator_2fa", 0))
        st.session_state[STATE_KEYS["security_sms_verification"]] = bool(preferences.get("security_sms_verification", 1))
        st.session_state[STATE_KEYS["security_login_alerts"]] = bool(preferences.get("security_login_alerts", 1))
        st.session_state[STATE_KEYS["loaded_signature"]] = signature
    st.session_state.setdefault(STATE_KEYS["view"], "main")
    st.session_state.setdefault(STATE_KEYS["tab"], "Signal Routing")
    st.session_state.setdefault(STATE_KEYS["password_change_code"], "")
    st.session_state.setdefault(STATE_KEYS["password_change_new_password"], "")
    st.session_state.setdefault(STATE_KEYS["password_change_confirm_password"], "")


def _current_draft() -> dict:
    return {
        "phone": str(st.session_state.get(STATE_KEYS["phone"], "") or "").strip(),
        "telegram_chat_id": str(st.session_state.get(STATE_KEYS["telegram_chat_id"], "") or "").strip(),
        "notification_whatsapp": bool(st.session_state.get(STATE_KEYS["notification_whatsapp"], False)),
        "notification_telegram": bool(st.session_state.get(STATE_KEYS["notification_telegram"], False)),
        "notify_buy_signals": bool(st.session_state.get(STATE_KEYS["notify_buy_signals"], True)),
        "notify_sell_signals": bool(st.session_state.get(STATE_KEYS["notify_sell_signals"], True)),
        "notify_signal_updates": bool(st.session_state.get(STATE_KEYS["notify_signal_updates"], False)),
        "notify_high_confidence_only": bool(st.session_state.get(STATE_KEYS["notify_high_confidence_only"], False)),
        "notify_market_digest": bool(st.session_state.get(STATE_KEYS["notify_market_digest"], True)),
        "security_authenticator_2fa": bool(st.session_state.get(STATE_KEYS["security_authenticator_2fa"], False)),
        "security_sms_verification": bool(st.session_state.get(STATE_KEYS["security_sms_verification"], True)),
        "security_login_alerts": bool(st.session_state.get(STATE_KEYS["security_login_alerts"], True)),
    }


def _draft_channel_summary(draft: dict) -> tuple[str, str]:
    active_channels = []
    if draft["notification_whatsapp"] and normalize_phone_number(draft["phone"]):
        active_channels.append("WhatsApp")
    if draft["notification_telegram"] and draft["telegram_chat_id"]:
        active_channels.append("Telegram")
    if len(active_channels) == 2:
        routing_label = "Full"
    elif len(active_channels) == 1:
        routing_label = "Partial"
    else:
        routing_label = "Off"
    active_text = ", ".join(active_channels) if active_channels else "No active destinations"
    return routing_label, active_text


def _telegram_destination_preview(chat_id: str) -> str:
    cleaned_chat_id = str(chat_id or "").strip()
    if not cleaned_chat_id:
        return "No Telegram chat linked yet."
    return f"Connected to {describe_telegram_destination(cleaned_chat_id)}."


def _finish_telegram_connection(username: str, *, save_user_notification_settings) -> None:
    linked, result = connect_telegram_chat(username)
    if not linked:
        st.warning(str(result))
        return

    payload = result if isinstance(result, dict) else {}
    chat_id = str(payload.get("chat_id") or "").strip()
    if not chat_id:
        st.warning("Telegram replied, but no chat destination was returned yet. Please tap Start in the bot and try again.")
        return

    save_user_notification_settings(
        username=username,
        phone=str(st.session_state.get(STATE_KEYS["phone"], "") or "").strip(),
        telegram_chat_id=chat_id,
        whatsapp_enabled=bool(st.session_state.get(STATE_KEYS["notification_whatsapp"], False)),
        telegram_enabled=True,
    )
    st.session_state[STATE_KEYS["telegram_chat_id"]] = chat_id
    st.session_state[STATE_KEYS["notification_telegram"]] = True
    destination_label = describe_telegram_destination(
        chat_id,
        chat_data=payload.get("chat") if isinstance(payload.get("chat"), dict) else None,
    )
    st.session_state["account_settings_notice"] = (
        f"Telegram connected to {destination_label}. Fresh AI signals can land there now."
    )
    st.rerun()


def _mask_email(email: str) -> str:
    value = str(email or "").strip()
    if "@" not in value:
        return value or "--"
    local, domain = value.split("@", 1)
    if len(local) <= 2:
        masked_local = local[:1] + "*"
    else:
        masked_local = local[:2] + ("*" * max(1, len(local) - 2))
    return f"{masked_local}@{domain}"


def _reset_password_change_form_fields() -> None:
    st.session_state[STATE_KEYS["password_change_code"]] = ""
    st.session_state[STATE_KEYS["password_change_new_password"]] = ""
    st.session_state[STATE_KEYS["password_change_confirm_password"]] = ""


def _close_password_change_view(clear_password_change_state) -> None:
    clear_password_change_state()
    _reset_password_change_form_fields()
    st.session_state[STATE_KEYS["view"]] = "main"


def _render_styles() -> None:
    st.markdown(
        dedent(
            """
            <style>
            .settings-root {
                display: grid;
                gap: 1.4rem;
                padding-bottom: 1rem;
            }
            .settings-topbar {
                background: rgba(7, 13, 26, 0.95);
                border: 1px solid rgba(26, 45, 69, 0.95);
                border-radius: 16px;
                padding: 18px 22px;
                backdrop-filter: blur(20px);
            }
            .settings-topbar-title {
                font-size: 20px;
                font-weight: 800;
                color: #e8f4f8;
            }
            .settings-topbar-copy {
                color: #7a9bb5;
                font-size: 12px;
                margin-top: 4px;
            }
            .password-change-shell {
                display: grid;
                gap: 1rem;
            }
            .password-change-card {
                background: linear-gradient(180deg, rgba(17, 29, 48, 0.98), rgba(13, 22, 40, 0.98));
                border: 1px solid #1a2d45;
                border-radius: 18px;
                padding: 24px;
                position: relative;
                overflow: hidden;
                box-shadow: 0 0 28px rgba(0, 212, 170, 0.07);
            }
            .password-change-card::before {
                content: "";
                position: absolute;
                inset: 0 0 auto 0;
                height: 2px;
                background: linear-gradient(90deg, #00d4aa, #0088ff, #7c3aed);
            }
            .password-change-kicker {
                color: #00d4aa;
                font-size: 11px;
                letter-spacing: 1.3px;
                text-transform: uppercase;
                font-weight: 700;
            }
            .password-change-title {
                color: #e8f4f8;
                font-size: 24px;
                font-weight: 850;
                margin-top: 8px;
            }
            .password-change-copy {
                color: #7a9bb5;
                font-size: 13px;
                line-height: 1.65;
                margin-top: 8px;
                max-width: 42rem;
            }
            .password-change-step-grid {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 12px;
                margin-top: 18px;
            }
            .password-change-step {
                background: #0a1525;
                border: 1px solid #1a2d45;
                border-radius: 14px;
                padding: 14px;
            }
            .password-change-step-num {
                color: #00d4aa;
                font-size: 10px;
                letter-spacing: 1px;
                text-transform: uppercase;
                font-weight: 800;
            }
            .password-change-step-title {
                color: #e8f4f8;
                font-size: 14px;
                font-weight: 800;
                margin-top: 6px;
            }
            .password-change-step-copy {
                color: #7a9bb5;
                font-size: 12px;
                line-height: 1.55;
                margin-top: 6px;
            }
            .password-change-email {
                margin-top: 14px;
                color: #bde6f1;
                font-size: 13px;
                font-weight: 700;
            }
            .account-overview {
                background: linear-gradient(180deg, rgba(17, 29, 48, 0.98), rgba(13, 22, 40, 0.98));
                border: 1px solid #1a2d45;
                border-radius: 16px;
                padding: 26px;
                position: relative;
                overflow: hidden;
                box-shadow: 0 0 30px rgba(0, 212, 170, 0.08);
            }
            .account-overview::before {
                content: "";
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                height: 2px;
                background: linear-gradient(90deg, #00d4aa, #0088ff, #7c3aed);
            }
            .account-overview-header {
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: 16px;
                flex-wrap: wrap;
                margin-bottom: 22px;
            }
            .account-overview-title {
                font-size: 11px;
                letter-spacing: 1.5px;
                text-transform: uppercase;
                color: #00d4aa;
                font-weight: 700;
            }
            .account-overview-heading {
                font-size: 22px;
                font-weight: 800;
                color: #e8f4f8;
                margin-top: 6px;
            }
            .account-overview-desc {
                font-size: 13px;
                color: #7a9bb5;
                margin-top: 4px;
                max-width: 46rem;
                line-height: 1.6;
            }
            .premium-badge {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 7px 14px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: 700;
                border: 1px solid rgba(124, 58, 237, 0.32);
                background: linear-gradient(135deg, rgba(124, 58, 237, 0.16), rgba(124, 58, 237, 0.08));
                color: #b99cff;
            }
            .premium-badge.free {
                border-color: rgba(0, 212, 170, 0.22);
                background: linear-gradient(135deg, rgba(0, 212, 170, 0.14), rgba(0, 136, 255, 0.08));
                color: #7fe8da;
            }
            .account-stats {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 16px;
                margin-bottom: 18px;
            }
            .stat-item {
                background: #0a1525;
                border: 1px solid #1a2d45;
                border-radius: 12px;
                padding: 16px;
            }
            .stat-label {
                font-size: 10px;
                letter-spacing: 1px;
                text-transform: uppercase;
                color: #4a6580;
                margin-bottom: 6px;
                font-weight: 700;
            }
            .stat-value {
                font-size: 16px;
                font-weight: 800;
                color: #e8f4f8;
                overflow-wrap: anywhere;
            }
            .stat-value.accent {
                color: #00d4aa;
            }
            .channel-badges {
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
            }
            .channel-badge {
                display: inline-flex;
                align-items: center;
                gap: 7px;
                padding: 7px 14px;
                border-radius: 8px;
                font-size: 12px;
                font-weight: 700;
            }
            .channel-badge.ready {
                background: rgba(16, 185, 129, 0.12);
                border: 1px solid rgba(16, 185, 129, 0.3);
                color: #34d399;
            }
            .channel-badge.warning {
                background: rgba(245, 158, 11, 0.12);
                border: 1px solid rgba(245, 158, 11, 0.3);
                color: #fbbf24;
            }
            .channel-badge .dot {
                width: 6px;
                height: 6px;
                border-radius: 50%;
            }
            .channel-badge.ready .dot {
                background: #34d399;
                box-shadow: 0 0 6px #34d399;
            }
            .channel-badge.warning .dot {
                background: #fbbf24;
                box-shadow: 0 0 6px #fbbf24;
            }
            .settings-section-header {
                margin: 0.1rem 0 0.3rem;
            }
            .settings-section-header h2 {
                font-size: 18px;
                font-weight: 800;
                color: #e8f4f8;
                margin-bottom: 4px;
            }
            .settings-section-header p {
                font-size: 13px;
                color: #7a9bb5;
                line-height: 1.55;
            }
            .settings-section-header p a {
                color: #00d4aa;
                text-decoration: none;
            }
            .settings-tab-strip {
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
                margin-bottom: 0.35rem;
            }
            .settings-tab {
                padding: 9px 15px;
                border-radius: 12px;
                background: #111d30;
                border: 1px solid #1a2d45;
                color: #7a9bb5;
                font-size: 13px;
                font-weight: 700;
            }
            .settings-tab.active {
                background: linear-gradient(135deg, rgba(0, 212, 170, 0.18), rgba(0, 136, 255, 0.12));
                border-color: rgba(0, 212, 170, 0.2);
                color: #e8f4f8;
                box-shadow: 0 0 18px rgba(0, 212, 170, 0.08);
            }
            .settings-surface {
                background: linear-gradient(180deg, rgba(17, 29, 48, 0.98), rgba(13, 22, 40, 0.98));
                border: 1px solid #1a2d45;
                border-radius: 16px;
                padding: 22px;
                box-shadow: 0 0 30px rgba(0, 212, 170, 0.05);
            }
            .destination-head {
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: 12px;
                margin-bottom: 16px;
            }
            .destination-icon-wrap {
                display: flex;
                align-items: center;
                gap: 12px;
            }
            .destination-icon {
                width: 44px;
                height: 44px;
                border-radius: 12px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 20px;
            }
            .destination-icon.whatsapp {
                background: rgba(37, 211, 102, 0.12);
                border: 1px solid rgba(37, 211, 102, 0.25);
            }
            .destination-icon.telegram {
                background: rgba(0, 136, 255, 0.12);
                border: 1px solid rgba(0, 136, 255, 0.25);
            }
            .destination-name {
                font-size: 16px;
                font-weight: 800;
                color: #e8f4f8;
            }
            .destination-status {
                font-size: 12px;
                margin-top: 2px;
            }
            .destination-status.ready {
                color: #34d399;
            }
            .destination-status.warn {
                color: #fbbf24;
            }
            .destination-active {
                font-size: 12px;
                color: #7a9bb5;
                font-weight: 700;
            }
            .destination-story {
                margin: 0.1rem 0 0.75rem;
                color: #c7d9e7;
                font-size: 12px;
                line-height: 1.65;
            }
            .destination-steps {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 10px;
                margin: 0 0 14px;
            }
            .destination-step {
                background: rgba(8, 18, 30, 0.82);
                border: 1px solid rgba(26, 45, 69, 0.92);
                border-radius: 12px;
                padding: 12px;
            }
            .destination-step-label {
                color: #00d4aa;
                font-size: 10px;
                letter-spacing: 1px;
                text-transform: uppercase;
                font-weight: 800;
            }
            .destination-step-copy {
                margin-top: 5px;
                color: #9cb5c9;
                font-size: 11px;
                line-height: 1.55;
            }
            .destination-connect-meta {
                margin: 0 0 12px;
                padding: 11px 13px;
                border-radius: 12px;
                background: rgba(8, 18, 30, 0.75);
                border: 1px solid rgba(0, 136, 255, 0.18);
                color: #a9c2d8;
                font-size: 11px;
                line-height: 1.6;
            }
            .destination-connect-meta strong {
                color: #eef7ff;
            }
            .destination-connect-actions {
                margin-bottom: 12px;
            }
            .destination-connect-actions [data-testid="stHorizontalBlock"] {
                gap: 0.6rem !important;
            }
            .destination-manual-shell {
                margin: 0.35rem 0 0.8rem;
            }
            .inline-hint {
                font-size: 12px;
                margin: 6px 0 12px;
                color: #7a9bb5;
            }
            .inline-hint.success {
                color: #34d399;
            }
            .inline-hint.warning {
                color: #fbbf24;
            }
            .signal-toggle-copy {
                margin: 0.1rem 0 0.8rem;
                color: #e8f4f8;
                font-size: 13px;
                font-weight: 700;
            }
            .signal-toggle-sub {
                color: #7a9bb5;
                font-size: 11px;
                margin-top: 4px;
                line-height: 1.5;
            }
            .gateway-status {
                padding: 10px 14px;
                background: rgba(16, 185, 129, 0.06);
                border: 1px solid rgba(16, 185, 129, 0.15);
                border-radius: 9px;
                margin-top: 0.8rem;
                color: #7a9bb5;
                font-size: 12px;
                line-height: 1.55;
            }
            .gateway-status.error {
                background: rgba(239, 68, 68, 0.06);
                border-color: rgba(239, 68, 68, 0.15);
            }
            .gateway-status strong {
                color: #34d399;
            }
            .gateway-status.error strong {
                color: #ef4444;
            }
            .settings-list-card {
                background: linear-gradient(180deg, rgba(17, 29, 48, 0.98), rgba(13, 22, 40, 0.98));
                border: 1px solid #1a2d45;
                border-radius: 16px;
                overflow: hidden;
            }
            .settings-list-head {
                padding: 18px 24px;
                border-bottom: 1px solid #1a2d45;
            }
            .settings-divider {
                height: 1px;
                background: rgba(26, 45, 69, 0.92);
                margin: 12px 0;
            }
            .settings-list-title {
                font-size: 15px;
                font-weight: 800;
                color: #e8f4f8;
            }
            .settings-list-copy {
                font-size: 12px;
                color: #7a9bb5;
                margin-top: 2px;
            }
            .plan-card {
                background: linear-gradient(180deg, rgba(17, 29, 48, 0.98), rgba(13, 22, 40, 0.98));
                border: 1px solid #1a2d45;
                border-radius: 16px;
                padding: 24px;
                position: relative;
                overflow: hidden;
            }
            .plan-card::after {
                content: "";
                position: absolute;
                top: -50%;
                right: -10%;
                width: 280px;
                height: 280px;
                background: radial-gradient(circle, rgba(124, 58, 237, 0.08), transparent 70%);
                pointer-events: none;
            }
            .plan-card h3 {
                font-size: 11px;
                letter-spacing: 1.2px;
                text-transform: uppercase;
                color: #4a6580;
                font-weight: 700;
                margin-bottom: 6px;
            }
            .plan-card-row {
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: 20px;
                flex-wrap: wrap;
                position: relative;
                z-index: 1;
            }
            .plan-meta {
                color: #7a9bb5;
                font-size: 12px;
                text-align: right;
                min-width: 14rem;
            }
            .plan-name {
                font-size: 24px;
                font-weight: 900;
                background: linear-gradient(135deg, #a78bfa, #7c3aed);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            .plan-copy {
                color: #7a9bb5;
                font-size: 13px;
                margin-top: 10px;
                line-height: 1.6;
            }
            .plan-feature-row {
                display: flex;
                flex-wrap: wrap;
                gap: 14px;
                margin-top: 12px;
            }
            .plan-feature {
                font-size: 13px;
                color: #e8f4f8;
                font-weight: 700;
            }
            .danger-zone {
                background: rgba(239, 68, 68, 0.04);
                border: 1px solid rgba(239, 68, 68, 0.15);
                border-radius: 16px;
                padding: 24px;
            }
            .danger-title {
                font-size: 14px;
                font-weight: 800;
                color: #ef4444;
                margin-bottom: 16px;
            }
            .danger-copy {
                color: #7a9bb5;
                font-size: 12px;
                line-height: 1.55;
                margin-bottom: 10px;
            }
            div[data-testid="stTextInput"] input,
            div[data-testid="stTextArea"] textarea,
            div[data-testid="stNumberInput"] input {
                background: #0a1525;
                border: 1px solid #1a2d45;
                color: #e8f4f8;
                border-radius: 10px;
            }
            div[data-testid="stTextInput"] label p,
            div[data-testid="stCheckbox"] label p,
            div[data-testid="stRadio"] label p,
            div[data-testid="stToggle"] label p {
                color: #e8f4f8;
                font-weight: 600;
            }
            div[data-testid="stTextInput"] input::placeholder,
            div[data-testid="stTextArea"] textarea::placeholder {
                color: #4a6580;
            }
            div[data-testid="stRadio"] > div {
                background: #111d30;
                border: 1px solid #1a2d45;
                border-radius: 12px;
                padding: 4px;
            }
            div[data-testid="stRadio"] [role="radiogroup"] {
                display: flex;
                flex-direction: row;
                gap: 4px;
            }
            div[data-testid="stRadio"] [role="radiogroup"] label {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 9px;
                padding: 8px 14px;
            }
            div[data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) {
                background: #0a1525;
                border-color: #1a2d45;
            }
            @media (max-width: 900px) {
                .account-stats {
                    grid-template-columns: 1fr 1fr;
                }
                .password-change-step-grid {
                    grid-template-columns: 1fr;
                }
            }
            @media (max-width: 640px) {
                .account-overview,
                .settings-surface,
                .plan-card,
                .danger-zone,
                .settings-topbar {
                    padding: 18px;
                }
                .account-stats {
                    grid-template-columns: 1fr;
                }
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )


def _render_page_header() -> tuple[bool, bool]:
    title_col, reset_col, save_col = st.columns([1.2, 0.18, 0.22], gap="small")
    with title_col:
        st.markdown(
            """
            <div class="settings-topbar">
                <div class="settings-topbar-title">Settings</div>
                <div class="settings-topbar-copy">Manage your account, signals, and preferences.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with reset_col:
        reset_clicked = st.button("Reset", key="account_settings_reset", use_container_width=True)
    with save_col:
        save_clicked = st.button("Save Changes", key="account_settings_save", use_container_width=True, type="primary")
    return reset_clicked, save_clicked


def _render_password_change_page(
    username: str,
    *,
    email: str,
    verify_otp,
    update_user_password,
    clear_login_failures,
    password_meets_policy,
    send_email_otp,
    clear_password_change_state,
) -> None:
    masked_email = _mask_email(email)
    sent = bool(st.session_state.get("password_change_sent", False))
    verified = bool(st.session_state.get("password_change_verified", False))

    back_col, title_col = st.columns([0.18, 0.82], gap="small")
    with back_col:
        if st.button("Back", key="account_settings_password_change_back", use_container_width=True):
            _close_password_change_view(clear_password_change_state)
            st.rerun()
    with title_col:
        st.markdown(
            """
            <div class="settings-topbar">
                <div class="settings-topbar-title">Password Security</div>
                <div class="settings-topbar-copy">Verify your registered email before choosing a new password.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if not email:
        st.warning("This account does not have a registered email address yet, so password verification cannot start from Settings.")
        return

    st.markdown(
        f"""
        <div class="password-change-shell">
            <div class="password-change-card">
                <div class="password-change-kicker">Verified Change</div>
                <div class="password-change-title">Change your password securely</div>
                <div class="password-change-copy">
                    Finwise will only open the new-password form after your verification code is confirmed.
                    The code is sent to your registered email on file.
                </div>
                <div class="password-change-email">Registered email: {escape(masked_email)}</div>
                <div class="password-change-step-grid">
                    <div class="password-change-step">
                        <div class="password-change-step-num">Step 1</div>
                        <div class="password-change-step-title">Send code</div>
                        <div class="password-change-step-copy">We send a 6-digit verification code to your saved email address.</div>
                    </div>
                    <div class="password-change-step">
                        <div class="password-change-step-num">Step 2</div>
                        <div class="password-change-step-title">Verify email</div>
                        <div class="password-change-step-copy">Enter the code to prove you still control the registered email.</div>
                    </div>
                    <div class="password-change-step">
                        <div class="password-change-step-num">Step 3</div>
                        <div class="password-change-step-title">Set password</div>
                        <div class="password-change-step-copy">Choose and confirm your new password after verification succeeds.</div>
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.session_state.setdefault("password_change_request", {"username": username, "email": email})

    if not sent:
        action_col1, action_col2 = st.columns([0.34, 0.18], gap="small")
        with action_col1:
            if st.button("Send Verification Code", key="account_settings_send_password_change_code", use_container_width=True, type="primary"):
                st.session_state.password_change_request = {"username": username, "email": email}
                st.session_state.pending_username = username
                st.session_state.pending_email = email
                st.session_state.auth_otp_context = "password_change"
                if send_email_otp(email, username, purpose="password_change"):
                    st.session_state.password_change_sent = True
                    st.session_state.password_change_verified = False
                    st.rerun()
        with action_col2:
            if st.button("Cancel", key="account_settings_cancel_password_change_send", use_container_width=True):
                _close_password_change_view(clear_password_change_state)
                st.rerun()
        return

    if not verified:
        st.info(f"Verification code sent to {email}. Enter it below to unlock the new-password form.")
        code_col, verify_col, resend_col = st.columns([0.56, 0.22, 0.22], gap="small")
        with code_col:
            st.text_input("Verification Code", key=STATE_KEYS["password_change_code"], placeholder="Enter the 6-digit code")
        with verify_col:
            verify_clicked = st.button("Verify Code", key="account_settings_verify_password_change_code", use_container_width=True, type="primary")
        with resend_col:
            resend_clicked = st.button("Resend Code", key="account_settings_resend_password_change_code", use_container_width=True)

        if verify_clicked:
            code = str(st.session_state.get(STATE_KEYS["password_change_code"], "") or "").strip()
            if not code:
                st.error("Enter the verification code from your email.")
            elif verify_otp(username, code):
                st.session_state.password_change_verified = True
                st.session_state[STATE_KEYS["password_change_code"]] = ""
                st.success("Email verified. You can now set your new password.")
                st.rerun()
            else:
                st.error("Invalid or expired verification code. Please try again.")

        if resend_clicked:
            st.session_state.password_change_request = {"username": username, "email": email}
            st.session_state.pending_username = username
            st.session_state.pending_email = email
            st.session_state.auth_otp_context = "password_change"
            if send_email_otp(email, username, purpose="password_change"):
                st.success(f"A fresh verification code was sent to {email}.")
                st.rerun()

        if st.button("Start Over", key="account_settings_restart_password_change", use_container_width=True):
            clear_password_change_state()
            st.session_state.password_change_request = {"username": username, "email": email}
            _reset_password_change_form_fields()
            st.rerun()
        return

    st.success("Verification complete. Set your new password below.")
    with st.form("account_settings_password_change_form"):
        st.text_input("New Password", type="password", key=STATE_KEYS["password_change_new_password"])
        st.text_input("Confirm Password", type="password", key=STATE_KEYS["password_change_confirm_password"])
        submit_password_change = st.form_submit_button("Update Password", use_container_width=True, type="primary")

    if submit_password_change:
        new_password = str(st.session_state.get(STATE_KEYS["password_change_new_password"], "") or "").strip()
        confirm_password = str(st.session_state.get(STATE_KEYS["password_change_confirm_password"], "") or "").strip()
        if not new_password or not confirm_password:
            st.error("Enter and confirm your new password.")
        elif new_password != confirm_password:
            st.error("New password and confirmation do not match.")
        else:
            password_ok, password_error = password_meets_policy(new_password)
            if not password_ok:
                st.error(password_error)
            else:
                update_user_password(username, new_password)
                clear_login_failures(username)
                _close_password_change_view(clear_password_change_state)
                st.session_state["account_settings_notice"] = "Password updated successfully."
                st.rerun()

    st.caption("Passwords must be at least 8 characters long and include both letters and numbers.")


def _render_account_overview(username: str, settings: dict, draft: dict, twilio_ready: bool, telegram_ready: bool) -> None:
    premium = bool(settings.get("premium", 0))
    routing_label, active_channel_text = _draft_channel_summary(draft)
    email_text = settings.get("email", "") or "Not configured"
    premium_badge_class = "" if premium else " free"
    premium_badge_text = "Premium Active" if premium else "Free Plan"
    whatsapp_badge_text, whatsapp_badge_ready = _whatsapp_setup_status(draft.get("phone", ""), twilio_ready=twilio_ready)
    telegram_badge_text, telegram_badge_ready = _telegram_setup_status(draft.get("telegram_chat_id", ""), telegram_ready=telegram_ready)
    st.markdown(
        f"""
        <div class="account-overview">
            <div class="account-overview-header">
                <div>
                    <div class="account-overview-title">Account Control</div>
                    <div class="account-overview-heading">Settings & Signal Routing</div>
                    <div class="account-overview-desc">Shape a sharper alert cockpit here so every fresh Finwise read reaches the channels you actually watch.</div>
                </div>
                <div class="premium-badge{premium_badge_class}">{escape(premium_badge_text)}</div>
            </div>
            <div class="account-stats">
                <div class="stat-item">
                    <div class="stat-label">Username</div>
                    <div class="stat-value">{escape(username)}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Email</div>
                    <div class="stat-value">{escape(email_text)}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Signal Routing</div>
                    <div class="stat-value accent">{escape(routing_label)}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Active Destinations</div>
                    <div class="stat-value">{escape(active_channel_text)}</div>
                </div>
            </div>
            <div class="channel-badges">
                {_status_badge("WhatsApp", whatsapp_badge_ready, whatsapp_badge_text)}
                {_status_badge("Telegram", telegram_badge_ready, telegram_badge_text)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _save_settings_draft(
    username: str,
    *,
    save_user_notification_settings,
    save_user_account_preferences,
    twilio_ready: bool,
    telegram_ready: bool,
) -> None:
    draft = _current_draft()
    raw_phone = draft["phone"]
    phone_value = normalize_phone_number(raw_phone)
    telegram_value = draft["telegram_chat_id"]

    if raw_phone and not phone_value:
        st.error("Enter a valid WhatsApp number. Use +2348012345678 or a local number like 08012345678.")
        return
    if draft["notification_whatsapp"] and not phone_value:
        st.error("Add a valid WhatsApp number before turning on WhatsApp routing.")
        return
    if draft["notification_telegram"] and not telegram_value:
        st.error("Connect Telegram before turning on Telegram routing.")
        return

    save_user_notification_settings(
        username=username,
        phone=phone_value or "",
        telegram_chat_id=telegram_value,
        whatsapp_enabled=draft["notification_whatsapp"],
        telegram_enabled=draft["notification_telegram"],
    )
    save_user_account_preferences(
        username,
        notify_buy_signals=draft["notify_buy_signals"],
        notify_sell_signals=draft["notify_sell_signals"],
        notify_signal_updates=draft["notify_signal_updates"],
        notify_high_confidence_only=draft["notify_high_confidence_only"],
        notify_market_digest=draft["notify_market_digest"],
        security_authenticator_2fa=draft["security_authenticator_2fa"],
        security_sms_verification=draft["security_sms_verification"],
        security_login_alerts=draft["security_login_alerts"],
    )

    st.session_state[STATE_KEYS["phone"]] = phone_value or ""
    saved_channels = []
    if draft["notification_whatsapp"]:
        saved_channels.append("WhatsApp")
    if draft["notification_telegram"]:
        saved_channels.append("Telegram")
    if saved_channels:
        st.success(f"Settings saved. New AI signals will route through {', '.join(saved_channels)} when those channels are available.")
    else:
        st.success("Settings saved. Signal delivery is currently turned off.")

    if raw_phone and phone_value and raw_phone != phone_value:
        st.info(f"Saved your WhatsApp number as {phone_value}.")
    if draft["notification_whatsapp"] and not twilio_ready:
        st.warning("WhatsApp alerts are turned on, but this channel still needs setup before messages can be delivered.")
    elif draft["notification_whatsapp"] and phone_value and is_twilio_sandbox_sender():
        st.warning("WhatsApp alerts are turned on, but this number still needs to be linked before delivery can start.")
    if draft["notification_telegram"] and not telegram_ready:
        st.warning("Telegram alerts are turned on, but this channel still needs setup before messages can be delivered.")


def _render_section_heading(title: str, copy: str) -> None:
    st.markdown(
        f"""
        <div class="settings-section-header">
            <h2>{escape(title)}</h2>
            <p>{copy}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_tabs_strip() -> None:
    st.markdown(
        """
        <div class="settings-tab-strip">
            <div class="settings-tab active">Signal Routing</div>
            <div class="settings-tab">Notifications</div>
            <div class="settings-tab">Security</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_signal_routing_tab(
    username: str,
    *,
    settings: dict,
    premium: bool,
    twilio_ready: bool,
    telegram_ready: bool,
    save_user_notification_settings,
    render_toggle_input,
) -> None:
    _render_section_heading(
        "Signal Destinations",
        "Build a delivery setup that feels instant, clear, and ready when the market starts moving.",
    )

    draft = _current_draft()
    normalized_phone_preview = normalize_phone_number(draft["phone"])
    whatsapp_status, whatsapp_ready = _whatsapp_setup_status(draft["phone"], twilio_ready=twilio_ready)
    telegram_status, telegram_connected = _telegram_setup_status(draft["telegram_chat_id"], telegram_ready=telegram_ready)

    whatsapp_col, telegram_col = st.columns(2, gap="large")

    with whatsapp_col:
        st.markdown(
            f"""
            <div class="settings-surface">
                <div class="destination-head">
                    <div class="destination-icon-wrap">
                        <div class="destination-icon whatsapp">💬</div>
                        <div>
                            <div class="destination-name">WhatsApp</div>
                            <div class="destination-status {'ready' if whatsapp_ready else 'warn'}">{escape(whatsapp_status)}</div>
                        </div>
                    </div>
                    <div class="destination-active">{'Active' if draft['notification_whatsapp'] else 'Inactive'}</div>
                </div>
            """,
            unsafe_allow_html=True,
        )
        st.text_input(
            "WhatsApp Number",
            key=STATE_KEYS["phone"],
            placeholder="+2348012345678",
        )
        if draft["phone"]:
            if normalized_phone_preview:
                st.markdown(
                    f'<div class="inline-hint success">Will send to: {escape(normalized_phone_preview)}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div class="inline-hint warning">Use an international number like +2348012345678 or a local number that starts with 0.</div>',
                    unsafe_allow_html=True,
                )
        st.markdown(
            """
            <div class="signal-toggle-copy">Let Finwise ping your phone the moment a setup is ready</div>
            <div class="signal-toggle-sub">Great for fast reads, quick entry zones, and confidence snapshots you want in your pocket.</div>
            """,
            unsafe_allow_html=True,
        )
        render_toggle_input(
            "Enable WhatsApp signal routing",
            value=draft["notification_whatsapp"],
            key=STATE_KEYS["notification_whatsapp"],
            help="Uses your saved phone number for WhatsApp alerts.",
        )
        if not premium:
            st.caption("Premium is required before live signal routing becomes active.")
        st.markdown("</div>", unsafe_allow_html=True)

    with telegram_col:
        connect_url = build_telegram_connect_url(username) if telegram_ready else ""
        bot_username = ""
        if connect_url.startswith("https://t.me/"):
            bot_username = connect_url.split("https://t.me/", 1)[1].split("?", 1)[0]
        st.markdown(
            f"""
            <div class="settings-surface">
                <div class="destination-head">
                    <div class="destination-icon-wrap">
                        <div class="destination-icon telegram">✈️</div>
                        <div>
                            <div class="destination-name">Telegram</div>
                            <div class="destination-status {'ready' if telegram_connected else 'warn'}">{escape(telegram_status)}</div>
                        </div>
                    </div>
                    <div class="destination-active">{'Active' if draft['notification_telegram'] else 'Inactive'}</div>
                </div>
                <div class="destination-story">Telegram works best as a quick signal cockpit. Open the Finwise bot, tap start, then let us lock the route in for you.</div>
                <div class="destination-steps">
                    <div class="destination-step">
                        <div class="destination-step-label">Step 1</div>
                        <div class="destination-step-copy">Jump into the bot and tap <strong>Start</strong> once.</div>
                    </div>
                    <div class="destination-step">
                        <div class="destination-step-label">Step 2</div>
                        <div class="destination-step-copy">Come back here and finish the connection. No chat ID digging.</div>
                    </div>
                </div>
            """,
            unsafe_allow_html=True,
        )
        bot_line = f"Bot: @{bot_username}" if bot_username else "Bot link will appear as soon as Telegram is reachable."
        st.markdown(
            f'<div class="destination-connect-meta"><strong>{escape(_telegram_destination_preview(draft["telegram_chat_id"]))}</strong><br>{escape(bot_line)}</div>',
            unsafe_allow_html=True,
        )
        with st.container(key=f"telegram_connect_actions_{username}"):
            open_col, finish_col = st.columns(2, gap="small")
            with open_col:
                if connect_url:
                    st.link_button(
                        "Open Telegram Bot",
                        connect_url,
                        use_container_width=True,
                    )
                else:
                    st.button(
                        "Open Telegram Bot",
                        use_container_width=True,
                        disabled=True,
                        key=f"telegram_open_unavailable_{username}",
                    )
            with finish_col:
                if st.button(
                    "Finish Connect",
                    key=f"telegram_finish_connect_{username}",
                    use_container_width=True,
                    type="primary",
                ):
                    _finish_telegram_connection(
                        username,
                        save_user_notification_settings=save_user_notification_settings,
                    )
        with st.expander("Advanced: use a chat ID instead"):
            st.markdown('<div class="destination-manual-shell">', unsafe_allow_html=True)
            st.text_input(
                "Telegram Chat ID",
                key=STATE_KEYS["telegram_chat_id"],
                placeholder="123456789 or @yourchannel",
            )
            st.markdown(
                '<div class="inline-hint">Only use this if you already know the destination or you are routing into a channel.</div>',
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown(
            """
            <div class="signal-toggle-copy">Keep Telegram ready for every new AI signal</div>
            <div class="signal-toggle-sub">Once connected, Finwise can drop new signal reads and follow-up updates straight into this chat.</div>
            """,
            unsafe_allow_html=True,
        )
        render_toggle_input(
            "Enable Telegram signal routing",
            value=draft["notification_telegram"],
            key=STATE_KEYS["notification_telegram"],
            help="Routes premium signal alerts through your Telegram connection.",
        )
        if not premium:
            st.caption("Premium is required before live signal routing becomes active.")
        st.markdown("</div>", unsafe_allow_html=True)


def _render_notifications_tab(render_toggle_input) -> None:
    _render_section_heading(
        "Notification Preferences",
        "Customize which events trigger signal notifications.",
    )
    st.markdown('<div class="settings-surface">', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="settings-list-head" style="padding:0 0 16px;border-bottom:1px solid #1a2d45;">
            <div class="settings-list-title">Signal Alerts</div>
            <div class="settings-list-copy">Configure what types of signals should reach your active destinations.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    rows = [
        ("New Buy Signals", "Get notified when AI generates a new buy opportunity.", STATE_KEYS["notify_buy_signals"], True),
        ("New Sell Signals", "Get notified when AI generates a new sell opportunity.", STATE_KEYS["notify_sell_signals"], True),
        ("Signal Updates", "Get notified when a refreshed Trade Desk signal updates the same market setup.", STATE_KEYS["notify_signal_updates"], False),
        ("High Confidence Only", "Only receive signals with 80%+ confidence score.", STATE_KEYS["notify_high_confidence_only"], False),
        ("Market Digest (Daily)", "Receive a daily market summary when this alert is available.", STATE_KEYS["notify_market_digest"], True),
    ]

    for index, (title, copy, key_name, default_value) in enumerate(rows):
        if index > 0:
            st.markdown('<div class="settings-divider"></div>', unsafe_allow_html=True)
        row_col, toggle_col = st.columns([1.0, 0.22], gap="small")
        with row_col:
            st.markdown(
                f"""
                <div style="padding:6px 0;">
                    <div class="destination-name" style="font-size:14px;">{escape(title)}</div>
                    <div class="destination-status" style="color:#7a9bb5;">{escape(copy)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with toggle_col:
            render_toggle_input(
                title,
                value=bool(st.session_state.get(key_name, default_value)),
                key=key_name,
                help=copy,
            )

    st.markdown("</div>", unsafe_allow_html=True)
    st.caption("Choose the kinds of alerts you want Finwise to send.")


def _render_security_tab(
    username: str,
    *,
    preferences: dict,
    render_toggle_input,
) -> None:
    _render_section_heading("Security", "Keep your account secure and manage access.")

    password_col, security_col = st.columns(2, gap="large")
    with password_col:
        st.markdown(
            """
            <div class="settings-surface">
                <div class="destination-head">
                    <div class="destination-icon-wrap">
                        <div class="destination-icon telegram">🔑</div>
                        <div>
                            <div class="destination-name">Change Password</div>
                            <div class="destination-status ready">Verify your registered email before choosing a new password.</div>
                        </div>
                    </div>
                </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="password-change-copy" style="margin-top:0;color:#7a9bb5;max-width:none;">
                Clicking below opens a dedicated verification page. Finwise will send a code to your registered email
                and only unlock the new-password form after the code is confirmed.
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open Password Verification", key="account_settings_open_password_change", use_container_width=True, type="primary"):
            st.session_state[STATE_KEYS["view"]] = "change_password"
            st.rerun()
        st.caption("This flow uses your registered email as the verification step before the password can be changed.")
        st.markdown("</div>", unsafe_allow_html=True)

    with security_col:
        st.markdown(
            """
            <div class="settings-surface">
                <div class="destination-head">
                    <div class="destination-icon-wrap">
                        <div class="destination-icon whatsapp">🛡</div>
                        <div>
                            <div class="destination-name">2FA Settings</div>
                            <div class="destination-status ready">Saved to your profile for this workspace.</div>
                        </div>
                    </div>
                </div>
            """,
            unsafe_allow_html=True,
        )
        render_toggle_input(
            "Authenticator App",
            value=bool(preferences.get("security_authenticator_2fa", 0)),
            key=STATE_KEYS["security_authenticator_2fa"],
            help="Store your preference for app-based 2FA.",
        )
        st.caption("Saved now. Full authenticator enforcement is not active in the current sign-in flow yet.")
        render_toggle_input(
            "SMS Verification",
            value=bool(preferences.get("security_sms_verification", 1)),
            key=STATE_KEYS["security_sms_verification"],
            help="Store whether WhatsApp or SMS verification should stay preferred for future security flows.",
        )
        st.caption("Saved now as a security preference tied to your account profile.")
        render_toggle_input(
            "Login Alerts",
            value=bool(preferences.get("security_login_alerts", 1)),
            key=STATE_KEYS["security_login_alerts"],
            help="Store whether login alerts should remain enabled.",
        )
        st.caption("Saved now for upcoming session alert coverage.")
        st.markdown("</div>", unsafe_allow_html=True)


def _render_plan_panel(username: str, *, premium: bool, upgrade_user_to_premium) -> None:
    plan_name = "Premium" if premium else "Free"
    plan_copy = (
        "Unlimited signals, multi-channel routing, and premium workspace tools are active on this account."
        if premium else
        "Upgrade to unlock unlimited signals, multi-channel routing, broker execution extras, and priority support."
    )
    renewal_text = "Renewal date not synced yet" if premium else "Upgrade to unlock billing schedule"
    st.markdown(
        f"""
        <div class="plan-card">
            <div class="plan-card-row">
                <div>
                    <h3>Premium Plan</h3>
                    <div class="plan-name">{escape(plan_name)}</div>
                    <div class="plan-copy">{escape(plan_copy)}</div>
                    <div class="plan-feature-row">
                        <div class="plan-feature">✓ Unlimited Signals</div>
                        <div class="plan-feature">✓ Multi-channel Routing</div>
                        <div class="plan-feature">✓ Priority Support</div>
                    </div>
                </div>
                <div class="plan-meta">{escape(renewal_text)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    action_col1, action_col2 = st.columns([0.32, 0.24], gap="small")
    with action_col1:
        action_label = "Manage Plan" if premium else "Open Upgrade"
        if st.button(action_label, key="account_settings_manage_plan", use_container_width=True, type="primary"):
            st.session_state.nav_choice = "Upgrade"
            st.rerun()
    with action_col2:
        if not premium and st.button("Simulate Premium (TEST)", key="account_settings_premium_test", use_container_width=True):
            upgrade_user_to_premium(username)
            st.success("Premium enabled for this account.")
            st.rerun()


def _render_danger_zone_panel(
    username: str,
    *,
    reset_user_signal_destinations,
    settings: dict,
    preferences: dict,
) -> None:
    st.markdown(
        """
        <div class="danger-zone">
            <div class="danger-title">Danger Zone</div>
            <div class="danger-copy">Reset all saved channels if you want to start fresh. Account deletion still needs a full confirmation and data-retention flow before it can be safely wired.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    row1_text, row1_action = st.columns([1.0, 0.24], gap="small")
    with row1_text:
        st.markdown(
            """
            <div class="settings-surface" style="padding:16px 18px;">
                <div class="destination-name" style="font-size:14px;">Reset All Signal Destinations</div>
                <div class="destination-status" style="color:#7a9bb5;">Remove all configured channels and start fresh.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with row1_action:
        if st.button("Reset", key="account_settings_reset_channels", use_container_width=True):
            reset_user_signal_destinations(username)
            settings = dict(settings)
            settings["phone"] = ""
            settings["telegram_chat_id"] = ""
            settings["notification_whatsapp"] = 0
            settings["notification_telegram"] = 0
            _seed_settings_state(username, settings, preferences, force=True)
            st.success("Signal destinations cleared. Save-ready drafts have been reset.")
            st.rerun()

    row2_text, row2_action = st.columns([1.0, 0.24], gap="small")
    with row2_text:
        st.markdown(
            """
            <div class="settings-surface" style="padding:16px 18px;">
                <div class="destination-name" style="font-size:14px;">Delete Account</div>
                <div class="destination-status" style="color:#7a9bb5;">Permanently delete your account and all local data once a safe confirmation flow is added.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with row2_action:
        if st.button("Delete", key="account_settings_delete_account", use_container_width=True):
            st.warning("Delete account is not wired into this build yet because it still needs a confirmed data-removal workflow.")


def render_account_page(
    username: str,
    *,
    get_user_notification_settings,
    save_user_notification_settings,
    get_user_account_preferences,
    save_user_account_preferences,
    change_user_password,
    verify_otp,
    update_user_password,
    clear_login_failures,
    password_meets_policy,
    send_email_otp,
    clear_password_change_state,
    reset_user_signal_destinations,
    upgrade_user_to_premium,
    render_toggle_input,
):
    settings = get_user_notification_settings(username)
    preferences = get_user_account_preferences(username)
    premium = bool(settings.get("premium", 0))
    readiness = notification_gateway_status()
    twilio_ready = readiness["twilio_ready"]
    telegram_ready = readiness["telegram_ready"]

    _seed_settings_state(username, settings, preferences)
    _render_styles()

    account_notice = str(st.session_state.pop("account_settings_notice", "") or "").strip()
    if account_notice:
        st.success(account_notice)

    if st.session_state.get(STATE_KEYS["view"]) == "change_password":
        _render_password_change_page(
            username,
            email=settings.get("email", ""),
            verify_otp=verify_otp,
            update_user_password=update_user_password,
            clear_login_failures=clear_login_failures,
            password_meets_policy=password_meets_policy,
            send_email_otp=send_email_otp,
            clear_password_change_state=clear_password_change_state,
        )
        return

    reset_clicked, save_clicked = _render_page_header()
    if reset_clicked:
        _seed_settings_state(username, settings, preferences, force=True)
        st.success("Unsaved changes reset to your last saved settings.")
        st.rerun()
    if save_clicked:
        _save_settings_draft(
            username,
            save_user_notification_settings=save_user_notification_settings,
            save_user_account_preferences=save_user_account_preferences,
            twilio_ready=twilio_ready,
            telegram_ready=telegram_ready,
        )
        settings = get_user_notification_settings(username)
        preferences = get_user_account_preferences(username)
        _seed_settings_state(username, settings, preferences, force=True)

    draft = _current_draft()
    _render_account_overview(username, settings, draft, twilio_ready, telegram_ready)
    _render_tabs_strip()
    _render_signal_routing_tab(
        username,
        settings=settings,
        premium=premium,
        twilio_ready=twilio_ready,
        telegram_ready=telegram_ready,
        save_user_notification_settings=save_user_notification_settings,
        render_toggle_input=render_toggle_input,
    )
    _render_notifications_tab(render_toggle_input)
    _render_security_tab(
        username,
        preferences=preferences,
        render_toggle_input=render_toggle_input,
    )
    _render_plan_panel(
        username,
        premium=premium,
        upgrade_user_to_premium=upgrade_user_to_premium,
    )
    _render_danger_zone_panel(
        username,
        reset_user_signal_destinations=reset_user_signal_destinations,
        settings=settings,
        preferences=preferences,
    )


def render_mobile_account_page(
    username: str,
    *,
    get_user_notification_settings,
    save_user_notification_settings,
    get_user_account_preferences,
    save_user_account_preferences,
    change_user_password,
    verify_otp,
    update_user_password,
    clear_login_failures,
    password_meets_policy,
    send_email_otp,
    clear_password_change_state,
    reset_user_signal_destinations,
    upgrade_user_to_premium,
    render_toggle_input,
):
    settings = get_user_notification_settings(username)
    preferences = get_user_account_preferences(username)
    premium = bool(settings.get("premium", 0))
    readiness = notification_gateway_status()
    twilio_ready = readiness["twilio_ready"]
    telegram_ready = readiness["telegram_ready"]

    _seed_settings_state(username, settings, preferences)
    _render_styles()

    st.markdown(
        """
        <style>
        .fw-mobile-settings-hero {
            padding: 1rem 1rem 0.95rem;
            border-radius: 1.18rem;
            border: 1px solid rgba(255,255,255,0.06);
            background:
                radial-gradient(circle at top right, rgba(34,231,202,0.10), transparent 28%),
                linear-gradient(180deg, rgba(14,23,36,0.96), rgba(9,17,29,0.98));
            box-shadow: 0 18px 40px rgba(0,0,0,0.22);
            margin-bottom: 0.82rem;
        }
        .fw-mobile-settings-kicker {
            color: #7fece0;
            font-size: 0.64rem;
            font-weight: 850;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }
        .fw-mobile-settings-title {
            color: #ffffff;
            font-size: 1.08rem;
            font-weight: 900;
            letter-spacing: -0.03em;
            margin-top: 0.34rem;
        }
        .fw-mobile-settings-copy {
            color: #8da3ba;
            font-size: 0.74rem;
            line-height: 1.58;
            margin-top: 0.32rem;
        }
        .fw-mobile-settings-action-row {
            margin-bottom: 0.5rem;
        }
        .fw-mobile-settings-action-row [data-testid="stHorizontalBlock"] {
            gap: 0.6rem !important;
        }
        .fw-mobile-settings-tabs {
            margin: 0.35rem 0 0.7rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    account_notice = str(st.session_state.pop("account_settings_notice", "") or "").strip()
    if account_notice:
        st.success(account_notice)

    if st.session_state.get(STATE_KEYS["view"]) == "change_password":
        _render_password_change_page(
            username,
            email=settings.get("email", ""),
            verify_otp=verify_otp,
            update_user_password=update_user_password,
            clear_login_failures=clear_login_failures,
            password_meets_policy=password_meets_policy,
            send_email_otp=send_email_otp,
            clear_password_change_state=clear_password_change_state,
        )
        return

    st.markdown(
        """
        <section class="fw-mobile-settings-hero">
            <div class="fw-mobile-settings-kicker">Account Control</div>
            <div class="fw-mobile-settings-title">Shape a tighter alert flow without leaving your mobile workspace.</div>
            <div class="fw-mobile-settings-copy">Connect the channels you trust, tune your market alerts, and keep your account secure in one focused pass.</div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="mobile_settings_action_row"):
        reset_col, save_col = st.columns(2, gap="small")
        with reset_col:
            reset_clicked = st.button("Reset Draft", key="mobile_account_settings_reset", use_container_width=True)
        with save_col:
            save_clicked = st.button("Save Changes", key="mobile_account_settings_save", use_container_width=True, type="primary")

    if reset_clicked:
        _seed_settings_state(username, settings, preferences, force=True)
        st.success("Unsaved changes reset to your last saved settings.")
        st.rerun()
    if save_clicked:
        _save_settings_draft(
            username,
            save_user_notification_settings=save_user_notification_settings,
            save_user_account_preferences=save_user_account_preferences,
            twilio_ready=twilio_ready,
            telegram_ready=telegram_ready,
        )
        settings = get_user_notification_settings(username)
        preferences = get_user_account_preferences(username)
        _seed_settings_state(username, settings, preferences, force=True)

    draft = _current_draft()
    _render_account_overview(username, settings, draft, twilio_ready, telegram_ready)

    section_default = st.session_state.get("mobile_account_settings_panel", "Routing")
    section = resolve_query_value(
        "maccount",
        default=section_default if section_default in {"Routing", "Alerts", "Security", "Plan"} else "Routing",
        allowed=["Routing", "Alerts", "Security", "Plan"],
        session_key="mobile_account_settings_panel",
    )
    section = render_mobile_link_tabs(
        options=["Routing", "Alerts", "Security", "Plan"],
        current_value=section,
        query_key="maccount",
    )

    if section == "Routing":
        _render_signal_routing_tab(
            username,
            settings=settings,
            premium=premium,
            twilio_ready=twilio_ready,
            telegram_ready=telegram_ready,
            save_user_notification_settings=save_user_notification_settings,
            render_toggle_input=render_toggle_input,
        )
    elif section == "Alerts":
        _render_notifications_tab(render_toggle_input)
    elif section == "Security":
        _render_security_tab(
            username,
            preferences=preferences,
            render_toggle_input=render_toggle_input,
        )
    else:
        _render_plan_panel(
            username,
            premium=premium,
            upgrade_user_to_premium=upgrade_user_to_premium,
        )
        _render_danger_zone_panel(
            username,
            reset_user_signal_destinations=reset_user_signal_destinations,
            settings=settings,
            preferences=preferences,
        )
