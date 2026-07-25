from typing import Any, Dict

import streamlit as st

from backend.market.candle_engine import split_market_symbol


def manual_profile_connected(session_state: Any) -> bool:
    profile = session_state.get("manual_broker_profile")
    return bool(profile and profile.get("broker_name"))


def build_manual_trade_guide(profile: Dict, signal_result: Dict, meta: Dict) -> Dict:
    broker_name = meta.get("broker_name") or profile.get("broker_name", "Broker")
    symbol = meta.get("symbol", "BTCUSDT")
    base_asset, _quote_asset = split_market_symbol(symbol)
    base_asset = base_asset or symbol
    tf_label = meta.get("tf_label", "1m")
    balance = float(meta.get("balance") or profile.get("balance") or 0.0)

    signal = signal_result.get("signal", "HOLD")
    confidence = float(signal_result.get("confidence", 0))
    position = signal_result.get("position_size", {})
    entry_exit = signal_result.get("entry_exit", {})
    regime = signal_result.get("regime", {})
    summary = signal_result.get("summary", {})
    risk = signal_result.get("black_swan_risk", {})

    suggested_notional = min(balance, float(position.get("position_size_usd", 0) or 0))
    entry_price = float(entry_exit.get("actual_entry") or entry_exit.get("entry_price") or 0)
    stop_loss = float(entry_exit.get("stop_loss") or 0)
    take_profit = float(entry_exit.get("take_profit") or 0)
    quantity = (suggested_notional / entry_price) if entry_price > 0 else 0.0
    risk_per_unit = abs(entry_price - stop_loss)
    reward_per_unit = abs(take_profit - entry_price)
    estimated_loss = quantity * risk_per_unit
    estimated_reward = quantity * reward_per_unit

    if signal == "BUY":
        action_title = "Manual Buy Setup"
        action_steps = [
            f"Open {broker_name} and load the {symbol} market.",
            f"Prepare a buy around {entry_price:,.4f} with size near {quantity:,.6f} {base_asset}.",
            f"Set stop loss near {stop_loss:,.4f} and take profit near {take_profit:,.4f}.",
            "Only confirm the trade if the live market still matches the signal conditions.",
        ]
    elif signal == "SELL":
        action_title = "Manual Sell Setup"
        action_steps = [
            f"Open {broker_name} and load the {symbol} market.",
            f"Prepare a sell around {entry_price:,.4f} with size near {quantity:,.6f} {base_asset}.",
            f"Set stop loss near {stop_loss:,.4f} and take profit near {take_profit:,.4f}.",
            "Only confirm the trade if the live market still matches the signal conditions.",
        ]
    else:
        action_title = "Stand Aside"
        action_steps = [
            f"Keep {broker_name} open for {symbol}, but do not enter yet.",
            "Wait for a clearer signal before committing capital.",
            "Review the next update if confidence improves or the setup quality changes.",
        ]

    return {
        "broker_name": broker_name,
        "symbol": symbol,
        "tf_label": tf_label,
        "balance": balance,
        "signal": signal,
        "confidence": confidence,
        "suggested_notional": round(suggested_notional, 2),
        "entry_price": round(entry_price, 8),
        "stop_loss": round(stop_loss, 8),
        "take_profit": round(take_profit, 8),
        "quantity": round(quantity, 8),
        "estimated_loss": round(estimated_loss, 2),
        "estimated_reward": round(estimated_reward, 2),
        "risk_reward_ratio": float(entry_exit.get("risk_reward_ratio", 0)),
        "reason": signal_result.get("reason", "No reason provided."),
        "regime": regime.get("regime", "unknown") if isinstance(regime, dict) else str(regime),
        "setup_quality": summary.get("setup_quality", "unknown") if isinstance(summary, dict) else "unknown",
        "risk_level": risk.get("risk_level", 0) if isinstance(risk, dict) else 0,
        "action_title": action_title,
        "action_steps": action_steps,
    }


def render_manual_trade_guide(guide: Dict):
    signal = guide["signal"]
    signal_color = "#26a69a" if signal == "BUY" else "#ef5350" if signal == "SELL" else "#ffc107"

    metric_cols = st.columns(4)
    metric_cols[0].metric("Signal", signal)
    metric_cols[1].metric("Confidence", f"{guide['confidence']}%")
    metric_cols[2].metric("Suggested Notional", f"${guide['suggested_notional']:,.2f}")
    metric_cols[3].metric("Reward/Risk", f"{guide['risk_reward_ratio']:.2f}x")

    price_cols = st.columns(4)
    price_cols[0].metric("Entry", f"{guide['entry_price']:,.4f}")
    price_cols[1].metric("Stop Loss", f"{guide['stop_loss']:,.4f}")
    price_cols[2].metric("Take Profit", f"{guide['take_profit']:,.4f}")
    price_cols[3].metric("Est. Quantity", f"{guide['quantity']:.6f}")

    risk_cols = st.columns(3)
    risk_cols[0].metric("Est. Loss", f"${guide['estimated_loss']:,.2f}")
    risk_cols[1].metric("Est. Reward", f"${guide['estimated_reward']:,.2f}")
    risk_cols[2].metric("Risk Score", f"{guide['risk_level']}/100")

    steps_html = "".join(
        f"<li style='margin-bottom:8px;'>{step}</li>"
        for step in guide["action_steps"]
    )
    st.markdown(
        f"""
        <div style="background:#0f2639;border:1px solid rgba(0,245,212,0.14);
                    border-radius:16px;padding:16px;margin-top:10px;">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
                <div>
                    <div style="color:white;font-size:18px;font-weight:700;">{guide['action_title']}</div>
                    <div style="color:#8ab4c8;font-size:13px;margin-top:6px;">
                        Broker: {guide['broker_name']} | Symbol: {guide['symbol']} | Timeframe: {guide['tf_label']} | Balance basis: ${guide['balance']:,.2f}
                    </div>
                </div>
                <div style="color:{signal_color};font-size:28px;font-weight:800;">{signal}</div>
            </div>
            <div style="color:#8ab4c8;font-size:13px;line-height:1.7;margin-top:14px;">
                {guide['reason']}<br>
                Regime: {guide['regime']}<br>
                Setup quality: {guide['setup_quality']}
            </div>
            <div style="margin-top:14px;padding:12px 14px;background:#0b1e2d;border-radius:12px;border:1px solid rgba(255,255,255,0.05);">
                <div style="color:white;font-size:14px;font-weight:700;margin-bottom:10px;">Manual Execution Checklist</div>
                <ol style="color:#8ab4c8;font-size:13px;line-height:1.6;padding-left:18px;margin:0;">
                    {steps_html}
                </ol>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info("Finwise Assistant is guiding this setup from your saved broker profile and balance. You still confirm the trade yourself.")
