import streamlit as st
import pandas as pd
from ai_worker import (
    fetch_bybit_klines, add_indicators, ai_signal
)

st.set_page_config(
    page_title="Finwise AI Dashboard",
    layout="wide",
    page_icon="💸"
)

st.markdown("""
<style>
body {background-color: #f5f7fa;}
.big-title {font-size: 3rem; font-weight: bold; color: #1a237e;}
.metric {font-size: 1.5rem; color: #388e3c;}
.error {color: #d32f2f; font-weight: bold;}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="big-title">Finwise AI Trading Dashboard</div>', unsafe_allow_html=True)

symbol = st.text_input("Symbol", value="BTCUSDT")
interval = st.selectbox("Interval (minutes)", ["1", "5", "15", "30", "60", "240", "D"])
balance = st.number_input("Current Balance (USD)", min_value=10.0, value=1000.0, step=10.0)

if st.button("Analyze Market"):
    try:
        df = fetch_bybit_klines(symbol=symbol, interval=interval)
        if df.empty or len(df) < 50:
            st.warning("Not enough data to analyze. Try a different symbol or interval.")
        else:
            df = add_indicators(df)
            signal = ai_signal(df, symbol=symbol, current_balance=balance)
            st.success(f"Signal: {signal['signal']} | Confidence: {signal['confidence']}%")
            st.write("Reason:", signal.get("reason", "-"))
            st.write("Position Sizing:", signal.get("position_size", {}))
            st.write("Entry/Exit:", signal.get("entry_exit", {}))
            st.write("Risk Assessment:", signal.get("black_swan_risk", {}))
            st.write("Regime:", signal.get("regime", {}))
            st.write("Robustness:", signal.get("robustness", {}))
            st.line_chart(df.set_index("timestamp")["close"])
    except Exception as e:
        st.markdown('<div class="error">An error occurred while analyzing the market. Please try again later.</div>', unsafe_allow_html=True)
        # Optionally log error to a file or monitoring system
