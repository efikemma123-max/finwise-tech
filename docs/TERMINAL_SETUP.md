# Finwise Desktop Terminal

The desktop terminal is a standalone browser UI built with HTML, CSS, and JavaScript.

## Run

```powershell
cd C:\Users\User\Desktop\Finwise
.\venv\Scripts\Activate.ps1
python bybit_ws_backend.py
```

Then open:

```text
http://localhost:8000
```

## What It Does

- serves the desktop UI from `terminal_web`
- streams and polls live market data through FastAPI routes
- renders the candlestick chart in the browser
- requests AI signals through `/api/signal`
- manages broker profiles and live broker connections through JSON APIs

## Frontend Rule

Keep desktop frontend code in `terminal_web` and keep it to HTML, CSS, and JavaScript. Python belongs in the backend API only.
