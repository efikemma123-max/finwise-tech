# Finwise Startup Guide

Finwise desktop now uses a plain HTML/CSS/JavaScript frontend served by the FastAPI backend. Streamlit is not part of the desktop frontend path.

## Architecture

```text
FastAPI Backend (port 8000)
  - serves terminal_web/index.html, styles.css, and app.js
  - exposes /api/market/*, /api/signal, /api/broker/*, /api/trade/auto
  - optional WebSocket endpoint at /ws/kline

Desktop Frontend
  - terminal_web/index.html
  - terminal_web/styles.css
  - terminal_web/app.js
```

## Start The Desktop App

```powershell
cd C:\Users\User\Desktop\Finwise
.\venv\Scripts\Activate.ps1
python bybit_ws_backend.py
```

Then open:

```text
http://localhost:8000
```

You can also run it with uvicorn:

```powershell
python -m uvicorn bybit_ws_backend:app --host 127.0.0.1 --port 8000 --reload
```

## Verify

```powershell
curl http://localhost:8000/health
curl http://localhost:8000/api/market/symbols
```

The browser frontend should load from `terminal_web` and call the FastAPI endpoints directly.

## Useful Files

- `bybit_ws_backend.py` - backend server and desktop API
- `terminal_web/index.html` - desktop markup
- `terminal_web/styles.css` - desktop styling
- `terminal_web/app.js` - desktop browser logic
- `candle_engine.py` - market data runtime
- `ai_worker.py` - signal logic used by the backend
- `trade_engine.py` - broker and auto-trade logic

## Troubleshooting

- If the page opens but data is empty, check the terminal running `bybit_ws_backend.py` for market API errors.
- If the chart library does not load, check browser DevTools Network for the Lightweight Charts CDN request.
- If a port is already in use, start uvicorn on another port and open that port in the browser.
