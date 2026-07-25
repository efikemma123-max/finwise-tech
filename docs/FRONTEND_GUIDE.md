# Finwise Frontend Guide

The desktop frontend is now plain HTML, CSS, and JavaScript. Python stays behind the API boundary in `bybit_ws_backend.py`.

## Active Frontends

| Frontend | Stack | Path | Purpose |
| --- | --- | --- | --- |
| Desktop Terminal | HTML/CSS/JavaScript | `terminal_web/` | Main desktop trading UI |
| Mobile Web | HTML/CSS/JavaScript | `mobile_web/` | Standalone mobile interface |
| React Terminal | React/TypeScript | `react-terminal/` | Experimental or alternate terminal |

## Desktop Terminal

Run:

```powershell
python bybit_ws_backend.py
```

Open:

```text
http://localhost:8000
```

The desktop page is served from:

- `terminal_web/index.html`
- `terminal_web/styles.css`
- `terminal_web/app.js`

The JavaScript app calls:

- `GET /api/market/symbols`
- `GET /api/market/terminal`
- `GET /api/signal`
- `GET /api/broker/status`
- `POST /api/broker/profile`
- `POST /api/broker/live`
- `POST /api/trade/auto`

## Backend Boundary

Frontend code should remain browser-native: HTML, CSS, and JavaScript only. Market data, AI signals, broker connections, and trade execution belong in backend Python modules and are reached through JSON APIs.

## Editing Guide

- Change desktop layout in `terminal_web/index.html`.
- Change desktop visuals in `terminal_web/styles.css`.
- Change desktop interactions/API calls in `terminal_web/app.js`.
- Add backend data routes in `bybit_ws_backend.py`.
