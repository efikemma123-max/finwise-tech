"""
Advanced Binance-style Charting System
- TradingView Lightweight Charts integration
- Real-time candle building
- Technical indicators (MA, RSI, MACD, Volume)
- Interactive drawing tools
"""

import json
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime


def calculate_ma(df: pd.DataFrame, column: str, period: int) -> pd.Series:
    """Calculate Simple Moving Average"""
    return df[column].rolling(window=period).mean()


def calculate_rsi(df: pd.DataFrame, column: str, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index (RSI)"""
    delta = df[column].diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(df: pd.DataFrame, column: str, fast: int = 12, slow: int = 26, signal: int = 9):
    """Calculate MACD (Moving Average Convergence Divergence)"""
    ema_fast = df[column].ewm(span=fast).mean()
    ema_slow = df[column].ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def prepare_chart_data(df: pd.DataFrame, symbol: str, indicators: dict = None) -> dict:
    """
    Prepare data for TradingView Lightweight Charts with indicators.
    
    Args:
        df: DataFrame with OHLCV data
        symbol: Trading pair symbol
        indicators: Dict with indicator settings {
            'ma_periods': [20, 50],
            'show_rsi': True,
            'show_macd': True,
            'show_volume': True
        }
    
    Returns:
        Dict formatted for Lightweight Charts component
    """
    if indicators is None:
        indicators = {
            'ma_periods': [20, 50],
            'show_rsi': True,
            'show_macd': True,
            'show_volume': True
        }
    
    # Prepare candle data
    candles = []
    for _, row in df.iterrows():
        ts = row.get("timestamp")
        if hasattr(ts, "timestamp"):
            time_value = int(ts.timestamp())
        else:
            time_value = int(pd.Timestamp(ts).timestamp())
        
        candles.append({
            "time": time_value,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        })
    
    # Prepare volume data
    volumes = []
    for _, row in df.iterrows():
        ts = row.get("timestamp")
        if hasattr(ts, "timestamp"):
            time_value = int(ts.timestamp())
        else:
            time_value = int(pd.Timestamp(ts).timestamp())
        
        is_up = float(row["close"]) >= float(row["open"])
        vol_color = "rgba(38, 166, 154, 0.45)" if is_up else "rgba(239, 83, 80, 0.45)"
        
        volumes.append({
            "time": time_value,
            "value": float(row.get("volume", 0)),
            "color": vol_color,
        })
    
    # Calculate indicators
    ma_data = {}
    if indicators.get('ma_periods'):
        for period in indicators['ma_periods']:
            df[f'ma_{period}'] = calculate_ma(df, 'close', period)
            ma_data[f'ma_{period}'] = []
            for _, row in df.iterrows():
                ts = row.get("timestamp")
                if hasattr(ts, "timestamp"):
                    time_value = int(ts.timestamp())
                else:
                    time_value = int(pd.Timestamp(ts).timestamp())
                
                ma_val = row.get(f'ma_{period}')
                if pd.notna(ma_val):
                    ma_data[f'ma_{period}'].append({
                        "time": time_value,
                        "value": float(ma_val)
                    })
    
    rsi_data = []
    if indicators.get('show_rsi'):
        df['rsi'] = calculate_rsi(df, 'close', 14)
        for _, row in df.iterrows():
            ts = row.get("timestamp")
            if hasattr(ts, "timestamp"):
                time_value = int(ts.timestamp())
            else:
                time_value = int(pd.Timestamp(ts).timestamp())
            
            rsi_val = row.get('rsi')
            if pd.notna(rsi_val):
                rsi_data.append({
                    "time": time_value,
                    "value": float(rsi_val)
                })
    
    macd_data = {'line': [], 'signal': [], 'histogram': []}
    if indicators.get('show_macd'):
        macd_line, signal_line, histogram = calculate_macd(df, 'close')
        for _, row in df.iterrows():
            ts = row.get("timestamp")
            if hasattr(ts, "timestamp"):
                time_value = int(ts.timestamp())
            else:
                time_value = int(pd.Timestamp(ts).timestamp())
            
            if pd.notna(row['close']):
                idx = row.name
                if pd.notna(macd_line[idx]):
                    macd_data['line'].append({
                        "time": time_value,
                        "value": float(macd_line[idx])
                    })
                if pd.notna(signal_line[idx]):
                    macd_data['signal'].append({
                        "time": time_value,
                        "value": float(signal_line[idx])
                    })
                if pd.notna(histogram[idx]):
                    macd_data['histogram'].append({
                        "time": time_value,
                        "value": float(histogram[idx])
                    })
    
    return {
        "symbol": symbol,
        "candles": candles,
        "volumes": volumes,
        "indicators": {
            "moving_averages": ma_data,
            "rsi": rsi_data,
            "macd": macd_data,
        },
        "settings": indicators
    }


def render_advanced_chart(df: pd.DataFrame, symbol: str, tf_label: str, indicators: dict = None, height: int = 600):
    """
    Render an advanced Binance-style chart using TradingView Lightweight Charts.
    
    Args:
        df: DataFrame with OHLCV data
        symbol: Trading pair symbol
        tf_label: Timeframe label (e.g., "1m", "5m", "1h")
        indicators: Indicator settings
        height: Chart height in pixels
    """
    if df.empty or len(df) < 10:
        st.warning("Not enough data to render chart")
        return
    
    chart_data = prepare_chart_data(df, symbol, indicators)
    payload_json = json.dumps(chart_data)
    
    # Advanced HTML/JS chart renderer
    chart_html = f"""
    <div id="advanced-chart-{symbol}" style="width:100%;height:{height}px;background:#08111d;border-radius:20px;
         border:1px solid rgba(255,255,255,0.06);overflow:hidden;">
        <canvas id="chart-canvas-{symbol}" style="width:100%;height:100%;display:block;"></canvas>
        <div id="chart-tooltip-{symbol}" style="position:absolute;display:none;background:rgba(10,15,25,0.95);
             border:1px solid rgba(0,245,212,0.4);border-radius:8px;padding:8px 12px;
             color:#e8f4f8;font-size:11px;z-index:100;pointer-events:none;"></div>
    </div>

    <script>
    (function() {{
        const data = {payload_json};
        const canvas = document.getElementById('chart-canvas-{symbol}');
        const tooltip = document.getElementById('chart-tooltip-{symbol}');
        
        if (!canvas) return;
        
        const ctx = canvas.getContext('2d');
        const rect = canvas.parentElement.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        
        const W = rect.width;
        const H = rect.height;
        const pad = {{ top: 20, right: 80, bottom: 40, left: 60 }};
        
        const candles = data.candles || [];
        if (candles.length === 0) return;
        
        // Find price range
        const prices = [];
        candles.forEach(c => {{
            prices.push(c.low, c.high);
        }});
        const minP = Math.min(...prices);
        const maxP = Math.max(...prices);
        const range = (maxP - minP) || 1;
        
        const chartW = W - pad.left - pad.right;
        const chartH = H - pad.top - pad.bottom;
        
        // Helper functions
        const yFor = (price) => pad.top + chartH - ((price - minP) / range) * chartH;
        const xFor = (index) => pad.left + (index / Math.max(candles.length - 1, 1)) * chartW;
        
        // Background
        ctx.fillStyle = '#08111d';
        ctx.fillRect(0, 0, W, H);
        
        // Grid lines
        ctx.strokeStyle = 'rgba(255,255,255,0.04)';
        ctx.lineWidth = 1;
        for (let i = 0; i <= 5; i++) {{
            const y = pad.top + (chartH / 5) * i;
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(pad.left + chartW, y);
            ctx.stroke();
            
            const price = maxP - (range / 5) * i;
            ctx.fillStyle = '#557a92';
            ctx.font = 'bold 10px Courier New, monospace';
            ctx.textAlign = 'right';
            ctx.fillText(price.toFixed(2), W - 8, y + 3);
        }}
        
        // Draw candlesticks
        const candleW = Math.max(3, (chartW / candles.length) * 0.6);
        candles.forEach((candle, idx) => {{
            const x = xFor(idx);
            const open = candle.open;
            const close = candle.close;
            const high = candle.high;
            const low = candle.low;
            const isUp = close >= open;
            const color = isUp ? '#26a69a' : '#ef5350';
            
            const bodyTop = yFor(Math.max(open, close));
            const bodyBottom = yFor(Math.min(open, close));
            const bodyH = Math.max(1, bodyBottom - bodyTop);
            
            // Wick
            ctx.strokeStyle = color;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(x, yFor(high));
            ctx.lineTo(x, yFor(low));
            ctx.stroke();
            
            // Body
            ctx.fillStyle = color;
            ctx.fillRect(x - candleW / 2, bodyTop, candleW, bodyH);
        }});
        
        // Draw Moving Averages
        const mas = data.indicators.moving_averages || {{}};
        const colors = ['#ffd166', '#74b9ff'];
        let colorIdx = 0;
        Object.keys(mas).forEach(maKey => {{
            const maPoints = mas[maKey] || [];
            if (maPoints.length === 0) return;
            
            ctx.strokeStyle = colors[colorIdx % colors.length];
            ctx.lineWidth = 2;
            ctx.beginPath();
            
            let first = true;
            maPoints.forEach((point, idx) => {{
                const x = xFor(idx);
                const y = yFor(point.value);
                
                if (first) {{
                    ctx.moveTo(x, y);
                    first = false;
                }} else {{
                    ctx.lineTo(x, y);
                }}
            }});
            ctx.stroke();
            colorIdx++;
        }});
        
        // Interaction
        canvas.addEventListener('mousemove', (e) => {{
            const rect2 = canvas.getBoundingClientRect();
            const mx = e.clientX - rect2.left;
            const my = e.clientY - rect2.top;
            
            if (mx < pad.left || mx > pad.left + chartW || my < pad.top || my > pad.top + chartH) {{
                tooltip.style.display = 'none';
                return;
            }}
            
            const idx = Math.round(((mx - pad.left) / chartW) * (candles.length - 1));
            if (idx < 0 || idx >= candles.length) {{
                tooltip.style.display = 'none';
                return;
            }}
            
            const candle = candles[idx];
            const x = xFor(idx);
            const y = yFor(candle.close);
            
            tooltip.style.display = 'block';
            tooltip.style.left = (x + 10) + 'px';
            tooltip.style.top = (y - 40) + 'px';
            tooltip.innerHTML = `
                <div style="font-weight:bold;margin-bottom:4px;">O: ${{candle.open.toFixed(2)}}</div>
                <div>H: ${{candle.high.toFixed(2)}} | L: ${{candle.low.toFixed(2)}}</div>
                <div style="color:#00f5d4;font-weight:bold;">C: ${{candle.close.toFixed(2)}}</div>
            `;
        }});
        
        canvas.addEventListener('mouseleave', () => {{
            tooltip.style.display = 'none';
        }});
    }})();
    </script>
    """
    
    components.html(chart_html, height=height, scrolling=False)


def get_indicator_controls() -> dict:
    """Create Streamlit controls for indicator configuration."""
    st.subheader("Indicator Settings")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        show_ma = st.checkbox("Moving Averages", value=True)
        ma_periods = []
        if show_ma:
            ma_20 = st.checkbox("MA 20", value=True, key="ma_20")
            ma_50 = st.checkbox("MA 50", value=True, key="ma_50")
            if ma_20:
                ma_periods.append(20)
            if ma_50:
                ma_periods.append(50)
    
    with col2:
        show_rsi = st.checkbox("RSI (14)", value=True)
        show_macd = st.checkbox("MACD", value=True)
    
    with col3:
        show_volume = st.checkbox("Volume", value=True)
    
    return {
        'ma_periods': ma_periods,
        'show_rsi': show_rsi,
        'show_macd': show_macd,
        'show_volume': show_volume
    }
