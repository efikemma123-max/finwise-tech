"""
Modular Technical Indicator System
Supports real-time calculation and rendering for Lightweight Charts

Phases:
- Phase 1 (MVP): Moving Averages (EMA 20, 50)
- Phase 2: RSI, MACD
- Phase 3: Drawing tools (trendlines, support/resistance, Fibonacci)
"""

import pandas as pd
from typing import Dict, List, Tuple


class IndicatorCalculator:
    """Calculate technical indicators from OHLCV data."""
    
    @staticmethod
    def calculate_ema(data: pd.Series, period: int) -> pd.Series:
        """Calculate Exponential Moving Average."""
        return data.ewm(span=period).mean()
    
    @staticmethod
    def calculate_sma(data: pd.Series, period: int) -> pd.Series:
        """Calculate Simple Moving Average."""
        return data.rolling(window=period).mean()
    
    @staticmethod
    def calculate_rsi(data: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index (0-100)."""
        delta = data.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss.replace(0, 1e-9)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)
    
    @staticmethod
    def calculate_macd(data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate MACD (Moving Average Convergence Divergence).
        Returns: (macd_line, signal_line, histogram)
        """
        ema_fast = data.ewm(span=fast).mean()
        ema_slow = data.ewm(span=slow).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    @staticmethod
    def calculate_bollinger_bands(data: pd.Series, period: int = 20, std_dev: int = 2) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate Bollinger Bands.
        Returns: (upper_band, middle_band, lower_band)
        """
        middle = data.rolling(window=period).mean()
        std = data.rolling(window=period).std()
        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)
        return upper, middle, lower


class IndicatorFormatter:
    """Format indicator data for Lightweight Charts rendering."""
    
    @staticmethod
    def format_line_series(df: pd.DataFrame, column: str, color: str, name: str) -> Dict:
        """
        Format a line indicator for Lightweight Charts.
        
        Args:
            df: DataFrame with indicator values
            column: Column name in df
            color: Hex color (e.g., "#ffd166")
            name: Indicator name
        
        Returns:
            Series dict for renderLightweightCharts
        """
        data = []
        for _, row in df.iterrows():
            ts = row.get("timestamp")
            if hasattr(ts, "timestamp"):
                time_val = int(ts.timestamp())
            else:
                time_val = int(pd.Timestamp(ts).timestamp())
            
            value = row.get(column)
            if pd.notna(value):
                data.append({
                    "time": time_val,
                    "value": float(value)
                })
        
        return {
            "type": "Line",
            "data": data,
            "options": {
                "color": color,
                "lineWidth": 2,
                "title": name,
                "priceLineVisible": False,
            }
        }
    
    @staticmethod
    def format_histogram_series(df: pd.DataFrame, column: str, name: str) -> Dict:
        """
        Format a histogram indicator (MACD histogram, volume).
        
        Args:
            df: DataFrame with indicator values
            column: Column name in df
            name: Indicator name
        
        Returns:
            Series dict for renderLightweightCharts
        """
        data = []
        for _, row in df.iterrows():
            ts = row.get("timestamp")
            if hasattr(ts, "timestamp"):
                time_val = int(ts.timestamp())
            else:
                time_val = int(pd.Timestamp(ts).timestamp())
            
            value = row.get(column)
            if pd.notna(value):
                color = "#26a69a" if value >= 0 else "#ef5350"
                data.append({
                    "time": time_val,
                    "value": float(abs(value)),
                    "color": color
                })
        
        return {
            "type": "Histogram",
            "data": data,
            "options": {
                "priceFormat": {"type": "volume"},
                "priceScaleId": "",
            },
            "priceScale": {
                "scaleMargins": {"top": 0.8, "bottom": 0.0},
            }
        }


class IndicatorPipeline:
    """
    Orchestrate indicator calculation and formatting.
    Modular design: enable/disable indicators via config.
    """
    
    def __init__(self, config: Dict = None):
        """
        Args:
            config: Indicator configuration
                {
                    "moving_averages": {
                        "enabled": True,
                        "ema": [20, 50],
                        "sma": []
                    },
                    "rsi": {"enabled": False, "period": 14},
                    "macd": {"enabled": False},
                    "bollinger_bands": {"enabled": False}
                }
        """
        self.config = config or {
            "moving_averages": {
                "enabled": True,
                "ema": [20, 50],
                "sma": []
            },
            "rsi": {"enabled": False},
            "macd": {"enabled": False},
            "bollinger_bands": {"enabled": False}
        }
        self.calc = IndicatorCalculator()
        self.fmt = IndicatorFormatter()
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all enabled indicators and add to dataframe.
        
        Args:
            df: OHLCV DataFrame
        
        Returns:
            DataFrame with indicator columns added
        """
        df = df.copy()
        
        # Phase 1 (MVP): Moving Averages
        if self.config.get("moving_averages", {}).get("enabled"):
            for period in self.config["moving_averages"].get("ema", []):
                df[f"ema_{period}"] = self.calc.calculate_ema(df["close"], period)
            for period in self.config["moving_averages"].get("sma", []):
                df[f"sma_{period}"] = self.calc.calculate_sma(df["close"], period)
        
        # Phase 2: RSI
        if self.config.get("rsi", {}).get("enabled"):
            period = self.config["rsi"].get("period", 14)
            df["rsi"] = self.calc.calculate_rsi(df["close"], period)
        
        # Phase 2: MACD
        if self.config.get("macd", {}).get("enabled"):
            df["macd"], df["macd_signal"], df["macd_histogram"] = self.calc.calculate_macd(df["close"])
        
        # Phase 2: Bollinger Bands
        if self.config.get("bollinger_bands", {}).get("enabled"):
            upper, middle, lower = self.calc.calculate_bollinger_bands(df["close"])
            df["bb_upper"] = upper
            df["bb_middle"] = middle
            df["bb_lower"] = lower
        
        return df
    
    def format_series(self, df: pd.DataFrame) -> List[Dict]:
        """
        Format calculated indicators into Lightweight Charts series.
        
        Args:
            df: DataFrame with indicator columns
        
        Returns:
            List of series dicts for renderLightweightCharts
        """
        series = []
        
        # Phase 1 (MVP): Moving Averages
        if self.config.get("moving_averages", {}).get("enabled"):
            colors = ["#ffd166", "#74b9ff", "#a29bfe", "#fd79a8"]
            for i, period in enumerate(self.config["moving_averages"].get("ema", [])):
                series.append(self.fmt.format_line_series(
                    df, f"ema_{period}", colors[i % len(colors)], f"EMA {period}"
                ))
            for i, period in enumerate(self.config["moving_averages"].get("sma", [])):
                series.append(self.fmt.format_line_series(
                    df, f"sma_{period}", colors[(i + len(self.config["moving_averages"]["ema"])) % len(colors)], f"SMA {period}"
                ))
        
        # Phase 2: RSI (separate subplot)
        if self.config.get("rsi", {}).get("enabled"):
            series.append(self.fmt.format_line_series(
                df, "rsi", "#a29bfe", "RSI 14"
            ))
        
        # Phase 2: MACD (separate subplot with histogram)
        if self.config.get("macd", {}).get("enabled"):
            series.append(self.fmt.format_line_series(df, "macd", "#00f5d4", "MACD"))
            series.append(self.fmt.format_line_series(df, "macd_signal", "#ff6b9d", "Signal"))
            series.append(self.fmt.format_histogram_series(df, "macd_histogram", "Histogram"))
        
        # Phase 2: Bollinger Bands
        if self.config.get("bollinger_bands", {}).get("enabled"):
            series.append(self.fmt.format_line_series(df, "bb_upper", "rgba(200, 120, 255, 0.5)", "BB Upper"))
            series.append(self.fmt.format_line_series(df, "bb_middle", "rgba(200, 120, 255, 0.7)", "BB Middle"))
            series.append(self.fmt.format_line_series(df, "bb_lower", "rgba(200, 120, 255, 0.5)", "BB Lower"))
        
        return series
