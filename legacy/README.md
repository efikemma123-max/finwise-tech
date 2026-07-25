# Legacy Code Archive

This folder contains deprecated/archived code from earlier versions of Finwise.

## Files

- **api_server.py** - Old REST API (replaced by FastAPI WebSocket backend)
- **streamlit_app.py** - Original Streamlit dashboard (replaced by the HTML/CSS/JS desktop terminal)
- **advanced_chart.py** - Old charting module (replaced by Lightweight Charts)

## Why Archived?

- ❌ **api_server.py** → Replaced by modern FastAPI WebSocket relay (`bybit_ws_backend.py`)
- ❌ **streamlit_app.py** → Replaced by the production desktop terminal (`terminal_web/`)
- ❌ **advanced_chart.py** → Replaced by TradingView Lightweight Charts

## Current Stack

✅ **Active Production Code:**
- `bybit_ws_backend.py` - FastAPI desktop API and static frontend server
- `candle_engine.py` - Multi-symbol live feed
- `trade_engine.py` - Broker abstraction
- `ai_worker.py` - Signal generation
- `indicators.py` - Technical indicators
- `manual_trade_assistant.py` - Manual trading UI
- `terminal_web/` - HTML/CSS/JavaScript desktop UI
- `react-terminal/` - alternate React UI

## If You Need Legacy Code

Reference these files if you need to:
- Understand old API architecture
- Extract utility functions
- Review previous implementations

**But do NOT use in production.** They are outdated and incompatible with the current WebSocket-based architecture.

---

Date Archived: April 20, 2026
