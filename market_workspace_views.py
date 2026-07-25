from html import escape
import math

import streamlit as st

from backend.market.candle_engine import is_forex_symbol, split_market_symbol
from backend.ai.broker_ai_copilot import render_copilot_drawer
from mobile_ui_helpers import build_query_href, render_mobile_link_tabs, resolve_query_value


def _render_dark_button_group(
    *,
    scope_key: str,
    options: list[str],
    current_value: str,
    labels: dict[str, str] | None = None,
    columns_spec=None,
    max_columns: int | None = None,
) -> str:
    labels = labels or {}
    if current_value not in options:
        current_value = options[0]

    st.markdown(
        f"""
        <style>
        .st-key-{scope_key} {{
            margin: 0;
            padding: 0;
        }}
        .st-key-{scope_key} [data-testid="stHorizontalBlock"] {{
            gap: 0.5rem !important;
            align-items: stretch !important;
        }}
        .st-key-{scope_key} [data-testid="column"] {{
            width: 100% !important;
            min-width: 0 !important;
            flex: 1 1 0 !important;
        }}
        .st-key-{scope_key} [data-testid="stButton"],
        .st-key-{scope_key} .stButton {{
            width: 100%;
        }}
        .st-key-{scope_key} [data-testid="stButton"] > button,
        .st-key-{scope_key} .stButton > button {{
            min-height: 2.56rem !important;
            border-radius: 0.82rem !important;
            font-size: 0.78rem !important;
            font-weight: 800 !important;
            letter-spacing: 0.01em !important;
            border: 1px solid rgba(92,118,151,0.2) !important;
            background: linear-gradient(180deg, rgba(11,24,39,0.98) 0%, rgba(7,18,31,0.99) 100%) !important;
            color: #dce8ff !important;
            box-shadow: 0 12px 26px rgba(0,0,0,0.14) !important;
            transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease !important;
        }}
        .st-key-{scope_key} [data-testid="stButton"] > button > div,
        .st-key-{scope_key} .stButton > button > div {{
            width: 100% !important;
        }}
        .st-key-{scope_key} [data-testid="stButton"] > button p,
        .st-key-{scope_key} .stButton > button p {{
            width: 100% !important;
            margin: 0 !important;
            text-align: center !important;
            white-space: nowrap !important;
            text-wrap: nowrap !important;
            overflow-wrap: normal !important;
            word-break: normal !important;
        }}
        .st-key-{scope_key} [data-testid="stButton"] > button[kind="primary"],
        .st-key-{scope_key} .stButton > button[kind="primary"] {{
            background: linear-gradient(135deg, rgba(25,223,208,0.18), rgba(64,212,255,0.22)) !important;
            color: #f8fdff !important;
            border-color: rgba(25,223,208,0.3) !important;
            box-shadow: 0 16px 30px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.05) !important;
        }}
        .st-key-{scope_key} [data-testid="stButton"] > button:hover,
        .st-key-{scope_key} .stButton > button:hover {{
            transform: translateY(-1px);
            border-color: rgba(89, 249, 232, 0.34) !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    current = current_value
    if columns_spec is None and max_columns and max_columns > 0 and len(options) > max_columns:
        option_rows = [options[index:index + max_columns] for index in range(0, len(options), max_columns)]
    else:
        option_rows = [options]

    with st.container(key=scope_key):
        option_offset = 0
        for row_index, option_row in enumerate(option_rows):
            row_columns_spec = columns_spec if len(option_rows) == 1 and columns_spec is not None else len(option_row)
            cols = st.columns(row_columns_spec, gap="small")
            for local_idx, option in enumerate(option_row):
                label = labels.get(option, option)
                global_idx = option_offset + local_idx
                with cols[local_idx]:
                    if st.button(
                        label,
                        key=f"{scope_key}_button_{global_idx}",
                        use_container_width=True,
                        type="primary" if option == current else "secondary",
                    ):
                        current = option
            option_offset += len(option_row)
    return current


def _render_top_right_desk_switcher(
    *,
    options: list[str],
    current_value: str,
    labels: dict[str, str] | None = None,
) -> str:
    labels = labels or {}
    if current_value not in options:
        current_value = options[0]
    widget_key = "desktop_trading_desk_view_switcher"
    last_query_key = f"{widget_key}__last_query_value"
    query_value = str(st.query_params.get("mdeskmode", "") or "").strip()
    if query_value not in options:
        query_value = ""
    session_value = st.session_state.get("trading_desk_view", current_value)
    if session_value not in options:
        session_value = current_value
    widget_value = st.session_state.get(widget_key)
    query_changed = bool(query_value) and query_value != st.session_state.get(last_query_key)
    if query_changed:
        current = query_value
    elif widget_value in options:
        current = widget_value
    elif query_value:
        current = query_value
    else:
        current = session_value
    st.session_state.trading_desk_view = current
    if st.session_state.get(widget_key) not in options or st.session_state.get(widget_key) != current:
        st.session_state[widget_key] = current

    st.markdown(
        """
        <style>
        .st-key-desktop_trading_desk_view_switcher {
            display: flex;
            justify-content: flex-end;
            margin: -0.12rem 0 0.72rem;
        }
        .st-key-desktop_trading_desk_view_switcher [data-baseweb="segmented-control"] {
            background: transparent;
            gap: 0.42rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    selected = st.segmented_control(
        "Desk Mode",
        options,
        default=current,
        key=widget_key,
        format_func=lambda option: labels.get(option, option),
        label_visibility="collapsed",
    )
    current = selected or current
    st.session_state.trading_desk_view = current
    if str(st.query_params.get("mdeskmode", "") or "").strip() != current:
        st.query_params["mdeskmode"] = current
    st.session_state[last_query_key] = current
    return current

def render_market_analysis_chart_tools():
    with st.expander("Chart Indicators & Settings", expanded=False):
        st.caption("Turn indicators on and off instantly. The live chart keeps streaming while these overlays update.")

        tool_col1, tool_col2, tool_col3, tool_col4 = st.columns(4)

        with tool_col1:
            show_ma = st.checkbox(
                "EMA 20 / 50",
                value=st.session_state.chart_indicators["moving_averages"]["enabled"],
                key="show_ma_live",
            )
            st.session_state.chart_indicators["moving_averages"]["enabled"] = show_ma
            st.session_state.chart_indicators["moving_averages"]["ema"] = [20, 50] if show_ma else []
            st.caption("Trend overlay on the main price chart.")

        with tool_col2:
            show_bb = st.checkbox(
                "Bollinger Bands",
                value=st.session_state.chart_indicators["bollinger_bands"]["enabled"],
                key="show_bb_live",
            )
            st.session_state.chart_indicators["bollinger_bands"]["enabled"] = show_bb
            st.caption("Upper, middle, and lower volatility bands.")

        with tool_col3:
            show_rsi = st.checkbox(
                "RSI 14",
                value=st.session_state.chart_indicators["rsi"]["enabled"],
                key="show_rsi_live",
            )
            st.session_state.chart_indicators["rsi"]["enabled"] = show_rsi
            st.caption("Dedicated momentum pane with 30 / 70 levels.")

        with tool_col4:
            show_macd = st.checkbox(
                "MACD",
                value=st.session_state.chart_indicators["macd"]["enabled"],
                key="show_macd_live",
            )
            st.session_state.chart_indicators["macd"]["enabled"] = show_macd
            st.caption("MACD, signal, and histogram in a separate pane.")

        st.divider()
        info_col1, info_col2, info_col3 = st.columns(3)
        info_col1.caption("Exchange-style layout")
        info_col2.caption("Live in-panel updates")
        info_col3.caption("OHLC hover strip")


def _current_mobile_indicator_preset() -> str:
    config = st.session_state.get("chart_indicators", {})
    moving_average_config = config.get("moving_averages", {})
    bollinger_config = config.get("bollinger_bands", {})
    rsi_config = config.get("rsi", {})
    macd_config = config.get("macd", {})

    if bollinger_config.get("enabled"):
        return "BOLL"
    if rsi_config.get("enabled"):
        return "RSI"
    if macd_config.get("enabled"):
        return "MACD"
    if moving_average_config.get("enabled"):
        if moving_average_config.get("sma"):
            return "MA"
        return "EMA"
    return "EMA"


def _apply_mobile_indicator_preset(preset: str) -> None:
    selected = str(preset or "EMA").upper()
    config = st.session_state.setdefault("chart_indicators", {})
    moving_average_config = config.setdefault("moving_averages", {"enabled": True, "ema": [20, 50], "sma": []})
    rsi_config = config.setdefault("rsi", {"enabled": False, "period": 14})
    macd_config = config.setdefault("macd", {"enabled": False, "fast": 12, "slow": 26, "signal": 9})
    bollinger_config = config.setdefault("bollinger_bands", {"enabled": False, "period": 20, "std_dev": 2})

    moving_average_config["enabled"] = selected in {"MA", "EMA"}
    moving_average_config["ema"] = [20, 50] if selected == "EMA" else []
    moving_average_config["sma"] = [20, 50] if selected == "MA" else []
    bollinger_config["enabled"] = selected == "BOLL"
    rsi_config["enabled"] = selected == "RSI"
    macd_config["enabled"] = selected == "MACD"


def render_mobile_chart_toolbar(
    *,
    current_timeframe: str,
    timeframe_options: list[str],
    timeframe_query_key: str,
    indicator_query_key: str = "mind",
) -> None:
    indicator_options = ["MA", "EMA", "BOLL", "RSI", "MACD"]
    current_indicator = resolve_query_value(
        indicator_query_key,
        default=_current_mobile_indicator_preset(),
        allowed=indicator_options,
        session_key="mobile_chart_indicator",
    )
    _apply_mobile_indicator_preset(current_indicator)

    st.markdown(
        """
        <style>
        .fw-mobile-chart-toolstack {
            display: grid;
            gap: 0.22rem;
            margin: 0.18rem 0 0.34rem;
        }
        .fw-mobile-link-tabs--inline {
            display: flex;
            align-items: center;
            gap: 0.62rem;
            margin: 0;
            overflow-x: auto;
            overflow-y: hidden;
            padding: 0.04rem 0 0.08rem;
            scrollbar-width: none;
            border: 0;
            background: transparent;
            box-shadow: none;
        }
        .fw-mobile-link-tabs--inline::-webkit-scrollbar {
            display: none;
        }
        .fw-mobile-link-tab--inline {
            flex: 0 0 auto;
            min-height: auto;
            padding: 0.08rem 0.08rem 0.18rem;
            border: 0;
            border-radius: 0;
            background: transparent;
            color: rgba(205, 220, 233, 0.42) !important;
            font-size: 0.88rem;
            font-weight: 760;
            line-height: 1.05;
            text-decoration: none !important;
            box-shadow: none;
            white-space: nowrap;
        }
        .fw-mobile-link-tab--inline.is-active {
            color: #f4fbff !important;
            border-bottom: 2px solid rgba(255,255,255,0.96);
        }
        .fw-mobile-link-tab--inline:hover {
            transform: none;
            color: #f4fbff !important;
            border-color: transparent;
        }
        .fw-mobile-inline-label {
            color: rgba(136, 160, 184, 0.66);
            font-size: 0.74rem;
            font-weight: 720;
            margin-right: 0.18rem;
            white-space: nowrap;
        }
        .fw-mobile-chart-toolrow {
            display: flex;
            align-items: center;
            gap: 0.42rem;
            min-width: 0;
        }
        .fw-mobile-chart-toolrow .fw-mobile-link-tabs--inline {
            flex: 1 1 auto;
            min-width: 0;
        }
        </style>
        <div class="fw-mobile-chart-toolstack">
            <div class="fw-mobile-chart-toolrow"><div class="fw-mobile-inline-label">Time</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_mobile_link_tabs(
        options=timeframe_options,
        current_value=current_timeframe,
        query_key=timeframe_query_key,
        variant="inline",
        layout="scroll",
    )
    render_mobile_link_tabs(
        options=indicator_options,
        current_value=current_indicator,
        query_key=indicator_query_key,
        variant="inline",
        layout="scroll",
    )


def _matching_signal_payload(symbol: str, tf_label: str) -> tuple[dict, dict]:
    signal_result = st.session_state.get("last_signal") or {}
    signal_meta = st.session_state.get("last_signal_meta") or {}
    active_trade_style = str(st.session_state.get("trade_style_preference", "day_trade") or "day_trade")
    has_matching_signal = bool(signal_result) and (
        not signal_meta
        or (
            signal_meta.get("symbol") == symbol
            and signal_meta.get("tf_label") == tf_label
            and str(signal_meta.get("trade_style", active_trade_style) or active_trade_style) == active_trade_style
        )
    )
    if not has_matching_signal:
        return {}, {}
    return signal_result, signal_meta or {"symbol": symbol, "tf_label": tf_label}


def _desk_terminal_number(value, digits: int = 2) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "--"
    if math.isnan(numeric) or math.isinf(numeric):
        return "--"
    return f"{numeric:,.{digits}f}"


def _desk_terminal_percent(value) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "--"
    if math.isnan(numeric) or math.isinf(numeric):
        return "--"
    scaled = numeric * 100 if abs(numeric) <= 1 else numeric
    return f"{scaled:+.2f}%"


def _desk_terminal_compact(value) -> str:
    try:
        numeric = abs(float(value))
    except (TypeError, ValueError):
        return "--"
    if math.isnan(numeric) or math.isinf(numeric):
        return "--"
    if numeric >= 1_000_000_000:
        return f"{numeric / 1_000_000_000:.2f}B"
    if numeric >= 1_000_000:
        return f"{numeric / 1_000_000:.2f}M"
    if numeric >= 1_000:
        return f"{numeric / 1_000:.2f}K"
    return f"{numeric:,.2f}"


def _render_desktop_trade_desk_frame(
    *,
    symbol: str,
    tf_label: str,
    snapshot: dict,
    df,
    engine_live: bool,
) -> None:
    snapshot = snapshot or {}
    latest_close = None
    if df is not None and not getattr(df, "empty", True):
        try:
            latest_close = float(df.iloc[-1]["close"])
        except Exception:
            latest_close = None

    last_price = snapshot.get("last_price", latest_close)
    day_change = snapshot.get("price_24h_pcnt")
    open_interest = snapshot.get("open_interest")
    volume_24h = snapshot.get("volume_24h")
    forex_market = is_forex_symbol(symbol) or snapshot.get("asset_class") == "forex"
    base_asset, _quote_asset = split_market_symbol(symbol)
    base_asset = base_asset or str(symbol or "").upper()
    flow_label = "Feed Source" if forex_market else "Open Interest / Volume"
    flow_value = "Spot FX" if forex_market else _desk_terminal_compact(open_interest)
    flow_meta = "Yahoo Finance FX quote feed" if forex_market else f"{_desk_terminal_compact(volume_24h)} {base_asset} traded"

    status_label = "Live feed online" if engine_live else "Feed warming"
    status_class = "is-live" if engine_live else "is-warm"
    change_class = "is-positive"
    try:
        if float(day_change or 0) < 0:
            change_class = "is-negative"
    except (TypeError, ValueError):
        change_class = ""

    st.markdown(
        f"""
        <style>
        .st-key-desktop_trade_controls {{
            margin: 0.25rem 0 0.75rem;
            padding: 1rem 1.05rem 1.08rem;
            border-radius: 1.3rem;
            border: 1px solid rgba(119, 154, 186, 0.14);
            background:
                radial-gradient(circle at top right, rgba(43, 233, 209, 0.08), transparent 30%),
                linear-gradient(180deg, rgba(10, 20, 33, 0.98) 0%, rgba(7, 15, 27, 0.98) 100%);
            box-shadow: 0 26px 56px rgba(0, 0, 0, 0.2);
        }}
        .st-key-desktop_trade_controls [data-testid="stHorizontalBlock"] {{
            gap: 0.88rem !important;
            align-items: end !important;
        }}
        .st-key-desktop_trade_controls [data-testid="stTextInput"] input,
        .st-key-desktop_trade_controls [data-baseweb="select"] > div,
        .st-key-desktop_trade_controls [data-testid="stTextInput"] > div > div,
        .st-key-desktop_trade_controls [data-baseweb="base-input"] {{
            min-height: 3.25rem !important;
            border-radius: 1rem !important;
            background: rgba(10, 18, 30, 0.88) !important;
            border: 1px solid rgba(119, 154, 186, 0.16) !important;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.03), 0 14px 30px rgba(0,0,0,0.16) !important;
        }}
        .st-key-desktop_trade_surface {{
            display: grid;
            gap: 1rem;
        }}
        .st-key-desktop_trade_chart_stage,
        .st-key-desktop_trade_overview_stage,
        .st-key-desktop_trade_flow_stage,
        .st-key-desktop_trade_signal_stage,
        .st-key-desktop_trade_depth_stage,
        .st-key-desktop_trade_tools_stage {{
            padding: 1rem 1rem 1.05rem;
            border-radius: 1.28rem;
            border: 1px solid rgba(119, 154, 186, 0.12);
            background:
                linear-gradient(180deg, rgba(10, 20, 33, 0.98) 0%, rgba(7, 15, 27, 0.98) 100%);
            box-shadow: 0 22px 48px rgba(0, 0, 0, 0.18);
        }}
        .st-key-desktop_trade_signal_stage {{
            padding: 0.85rem 0.9rem 0.92rem;
            background:
                radial-gradient(circle at top right, rgba(43, 233, 209, 0.07), transparent 26%),
                linear-gradient(180deg, rgba(8, 18, 31, 0.98) 0%, rgba(5, 13, 23, 0.98) 100%);
            border-color: rgba(119, 154, 186, 0.10);
        }}
        .st-key-desktop_trade_depth_stage {{
            padding: 0.85rem 0.9rem 0.92rem;
            background:
                radial-gradient(circle at top right, rgba(79, 162, 255, 0.08), transparent 28%),
                linear-gradient(180deg, rgba(8, 18, 31, 0.98) 0%, rgba(5, 13, 23, 0.98) 100%);
            border-color: rgba(119, 154, 186, 0.10);
        }}
        .st-key-desktop_trade_signal_stage > div[data-testid="stVerticalBlock"] {{
            gap: 0.72rem;
        }}
        .st-key-desktop_trade_chart_stage iframe,
        .st-key-desktop_trade_flow_stage iframe,
        .st-key-desktop_trade_signal_stage iframe,
        .st-key-desktop_trade_depth_stage iframe,
        .st-key-desktop_trade_overview_stage iframe {{
            border-radius: 1rem;
        }}
        .st-key-desktop_trade_chart_stage [data-testid="stInfo"],
        .st-key-desktop_trade_signal_stage [data-testid="stInfo"],
        .st-key-desktop_trade_depth_stage [data-testid="stInfo"] {{
            border-radius: 1rem;
        }}
        .st-key-desktop_trade_tools_stage details {{
            border: 1px solid rgba(119, 154, 186, 0.14);
            border-radius: 1rem;
            background: rgba(8, 17, 29, 0.78);
            padding: 0.35rem 0.8rem;
        }}
        .fw-desk-shell {{
            display: grid;
            gap: 1rem;
        }}
        .fw-desk-hero {{
            padding: 1.18rem 1.22rem 1.24rem;
            border-radius: 1.45rem;
            border: 1px solid rgba(119, 154, 186, 0.14);
            background:
                radial-gradient(circle at top right, rgba(43, 233, 209, 0.1), transparent 28%),
                linear-gradient(180deg, rgba(10, 20, 33, 0.98) 0%, rgba(6, 14, 24, 1) 100%);
            box-shadow: 0 30px 64px rgba(0, 0, 0, 0.22);
        }}
        .fw-desk-hero-top {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
        }}
        .fw-desk-kicker {{
            color: #7fece0;
            font-size: 0.68rem;
            font-weight: 800;
            letter-spacing: 0.16em;
            text-transform: uppercase;
        }}
        .fw-desk-title {{
            margin-top: 0.4rem;
            color: #f6fbff;
            font-size: 2rem;
            font-weight: 840;
            letter-spacing: -0.05em;
            line-height: 1;
        }}
        .fw-desk-copy {{
            margin-top: 0.5rem;
            max-width: 48rem;
            color: #8fa8bb;
            font-size: 0.96rem;
            line-height: 1.6;
        }}
        .fw-desk-status-stack {{
            display: flex;
            align-items: center;
            gap: 0.65rem;
            flex-wrap: wrap;
            justify-content: flex-end;
        }}
        .fw-desk-status-pill {{
            min-height: 2.55rem;
            padding: 0 0.95rem;
            display: inline-flex;
            align-items: center;
            gap: 0.58rem;
            border-radius: 999px;
            border: 1px solid rgba(119, 154, 186, 0.14);
            background: rgba(9, 18, 31, 0.86);
            color: #dce9f5;
            font-size: 0.82rem;
            font-weight: 760;
            white-space: nowrap;
        }}
        .fw-desk-status-pill-dot {{
            width: 0.54rem;
            height: 0.54rem;
            border-radius: 999px;
            background: #ffd166;
            box-shadow: 0 0 0 4px rgba(255, 209, 102, 0.14);
        }}
        .fw-desk-status-pill.is-live .fw-desk-status-pill-dot {{
            background: #2be9d1;
            box-shadow: 0 0 0 4px rgba(43, 233, 209, 0.14);
        }}
        .fw-desk-metric-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.82rem;
            margin-top: 1rem;
        }}
        .fw-desk-metric {{
            min-width: 0;
            padding: 0.95rem 0.98rem;
            border-radius: 1.08rem;
            border: 1px solid rgba(119, 154, 186, 0.12);
            background: rgba(8, 17, 29, 0.82);
        }}
        .fw-desk-metric-label {{
            color: #6f8ca2;
            font-size: 0.7rem;
            font-weight: 760;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }}
        .fw-desk-metric-value {{
            margin-top: 0.45rem;
            color: #f8fbff;
            font-size: 1.4rem;
            font-weight: 820;
            letter-spacing: -0.04em;
            line-height: 1;
        }}
        .fw-desk-metric-value.is-positive {{
            color: #2be9d1;
        }}
        .fw-desk-metric-value.is-negative {{
            color: #ff6b7d;
        }}
        .fw-desk-metric-meta {{
            margin-top: 0.34rem;
            color: #88a0b4;
            font-size: 0.8rem;
            line-height: 1.45;
        }}
        .fw-desk-section-head {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.8rem;
            margin-bottom: 0.7rem;
        }}
        .fw-desk-section-kicker {{
            color: #6f8ca2;
            font-size: 0.64rem;
            font-weight: 800;
            letter-spacing: 0.14em;
            text-transform: uppercase;
        }}
        .fw-desk-section-title {{
            color: #f6fbff;
            font-size: 1.08rem;
            font-weight: 800;
            letter-spacing: -0.03em;
            margin-top: 0.18rem;
        }}
        .fw-desk-section-meta {{
            color: #88a0b4;
            font-size: 0.8rem;
        }}
        @media (max-width: 1180px) {{
            .fw-desk-metric-grid {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }}
            .fw-desk-hero-top {{
                flex-direction: column;
            }}
            .fw-desk-status-stack {{
                justify-content: flex-start;
            }}
        }}
        </style>
        <div class="fw-desk-shell">
            <div class="fw-desk-hero">
                <div class="fw-desk-hero-top">
                    <div>
                        <div class="fw-desk-kicker">Signal Workspace</div>
                        <div class="fw-desk-title">Trade Desk Terminal</div>
                        <div class="fw-desk-copy">
                            Manage {escape(symbol)} across live charting, AI signal context, market depth, and execution readiness without leaving the desk.
                        </div>
                    </div>
                    <div class="fw-desk-status-stack">
                        <div class="fw-desk-status-pill {status_class}">
                            <span class="fw-desk-status-pill-dot"></span>
                            <span>{status_label}</span>
                        </div>
                        <div class="fw-desk-status-pill">
                            <span>{escape(tf_label)} workflow</span>
                        </div>
                        <div class="fw-desk-status-pill">
                            <span>Copilot layered</span>
                        </div>
                    </div>
                </div>
                <div class="fw-desk-metric-grid">
                    <div class="fw-desk-metric">
                        <div class="fw-desk-metric-label">Market</div>
                        <div class="fw-desk-metric-value">{escape(symbol)}</div>
                        <div class="fw-desk-metric-meta">Selected {'forex market' if forex_market else 'execution pair'}</div>
                    </div>
                    <div class="fw-desk-metric">
                        <div class="fw-desk-metric-label">Last Price</div>
                        <div class="fw-desk-metric-value">{escape(_desk_terminal_number(last_price, 2))}</div>
                        <div class="fw-desk-metric-meta">Mark-based desk anchor</div>
                    </div>
                    <div class="fw-desk-metric">
                        <div class="fw-desk-metric-label">24h Change</div>
                        <div class="fw-desk-metric-value {change_class}">{escape(_desk_terminal_percent(day_change))}</div>
                        <div class="fw-desk-metric-meta">Session pressure across the last day</div>
                    </div>
                    <div class="fw-desk-metric">
                        <div class="fw-desk-metric-label">{escape(flow_label)}</div>
                        <div class="fw-desk-metric-value">{escape(flow_value)}</div>
                        <div class="fw-desk-metric-meta">{escape(flow_meta)}</div>
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_standalone_market_shell(engine_live: bool) -> None:
    status_class = "is-live" if engine_live else "is-warming"
    status_label = "Live Feed" if engine_live else "Warming Up"
    st.markdown(
        f"""
        <style>
        .fw-market-shell {{
            max-width: 1240px;
            margin: 0 auto;
        }}
        [data-testid="stTextInput"] input,
        [data-baseweb="select"] > div,
        [data-testid="stTextInput"] > div > div,
        [data-baseweb="base-input"] {{
            min-height: 3rem !important;
            border-radius: 1rem !important;
            background: rgba(9, 17, 31, 0.76) !important;
            border: 1px solid rgba(255,255,255,0.07) !important;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.02) !important;
        }}
        [data-testid="stTextInput"] input {{
            color: #dfe9ff !important;
            font-size: 0.9rem !important;
        }}
        [data-testid="stTextInput"] input::placeholder {{
            color: rgba(129, 149, 180, 0.7) !important;
        }}
        [data-baseweb="select"] * {{
            color: #dfe9ff !important;
        }}
        [data-baseweb="popover"] {{
            background: rgba(11, 20, 37, 0.96) !important;
        }}
        [data-baseweb="popover"],
        [data-baseweb="popover"] > div,
        [data-baseweb="popover"] ul,
        [data-baseweb="popover"] li,
        [data-baseweb="popover"] [role="listbox"] {{
            background: rgba(11, 20, 37, 0.98) !important;
            color: #e7f5fb !important;
        }}
        [data-baseweb="popover"] [role="option"],
        [data-baseweb="popover"] [role="option"] * {{
            color: #e7f5fb !important;
            background: transparent !important;
        }}
        [data-baseweb="popover"] [role="option"]:hover,
        [data-baseweb="popover"] [role="option"][aria-selected="true"] {{
            background: rgba(100, 240, 209, 0.12) !important;
        }}
        [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] {{
            gap: 0.7rem !important;
        }}
        .fw-market-topbar {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            flex-wrap: wrap;
            margin-bottom: 1.1rem;
        }}
        .fw-market-topbar__brand {{
            display: flex;
            align-items: center;
            gap: 0.8rem;
            min-width: 0;
        }}
        .fw-market-topbar__logo {{
            width: 2.6rem;
            height: 2.6rem;
            border-radius: 0.9rem;
            display: grid;
            place-items: center;
            font-size: 1.05rem;
            font-weight: 800;
            color: #06212a;
            background: linear-gradient(135deg, #2ef1d3 0%, #34d8ff 100%);
            box-shadow: 0 10px 22px rgba(38, 221, 197, 0.28);
        }}
        .fw-market-topbar__title {{
            color: #f7fbff;
            font-size: 1.28rem;
            font-weight: 800;
            letter-spacing: -0.03em;
        }}
        .fw-market-topbar__actions {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}
        .fw-market-live-pill {{
            height: 2.9rem;
            padding: 0 1rem;
            display: inline-flex;
            align-items: center;
            gap: 0.65rem;
            border-radius: 999px;
            font-size: 0.85rem;
            font-weight: 700;
            letter-spacing: 0.01em;
            background: rgba(20, 34, 58, 0.86);
            border: 1px solid rgba(255,255,255,0.08);
            color: #ffd27d;
        }}
        .fw-market-live-pill.is-live {{
            color: #74ffe5;
        }}
        .fw-market-live-pill__dot {{
            width: 0.55rem;
            height: 0.55rem;
            border-radius: 999px;
            background: currentColor;
            box-shadow: 0 0 0 4px rgba(34, 240, 202, 0.12), 0 0 12px currentColor;
        }}
        .fw-market-heading {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 1rem;
        }}
        .fw-market-heading h1 {{
            margin: 0;
            font-size: 2.2rem;
            line-height: 1;
            letter-spacing: -0.05em;
            color: #f7fbff;
        }}
        .fw-market-heading p {{
            margin: 0.45rem 0 0;
            color: rgba(164, 182, 212, 0.82);
            font-size: 0.97rem;
            line-height: 1.55;
            max-width: 44rem;
        }}
        .fw-market-divider {{
            height: 1px;
            margin: 0.4rem 0 1rem;
            background: linear-gradient(90deg, rgba(255,255,255,0.08), rgba(255,255,255,0.03));
        }}
        @media (max-width: 980px) {{
            .fw-market-heading {{
                grid-template-columns: 1fr;
                display: grid;
            }}
            .fw-market-topbar__actions {{
                width: 100%;
                justify-content: flex-start;
            }}
            .fw-market-heading h1 {{
                font-size: 1.9rem;
            }}
        }}
        </style>
        <div class="fw-market-shell">
          <div class="fw-market-topbar">
            <div class="fw-market-topbar__brand">
              <div class="fw-market-topbar__logo">F</div>
              <div class="fw-market-topbar__title">Finwise AI</div>
            </div>
            <div class="fw-market-topbar__actions">
              <div class="fw-market-live-pill {status_class}">
                <span class="fw-market-live-pill__dot"></span>
                <span>{status_label}</span>
              </div>
            </div>
          </div>
          <div class="fw-market-heading">
            <div>
              <h1>Market Analysis</h1>
              <p>Live chart, depth, and execution levels for your selected market.</p>
            </div>
          </div>
          <div class="fw-market-divider"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_ai_page(
    username: str,
    *,
    embedded_in_trading_desk: bool,
    get_pair_universe,
    default_tracked_symbols,
    default_timeframes,
    load_trading_desk_panel_data,
    render_component_html,
    render_chart_panel_fragment,
    render_market_signal_sidebar,
    render_orderbook_terminal,
    render_market_analysis_overview,
    render_market_analysis_live_board,
    render_market_analysis_upgrade_banner,
    render_market_analysis_ticker_strip,
    coalesce_market_number,
    market_last_candle,
    fmt_price,
    fmt_pct,
    fmt_compact,
    base_asset_from_symbol,
    market_series,
    build_volume_bar_svg,
    snapshot_for_symbol,
    metric_series_for_symbol,
    trigger_ai_signal,
    signal_usage,
    engine_ready,
    engine_status,
    start_market_feed,
    render_fast_market_panel_fragment,
    render_market_analysis_summary,
    trade_style_options,
    default_trade_style,
    normalize_trade_style,
):
    pair_universe = get_pair_universe()
    default_symbol = st.session_state.get("market_analysis_pair_select", default_tracked_symbols[0]).upper()
    if default_symbol not in pair_universe:
        pair_universe = [default_symbol] + [pair for pair in pair_universe if pair != default_symbol]

    search_key = "market_analysis_pair_search"
    select_key = "market_analysis_pair_select"
    standalone_content_col = None

    if not embedded_in_trading_desk:
        _render_standalone_market_shell(bool(engine_status.get("ok")))
        outer_left, standalone_content_col, outer_right = st.columns([0.04, 0.92, 0.04], gap="small")

    if embedded_in_trading_desk:
        controls_parent = st.container(key="desktop_trade_controls")
    else:
        controls_parent = standalone_content_col if standalone_content_col is not None else st.container()
    with controls_parent:
        st.markdown('<div class="market-controls-strip"></div>', unsafe_allow_html=True)
        search_col, pair_col, tf_col, style_col = st.columns([1.24, 0.84, 1.04, 0.92], gap="small")
        with search_col:
            st.markdown('<div class="market-control-label">Search Market</div>', unsafe_allow_html=True)
            search_query = st.text_input(
                "Search pair",
                value=st.session_state.get(search_key, ""),
                placeholder=f"Search {len(pair_universe)} markets (BTC, EURUSD, USDJPY...)",
                key=search_key,
                label_visibility="collapsed",
            ).strip().upper()

    filtered_pairs = [pair for pair in pair_universe if search_query in pair] if search_query else pair_universe
    if not filtered_pairs:
        filtered_pairs = pair_universe

    current_symbol = st.session_state.get(select_key, default_symbol)
    if current_symbol not in filtered_pairs:
        current_symbol = filtered_pairs[0]

    with pair_col:
        st.markdown('<div class="market-control-label">Market</div>', unsafe_allow_html=True)
        symbol = st.selectbox(
            "Trading pair",
            filtered_pairs[:160],
            index=filtered_pairs[:160].index(current_symbol) if current_symbol in filtered_pairs[:160] else 0,
            key=select_key,
            label_visibility="collapsed",
        )

    with tf_col:
        st.markdown('<div class="market-control-label">Timeframe</div>', unsafe_allow_html=True)
        default_tf = st.session_state.get("market_analysis_tf_control", st.session_state.get("market_analysis_tf_radio", default_timeframes[0]))
        tf_label = _render_dark_button_group(
            scope_key="desktop_market_timeframe_group",
            options=default_timeframes,
            current_value=default_tf if default_tf in default_timeframes else default_timeframes[0],
            max_columns=4,
        )
        if not tf_label:
            tf_label = default_timeframes[0]
        st.session_state.market_analysis_tf_control = tf_label
        st.session_state.market_analysis_tf_radio = tf_label

    style_choices = [option["value"] for option in trade_style_options]
    style_labels = {option["value"]: option["label"] for option in trade_style_options}
    style_descriptions = {option["value"]: option["description"] for option in trade_style_options}
    current_trade_style = normalize_trade_style(st.session_state.get("trade_style_preference", default_trade_style))
    if current_trade_style not in style_choices:
        current_trade_style = default_trade_style
    with style_col:
        st.markdown('<div class="market-control-label">Trading Style</div>', unsafe_allow_html=True)
        selected_trade_style = st.selectbox(
            "Trading style",
            style_choices,
            index=style_choices.index(current_trade_style),
            key="trade_style_preference",
            format_func=lambda value: style_labels.get(value, value.replace("_", " ").title()),
            label_visibility="collapsed",
        )
        st.caption(style_descriptions.get(selected_trade_style, ""))

    if not embedded_in_trading_desk:
        desk_df, desk_snapshot, desk_orderbook = load_trading_desk_panel_data(symbol, tf_label)

        if engine_ready.is_set() and not engine_status.get("ok") and (desk_df is None or desk_df.empty):
            st.warning(engine_status.get("message", "Live market feed is warming up."))
            if st.button("Retry Market Feed", use_container_width=True):
                start_market_feed(force_refresh=True)
                st.rerun()
            return

        with standalone_content_col:
            render_market_analysis_summary(symbol, tf_label, desk_snapshot, desk_df)
            render_chart_panel_fragment(symbol, tf_label, desk_df)
            render_market_analysis_chart_tools()
            render_market_analysis_overview(symbol, tf_label, desk_snapshot, desk_df)
            render_orderbook_terminal(desk_orderbook)
            render_market_signal_sidebar(
                username,
                symbol,
                tf_label,
                desk_df,
                cta_mode="open_trade_desk",
            )
            render_market_analysis_upgrade_banner(username, show_action=False)
            render_market_analysis_ticker_strip(symbol)
        return

    quick_load_context_key = f"{symbol}|{tf_label}|{selected_trade_style}"
    previous_quick_load_context_key = st.session_state.get("desktop_trade_quick_load_context_key")
    if previous_quick_load_context_key != quick_load_context_key:
        st.session_state.desktop_trade_quick_load_context_key = quick_load_context_key
        st.session_state.desktop_trade_full_workspace_loaded = True

    full_workspace_loaded = bool(st.session_state.get("desktop_trade_full_workspace_loaded", True))
    desk_df, desk_snapshot, desk_orderbook = load_trading_desk_panel_data(
        symbol,
        tf_label,
        allow_blocking_refresh=full_workspace_loaded,
    )

    if full_workspace_loaded and engine_ready.is_set() and not engine_status.get("ok") and (desk_df is None or desk_df.empty):
        st.warning(engine_status.get("message", "Live market feed is warming up."))
        if st.button("Retry Market Feed", use_container_width=True):
            start_market_feed(force_refresh=True)
            st.rerun()
        return

    with st.container(key="desktop_trade_surface"):
        _render_desktop_trade_desk_frame(
            symbol=symbol,
            tf_label=tf_label,
            snapshot=desk_snapshot,
            df=desk_df,
            engine_live=bool(engine_status.get("ok")),
        )
        render_market_analysis_summary(symbol, tf_label, desk_snapshot, desk_df)

        chart_col, side_col = st.columns([1.62, 0.92], gap="large")
        with chart_col:
            with st.container(key="desktop_trade_chart_stage"):
                st.markdown(
                    """
                    <div class="fw-desk-section-head">
                        <div>
                            <div class="fw-desk-section-kicker">Chart Stage</div>
                            <div class="fw-desk-section-title">Execution chart and structure</div>
                        </div>
                        <div class="fw-desk-section-meta">Live candles, overlays, and active context</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                render_chart_panel_fragment(
                    symbol,
                    tf_label,
                    desk_df,
                    allow_blocking_refresh=False,
                    allow_depth_refresh=False,
                )
            with st.container(key="desktop_trade_overview_stage"):
                st.markdown(
                    """
                    <div class="fw-desk-section-head">
                        <div>
                            <div class="fw-desk-section-kicker">Overview Grid</div>
                            <div class="fw-desk-section-title">Key market levels</div>
                        </div>
                        <div class="fw-desk-section-meta">High, low, funding, open interest, and session state</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                render_market_analysis_overview(symbol, tf_label, desk_snapshot, desk_df)
            with st.container(key="desktop_trade_flow_stage"):
                st.markdown(
                    """
                    <div class="fw-desk-section-head">
                        <div>
                            <div class="fw-desk-section-kicker">Flow Board</div>
                            <div class="fw-desk-section-title">Market pressure and live board</div>
                        </div>
                        <div class="fw-desk-section-meta">Momentum, volume, mark, and session flow cards</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                render_market_analysis_live_board(symbol, tf_label, desk_snapshot, desk_df)
        with side_col:
            with st.container(key="desktop_trade_signal_stage"):
                st.markdown(
                    """
                    <div class="fw-desk-section-head">
                        <div>
                            <div class="fw-desk-section-kicker">Signal Rail</div>
                            <div class="fw-desk-section-title">AI signal and execution context</div>
                        </div>
                        <div class="fw-desk-section-meta">Live signal, route quality, and broker execution cues</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                render_fast_market_panel_fragment(username, symbol, tf_label, desk_df, desk_orderbook)
            with st.container(key="desktop_trade_depth_stage"):
                st.markdown(
                    """
                    <div class="fw-desk-section-head">
                        <div>
                            <div class="fw-desk-section-kicker">Depth Board</div>
                            <div class="fw-desk-section-title">Order book and bid-ask pressure</div>
                        </div>
                        <div class="fw-desk-section-meta">Live ladder, spread, and depth imbalance for the active market</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                render_orderbook_terminal(desk_orderbook)
            with st.container(key="desktop_trade_tools_stage"):
                st.markdown(
                    """
                    <div class="fw-desk-section-head">
                        <div>
                            <div class="fw-desk-section-kicker">Overlay Controls</div>
                            <div class="fw-desk-section-title">Indicator and chart settings</div>
                        </div>
                        <div class="fw-desk-section-meta">Fine-tune the chart without leaving the desk</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                render_market_analysis_chart_tools()

    render_copilot_drawer(
        username=username,
        context={
            "broker_name": (
                getattr(st.session_state.get("auto_trade_broker"), "name", "")
                or str((st.session_state.get("manual_broker_profile") or {}).get("broker_name") or "Finwise")
            ),
            "connection_method": st.session_state.get(
                "auto_trade_connection_method",
                "profile" if st.session_state.get("manual_broker_profile") else "not_connected",
            ),
            "balance": float((st.session_state.get("manual_broker_profile") or {}).get("balance", 10000.0) or 10000.0),
            "total_trades": (
                st.session_state.get("auto_trade_bot").get_performance().get("total_trades", 0)
                if st.session_state.get("auto_trade_bot") is not None
                else 0
            ),
            "drawdown": (
                st.session_state.get("auto_trade_bot").get_performance().get("current_drawdown", 0)
                if st.session_state.get("auto_trade_bot") is not None
                else 0
            ),
            "status_text": st.session_state.get("auto_trade_status", ""),
            "signal": (_matching_signal_payload(symbol, tf_label)[0]),
            "signal_meta": (_matching_signal_payload(symbol, tf_label)[1] or {"symbol": symbol, "tf_label": tf_label}),
            "preview": (
                {}
                if (
                    (st.session_state.get("auto_trade_preview_report") or {}).get("broker_key")
                    and (st.session_state.get("auto_trade_preview_report") or {}).get("broker_key")
                    != (
                        getattr(st.session_state.get("auto_trade_broker"), "name", "")
                        or str((st.session_state.get("manual_broker_profile") or {}).get("broker_name") or "Finwise")
                    )
                )
                else (st.session_state.get("auto_trade_preview_report") or {})
            ),
            "connector": (
                {}
                if (
                    (st.session_state.get("broker_connector_test_report") or {}).get("broker_key")
                    and (st.session_state.get("broker_connector_test_report") or {}).get("broker_key")
                    != (
                        getattr(st.session_state.get("auto_trade_broker"), "name", "")
                        or str((st.session_state.get("manual_broker_profile") or {}).get("broker_name") or "Finwise")
                    )
                )
                else (st.session_state.get("broker_connector_test_report") or {})
            ),
            "execution": (
                {}
                if (
                    (st.session_state.get("last_auto_trade_execution") or {}).get("broker_key")
                    and (st.session_state.get("last_auto_trade_execution") or {}).get("broker_key")
                    != (
                        getattr(st.session_state.get("auto_trade_broker"), "name", "")
                        or str((st.session_state.get("manual_broker_profile") or {}).get("broker_name") or "Finwise")
                    )
                )
                else (st.session_state.get("last_auto_trade_execution") or {})
            ),
            "bot_thresholds": {
                "min_confidence": getattr(getattr(st.session_state.get("auto_trade_bot"), "config", None), "min_confidence_percent", 0),
                "min_rr": getattr(getattr(st.session_state.get("auto_trade_bot"), "config", None), "min_risk_reward_ratio", 0),
                "min_edge": getattr(getattr(st.session_state.get("auto_trade_bot"), "config", None), "min_projected_profit_percent", 0),
                "growth_goal": getattr(getattr(st.session_state.get("auto_trade_bot"), "config", None), "account_growth_goal_percent", 0),
            },
        },
        scope="trade",
        state_key="trading_desk_copilot_open",
    )

    render_market_analysis_upgrade_banner(username, show_action=False)
    render_market_analysis_ticker_strip(symbol)


def render_mobile_market_analysis_page(
    username: str,
    *,
    get_pair_universe,
    default_tracked_symbols,
    default_timeframes,
    load_trading_desk_panel_data,
    render_chart_panel_fragment,
    render_market_signal_sidebar,
    render_orderbook_terminal,
    render_market_analysis_overview,
    render_market_analysis_upgrade_banner,
    render_market_analysis_ticker_strip,
    engine_ready,
    engine_status,
    start_market_feed,
    render_market_analysis_summary,
    render_market_analysis_chart_tools,
    show_upgrade_banner: bool = True,
    show_ticker_strip: bool = True,
    panel_state_key: str = "mobile_market_analysis_panel",
    default_panel: str = "Chart",
    panel_query_key: str = "mmarketpanel",
    show_search: bool = True,
    controls_title: str = "Market Setup",
    workspace_kicker: str = "Market Analysis",
    workspace_title: str = "Chart, signal preview, depth, and market stats",
    workspace_meta_template: str = "{symbol} | {tf_label} | review the live market surface or jump into Trade Desk for AI routing.",
    signal_cta_mode: str = "open_trade_desk",
    trade_style_options=None,
    default_trade_style: str = "day_trade",
    normalize_trade_style=lambda value: value,
):
    st.markdown(
        """
        <style>
        .fw-mobile-control-label {
            color: #6d7892;
            font-size: 0.64rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin: 0.1rem 0 0.38rem;
        }
        .st-key-mobile_market_controls {
            margin-bottom: 0.6rem;
            padding: 0.88rem 0.92rem 0.94rem;
            border-radius: 1.08rem;
            border: 1px solid rgba(255,255,255,0.06);
            background:
                radial-gradient(circle at top right, rgba(34,231,202,0.08), transparent 28%),
                linear-gradient(180deg, rgba(14,23,36,0.96), rgba(9,17,29,0.98));
            box-shadow: 0 16px 34px rgba(0,0,0,0.16);
        }
        .fw-mobile-market-setup-head {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.7rem;
            margin-bottom: 0.62rem;
        }
        .fw-mobile-market-setup-kicker {
            color: #7fece0;
            font-size: 0.58rem;
            font-weight: 850;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }
        .fw-mobile-market-setup-title {
            color: #f7fbff;
            font-size: 0.9rem;
            font-weight: 850;
            letter-spacing: -0.02em;
            margin-top: 0.18rem;
        }
        .fw-mobile-market-setup-meta {
            color: #88a0b8;
            font-size: 0.64rem;
            line-height: 1.45;
            margin-top: 0.18rem;
        }
        .fw-mobile-market-setup-badge {
            padding: 0.3rem 0.54rem;
            border-radius: 999px;
            border: 1px solid rgba(34,231,202,0.16);
            background: rgba(34,231,202,0.08);
            color: #dffff8;
            font-size: 0.58rem;
            font-weight: 800;
            white-space: nowrap;
        }
        .fw-mobile-workspace-head {
            margin: 0.22rem 0 0.12rem;
        }
        .fw-mobile-workspace-kicker {
            color: #7d90aa;
            font-size: 0.56rem;
            font-weight: 850;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }
        .fw-mobile-workspace-title {
            color: #f5fbff;
            font-size: 0.92rem;
            font-weight: 850;
            letter-spacing: -0.02em;
            margin-top: 0.18rem;
        }
        .fw-mobile-workspace-meta {
            color: #88a0b8;
            font-size: 0.64rem;
            line-height: 1.45;
            margin-top: 0.16rem;
        }
        .st-key-mobile_market_controls [data-testid="stTextInput"] input,
        .st-key-mobile_market_controls [data-baseweb="select"] > div,
        .st-key-mobile_market_controls [data-testid="stTextInput"] > div > div,
        .st-key-mobile_market_controls [data-baseweb="base-input"] {
            min-height: 3rem !important;
            border-radius: 1rem !important;
            background: rgba(16, 23, 35, 0.82) !important;
            border: 1px solid rgba(255,255,255,0.06) !important;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.03), 0 16px 34px rgba(0,0,0,0.14) !important;
        }
        .st-key-mobile_market_controls [data-testid="stTextInput"] input {
            color: #eef6ff !important;
            font-size: 0.84rem !important;
        }
        .st-key-mobile_market_controls [data-testid="stTextInput"] input::placeholder {
            color: rgba(132, 148, 176, 0.72) !important;
        }
        .st-key-mobile_market_controls [data-baseweb="select"] * {
            color: #eef6ff !important;
        }
        [data-baseweb="popover"],
        [data-baseweb="popover"] > div,
        [data-baseweb="popover"] ul,
        [data-baseweb="popover"] li,
        [data-baseweb="popover"] [role="listbox"] {
            background: rgba(12, 22, 35, 0.98) !important;
            color: #eef6ff !important;
        }
        [data-baseweb="popover"] [role="option"],
        [data-baseweb="popover"] [role="option"] * {
            color: #eef6ff !important;
            background: transparent !important;
        }
        [data-baseweb="popover"] [role="option"]:hover,
        [data-baseweb="popover"] [role="option"][aria-selected="true"] {
            background: rgba(100, 240, 209, 0.12) !important;
        }
        .st-key-mobile_market_controls [data-testid="stHorizontalBlock"] {
            gap: 0.72rem !important;
            align-items: end !important;
        }
        .st-key-mobile_market_tools summary {
            color: #d8e8ff !important;
            font-weight: 700 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    pair_universe = get_pair_universe()
    default_symbol = st.session_state.get("market_analysis_pair_select", default_tracked_symbols[0]).upper()
    if default_symbol not in pair_universe:
        pair_universe = [default_symbol] + [pair for pair in pair_universe if pair != default_symbol]

    search_key = "mobile_market_analysis_pair_search"
    select_key = "market_analysis_pair_select"

    with st.container(key="mobile_market_controls"):
        current_symbol = st.session_state.get(select_key, default_symbol)
        st.markdown(
            f"""
            <div class="fw-mobile-market-setup-head">
                <div>
                    <div class="fw-mobile-market-setup-kicker">{controls_title}</div>
                    <div class="fw-mobile-market-setup-title">{escape(current_symbol)} Workspace</div>
                    <div class="fw-mobile-market-setup-meta">Select the active pair and timeframe for this desk view.</div>
                </div>
                <div class="fw-mobile-market-setup-badge">Live Feed</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        search_query = ""
        if show_search:
            st.markdown('<div class="fw-mobile-control-label">Search Market</div>', unsafe_allow_html=True)
            search_query = st.text_input(
                "Search pair",
                value=st.session_state.get(search_key, ""),
                placeholder=f"Search {len(pair_universe)} markets (BTC, EURUSD, USDJPY...)",
                key=search_key,
                label_visibility="collapsed",
            ).strip().upper()

        filtered_pairs = [pair for pair in pair_universe if search_query in pair] if search_query else pair_universe
        if not filtered_pairs:
            filtered_pairs = pair_universe

        current_symbol = st.session_state.get(select_key, default_symbol)
        if current_symbol not in filtered_pairs:
            current_symbol = filtered_pairs[0]

        pair_col, tf_col = st.columns([1.05, 1.25], gap="small")
        with pair_col:
            st.markdown('<div class="fw-mobile-control-label">Market</div>', unsafe_allow_html=True)
            symbol = st.selectbox(
                "Trading pair",
                filtered_pairs[:160],
                index=filtered_pairs[:160].index(current_symbol) if current_symbol in filtered_pairs[:160] else 0,
                key=select_key,
                label_visibility="collapsed",
            )

        with tf_col:
            st.markdown('<div class="fw-mobile-control-label">Timeframe</div>', unsafe_allow_html=True)
            default_tf = st.session_state.get(
                "market_analysis_tf_control",
                st.session_state.get("market_analysis_tf_radio", default_timeframes[0]),
            )
            mobile_timeframes = list(default_timeframes) or [default_tf]
            tf_label = resolve_query_value(
                "mtf",
                default=default_tf if default_tf in mobile_timeframes else mobile_timeframes[0],
                allowed=mobile_timeframes,
                session_key="market_analysis_tf_control",
            )
            tf_label = render_mobile_link_tabs(
                options=mobile_timeframes,
                current_value=tf_label,
                query_key="mtf",
                variant="pill",
            )
            st.session_state.market_analysis_tf_control = tf_label
            st.session_state.market_analysis_tf_radio = tf_label

        style_choices = [option["value"] for option in (trade_style_options or [])]
        style_labels = {option["value"]: option["label"] for option in (trade_style_options or [])}
        style_descriptions = {option["value"]: option["description"] for option in (trade_style_options or [])}
        current_trade_style = normalize_trade_style(st.session_state.get("trade_style_preference", default_trade_style))
        if current_trade_style not in style_choices and style_choices:
            current_trade_style = style_choices[0]
        if style_choices:
            st.markdown('<div class="fw-mobile-control-label">Trading Style</div>', unsafe_allow_html=True)
            selected_trade_style = st.selectbox(
                "Trading style",
                style_choices,
                index=style_choices.index(current_trade_style),
                key="trade_style_preference",
                format_func=lambda value: style_labels.get(value, value.replace("_", " ").title()),
                label_visibility="collapsed",
            )
            st.caption(style_descriptions.get(selected_trade_style, ""))

    symbol = st.session_state.get(select_key, default_symbol)
    tf_label = st.session_state.get("market_analysis_tf_control", st.session_state.get("market_analysis_tf_radio", default_timeframes[0]))

    desk_df, desk_snapshot, desk_orderbook = load_trading_desk_panel_data(symbol, tf_label)

    if engine_ready.is_set() and not engine_status.get("ok") and (desk_df is None or desk_df.empty):
        st.warning(engine_status.get("message", "Live market feed is warming up."))
        if st.button("Retry Market Feed", key="mobile_retry_market_feed", use_container_width=True):
            start_market_feed(force_refresh=True)
            st.rerun()
        return

    current_panel = st.session_state.get(panel_state_key, default_panel)
    market_panel = resolve_query_value(
        panel_query_key,
        default=current_panel if current_panel in {"Chart", "Signal", "Depth", "Stats"} else default_panel,
        allowed=["Chart", "Signal", "Depth", "Stats"],
        session_key=panel_state_key,
    )
    workspace_meta = workspace_meta_template.format(symbol=symbol, tf_label=tf_label)
    st.markdown(
        f"""
        <div class="fw-mobile-workspace-head">
            <div class="fw-mobile-workspace-kicker">{escape(workspace_kicker)}</div>
            <div class="fw-mobile-workspace-title">{escape(workspace_title)}</div>
            <div class="fw-mobile-workspace-meta">{escape(workspace_meta)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_market_analysis_summary(symbol, tf_label, desk_snapshot, desk_df, mobile_layout=True)
    market_panel = render_mobile_link_tabs(
        options=["Chart", "Signal", "Depth", "Stats"],
        current_value=market_panel,
        query_key=panel_query_key,
        variant="rail",
    )

    if market_panel == "Chart":
        render_mobile_chart_toolbar(
            current_timeframe=tf_label,
            timeframe_options=mobile_timeframes,
            timeframe_query_key="mtf",
        )
        render_chart_panel_fragment(symbol, tf_label, desk_df, compact_layout=True)
    elif market_panel == "Signal":
        render_market_signal_sidebar(
            username,
            symbol,
            tf_label,
            desk_df,
            cta_mode=signal_cta_mode,
            mobile_target=True,
        )
    elif market_panel == "Depth":
        render_orderbook_terminal(desk_orderbook)
    else:
        render_market_analysis_overview(symbol, tf_label, desk_snapshot, desk_df, mobile_layout=True)
        if show_ticker_strip:
            render_market_analysis_ticker_strip(symbol, mobile_layout=True)

    if show_upgrade_banner and market_panel in {"Signal", "Stats"}:
        render_market_analysis_upgrade_banner(username, show_action=True, mobile_layout=True)


def render_mobile_trading_desk_page(
    username: str,
    premium: bool,
    *,
    auto_trade_page,
    render_synthetic_trade_page_fn=None,
    get_pair_universe,
    default_tracked_symbols,
    default_timeframes,
    load_trading_desk_panel_data,
    render_chart_panel_fragment,
    render_market_signal_sidebar,
    render_orderbook_terminal,
    render_market_analysis_overview,
    render_market_analysis_upgrade_banner,
    render_market_analysis_ticker_strip,
    engine_ready,
    engine_status,
    start_market_feed,
    render_market_analysis_summary,
    render_market_analysis_chart_tools,
    trade_style_options,
    default_trade_style,
    normalize_trade_style,
):
    open_broker_first = st.session_state.pop("open_broker_execution", False)
    if open_broker_first:
        st.session_state.trading_desk_view = "Broker & Execution"
        st.query_params["mdeskmode"] = "Broker & Execution"

    desk_options = ["Signal Workspace", "Broker & Execution", "Synthetic Trade"]
    desk_view_default = st.session_state.get("trading_desk_view", "Signal Workspace")
    if desk_view_default not in set(desk_options):
        desk_view_default = "Signal Workspace"

    st.markdown('<div class="fw-mobile-control-label">Desk Mode</div>', unsafe_allow_html=True)
    desk_view = resolve_query_value(
        "mdeskmode",
        default=desk_view_default,
        allowed=desk_options,
        session_key="trading_desk_view",
    )
    desk_view = render_mobile_link_tabs(
        options=desk_options,
        current_value=desk_view,
        query_key="mdeskmode",
        labels={
            "Signal Workspace": "Signals",
            "Broker & Execution": "Broker",
            "Synthetic Trade": "Synthetic",
        },
        layout="scroll",
    )
    st.session_state.trading_desk_view = desk_view or desk_view_default

    if st.session_state.trading_desk_view == "Broker & Execution":
        auto_trade_page(username, premium)
        render_market_analysis_upgrade_banner(username, show_action=not premium)
        return
    if st.session_state.trading_desk_view == "Synthetic Trade":
        if render_synthetic_trade_page_fn is None:
            st.error("Synthetic Trade is unavailable because the Deriv trading workspace did not load.")
            return
        try:
            render_synthetic_trade_page_fn(username, mobile_layout=True)
        except TypeError:
            render_synthetic_trade_page_fn(username)
        return

    render_mobile_market_analysis_page(
        username,
        get_pair_universe=get_pair_universe,
        default_tracked_symbols=default_tracked_symbols,
        default_timeframes=default_timeframes,
        load_trading_desk_panel_data=load_trading_desk_panel_data,
        render_chart_panel_fragment=render_chart_panel_fragment,
        render_market_signal_sidebar=render_market_signal_sidebar,
        render_orderbook_terminal=render_orderbook_terminal,
        render_market_analysis_overview=render_market_analysis_overview,
        render_market_analysis_upgrade_banner=render_market_analysis_upgrade_banner,
        render_market_analysis_ticker_strip=render_market_analysis_ticker_strip,
        engine_ready=engine_ready,
        engine_status=engine_status,
        start_market_feed=start_market_feed,
        render_market_analysis_summary=render_market_analysis_summary,
        render_market_analysis_chart_tools=render_market_analysis_chart_tools,
        show_upgrade_banner=False,
        show_ticker_strip=False,
        panel_state_key="mobile_trading_desk_panel",
        default_panel="Signal",
        panel_query_key="mdeskpanel",
        show_search=False,
        controls_title="Trade Desk Setup",
        workspace_kicker="Trade Desk",
        workspace_title="Signal, execution, and routing",
        workspace_meta_template="{symbol} | {tf_label} | generate the AI signal here, then move into broker execution when you're ready.",
        signal_cta_mode="generate",
        trade_style_options=trade_style_options,
        default_trade_style=default_trade_style,
        normalize_trade_style=normalize_trade_style,
    )

def render_desktop_trading_desk_page(
    username: str,
    premium: bool,
    *,
    render_ai_page_fn,
    auto_trade_page,
    render_synthetic_trade_page_fn=None,
):
    open_broker_first = st.session_state.pop("open_broker_execution", False)
    if open_broker_first:
        st.session_state.trading_desk_view = "Broker & Execution"
        st.query_params["mdeskmode"] = "Broker & Execution"

    desk_options = ["Signal Workspace", "Broker & Execution", "Synthetic Trade"]
    desk_view_default = st.session_state.get("trading_desk_view", "Signal Workspace")
    if desk_view_default not in set(desk_options):
        desk_view_default = "Signal Workspace"

    desk_view = _render_top_right_desk_switcher(
        options=desk_options,
        current_value=desk_view_default,
        labels={
            "Signal Workspace": "Signal Workspace",
            "Broker & Execution": "Broker & Execution",
            "Synthetic Trade": "Synthetic Trade",
        },
    )
    st.session_state.trading_desk_view = desk_view or desk_view_default

    if st.session_state.trading_desk_view == "Broker & Execution":
        auto_trade_page(username, premium)
    elif st.session_state.trading_desk_view == "Synthetic Trade":
        if render_synthetic_trade_page_fn is None:
            st.error("Synthetic Trade is unavailable because the Deriv trading workspace did not load.")
            return
        try:
            render_synthetic_trade_page_fn(username, mobile_layout=False)
        except TypeError:
            render_synthetic_trade_page_fn(username)
    else:
        render_ai_page_fn(username, embedded_in_trading_desk=True)
