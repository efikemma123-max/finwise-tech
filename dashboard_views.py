from html import escape
from textwrap import dedent
from uuid import uuid4

import pandas as pd
import streamlit as st
from mobile_ui_helpers import render_mobile_link_tabs, resolve_query_value


def _metric_tone(value: float) -> tuple[str, str]:
    return ("#2df4a4", "rgba(45,244,164,0.12)") if value >= 0 else ("#ff6a72", "rgba(255,106,114,0.12)")


def _dashboard_kpi_card(label: str, value: str, detail: str, *, tone: str = "#2df4cc", bg: str = "rgba(45,244,204,0.10)") -> str:
    return dedent(
        f"""
        <section class="fw-dash-kpi">
            <div class="fw-dash-kpi__top">
                <span class="fw-dash-kpi__label">{escape(label)}</span>
                <span class="fw-dash-kpi__dot" style="background:{tone};box-shadow:0 0 16px {tone};"></span>
            </div>
            <div class="fw-dash-kpi__value" style="color:{tone};background:{bg};">{escape(value)}</div>
            <div class="fw-dash-kpi__detail">{escape(detail)}</div>
        </section>
        """
    ).strip()


def render_dashboard_page(
    username: str,
    *,
    build_trade_metrics,
    get_used,
    is_premium,
    get_limit,
    default_tracked_symbols,
    engine,
    ensure_symbol_loaded,
    fmt_price,
    fmt_pct,
    dashboard_broker_snapshot,
    dashboard_coach_cards,
    dashboard_insights,
    dashboard_recent_activity_feed,
    classify_session,
):
    metrics, trade_df, closed_df = build_trade_metrics(username)
    open_df = trade_df[trade_df["status"].isin(["open", "executed"])].copy() if not trade_df.empty else trade_df
    recent_df = trade_df.head(6).copy() if not trade_df.empty else trade_df
    today_tone, today_bg = _metric_tone(float(metrics.get("today_net", 0.0) or 0.0))
    lifetime_tone, lifetime_bg = _metric_tone(float(metrics.get("lifetime_net", 0.0) or 0.0))
    avg_loss_tone, avg_loss_bg = _metric_tone(-abs(float(metrics.get("avg_loss", 0.0) or 0.0)))
    used_today = str(get_used(username))
    signal_limit = "unlimited" if is_premium(username) else str(get_limit(username))
    broker_snapshot = dashboard_broker_snapshot()
    kpi_cards = [
        ("Today P&L", f"${metrics['today_net']:,.2f}", "Net movement from today's closed and active journal entries.", today_tone, today_bg),
        ("Lifetime P&L", f"${metrics['lifetime_net']:,.2f}", f"{metrics['lifetime_trades']} closed trades tracked.", lifetime_tone, lifetime_bg),
        ("Open Trades", str(int(len(open_df)) if not open_df.empty else 0), "Open or executed positions still being monitored.", "#5cf1ff", "rgba(92,241,255,0.10)"),
        ("Win Rate", f"{metrics['win_rate']:.1f}%", f"Avg win ${metrics['avg_win']:,.2f} · Avg loss ${metrics['avg_loss']:,.2f}", "#2df4cc", "rgba(45,244,204,0.10)"),
        ("Closed Trades", str(metrics["lifetime_trades"]), "Total completed trades in the journal.", "#c7d7ff", "rgba(122,150,255,0.10)"),
        ("Avg Win", f"${metrics['avg_win']:,.2f}", "Mean profit on winning trades.", "#2df4a4", "rgba(45,244,164,0.10)"),
        ("Avg Loss", f"${metrics['avg_loss']:,.2f}", "Mean result on losing trades.", avg_loss_tone, avg_loss_bg),
        ("Signals Today", f"{used_today} / {signal_limit}", "Daily signal usage for this account tier.", "#37eadb", "rgba(55,234,219,0.10)"),
    ]
    if broker_snapshot["broker_name"] == "Deriv" and broker_snapshot["broker_status"] != "No broker connected":
        kpi_cards.insert(
            0,
            (
                "Deriv Balance",
                broker_snapshot["balance_text"],
                f"{broker_snapshot['connection_method']} | {broker_snapshot['sync_state']} sync.",
                "#37eadb",
                "rgba(55,234,219,0.10)",
            ),
        )
    dashboard_shell_html = dedent(
        """
        <style>
        .fw-dashboard-shell {
            display: grid;
            gap: 1rem;
            margin-bottom: 1.2rem;
        }
        .fw-dashboard-hero {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 1rem;
            align-items: end;
            padding: 1.1rem 1.18rem;
            border: 1px solid rgba(255,255,255,0.065);
            border-radius: 1.1rem;
            background:
                radial-gradient(circle at 10% 0%, rgba(25,223,208,0.12), transparent 34%),
                linear-gradient(180deg, rgba(12,28,43,0.96), rgba(7,17,29,0.98));
            box-shadow: 0 20px 42px rgba(0,0,0,0.2);
        }
        .fw-dashboard-hero__kicker {
            color: #37eadb;
            font-size: 0.68rem;
            font-weight: 850;
            letter-spacing: 0.09em;
            text-transform: uppercase;
        }
        .fw-dashboard-hero__title {
            color: #f5fbff;
            font-size: 1.28rem;
            font-weight: 850;
            margin-top: 0.32rem;
        }
        .fw-dashboard-hero__copy {
            color: #8ea6bc;
            font-size: 0.82rem;
            line-height: 1.55;
            margin-top: 0.36rem;
        }
        .fw-dashboard-hero__pill {
            color: #dffffb;
            border: 1px solid rgba(74,245,230,0.18);
            background: rgba(24,223,208,0.09);
            border-radius: 999px;
            padding: 0.48rem 0.7rem;
            font-size: 0.72rem;
            font-weight: 800;
            white-space: nowrap;
        }
        .fw-dash-kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.74rem;
        }
        .fw-dash-kpi {
            min-height: 8.2rem;
            padding: 0.9rem;
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 1rem;
            background: linear-gradient(180deg, rgba(13,27,41,0.96), rgba(8,18,30,0.98));
            box-shadow: 0 16px 34px rgba(0,0,0,0.18);
        }
        .fw-dash-kpi__top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.6rem;
        }
        .fw-dash-kpi__label {
            color: #8fa8bd;
            font-size: 0.68rem;
            font-weight: 850;
            text-transform: uppercase;
            letter-spacing: 0.07em;
        }
        .fw-dash-kpi__dot {
            width: 0.42rem;
            height: 0.42rem;
            border-radius: 999px;
            flex: 0 0 auto;
        }
        .fw-dash-kpi__value {
            display: inline-flex;
            align-items: center;
            max-width: 100%;
            margin-top: 0.88rem;
            border-radius: 0.8rem;
            padding: 0.42rem 0.58rem;
            font-size: 1.42rem;
            font-weight: 900;
            line-height: 1.05;
            overflow-wrap: anywhere;
        }
        .fw-dash-kpi__detail {
            color: #7893aa;
            font-size: 0.74rem;
            line-height: 1.45;
            margin-top: 0.72rem;
        }
        @media (max-width: 980px) {
            .fw-dash-kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 640px) {
            .fw-dashboard-hero { grid-template-columns: 1fr; align-items: start; }
            .fw-dash-kpi-grid { grid-template-columns: 1fr; }
            .fw-dash-kpi { min-height: auto; }
            .fw-dash-kpi__value { font-size: 1.28rem; }
        }
        </style>
        <div class="fw-dashboard-shell">
            <section class="fw-dashboard-hero">
                <div>
                    <div class="fw-dashboard-hero__kicker">Workspace Pulse</div>
                    <div class="fw-dashboard-hero__title">Trading performance, live markets, and execution context.</div>
                    <div class="fw-dashboard-hero__copy">A compact overview of today's P&L, lifetime performance, broker readiness, and the signals flowing through Finwise.</div>
                </div>
                <div class="fw-dashboard-hero__pill">__SIGNAL_USAGE__ signals today</div>
            </section>
        </div>
        """
    ).strip()
    st.markdown(
        dashboard_shell_html
        .replace("__SIGNAL_USAGE__", escape(f"{used_today} / {signal_limit}")),
        unsafe_allow_html=True,
    )
    for start in range(0, len(kpi_cards), 4):
        row_cards = kpi_cards[start:start + 4]
        row_cols = st.columns(len(row_cards), gap="small")
        for col, (label, value, detail, tone, bg) in zip(row_cols, row_cards):
            with col:
                st.markdown(
                    _dashboard_kpi_card(label, value, detail, tone=tone, bg=bg),
                    unsafe_allow_html=True,
                )
    if False:
        st.markdown(
        dedent(
            f"""
        <style>
        .fw-dashboard-shell {{
            display: grid;
            gap: 1rem;
            margin-bottom: 1.2rem;
        }}
        .fw-dashboard-hero {{
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 1rem;
            align-items: end;
            padding: 1.1rem 1.18rem;
            border: 1px solid rgba(255,255,255,0.065);
            border-radius: 1.1rem;
            background:
                radial-gradient(circle at 10% 0%, rgba(25,223,208,0.12), transparent 34%),
                linear-gradient(180deg, rgba(12,28,43,0.96), rgba(7,17,29,0.98));
            box-shadow: 0 20px 42px rgba(0,0,0,0.2);
        }}
        .fw-dashboard-hero__kicker {{
            color: #37eadb;
            font-size: 0.68rem;
            font-weight: 850;
            letter-spacing: 0.09em;
            text-transform: uppercase;
        }}
        .fw-dashboard-hero__title {{
            color: #f5fbff;
            font-size: 1.28rem;
            font-weight: 850;
            margin-top: 0.32rem;
        }}
        .fw-dashboard-hero__copy {{
            color: #8ea6bc;
            font-size: 0.82rem;
            line-height: 1.55;
            margin-top: 0.36rem;
        }}
        .fw-dashboard-hero__pill {{
            color: #dffffb;
            border: 1px solid rgba(74,245,230,0.18);
            background: rgba(24,223,208,0.09);
            border-radius: 999px;
            padding: 0.48rem 0.7rem;
            font-size: 0.72rem;
            font-weight: 800;
            white-space: nowrap;
        }}
        .fw-dash-kpi-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.74rem;
        }}
        .fw-dash-kpi {{
            min-height: 8.2rem;
            padding: 0.9rem;
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 1rem;
            background: linear-gradient(180deg, rgba(13,27,41,0.96), rgba(8,18,30,0.98));
            box-shadow: 0 16px 34px rgba(0,0,0,0.18);
        }}
        .fw-dash-kpi__top {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.6rem;
        }}
        .fw-dash-kpi__label {{
            color: #8fa8bd;
            font-size: 0.68rem;
            font-weight: 850;
            text-transform: uppercase;
            letter-spacing: 0.07em;
        }}
        .fw-dash-kpi__dot {{
            width: 0.42rem;
            height: 0.42rem;
            border-radius: 999px;
            flex: 0 0 auto;
        }}
        .fw-dash-kpi__value {{
            display: inline-flex;
            align-items: center;
            max-width: 100%;
            margin-top: 0.88rem;
            border-radius: 0.8rem;
            padding: 0.42rem 0.58rem;
            font-size: 1.42rem;
            font-weight: 900;
            line-height: 1.05;
            overflow-wrap: anywhere;
        }}
        .fw-dash-kpi__detail {{
            color: #7893aa;
            font-size: 0.74rem;
            line-height: 1.45;
            margin-top: 0.72rem;
        }}
        @media (max-width: 980px) {{
            .fw-dash-kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        }}
        @media (max-width: 640px) {{
            .fw-dashboard-hero {{ grid-template-columns: 1fr; align-items: start; }}
            .fw-dash-kpi-grid {{ grid-template-columns: 1fr; }}
            .fw-dash-kpi {{ min-height: auto; }}
            .fw-dash-kpi__value {{ font-size: 1.28rem; }}
        }}
        </style>
        <div class="fw-dashboard-shell">
            <section class="fw-dashboard-hero">
                <div>
                    <div class="fw-dashboard-hero__kicker">Workspace Pulse</div>
                    <div class="fw-dashboard-hero__title">Trading performance, live markets, and execution context.</div>
                    <div class="fw-dashboard-hero__copy">A compact overview of today's P&L, lifetime performance, broker readiness, and the signals flowing through Finwise.</div>
                </div>
                <div class="fw-dashboard-hero__pill">{escape(used_today)} / {escape(signal_limit)} signals today</div>
            </section>
            <div class="fw-dash-kpi-grid">
                {_dashboard_kpi_card("Today P&L", f"${metrics['today_net']:,.2f}", "Net movement from today's closed and active journal entries.", tone=today_tone, bg=today_bg)}
                {_dashboard_kpi_card("Lifetime P&L", f"${metrics['lifetime_net']:,.2f}", f"{metrics['lifetime_trades']} closed trades tracked.", tone=lifetime_tone, bg=lifetime_bg)}
                {_dashboard_kpi_card("Open Trades", str(int(len(open_df)) if not open_df.empty else 0), "Open or executed positions still being monitored.", tone="#5cf1ff", bg="rgba(92,241,255,0.10)")}
                {_dashboard_kpi_card("Win Rate", f"{metrics['win_rate']:.1f}%", f"Avg win ${metrics['avg_win']:,.2f} · Avg loss ${metrics['avg_loss']:,.2f}", tone="#2df4cc", bg="rgba(45,244,204,0.10)")}
                {_dashboard_kpi_card("Closed Trades", str(metrics["lifetime_trades"]), "Total completed trades in the journal.", tone="#c7d7ff", bg="rgba(122,150,255,0.10)")}
                {_dashboard_kpi_card("Avg Win", f"${metrics['avg_win']:,.2f}", "Mean profit on winning trades.", tone="#2df4a4", bg="rgba(45,244,164,0.10)")}
                {_dashboard_kpi_card("Avg Loss", f"${metrics['avg_loss']:,.2f}", "Mean result on losing trades.", tone=avg_loss_tone, bg=avg_loss_bg)}
                {_dashboard_kpi_card("Signals Today", f"{used_today} / {signal_limit}", "Daily signal usage for this account tier.", tone="#37eadb", bg="rgba(55,234,219,0.10)")}
            </div>
        </div>
        """
        ).strip(),
        unsafe_allow_html=True,
    )

    market_col, insight_col = st.columns([1.45, 0.95], gap="large")
    with market_col:
        st.markdown("### Live Market")
        tracked_symbols = list(default_tracked_symbols)
        for start in range(0, len(tracked_symbols), 3):
            row_symbols = tracked_symbols[start:start + 3]
            snapshot_cols = st.columns(len(row_symbols))
            for col, symbol in zip(snapshot_cols, row_symbols):
                snapshot = engine.get_market_snapshot(symbol) or {}
                price = fmt_price(snapshot.get("last_price"))
                change = snapshot.get("price_24h_pcnt")
                if change is not None:
                    change *= 100
                color = "#26a69a" if (change or 0) >= 0 else "#ef5350"
                source_label = "Live" if snapshot.get("last_price") is not None else "Warming"
                with col:
                    st.markdown(
                        f"""
                        <div style="background:#0f2639;border:1px solid rgba(0,245,212,0.12);
                                    border-radius:16px;padding:16px 18px;min-height:132px;">
                            <div style="display:flex;align-items:center;justify-content:space-between;">
                                <div style="color:white;font-size:16px;font-weight:700;">{escape(str(symbol))}</div>
                                <div style="color:#4a7a94;font-size:11px;">{escape(source_label)}</div>
                            </div>
                            <div style="color:white;font-size:28px;font-weight:800;margin-top:16px;">{price}</div>
                            <div style="color:{color};font-size:13px;font-weight:700;margin-top:6px;">
                                {fmt_pct(change)}
                            </div>
                            <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:16px;">
                                <div style="background:#0b1e2d;border-radius:10px;padding:8px 10px;">
                                    <div style="color:#4a7a94;font-size:10px;">24h High</div>
                                    <div style="color:#e8f4f8;font-size:13px;font-weight:700;">{fmt_price(snapshot.get('high_24h'))}</div>
                                </div>
                                <div style="background:#0b1e2d;border-radius:10px;padding:8px 10px;">
                                    <div style="color:#4a7a94;font-size:10px;">24h Low</div>
                                    <div style="color:#e8f4f8;font-size:13px;font-weight:700;">{fmt_price(snapshot.get('low_24h'))}</div>
                                </div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        if not closed_df.empty:
            best_trade = closed_df.sort_values("pnl_usd", ascending=False).iloc[0]
            worst_trade = closed_df.sort_values("pnl_usd", ascending=True).iloc[0]
            session_df = closed_df.copy()
            session_df["session_name"] = session_df["closed_at"].apply(classify_session)
            session_mix = session_df.groupby("session_name", dropna=False)["pnl_usd"].sum().sort_values(ascending=False)

            st.markdown("### Trade Highlights")
            highlight_left, highlight_right = st.columns(2, gap="large")
            with highlight_left:
                st.markdown(
                    f"""
                    <div style="background:#111c2a;border:1px solid rgba(38,166,154,0.18);border-radius:16px;padding:14px 16px;">
                        <div style="color:#8ab4c8;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;">Best Trade</div>
                        <div style="color:white;font-size:18px;font-weight:700;margin-top:8px;">{best_trade['symbol']} {best_trade['side']}</div>
                        <div style="color:#26a69a;font-size:26px;font-weight:800;margin-top:8px;">${float(best_trade['pnl_usd']):,.2f}</div>
                        <div style="color:#8ab4c8;font-size:12px;margin-top:6px;">{best_trade['timeframe']} | {best_trade['source']} | {str(best_trade['closed_at'])[:10]}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with highlight_right:
                st.markdown(
                    f"""
                    <div style="background:#111c2a;border:1px solid rgba(239,83,80,0.18);border-radius:16px;padding:14px 16px;">
                        <div style="color:#8ab4c8;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;">Worst Trade</div>
                        <div style="color:white;font-size:18px;font-weight:700;margin-top:8px;">{worst_trade['symbol']} {worst_trade['side']}</div>
                        <div style="color:#ef5350;font-size:26px;font-weight:800;margin-top:8px;">${float(worst_trade['pnl_usd']):,.2f}</div>
                        <div style="color:#8ab4c8;font-size:12px;margin-top:6px;">{worst_trade['timeframe']} | {worst_trade['source']} | {str(worst_trade['closed_at'])[:10]}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            st.markdown("### Session Analysis")
            if session_mix.empty:
                st.info("Session performance will appear after more closed trades.")
            else:
                st.bar_chart(session_mix)

        st.markdown("### Trade Log")
        st.caption("Detailed execution history behind the activity feed in the right rail.")
        if recent_df.empty:
            st.info("No trade activity recorded yet.")
        else:
            recent_display = recent_df[[
                "symbol", "side", "status", "source", "entry_price", "exit_price", "pnl_usd", "opened_at"
            ]].copy()
            recent_display["pnl_usd"] = recent_display["pnl_usd"].map(lambda x: round(float(x), 2))
            st.dataframe(recent_display, use_container_width=True, hide_index=True)

    with insight_col:
        insights_html = dashboard_coach_cards(dashboard_insights(metrics, trade_df, closed_df))
        status_color = "#26a69a" if broker_snapshot["broker_status"] != "No broker connected" else "#4a7a94"
        status_bg = "rgba(38,166,154,0.10)" if broker_snapshot["broker_status"] != "No broker connected" else "rgba(74,122,148,0.12)"
        status_border = "rgba(38,166,154,0.22)" if broker_snapshot["broker_status"] != "No broker connected" else "rgba(74,122,148,0.20)"
        sync_color = "#00f5d4" if broker_snapshot["sync_state"] == "Live" else "#8ab4c8" if broker_snapshot["sync_state"] == "Snapshot" else "#ef5350"
        logo_html = (
            f'<img src="{escape(broker_snapshot["logo_path"])}" alt="{escape(broker_snapshot["broker_name"])}" '
            'style="max-width:120px;max-height:34px;object-fit:contain;filter:drop-shadow(0 6px 12px rgba(0,0,0,0.18));" />'
            if broker_snapshot["logo_path"]
            else f'<div style="width:54px;height:54px;border-radius:16px;background:rgba(0,245,212,0.10);'
                 'border:1px solid rgba(0,245,212,0.22);display:flex;align-items:center;justify-content:center;'
                 'color:#00f5d4;font-size:22px;font-weight:800;">F</div>'
        )
        recent_activity_html = dashboard_recent_activity_feed(recent_df)
        st.markdown(
            f"""
            <div class="dashboard-rail">
                <section class="premium-rail-card">
                    <div class="rail-kicker">Performance Intelligence</div>
                    <div class="rail-title">AI Coach</div>
                    <div class="rail-copy">
                        Journal-driven coaching, surfaced in the same premium rail as your broker context and latest executions.
                    </div>
                    <div class="coach-stack">
                        {insights_html}
                    </div>
                </section>
                <section class="premium-rail-card">
                    <div class="rail-kicker">Broker Wallet</div>
                    <div class="rail-title">Broker Status</div>
                    <div class="rail-copy">
                        Keep account sync, connection health, and available capital in view while you trade.
                    </div>
                    <div class="broker-hero">
                        <div>
                            <div style="display:flex;align-items:center;gap:10px;">
                                <div>{logo_html}</div>
                                <div>
                                    <div style="color:white;font-size:18px;font-weight:700;line-height:1.1;">{escape(broker_snapshot["broker_name"])}</div>
                                    <div style="color:#8ab4c8;font-size:12px;margin-top:5px;">{escape(broker_snapshot["connection_method"])}</div>
                                </div>
                            </div>
                        </div>
                        <div style="padding:7px 12px;border-radius:999px;background:{status_bg};
                                    border:1px solid {status_border};color:{status_color};
                                    font-size:11px;font-weight:700;white-space:nowrap;">
                            {escape(broker_snapshot["broker_status"])}
                        </div>
                    </div>
                    <div class="broker-balance">
                        <div class="rail-label-sm">Available Balance</div>
                        <div class="broker-balance-value">{escape(broker_snapshot["balance_text"])}</div>
                        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:14px;">
                            <span style="color:#4a7a94;font-size:11px;">Sync State</span>
                            <span style="color:{sync_color};font-size:12px;font-weight:700;">{escape(broker_snapshot["sync_state"])}</span>
                        </div>
                    </div>
                    <div class="broker-meta-grid">
                        <div class="broker-meta-item">
                            <div class="rail-label-sm">Connection</div>
                            <div class="rail-value-md">{escape(broker_snapshot["connection_method"])}</div>
                        </div>
                        <div class="broker-meta-item">
                            <div class="rail-label-sm">Status</div>
                            <div class="rail-value-md">{escape(broker_snapshot["sync_state"])}</div>
                        </div>
                    </div>
                </section>
                <section class="premium-rail-card">
                    <div class="rail-kicker">Execution Feed</div>
                    <div class="rail-title">Recent Activity</div>
                    <div class="rail-copy">
                        A compact pulse of the newest positions and journal events feeding the dashboard.
                    </div>
                    <div class="activity-stack">
                        {recent_activity_html}
                    </div>
                </section>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("### Trading Calendar")
        if closed_df.empty:
            st.info("Close trades to build a day-by-day calendar of your results.")
        else:
            calendar_df = closed_df.copy()
            if "closed_day" not in calendar_df.columns:
                calendar_df["closed_day"] = calendar_df["closed_at"].fillna("").astype(str).str.slice(0, 10)
            calendar_df = (
                calendar_df.groupby("closed_day", dropna=False)
                .agg(
                    trades=("id", "count"),
                    net_pnl=("pnl_usd", "sum"),
                    wins=("pnl_usd", lambda s: int((s > 0).sum())),
                    losses=("pnl_usd", lambda s: int((s < 0).sum())),
                )
                .reset_index()
                .sort_values("closed_day", ascending=False)
                .head(14)
            )
            calendar_df["day_result"] = calendar_df["net_pnl"].apply(
                lambda x: "Green Day" if x > 0 else "Red Day" if x < 0 else "Flat"
            )
            calendar_df = calendar_df.rename(
                columns={"closed_day": "Day", "net_pnl": "Net P&L", "wins": "Wins", "losses": "Losses", "trades": "Trades"}
            )
            st.dataframe(calendar_df, use_container_width=True, hide_index=True)


def _mobile_metric_card(label: str, value: str, detail: str, *, tone: str = "#2df4cc", bg: str = "rgba(45,244,204,0.10)") -> str:
    return dedent(
        f"""
        <section class="fw-mobile-metric-card">
            <div class="fw-mobile-metric-top">
                <span class="fw-mobile-metric-label">{escape(label)}</span>
                <span class="fw-mobile-metric-dot" style="background:{tone};box-shadow:0 0 14px {tone};"></span>
            </div>
            <div class="fw-mobile-metric-value" style="color:{tone};background:{bg};">{escape(value)}</div>
            <div class="fw-mobile-metric-detail">{escape(detail)}</div>
        </section>
        """
    ).strip()


def _mobile_trade_activity_card(row) -> str:
    symbol = escape(str(getattr(row, "symbol", "") or "Unknown"))
    side = escape(str(getattr(row, "side", "") or "Tracked").title())
    timeframe = escape(str(getattr(row, "timeframe", "") or "--"))
    source = escape(str(getattr(row, "source", "") or "Manual").replace("_", " ").title())
    status = escape(str(getattr(row, "status", "") or "Tracked").replace("_", " ").title())
    timestamp = escape(str(getattr(row, "opened_at", "") or getattr(row, "closed_at", "") or "")[:16] or "Awaiting timestamp")
    try:
        pnl_value = float(getattr(row, "pnl_usd", 0) or 0)
    except Exception:
        pnl_value = 0.0
    pnl_color = "#2df4a4" if pnl_value >= 0 else "#ff6a72"
    pnl_text = f"${pnl_value:,.2f}"
    return dedent(
        f"""
        <section class="fw-mobile-activity-card">
            <div class="fw-mobile-activity-top">
                <div>
                    <div class="fw-mobile-activity-symbol">{symbol}</div>
                    <div class="fw-mobile-activity-meta">{side} | {timeframe} | {source}</div>
                </div>
                <div class="fw-mobile-activity-pnl" style="color:{pnl_color};">{pnl_text}</div>
            </div>
            <div class="fw-mobile-activity-foot">
                <span class="fw-mobile-activity-status">{status}</span>
                <span>{timestamp}</span>
            </div>
        </section>
        """
    ).strip()


def render_mobile_dashboard_page(
    username: str,
    *,
    build_trade_metrics,
    get_used,
    is_premium,
    get_limit,
    default_tracked_symbols,
    engine,
    ensure_symbol_loaded,
    fmt_price,
    fmt_pct,
    dashboard_broker_snapshot,
    dashboard_logo_inner: str = "F",
):
    metrics, trade_df, closed_df = build_trade_metrics(username)
    open_df = trade_df[trade_df["status"].isin(["open", "executed"])].copy() if not trade_df.empty else trade_df
    recent_df = trade_df.head(5).copy() if not trade_df.empty else trade_df
    today_tone, today_bg = _metric_tone(float(metrics.get("today_net", 0.0) or 0.0))
    lifetime_tone, lifetime_bg = _metric_tone(float(metrics.get("lifetime_net", 0.0) or 0.0))
    avg_loss_tone, avg_loss_bg = _metric_tone(-abs(float(metrics.get("avg_loss", 0.0) or 0.0)))
    used_today = str(get_used(username))
    signal_limit = "unlimited" if is_premium(username) else str(get_limit(username))
    broker_snapshot = dashboard_broker_snapshot()
    broker_status_label = broker_snapshot["broker_status"]
    if broker_status_label == "No broker connected":
        broker_status_label = "No broker"
    sync_status_label = broker_snapshot["sync_state"]

    st.markdown(
        """
        <style>
        .fw-mobile-dash-banner {
            width: min(100%, 18.4rem);
            padding: 0.58rem 0.68rem 0.62rem;
            border-radius: 0.96rem;
            border: 1px solid rgba(255,255,255,0.06);
            background:
                radial-gradient(circle at top right, rgba(34,231,202,0.10), transparent 28%),
                linear-gradient(180deg, rgba(14,23,36,0.96), rgba(9,17,29,0.98));
            box-shadow: 0 14px 26px rgba(0,0,0,0.18);
            margin: 0 0 0.34rem;
        }
        .fw-mobile-dash-banner-top {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.58rem;
        }
        .fw-mobile-dash-brand {
            display: flex;
            align-items: center;
            gap: 0.56rem;
            min-width: 0;
        }
        .fw-mobile-dash-brand-logo {
            width: 1.58rem;
            height: 1.58rem;
            border-radius: 0.5rem;
            display: grid;
            place-items: center;
            overflow: hidden;
            color: #041921;
            font-size: 0.72rem;
            font-weight: 900;
            background: linear-gradient(135deg, #2ef1d3 0%, #35d6ff 100%);
            box-shadow: 0 8px 18px rgba(34,231,202,0.16);
            flex: 0 0 auto;
        }
        .fw-mobile-dash-brand-logo img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }
        .fw-mobile-dash-brand-name {
            color: #f5fbff;
            font-size: 0.8rem;
            font-weight: 820;
            letter-spacing: -0.02em;
        }
        .fw-mobile-dash-brand-tag {
            color: #8aa0b8;
            font-size: 0.56rem;
            margin-top: 0.08rem;
            letter-spacing: 0.03em;
        }
        .fw-mobile-dash-live-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            padding: 0.2rem 0.46rem;
            border-radius: 999px;
            border: 1px solid rgba(34,231,202,0.18);
            background: rgba(34,231,202,0.08);
            color: #95f7ea;
            font-size: 0.56rem;
            font-weight: 800;
            white-space: nowrap;
        }
        .fw-mobile-dash-live-pill::before {
            content: "";
            width: 0.36rem;
            height: 0.36rem;
            border-radius: 999px;
            background: #22e7ca;
            box-shadow: 0 0 10px rgba(34,231,202,0.62);
        }
        .fw-mobile-dash-banner-title {
            color: #ffffff;
            font-size: 0.98rem;
            font-weight: 900;
            letter-spacing: -0.03em;
            margin-top: 0.42rem;
            line-height: 1.04;
        }
        .fw-mobile-dash-banner-copy {
            color: #8fa4bb;
            font-size: 0.6rem;
            line-height: 1.34;
            margin-top: 0.18rem;
        }
        .fw-mobile-dash-hero {
            display: flex;
            flex-wrap: wrap;
            gap: 0.34rem;
            margin: 0 0 0.18rem;
        }
        .fw-mobile-dash-kicker {
            display: none;
        }
        .fw-mobile-dash-title {
            display: none;
        }
        .fw-mobile-dash-copy {
            display: none;
        }
        .fw-mobile-dash-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
            width: 100%;
        }
        .fw-mobile-dash-pill {
            padding: 0.22rem 0.46rem;
            border-radius: 999px;
            border: 1px solid rgba(34,231,202,0.14);
            background: rgba(34,231,202,0.08);
            color: #d9fffa;
            font-size: 0.56rem;
            font-weight: 800;
            line-height: 1.2;
        }
        .fw-mobile-metrics-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.42rem;
            margin-top: 0.02rem;
        }
        .fw-mobile-metric-card {
            min-height: 4.7rem;
            padding: 0.56rem 0.58rem;
            border-radius: 0.86rem;
            border: 1px solid rgba(255,255,255,0.06);
            background: linear-gradient(180deg, rgba(13,24,38,0.96), rgba(8,16,28,0.99));
            box-shadow: 0 12px 26px rgba(0,0,0,0.16);
        }
        .fw-mobile-metric-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.42rem;
        }
        .fw-mobile-metric-label {
            color: #90a8bf;
            font-size: 0.56rem;
            font-weight: 850;
            letter-spacing: 0.07em;
            text-transform: uppercase;
        }
        .fw-mobile-metric-dot {
            width: 0.34rem;
            height: 0.34rem;
            border-radius: 999px;
            flex: 0 0 auto;
        }
        .fw-mobile-metric-value {
            display: inline-flex;
            align-items: center;
            max-width: 100%;
            margin-top: 0.34rem;
            border-radius: 0.72rem;
            padding: 0.26rem 0.38rem;
            font-size: 0.84rem;
            font-weight: 900;
            line-height: 1.05;
        }
        .fw-mobile-metric-detail {
            color: #748ea4;
            font-size: 0.56rem;
            line-height: 1.28;
            margin-top: 0.3rem;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .fw-mobile-section-title {
            color: #eef7ff;
            font-size: 0.98rem;
            font-weight: 850;
            letter-spacing: -0.02em;
            margin: 0.4rem 0 0.65rem;
        }
        .fw-mobile-broker-card,
        .fw-mobile-market-card,
        .fw-mobile-activity-card {
            border-radius: 1rem;
            border: 1px solid rgba(255,255,255,0.06);
            background: linear-gradient(180deg, rgba(14,24,38,0.96), rgba(8,16,28,0.99));
            box-shadow: 0 16px 34px rgba(0,0,0,0.16);
        }
        .fw-mobile-broker-card {
            padding: 0.8rem 0.84rem;
            margin-bottom: 0.54rem;
        }
        .fw-mobile-broker-top,
        .fw-mobile-market-top,
        .fw-mobile-activity-top {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.7rem;
        }
        .fw-mobile-broker-label,
        .fw-mobile-market-label {
            color: #7b90a8;
            font-size: 0.62rem;
            font-weight: 850;
            letter-spacing: 0.09em;
            text-transform: uppercase;
        }
        .fw-mobile-broker-name,
        .fw-mobile-market-symbol,
        .fw-mobile-activity-symbol {
            color: #ffffff;
            font-size: 0.98rem;
            font-weight: 850;
            margin-top: 0.28rem;
        }
        .fw-mobile-broker-balance,
        .fw-mobile-market-price {
            color: #dffffb;
            font-size: 1.06rem;
            font-weight: 900;
            letter-spacing: -0.03em;
            margin-top: 0.52rem;
        }
        .fw-mobile-broker-meta,
        .fw-mobile-market-meta,
        .fw-mobile-activity-meta,
        .fw-mobile-activity-foot {
            color: #7890a6;
            font-size: 0.64rem;
            line-height: 1.38;
        }
        .fw-mobile-broker-status,
        .fw-mobile-activity-status {
            padding: 0.34rem 0.52rem;
            border-radius: 999px;
            border: 1px solid rgba(34,231,202,0.12);
            background: rgba(34,231,202,0.07);
            color: #bffff6;
            font-size: 0.64rem;
            font-weight: 800;
            white-space: nowrap;
        }
        .fw-mobile-market-card {
            padding: 0.72rem 0.78rem;
            margin-bottom: 0.52rem;
        }
        .fw-mobile-market-change {
            font-size: 0.76rem;
            font-weight: 850;
            margin-top: 0.18rem;
        }
        .fw-mobile-market-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.4rem;
            margin-top: 0.5rem;
        }
        .fw-mobile-market-stat {
            padding: 0.44rem 0.5rem;
            border-radius: 0.7rem;
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.04);
        }
        .fw-mobile-market-stat-label {
            color: #69829a;
            font-size: 0.58rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.09em;
        }
        .fw-mobile-market-stat-value {
            color: #edf7ff;
            font-size: 0.72rem;
            font-weight: 800;
            margin-top: 0.2rem;
        }
        .fw-mobile-activity-card {
            padding: 0.72rem 0.78rem;
            margin-bottom: 0.52rem;
        }
        .fw-mobile-activity-pnl {
            font-size: 0.86rem;
            font-weight: 900;
            letter-spacing: -0.02em;
        }
        .fw-mobile-activity-foot {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.6rem;
            margin-top: 0.55rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <section class="fw-mobile-dash-banner">
            <div class="fw-mobile-dash-banner-top">
                <div class="fw-mobile-dash-brand">
                    <div class="fw-mobile-dash-brand-logo">{dashboard_logo_inner}</div>
                    <div>
                        <div class="fw-mobile-dash-brand-name">Finwise AI</div>
                        <div class="fw-mobile-dash-brand-tag">Mobile Workspace</div>
                    </div>
                </div>
                <div class="fw-mobile-dash-live-pill">Live Feed</div>
            </div>
            <div class="fw-mobile-dash-banner-title">Dashboard</div>
            <div class="fw-mobile-dash-banner-copy">Live market overview for your tracked instruments.</div>
        </section>
        <section class="fw-mobile-dash-hero">
            <div class="fw-mobile-dash-pills">
                <span class="fw-mobile-dash-pill">{escape(used_today)}/{escape(signal_limit)} signals</span>
                <span class="fw-mobile-dash-pill">{escape(broker_status_label)}</span>
                <span class="fw-mobile-dash-pill">{escape(sync_status_label)}</span>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    default_panel = st.session_state.get("mobile_dashboard_panel", "Overview")
    dashboard_panel = resolve_query_value(
        "mdash",
        default=default_panel if default_panel in {"Overview", "Markets", "Activity"} else "Overview",
        allowed=["Overview", "Markets", "Activity"],
        session_key="mobile_dashboard_panel",
    )
    dashboard_panel = render_mobile_link_tabs(
        options=["Overview", "Markets", "Activity"],
        current_value=dashboard_panel,
        query_key="mdash",
    )

    metric_cards = [
        ("Today P&L", f"${metrics['today_net']:,.2f}", "Closed and active journal impact today.", today_tone, today_bg),
        ("Lifetime P&L", f"${metrics['lifetime_net']:,.2f}", f"{metrics['lifetime_trades']} closed trades tracked.", lifetime_tone, lifetime_bg),
        ("Open Trades", str(int(len(open_df)) if not open_df.empty else 0), "Open or executed positions still being monitored.", "#5cf1ff", "rgba(92,241,255,0.10)"),
        ("Win Rate", f"{metrics['win_rate']:.1f}%", f"Avg win ${metrics['avg_win']:,.2f} · Avg loss ${metrics['avg_loss']:,.2f}", "#2df4cc", "rgba(45,244,204,0.10)"),
        ("Closed Trades", str(metrics["lifetime_trades"]), "Total completed trades in the journal.", "#c7d7ff", "rgba(122,150,255,0.10)"),
        ("Avg Loss", f"${metrics['avg_loss']:,.2f}", "Mean result on losing trades.", avg_loss_tone, avg_loss_bg),
    ]
    if dashboard_panel == "Overview":
        st.markdown(
            f"""
            <section class="fw-mobile-broker-card">
                <div class="fw-mobile-broker-top">
                    <div>
                        <div class="fw-mobile-broker-label">Broker Wallet</div>
                        <div class="fw-mobile-broker-name">{escape(broker_snapshot["broker_name"])}</div>
                    </div>
                    <div class="fw-mobile-broker-status">{escape(broker_status_label)}</div>
                </div>
                <div class="fw-mobile-broker-balance">{escape(broker_snapshot["balance_text"])}</div>
                <div class="fw-mobile-broker-meta">{escape(broker_snapshot["connection_method"])} | {escape(sync_status_label)} sync</div>
            </section>
            """,
            unsafe_allow_html=True,
        )
        overview_cards = "".join(
            _mobile_metric_card(label, value, detail, tone=tone, bg=bg)
            for label, value, detail, tone, bg in metric_cards[:4]
        )
        st.markdown(
            f'<div class="fw-mobile-metrics-grid">{overview_cards}</div>',
            unsafe_allow_html=True,
        )
    elif dashboard_panel == "Markets":
        for symbol in list(default_tracked_symbols)[:4]:
            snapshot = engine.get_market_snapshot(symbol) or {}
            if snapshot.get("last_price") is None:
                ensure_symbol_loaded(symbol)
            snapshot = engine.get_market_snapshot(symbol) or {}
            change = snapshot.get("price_24h_pcnt")
            if change is not None:
                change *= 100
            change_color = "#2df4a4" if (change or 0) >= 0 else "#ff6a72"
            st.markdown(
                f"""
                <section class="fw-mobile-market-card">
                    <div class="fw-mobile-market-top">
                        <div>
                            <div class="fw-mobile-market-label">Perpetual Market</div>
                            <div class="fw-mobile-market-symbol">{escape(symbol)}</div>
                        </div>
                        <div class="fw-mobile-market-change" style="color:{change_color};">{fmt_pct(change)}</div>
                    </div>
                    <div class="fw-mobile-market-price">{fmt_price(snapshot.get("last_price"))}</div>
                    <div class="fw-mobile-market-meta">24h market range and volume snapshot.</div>
                    <div class="fw-mobile-market-grid">
                        <div class="fw-mobile-market-stat">
                            <div class="fw-mobile-market-stat-label">24h High</div>
                            <div class="fw-mobile-market-stat-value">{fmt_price(snapshot.get("high_24h"))}</div>
                        </div>
                        <div class="fw-mobile-market-stat">
                            <div class="fw-mobile-market-stat-label">24h Low</div>
                            <div class="fw-mobile-market-stat-value">{fmt_price(snapshot.get("low_24h"))}</div>
                        </div>
                    </div>
                </section>
                """,
                unsafe_allow_html=True,
            )
    else:
        if recent_df.empty:
            st.info("No trade activity recorded yet.")
        else:
            for row in recent_df.itertuples():
                st.markdown(_mobile_trade_activity_card(row), unsafe_allow_html=True)


def render_trade_journal_page(
    username: str,
    *,
    build_trade_metrics,
    close_trade_entry,
):
    metrics, trade_df, closed_df = build_trade_metrics(username)

    top_metrics = st.columns(4)
    top_metrics[0].metric("Today Trades", metrics["today_trades"])
    top_metrics[1].metric("Today Net P&L", f"${metrics['today_net']:,.2f}")
    top_metrics[2].metric("Lifetime Net P&L", f"${metrics['lifetime_net']:,.2f}")
    top_metrics[3].metric("Win Rate", f"{metrics['win_rate']:.1f}%")

    mid_metrics = st.columns(4)
    mid_metrics[0].metric("Lifetime Closed Trades", metrics["lifetime_trades"])
    mid_metrics[1].metric("Today Profit", f"${metrics['today_profit']:,.2f}")
    mid_metrics[2].metric("Today Loss", f"${metrics['today_loss']:,.2f}")
    mid_metrics[3].metric("Average Win / Loss", f"${metrics['avg_win']:,.2f} / ${metrics['avg_loss']:,.2f}")

    open_df = trade_df[trade_df["status"].isin(["open", "executed"])].copy() if not trade_df.empty else trade_df
    if not open_df.empty:
        st.markdown("### Open Trades")
        display_open = open_df[[
            "id", "broker_name", "source", "symbol", "timeframe", "side", "entry_price",
            "quantity", "notional_usd", "stop_loss", "take_profit", "opened_at"
        ]].copy()
        st.dataframe(display_open, use_container_width=True, hide_index=True)

        st.markdown("### Close A Trade")
        close_col1, close_col2, close_col3 = st.columns(3)
        with close_col1:
            trade_options = [
                f"#{int(row.id)} | {row.symbol} | {row.side} | {row.source}"
                for row in open_df.itertuples()
            ]
            selected = st.selectbox("Open Trade", trade_options, key="journal_close_trade_select")
        selected_id = int(selected.split("|")[0].replace("#", "").strip()) if trade_options else None
        with close_col2:
            exit_price = st.number_input("Exit Price", min_value=0.0, value=0.0, step=0.01, key="journal_exit_price")
        with close_col3:
            extra_fee = st.number_input("Extra Fee", min_value=0.0, value=0.0, step=0.01, key="journal_exit_fee")

        close_notes = st.text_input("Close Notes", key="journal_close_notes")
        if st.button("Close Trade", use_container_width=True):
            if not selected_id or exit_price <= 0:
                st.error("Select a trade and enter a valid exit price.")
            elif close_trade_entry(selected_id, exit_price, extra_fee, close_notes):
                st.success("Trade closed and journal updated.")
                st.rerun()
            else:
                st.error("Could not close that trade.")
    else:
        st.info("No open trades recorded yet.")

    st.markdown("### Closed Trade History")
    if closed_df.empty:
        st.info("No closed trades yet. Once you start recording and closing trades, Finwise will build your statistics automatically.")
    else:
        history_df = closed_df[[
            "id", "broker_name", "source", "symbol", "timeframe", "side", "entry_price",
            "exit_price", "quantity", "fee_paid", "pnl_usd", "pnl_pct", "opened_at", "closed_at"
        ]].copy()
        history_df["pnl_usd"] = history_df["pnl_usd"].map(lambda x: round(float(x), 2))
        history_df["pnl_pct"] = history_df["pnl_pct"].map(lambda x: round(float(x), 2))
        st.dataframe(history_df, use_container_width=True, hide_index=True)

        if "closed_day" not in closed_df.columns:
            closed_df["closed_day"] = closed_df["closed_at"].fillna("").astype(str).str.slice(0, 10)
        daily = closed_df.groupby("closed_day", dropna=False)["pnl_usd"].sum().reset_index()
        daily = daily.rename(columns={"closed_day": "Day", "pnl_usd": "Net P&L"})
        st.markdown("### Daily Performance")
        st.line_chart(daily.set_index("Day"))


def render_mobile_trade_journal_page(
    username: str,
    *,
    build_trade_metrics,
    close_trade_entry,
):
    metrics, trade_df, closed_df = build_trade_metrics(username)
    open_df = trade_df[trade_df["status"].isin(["open", "executed"])].copy() if not trade_df.empty else trade_df

    st.markdown(
        """
        <style>
        .fw-mobile-journal-summary {
            padding: 0.96rem 1rem;
            border-radius: 1.18rem;
            border: 1px solid rgba(255,255,255,0.06);
            background:
                radial-gradient(circle at top right, rgba(34,231,202,0.10), transparent 28%),
                linear-gradient(180deg, rgba(14,23,36,0.96), rgba(9,17,29,0.98));
            box-shadow: 0 18px 40px rgba(0,0,0,0.22);
            margin-bottom: 0.82rem;
        }
        .fw-mobile-journal-kicker {
            color: #7fece0;
            font-size: 0.64rem;
            font-weight: 850;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }
        .fw-mobile-journal-title {
            color: #ffffff;
            font-size: 1.08rem;
            font-weight: 900;
            letter-spacing: -0.03em;
            margin-top: 0.34rem;
        }
        .fw-mobile-journal-copy {
            color: #8da3ba;
            font-size: 0.74rem;
            line-height: 1.58;
            margin-top: 0.32rem;
        }
        .fw-mobile-metrics-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.5rem;
            margin: 0.12rem 0 0.78rem;
        }
        .fw-mobile-metric-card {
            min-height: 5.2rem;
            padding: 0.66rem 0.66rem;
            border-radius: 0.94rem;
            border: 1px solid rgba(255,255,255,0.06);
            background: linear-gradient(180deg, rgba(13,24,38,0.96), rgba(8,16,28,0.99));
            box-shadow: 0 12px 26px rgba(0,0,0,0.16);
        }
        .fw-mobile-metric-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.42rem;
        }
        .fw-mobile-metric-label {
            color: #90a8bf;
            font-size: 0.56rem;
            font-weight: 850;
            letter-spacing: 0.07em;
            text-transform: uppercase;
        }
        .fw-mobile-metric-dot {
            width: 0.34rem;
            height: 0.34rem;
            border-radius: 999px;
            flex: 0 0 auto;
        }
        .fw-mobile-metric-value {
            display: inline-flex;
            align-items: center;
            max-width: 100%;
            margin-top: 0.46rem;
            border-radius: 0.72rem;
            padding: 0.3rem 0.42rem;
            font-size: 0.92rem;
            font-weight: 900;
            line-height: 1.05;
        }
        .fw-mobile-metric-detail {
            color: #748ea4;
            font-size: 0.56rem;
            line-height: 1.28;
            margin-top: 0.4rem;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .fw-mobile-trade-card {
            padding: 0.88rem 0.92rem;
            border-radius: 1rem;
            border: 1px solid rgba(255,255,255,0.06);
            background: linear-gradient(180deg, rgba(13,24,38,0.96), rgba(8,16,28,0.99));
            box-shadow: 0 16px 34px rgba(0,0,0,0.16);
            margin-bottom: 0.65rem;
        }
        .fw-mobile-trade-top {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.7rem;
        }
        .fw-mobile-trade-symbol {
            color: #ffffff;
            font-size: 0.96rem;
            font-weight: 850;
        }
        .fw-mobile-trade-meta,
        .fw-mobile-trade-row {
            color: #7f95ac;
            font-size: 0.72rem;
            line-height: 1.55;
        }
        .fw-mobile-trade-side {
            padding: 0.34rem 0.54rem;
            border-radius: 999px;
            font-size: 0.64rem;
            font-weight: 850;
            white-space: nowrap;
        }
        .fw-mobile-trade-side.buy {
            color: #d7fff1;
            background: rgba(45,244,164,0.12);
            border: 1px solid rgba(45,244,164,0.18);
        }
        .fw-mobile-trade-side.sell {
            color: #ffe1e4;
            background: rgba(255,106,114,0.12);
            border: 1px solid rgba(255,106,114,0.18);
        }
        .fw-mobile-trade-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.48rem;
            margin-top: 0.72rem;
        }
        .fw-mobile-trade-stat {
            padding: 0.54rem 0.6rem;
            border-radius: 0.78rem;
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.04);
        }
        .fw-mobile-trade-stat-label {
            color: #667e95;
            font-size: 0.58rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .fw-mobile-trade-stat-value {
            color: #edf7ff;
            font-size: 0.78rem;
            font-weight: 850;
            margin-top: 0.24rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <section class="fw-mobile-journal-summary">
            <div class="fw-mobile-journal-kicker">Trade Journal</div>
            <div class="fw-mobile-journal-title">Review open positions, close trades, and inspect performance.</div>
            <div class="fw-mobile-journal-copy">A phone-first journal flow for managing active trades and looking back at completed ones.</div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    metric_cards = [
        ("Today Trades", str(metrics["today_trades"]), "Trades opened or closed today.", "#5cf1ff", "rgba(92,241,255,0.10)"),
        ("Today Net", f"${metrics['today_net']:,.2f}", "Net P&L across today's results.", *_metric_tone(float(metrics["today_net"] or 0.0))),
        ("Lifetime Net", f"${metrics['lifetime_net']:,.2f}", "Closed-trade performance since tracking started.", *_metric_tone(float(metrics["lifetime_net"] or 0.0))),
        ("Win Rate", f"{metrics['win_rate']:.1f}%", f"{metrics['lifetime_trades']} closed trades tracked.", "#2df4cc", "rgba(45,244,204,0.10)"),
    ]
    summary_cards = "".join(
        _mobile_metric_card(label, value, detail, tone=tone, bg=bg)
        for label, value, detail, tone, bg in metric_cards
    )
    st.markdown(
        f'<div class="fw-mobile-metrics-grid">{summary_cards}</div>',
        unsafe_allow_html=True,
    )

    default_panel = st.session_state.get("mobile_trade_journal_panel", "Open Trades")
    journal_panel = resolve_query_value(
        "mjournal",
        default=default_panel if default_panel in {"Open Trades", "Closed History", "Analytics"} else "Open Trades",
        allowed=["Open Trades", "Closed History", "Analytics"],
        session_key="mobile_trade_journal_panel",
    )
    render_mobile_link_tabs(
        options=["Open Trades", "Closed History", "Analytics"],
        current_value=journal_panel,
        query_key="mjournal",
        labels={
            "Open Trades": "Open",
            "Closed History": "Closed",
            "Analytics": "Stats",
        },
    )

    if journal_panel == "Open Trades":
        if open_df.empty:
            st.info("No open trades recorded yet.")
        else:
            for row in open_df.itertuples():
                side_class = "buy" if str(getattr(row, "side", "")).upper() == "BUY" else "sell"
                st.markdown(
                    f"""
                    <section class="fw-mobile-trade-card">
                        <div class="fw-mobile-trade-top">
                            <div>
                                <div class="fw-mobile-trade-symbol">{escape(str(getattr(row, "symbol", "") or "Unknown"))}</div>
                                <div class="fw-mobile-trade-meta">{escape(str(getattr(row, "timeframe", "") or "--"))} | {escape(str(getattr(row, "source", "") or "manual").replace("_", " ").title())}</div>
                            </div>
                            <div class="fw-mobile-trade-side {side_class}">{escape(str(getattr(row, "side", "") or "Tracked").title())}</div>
                        </div>
                        <div class="fw-mobile-trade-grid">
                            <div class="fw-mobile-trade-stat">
                                <div class="fw-mobile-trade-stat-label">Entry</div>
                                <div class="fw-mobile-trade-stat-value">{float(getattr(row, "entry_price", 0) or 0):,.4f}</div>
                            </div>
                            <div class="fw-mobile-trade-stat">
                                <div class="fw-mobile-trade-stat-label">Quantity</div>
                                <div class="fw-mobile-trade-stat-value">{float(getattr(row, "quantity", 0) or 0):,.4f}</div>
                            </div>
                            <div class="fw-mobile-trade-stat">
                                <div class="fw-mobile-trade-stat-label">Stop Loss</div>
                                <div class="fw-mobile-trade-stat-value">{float(getattr(row, "stop_loss", 0) or 0):,.4f}</div>
                            </div>
                            <div class="fw-mobile-trade-stat">
                                <div class="fw-mobile-trade-stat-label">Take Profit</div>
                                <div class="fw-mobile-trade-stat-value">{float(getattr(row, "take_profit", 0) or 0):,.4f}</div>
                            </div>
                        </div>
                    </section>
                    """,
                    unsafe_allow_html=True,
                )

            with st.expander("Close A Trade", expanded=False):
                trade_options = [
                    f"#{int(row.id)} | {row.symbol} | {row.side} | {row.source}"
                    for row in open_df.itertuples()
                ]
                selected = st.selectbox("Open Trade", trade_options, key="mobile_journal_close_trade_select")
                selected_id = int(selected.split("|")[0].replace("#", "").strip()) if trade_options else None
                exit_price = st.number_input("Exit Price", min_value=0.0, value=0.0, step=0.01, key="mobile_journal_exit_price")
                extra_fee = st.number_input("Extra Fee", min_value=0.0, value=0.0, step=0.01, key="mobile_journal_exit_fee")
                close_notes = st.text_input("Close Notes", key="mobile_journal_close_notes")
                if st.button("Close Trade", key="mobile_journal_close_trade", use_container_width=True):
                    if not selected_id or exit_price <= 0:
                        st.error("Select a trade and enter a valid exit price.")
                    elif close_trade_entry(selected_id, exit_price, extra_fee, close_notes):
                        st.success("Trade closed and journal updated.")
                        st.rerun()
                    else:
                        st.error("Could not close that trade.")

    elif journal_panel == "Closed History":
        if closed_df.empty:
            st.info("No closed trades yet.")
        else:
            for row in closed_df.head(12).itertuples():
                pnl_value = float(getattr(row, "pnl_usd", 0) or 0)
                pnl_color = "#2df4a4" if pnl_value >= 0 else "#ff6a72"
                st.markdown(
                    f"""
                    <section class="fw-mobile-trade-card">
                        <div class="fw-mobile-trade-top">
                            <div>
                                <div class="fw-mobile-trade-symbol">{escape(str(getattr(row, "symbol", "") or "Unknown"))}</div>
                                <div class="fw-mobile-trade-meta">{escape(str(getattr(row, "timeframe", "") or "--"))} | {escape(str(getattr(row, "source", "") or "manual").replace("_", " ").title())}</div>
                            </div>
                            <div style="color:{pnl_color};font-size:0.9rem;font-weight:900;">${pnl_value:,.2f}</div>
                        </div>
                        <div class="fw-mobile-trade-row" style="margin-top:0.65rem;">
                            {escape(str(getattr(row, "opened_at", "") or "")[:16])} → {escape(str(getattr(row, "closed_at", "") or "")[:16])}
                        </div>
                    </section>
                    """,
                    unsafe_allow_html=True,
                )

    else:
        analytics_df = closed_df.copy()
        if analytics_df.empty:
            st.info("Close trades to unlock daily performance analytics.")
        else:
            if "closed_day" not in analytics_df.columns:
                analytics_df["closed_day"] = analytics_df["closed_at"].fillna("").astype(str).str.slice(0, 10)
            daily = analytics_df.groupby("closed_day", dropna=False)["pnl_usd"].sum().reset_index()
            daily = daily.rename(columns={"closed_day": "Day", "pnl_usd": "Net P&L"})
            st.line_chart(daily.set_index("Day"))
            history_df = analytics_df[[
                "symbol", "timeframe", "side", "entry_price", "exit_price", "pnl_usd", "pnl_pct"
            ]].copy()
            history_df["pnl_usd"] = history_df["pnl_usd"].map(lambda x: round(float(x), 2))
            history_df["pnl_pct"] = history_df["pnl_pct"].map(lambda x: round(float(x), 2))
            st.dataframe(history_df, use_container_width=True, hide_index=True)


