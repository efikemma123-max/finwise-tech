# Finwise React Terminal

**Production-grade real-time crypto trading terminal** built with React, TypeScript, and TradingView Lightweight Charts.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│           React Terminal (This App)                  │
│  • TradingView Lightweight Charts                   │
│  • Real-time candlestick rendering                 │
│  • WebSocket streaming from FastAPI backend        │
│  • Modular indicator system                        │
└─────────────────────────────────────────────────────┘
                        ↕
┌─────────────────────────────────────────────────────┐
│      FastAPI Backend (bybit_ws_backend.py)          │
│  • WebSocket relay from Bybit API                  │
│  • Kline history + live streaming                  │
│  • Serves both React & Web Terminal                │
└─────────────────────────────────────────────────────┘
                        ↕
┌─────────────────────────────────────────────────────┐
│         Bybit WebSocket (Public API)                │
│  • Real-time kline data (no auth required)         │
└─────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd react-terminal
npm install
```

### 2. Configure Environment

Copy `.env.example` to `.env` and update:

```bash
cp .env.example .env
```

Default values work if FastAPI backend runs on `localhost:8000`:

```env
VITE_WS_URL=ws://localhost:8000/ws/kline
VITE_API_BASE_URL=http://localhost:8000
```

### 3. Start FastAPI Backend

From the parent directory:

```bash
python bybit_ws_backend.py
# Server starts on http://localhost:8000
```

### 4. Start React Dev Server

```bash
npm run dev
# Opens http://localhost:58021 automatically
```

## 📊 Features

### Phase 1: MVP ✅
- **Real-time Candlesticks** - Lightweight Charts rendering
- **Moving Averages** - EMA 20, EMA 50 overlay
- **WebSocket Streaming** - Live updates from Bybit
- **Dark Theme** - Professional trading interface

### Phase 2: In Development 🔄
- **RSI (Relative Strength Index)** - Code ready, toggle in UI
- **MACD** - Code ready, toggle in UI
- Advanced indicator calculations

### Phase 3: Future 🎯
- **Drawing Tools** - Trendlines, support/resistance
- **Fibonacci Retracements**
- **Annotations**

## 🛠️ Development

### Project Structure

```
react-terminal/
├── src/
│   ├── components/
│   │   ├── Chart.tsx              # TradingView Lightweight Charts wrapper
│   │   ├── StatusBar.tsx          # Connection & market data status
│   │   ├── IndicatorPanel.tsx     # Indicator config toggles
│   │   └── *.css                  # Component styles
│   ├── services/
│   │   └── websocket.ts           # WebSocket connection management
│   ├── hooks/
│   │   └── useMarketData.ts       # React hook for market data streaming
│   ├── types/
│   │   └── market.ts              # TypeScript interfaces
│   ├── App.tsx                    # Main component
│   ├── main.tsx                   # Entry point
│   └── index.css                  # Global styles
├── public/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── .env.example
└── index.html
```

### Build for Production

```bash
npm run build
# Output: dist/
```

Preview production build locally:

```bash
npm run preview
```

## 🔌 WebSocket Protocol

The backend sends market data in JSON format:

### History (On Connect)

```json
{
  "type": "history",
  "data": [
    {
      "time": 1682592000,
      "open": 29000,
      "high": 29500,
      "low": 28900,
      "close": 29300,
      "volume": 1234.56
    }
  ]
}
```

### Live Updates

```json
{
  "type": "update",
  "data": {
    "time": 1682592060,
    "open": 29300,
    "high": 29450,
    "low": 29250,
    "close": 29400,
    "volume": 567.89
  }
}
```

## 🎨 Customization

### Change Chart Colors

Edit [src/components/Chart.tsx](src/components/Chart.tsx):

```typescript
const candleSeries = chart.addCandlestickSeries({
  upColor: '#26a69a',      // Green (up)
  downColor: '#ef5350',    // Red (down)
  wickUpColor: '#26a69a',
  wickDownColor: '#ef5350',
});
```

### Add New Indicators

1. Update `IndicatorConfig` in [src/types/market.ts](src/types/market.ts)
2. Add calculation logic in [src/App.tsx](src/App.tsx)
3. Enable toggle in [src/components/IndicatorPanel.tsx](src/components/IndicatorPanel.tsx)

### Customize Layout

Edit [src/App.css](src/App.css):

```css
.app-layout {
  display: flex;
  gap: 12px;
  /* Adjust gap, padding, responsive breakpoints */
}
```

## 📝 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_WS_URL` | `ws://localhost:8000/ws/kline` | Backend WebSocket URL |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend REST API URL |

For **production**, set:

```bash
VITE_WS_URL=wss://api.example.com/ws/kline
VITE_API_BASE_URL=https://api.example.com
```

## 🔒 Security Notes

- **No authentication** currently implemented (public Bybit API)
- For production, implement JWT token refresh in `websocket.ts`
- Never expose API keys in environment files
- Use CORS proxy in production if needed

## 📚 Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `react` | 18.2.0 | UI framework |
| `lightweight-charts` | 4.1.1 | Charting library |
| `typescript` | 5.3.3 | Type safety |
| `vite` | 5.0.8 | Build tool |

## 🐛 Troubleshooting

### WebSocket Connection Failed

**Issue**: `Error: WebSocket is closed before the connection is established`

**Solution**:
1. Ensure FastAPI backend is running: `python bybit_ws_backend.py`
2. Check `VITE_WS_URL` environment variable
3. Verify backend listening on correct port: `lsof -i :8000`

### Chart Not Rendering

**Issue**: Container div is hidden or has zero height

**Solution**:
1. Check browser DevTools → Elements
2. Verify `.chart-content` has `flex: 1` and `height: 100%`
3. Check parent `.chart-container` has height constraint

### No Data Appearing

**Issue**: WebSocket connects but no candles appear

**Solution**:
1. Check backend logs for Bybit API errors
2. Verify `useMarketData()` hook receives candles
3. Check browser console for React warnings

## 📞 Support

- Backend Issues? Check [bybit_ws_backend.py](../bybit_ws_backend.py)
- Desktop web app? Check [terminal_web/](../terminal_web/)
- Web Terminal MVP? Check [terminal_web/](../terminal_web/)

## 📄 License

Internal project for Finwise trading system.

---

**Next Steps**: 
- Deploy backend to production server
- Configure HTTPS/WSS for secure communication
- Implement Phase 2 indicators (RSI, MACD)
- Add drawing tools (Phase 3)
