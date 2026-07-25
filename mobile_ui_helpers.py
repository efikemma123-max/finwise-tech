from html import escape
from urllib.parse import urlencode

import streamlit as st


def _query_params_snapshot() -> dict[str, str | list[str]]:
    snapshot: dict[str, str | list[str]] = {}
    for key, value in dict(st.query_params).items():
        if isinstance(value, list):
            snapshot[key] = [str(item) for item in value]
        else:
            snapshot[key] = str(value)
    return snapshot


def build_query_href(**updates: str | None) -> str:
    params = _query_params_snapshot()
    for key, value in updates.items():
        if value is None or value == "":
            params.pop(key, None)
        else:
            params[key] = str(value)
    query = urlencode(params, doseq=True)
    return f"?{query}" if query else "?"


def resolve_query_value(
    query_key: str,
    *,
    default: str,
    allowed: list[str] | tuple[str, ...] | set[str],
    session_key: str | None = None,
) -> str:
    allowed_values = list(allowed)
    raw_value = st.query_params.get(query_key, "")
    value = str(raw_value or "").strip()
    if value not in allowed_values:
        if session_key:
            value = str(st.session_state.get(session_key, default) or default).strip()
        else:
            value = default
    if value not in allowed_values:
        value = default
    if session_key:
        st.session_state[session_key] = value
    return value


def render_mobile_link_tabs(
    *,
    options: list[str],
    current_value: str,
    query_key: str,
    labels: dict[str, str] | None = None,
    extra_updates: dict[str, str | None] | None = None,
    variant: str = "pill",
    layout: str = "auto",
) -> str:
    labels = labels or {}
    allowed_options = list(options)
    if not allowed_options:
        return current_value
    if current_value not in allowed_options:
        current_value = allowed_options[0]

    session_key_map = {
        "mnav": "nav_choice",
        "mdash": "mobile_dashboard_panel",
        "maccount": "mobile_account_settings_panel",
        "mdeskmode": "trading_desk_view",
        "mdeskpanel": "mobile_trading_desk_panel",
        "mtf": "market_analysis_tf_control",
    }
    target_session_key = session_key_map.get(query_key, query_key)
    widget_key = f"fw_mobile_tabs_{query_key}_{variant}"
    last_query_key = f"{widget_key}__last_query_value"
    query_value = str(st.query_params.get(query_key, "") or "").strip()
    if query_value not in allowed_options:
        query_value = ""
    session_value = st.session_state.get(target_session_key, current_value)
    if session_value not in allowed_options:
        session_value = current_value
    widget_value = st.session_state.get(widget_key)
    query_changed = bool(query_value) and query_value != st.session_state.get(last_query_key)
    if query_changed:
        existing = query_value
    elif widget_value in allowed_options:
        existing = widget_value
    elif query_value:
        existing = query_value
    else:
        existing = session_value
    if st.session_state.get(widget_key) not in allowed_options or st.session_state.get(widget_key) != existing:
        st.session_state[widget_key] = existing

    label_text = str(query_key).replace("_", " ").title()
    selected = st.segmented_control(
        label_text,
        allowed_options,
        default=existing,
        key=widget_key,
        format_func=lambda option: labels.get(option, option),
        label_visibility="collapsed",
        width="stretch" if layout != "scroll" else "content",
    )
    selected = selected or existing
    st.session_state[target_session_key] = selected
    if str(st.query_params.get(query_key, "") or "").strip() != selected:
        st.query_params[query_key] = selected
    st.session_state[last_query_key] = selected
    if query_key == "mtf":
        st.session_state["market_analysis_tf_radio"] = selected
    return selected

def _nav_icon_svg(icon_key: str) -> str:
    icons = {
        "home": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5"/><path d="M6.75 9.75V20h10.5V9.75"/></svg>',
        "markets": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19h16"/><path d="M7 15v-4"/><path d="M12 15V8"/><path d="M17 15v-7"/></svg>',
        "desk": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9"/><path d="M12 7v5l3 3"/></svg>',
        "journal": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3.75h7.5L19.5 8.8V20.25H7z"/><path d="M14.25 3.75v5.1h5.25"/><path d="M10 13h5"/><path d="M10 16.25h5"/></svg>',
        "settings": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8.25a3.75 3.75 0 1 0 0 7.5 3.75 3.75 0 0 0 0-7.5Z"/><path d="M19.4 15a1 1 0 0 0 .2 1.1l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1 1 0 0 0-1.1-.2 1 1 0 0 0-.6.9V20a2 2 0 1 1-4 0v-.2a1 1 0 0 0-.6-.9 1 1 0 0 0-1.1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1 1 0 0 0 .2-1.1 1 1 0 0 0-.9-.6H4a2 2 0 1 1 0-4h.2a1 1 0 0 0 .9-.6 1 1 0 0 0-.2-1.1l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1 1 0 0 0 1.1.2 1 1 0 0 0 .6-.9V4a2 2 0 1 1 4 0v.2a1 1 0 0 0 .6.9 1 1 0 0 0 1.1-.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1 1 0 0 0-.2 1.1 1 1 0 0 0 .9.6H20a2 2 0 1 1 0 4h-.2a1 1 0 0 0-.9.6Z"/></svg>',
    }
    return icons.get(icon_key, icons["home"])


def render_mobile_bottom_nav(
    *,
    items: list[tuple[str, str, str]],
    current_value: str,
    query_key: str,
) -> None:
    links: list[str] = []
    for label, value, icon_key in items:
        href = build_query_href(**{query_key: value})
        active_class = " is-active" if value == current_value else ""
        links.append(
            f'<a class="fw-mobile-bottom-nav-item{active_class}" href="{escape(href, quote=True)}" target="_self">'
            f'<span class="fw-mobile-bottom-nav-icon">{_nav_icon_svg(icon_key)}</span>'
            f'<span class="fw-mobile-bottom-nav-label">{escape(label)}</span>'
            f"</a>"
        )
    st.markdown(
        f'<nav class="fw-mobile-bottom-nav-grid">{"".join(links)}</nav>',
        unsafe_allow_html=True,
    )
