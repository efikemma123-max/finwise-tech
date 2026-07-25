try:
    import streamlit as st
except ModuleNotFoundError:
    class _StreamlitUnavailable:
        session_state = {}

        def __getattr__(self, name):
            raise RuntimeError(
                "Streamlit UI helpers require streamlit. "
                "Use the HTML/CSS/JS desktop frontend for browser UI."
            )

    st = _StreamlitUnavailable()
import pandas as pd
import requests
import sqlite3
from datetime import datetime

from backend.market.candle_engine import (
    POPULAR_SYMBOL_FALLBACK,
    discover_tradable_symbols,
    fetch_market_klines,
    normalize_market_symbol,
    sort_symbols,
)


BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
PAIR_FALLBACK = list(POPULAR_SYMBOL_FALLBACK)
DB_PATH = "finwise.db"
TRADE_STYLE_PROFILES = {
    "scalp": {
        "key": "scalp",
        "label": "Scalp",
        "description": "Fast entries with tighter targets and smaller sizing.",
        "preferred_timeframes": {"1m", "3m", "5m"},
        "min_confidence": 48,
        "min_rr_ratio": 1.15,
        "size_multiplier": 0.7,
        "timeframe_mismatch_penalty": 4,
        "ema_fast_span": 8,
        "ema_slow_span": 21,
        "rsi_period": 7,
        "momentum_window": 3,
        "momentum_threshold": 0.03,
        "trend_gap_threshold": 0.12,
        "rsi_bull_floor": 50,
        "rsi_bull_ceiling": 74,
        "rsi_bear_floor": 26,
        "rsi_bear_ceiling": 48,
        "rsi_extreme_high": 82,
        "rsi_extreme_low": 18,
        "volume_confirmation_ratio": 0.95,
        "pullback_tolerance_pct": 0.3,
        "reward_multiple": 2.25,
        "stop_atr_multiplier": 1.1,
        "profitability_floor": 1.1,
        "requires_structure_confirmation": False,
        "robustness_penalty": 2,
        "profitability_penalty": 8,
        "black_swan_penalty_divisor": 10.0,
        "confidence_floor": 38,
        "regime_penalty_scale": 0.6,
        "regime_boost_scale": 1.1,
        "blocked_risk_level": 84,
        "style_confidence_boost": 4,
        "style_reason": "This style is tuned for fast momentum and quick rotation.",
    },
    "day_trade": {
        "key": "day_trade",
        "label": "Day Trade",
        "description": "Balanced intraday setups without holding too long.",
        "preferred_timeframes": {"5m", "15m", "30m", "1h"},
        "min_confidence": 48,
        "min_rr_ratio": 1.5,
        "size_multiplier": 0.9,
        "timeframe_mismatch_penalty": 4,
        "ema_fast_span": 20,
        "ema_slow_span": 50,
        "rsi_period": 14,
        "momentum_window": 5,
        "momentum_threshold": 0.08,
        "trend_gap_threshold": 0.3,
        "rsi_bull_floor": 52,
        "rsi_bull_ceiling": 69,
        "rsi_bear_floor": 31,
        "rsi_bear_ceiling": 48,
        "rsi_extreme_high": 77,
        "rsi_extreme_low": 23,
        "volume_confirmation_ratio": 1.0,
        "pullback_tolerance_pct": 0.45,
        "reward_multiple": 2.0,
        "stop_atr_multiplier": 2.0,
        "profitability_floor": 1.45,
        "requires_structure_confirmation": False,
        "robustness_penalty": 5,
        "profitability_penalty": 14,
        "black_swan_penalty_divisor": 7.5,
        "confidence_floor": 40,
        "regime_penalty_scale": 0.85,
        "regime_boost_scale": 1.0,
        "blocked_risk_level": 80,
        "style_confidence_boost": 0,
        "style_reason": "This style looks for cleaner intraday structure before committing.",
    },
    "swing": {
        "key": "swing",
        "label": "Swing",
        "description": "Higher-conviction setups meant to breathe across larger moves.",
        "preferred_timeframes": {"30m", "1h", "4h"},
        "min_confidence": 58,
        "min_rr_ratio": 1.8,
        "size_multiplier": 0.85,
        "timeframe_mismatch_penalty": 7,
        "ema_fast_span": 34,
        "ema_slow_span": 89,
        "rsi_period": 14,
        "momentum_window": 9,
        "momentum_threshold": 0.18,
        "trend_gap_threshold": 0.4,
        "rsi_bull_floor": 53,
        "rsi_bull_ceiling": 68,
        "rsi_bear_floor": 33,
        "rsi_bear_ceiling": 47,
        "rsi_extreme_high": 75,
        "rsi_extreme_low": 25,
        "volume_confirmation_ratio": 1.05,
        "pullback_tolerance_pct": 0.6,
        "reward_multiple": 2.4,
        "stop_atr_multiplier": 2.4,
        "profitability_floor": 1.7,
        "requires_structure_confirmation": True,
        "robustness_penalty": 6,
        "profitability_penalty": 16,
        "black_swan_penalty_divisor": 6.5,
        "confidence_floor": 42,
        "regime_penalty_scale": 1.0,
        "regime_boost_scale": 1.0,
        "blocked_risk_level": 76,
        "style_confidence_boost": 2,
        "style_reason": "This style waits for broader structure to line up before taking risk.",
    },
    "position_hold": {
        "key": "position_hold",
        "label": "Position Hold",
        "description": "Longer-duration positioning with stricter quality gates.",
        "preferred_timeframes": {"1h", "4h"},
        "min_confidence": 62,
        "min_rr_ratio": 2.1,
        "size_multiplier": 0.75,
        "timeframe_mismatch_penalty": 9,
        "ema_fast_span": 55,
        "ema_slow_span": 144,
        "rsi_period": 21,
        "momentum_window": 14,
        "momentum_threshold": 0.28,
        "trend_gap_threshold": 0.5,
        "rsi_bull_floor": 54,
        "rsi_bull_ceiling": 66,
        "rsi_bear_floor": 34,
        "rsi_bear_ceiling": 46,
        "rsi_extreme_high": 73,
        "rsi_extreme_low": 27,
        "volume_confirmation_ratio": 1.08,
        "pullback_tolerance_pct": 0.75,
        "reward_multiple": 3.0,
        "stop_atr_multiplier": 2.8,
        "profitability_floor": 2.0,
        "requires_structure_confirmation": True,
        "robustness_penalty": 8,
        "profitability_penalty": 18,
        "black_swan_penalty_divisor": 5.5,
        "confidence_floor": 44,
        "regime_penalty_scale": 1.1,
        "regime_boost_scale": 0.95,
        "blocked_risk_level": 72,
        "style_confidence_boost": 4,
        "style_reason": "This style is more patient and only wants the stronger, longer hold setups.",
    },
}
DEFAULT_TRADE_STYLE = "day_trade"


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_trade_style(style: str) -> str:
    raw_value = str(style or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "scalping": "scalp",
        "intraday": "day_trade",
        "daytrade": "day_trade",
        "day_trading": "day_trade",
        "swing_trade": "swing",
        "hold": "position_hold",
        "position": "position_hold",
        "position_trade": "position_hold",
        "position_trading": "position_hold",
    }
    normalized = aliases.get(raw_value, raw_value)
    return normalized if normalized in TRADE_STYLE_PROFILES else DEFAULT_TRADE_STYLE


def normalize_timeframe_label(timeframe: str) -> str:
    raw_value = str(timeframe or "").strip().lower().replace(" ", "")
    aliases = {
        "1": "1m",
        "3": "3m",
        "5": "5m",
        "15": "15m",
        "30": "30m",
        "60": "1h",
        "120": "2h",
        "240": "4h",
        "d": "1d",
        "day": "1d",
        "ticks": "ticks",
        "tick": "ticks",
    }
    return aliases.get(raw_value, raw_value)


def get_trade_style_profile(style: str = "") -> dict:
    normalized_style = normalize_trade_style(style)
    profile = dict(TRADE_STYLE_PROFILES.get(normalized_style, TRADE_STYLE_PROFILES[DEFAULT_TRADE_STYLE]))
    profile["preferred_timeframes"] = list(profile.get("preferred_timeframes", []))
    profile["style_key"] = normalized_style
    return profile


def list_trade_style_options() -> list[dict]:
    options = []
    for style_key in ["scalp", "day_trade", "swing", "position_hold"]:
        profile = TRADE_STYLE_PROFILES[style_key]
        options.append(
            {
                "value": style_key,
                "label": profile["label"],
                "description": profile["description"],
            }
        )
    return options


def _log_trade_history(
    username: str,
    broker_name: str,
    account_alias: str,
    source: str,
    status: str,
    symbol: str,
    timeframe: str,
    side: str,
    confidence: float = 0.0,
    quantity: float = 0.0,
    notional_usd: float = 0.0,
    entry_price: float = 0.0,
    stop_loss: float = 0.0,
    take_profit: float = 0.0,
    fee_paid: float = 0.0,
    regime: str = "",
    setup_quality: str = "",
    risk_reward_ratio: float = 0.0,
    notes: str = "",
):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                broker_name TEXT,
                account_alias TEXT,
                source TEXT,
                status TEXT,
                symbol TEXT,
                timeframe TEXT,
                side TEXT,
                confidence REAL DEFAULT 0,
                quantity REAL DEFAULT 0,
                notional_usd REAL DEFAULT 0,
                entry_price REAL DEFAULT 0,
                exit_price REAL DEFAULT 0,
                stop_loss REAL DEFAULT 0,
                take_profit REAL DEFAULT 0,
                fee_paid REAL DEFAULT 0,
                pnl_usd REAL DEFAULT 0,
                pnl_pct REAL DEFAULT 0,
                regime TEXT,
                setup_quality TEXT,
                risk_reward_ratio REAL DEFAULT 0,
                notes TEXT,
                opened_at TEXT,
                closed_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO trade_history (
                username, broker_name, account_alias, source, status, symbol, timeframe, side,
                confidence, quantity, notional_usd, entry_price, stop_loss, take_profit,
                fee_paid, regime, setup_quality, risk_reward_ratio, notes, opened_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                broker_name,
                account_alias,
                source,
                status,
                symbol,
                timeframe,
                side,
                float(confidence or 0),
                float(quantity or 0),
                float(notional_usd or 0),
                float(entry_price or 0),
                float(stop_loss or 0),
                float(take_profit or 0),
                float(fee_paid or 0),
                regime,
                setup_quality,
                float(risk_reward_ratio or 0),
                notes,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _get_pair_universe(refresh: bool = False) -> list:
    cache_key = "trading_desk_pairs"
    if refresh or cache_key not in st.session_state:
        try:
            discovered_symbols = discover_tradable_symbols()
        except Exception:
            discovered_symbols = []
        st.session_state[cache_key] = sort_symbols(list(PAIR_FALLBACK) + list(discovered_symbols or []))

    symbols = st.session_state.get(cache_key) or list(PAIR_FALLBACK)
    return sort_symbols(symbols or PAIR_FALLBACK)


def _render_pair_picker(label: str, key_prefix: str, default_symbol: str = "BTCUSDT") -> str:
    pair_universe = _get_pair_universe()
    default_symbol = normalize_market_symbol(default_symbol or "BTCUSDT") or "BTCUSDT"
    if default_symbol not in pair_universe:
        pair_universe = [default_symbol] + [symbol for symbol in pair_universe if symbol != default_symbol]

    search_key = f"{key_prefix}_search"
    select_key = f"{key_prefix}_select"
    query = st.text_input(
        "Search pair",
        value=st.session_state.get(search_key, ""),
        placeholder="BTC, EURUSD, USDJPY...",
        key=search_key,
    ).strip().upper()

    filtered_pairs = [symbol for symbol in pair_universe if query in symbol] if query else pair_universe
    if not filtered_pairs:
        filtered_pairs = pair_universe

    current_symbol = normalize_market_symbol(st.session_state.get(select_key, default_symbol)) or default_symbol
    if current_symbol not in pair_universe:
        pair_universe = [current_symbol] + [symbol for symbol in pair_universe if symbol != current_symbol]
        filtered_pairs = [symbol for symbol in pair_universe if query in symbol] if query else pair_universe
        if not filtered_pairs:
            filtered_pairs = pair_universe

    if query and current_symbol not in filtered_pairs:
        current_symbol = filtered_pairs[0]

    visible_pairs = filtered_pairs[:120]
    if current_symbol not in visible_pairs:
        visible_pairs = [current_symbol] + [symbol for symbol in visible_pairs if symbol != current_symbol]
    if not visible_pairs:
        visible_pairs = list(PAIR_FALLBACK)
        current_symbol = default_symbol if default_symbol in visible_pairs else visible_pairs[0]

    symbol = st.selectbox(
        label,
        visible_pairs,
        index=visible_pairs.index(current_symbol),
        key=select_key,
        help=f"Showing {len(visible_pairs)} of {len(filtered_pairs)} matches.",
    )
    st.caption(f"{len(filtered_pairs)} searchable pairs available.")
    return symbol


def _empty_signal(reason: str, current_balance: float = 10000, extra: dict = None) -> dict:
    payload = {
        "signal": "HOLD",
        "confidence": 0,
        "trade_allowed": False,
        "reason": reason,
        "position_size": {
            "size_percent": 0.0,
            "multiplier": 0.0,
            "volatility_ratio": 0.0,
            "reason": "blocked",
            "position_size_usd": 0.0,
        },
        "entry_exit": {
            "entry_price": 0.0,
            "actual_entry": 0.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "risk_amount": 0.0,
            "reward_amount": 0.0,
            "risk_reward_ratio": 0.0,
            "slippage_cost": 0.0,
            "fee_impact": 0.0,
            "is_profitable_setup": False,
        },
        "regime": {
            "regime": "unknown",
            "action": "WAIT",
            "position_multiplier": 0.0,
            "min_rr_ratio": 1.5,
            "reason": reason,
        },
        "black_swan_risk": {
            "risk_level": 0,
            "is_risky": False,
            "reasons": [],
            "gap_percent": 0.0,
            "vol_ratio": 1.0,
            "volume_spike": 1.0,
        },
        "robustness": {
            "robust": False,
            "reason": "insufficient_data",
        },
        "summary": {
            "bias": "neutral",
            "trend_score": 0,
            "momentum_score": 0,
            "setup_quality": "blocked",
        },
    }
    if extra:
        payload.update(extra)
    return payload


def detect_black_swan_risk(df):
    if df.empty or len(df) < 2:
        return {
            "risk_level": 0,
            "is_risky": False,
            "reasons": [],
            "gap_percent": 0.0,
            "vol_ratio": 1.0,
            "volume_spike": 1.0,
        }

    last = df.iloc[-1]
    prev = df.iloc[-2]

    avg_price = df.tail(90)["close"].mean()
    if avg_price <= 0:
        return {
            "risk_level": 0,
            "is_risky": False,
            "reasons": ["invalid_price_data"],
            "gap_percent": 0.0,
            "vol_ratio": 1.0,
            "volume_spike": 1.0,
        }

    vol_avg = df["volatility"].tail(50).mean() if "volatility" in df.columns else 0
    current_vol = ((last["high"] - last["low"]) / max(last["close"], 1e-9)) * 100
    gap = abs((last["close"] - prev["close"]) / max(prev["close"], 1e-9)) * 100
    vol_avg_vol = df.tail(50)["volume"].mean() if len(df) > 50 else 0

    risk_score = 0
    reasons = []

    if vol_avg > 0 and current_vol > vol_avg * 2:
        risk_score += 30
        reasons.append("abnormal_volatility")
    if gap > 3:
        risk_score += 25
        reasons.append("price_gap")
    if vol_avg_vol > 0 and last["volume"] > vol_avg_vol * 5:
        risk_score += 25
        reasons.append("volume_spike")

    high_90 = df.tail(90)["close"].max()
    low_90 = df.tail(90)["close"].min()
    if last["close"] > high_90 * 0.99 or last["close"] < low_90 * 1.01:
        risk_score += 20
        reasons.append("market_extreme")

    risk_level = min(100, risk_score)
    return {
        "risk_level": risk_level,
        "is_risky": risk_level >= 60,
        "reasons": reasons,
        "gap_percent": round(gap, 2),
        "vol_ratio": round(current_vol / (vol_avg + 1e-4), 2) if vol_avg > 0 else 1.0,
        "volume_spike": round(last["volume"] / (vol_avg_vol + 1e-4), 2) if vol_avg_vol > 0 else 1.0,
    }


def calculate_dynamic_position_size(df, balance, max_risk_percent=1.0):
    if df.empty or len(df) < 20:
        return {
            "size_percent": 0.25,
            "multiplier": 0.25,
            "volatility_ratio": 0.0,
            "reason": "insufficient_data",
            "position_size_usd": round(balance * 0.0025, 2),
        }

    working = df.copy()
    working["volatility"] = ((working["high"] - working["low"]) / working["close"]) * 100

    vol_avg = working["volatility"].tail(20).mean()
    current_vol = working["volatility"].iloc[-1]
    vol_ratio = current_vol / (vol_avg + 1e-4)

    if vol_ratio > 3:
        multiplier, reason = 0.2, "extreme_volatility"
    elif vol_ratio > 2:
        multiplier, reason = 0.4, "high_volatility"
    elif vol_ratio > 1.5:
        multiplier, reason = 0.7, "moderate_volatility"
    else:
        multiplier, reason = 1.0, "normal_volatility"

    size_percent = max_risk_percent * multiplier
    return {
        "size_percent": round(size_percent, 2),
        "multiplier": multiplier,
        "volatility_ratio": round(vol_ratio, 2),
        "reason": reason,
        "position_size_usd": round(balance * size_percent / 100, 2),
    }


def calculate_optimal_entry_exit(df, signal, atr_value, style_profile: dict | None = None):
    style_profile = style_profile or {}
    last_price = _safe_float(df.iloc[-1]["close"])
    exchange_fee = 0.1
    base_slippage = 0.05
    stop_atr_multiplier = _safe_float(style_profile.get("stop_atr_multiplier"), 2.0)
    reward_multiple = _safe_float(style_profile.get("reward_multiple"), 2.0)
    profitability_floor = _safe_float(style_profile.get("profitability_floor"), 1.5)
    minimum_stop_ratio = 0.0012 if normalize_trade_style(style_profile.get("style_key", "")) == "scalp" else 0.002
    stop_loss_distance = max(_safe_float(atr_value), last_price * minimum_stop_ratio) * stop_atr_multiplier

    if signal == "BUY":
        slippage_amount = last_price * (base_slippage / 100)
        actual_entry = last_price + slippage_amount
        stop_loss = actual_entry - stop_loss_distance
        reward_distance = (actual_entry - stop_loss) * reward_multiple
        take_profit = actual_entry + reward_distance
        exit_fee_impact = actual_entry * (exchange_fee / 100)
        adjusted_take_profit = take_profit - exit_fee_impact
        risk = actual_entry - stop_loss
        reward = adjusted_take_profit - actual_entry
    else:
        slippage_amount = last_price * (base_slippage / 100)
        actual_entry = last_price - slippage_amount
        stop_loss = actual_entry + stop_loss_distance
        reward_distance = (stop_loss - actual_entry) * reward_multiple
        take_profit = actual_entry - reward_distance
        exit_fee_impact = actual_entry * (exchange_fee / 100)
        adjusted_take_profit = take_profit + exit_fee_impact
        risk = stop_loss - actual_entry
        reward = actual_entry - adjusted_take_profit

    rr_ratio = max(reward, 0.0) / risk if risk > 1e-12 else 0.0
    return {
        "entry_price": round(last_price, 8),
        "actual_entry": round(actual_entry, 8),
        "stop_loss": round(stop_loss, 8),
        "take_profit": round(adjusted_take_profit, 8),
        "risk_amount": round(risk, 8),
        "reward_amount": round(reward, 8),
        "risk_reward_ratio": round(rr_ratio, 2),
        "slippage_cost": round(slippage_amount, 8),
        "fee_impact": round(exit_fee_impact, 8),
        "reward_multiple": round(reward_multiple, 2),
        "profitability_floor": round(profitability_floor, 2),
        "is_profitable_setup": rr_ratio >= profitability_floor,
    }


def get_regime_strategy(df):
    if df.empty or len(df) < 50:
        return {
            "regime": "unknown",
            "action": "WAIT",
            "position_multiplier": 0.5,
            "min_rr_ratio": 1.5,
            "reason": "Not enough data to classify market regime",
        }

    working = df.copy()
    working["ema_20"] = working["close"].ewm(span=20).mean()
    working["ema_50"] = working["close"].ewm(span=50).mean()
    working["volatility"] = ((working["high"] - working["low"]) / working["close"]) * 100

    vol_avg = working["volatility"].tail(20).mean()
    current_vol = working["volatility"].iloc[-1]
    last = working.iloc[-1]

    if vol_avg > 0 and current_vol > vol_avg * 2:
        regime = "volatile"
    elif last["ema_20"] > last["ema_50"] * 1.01:
        regime = "strong_uptrend"
    elif last["ema_20"] < last["ema_50"] * 0.99:
        regime = "strong_downtrend"
    elif abs(last["ema_20"] - last["ema_50"]) / max(last["ema_50"], 1e-9) < 0.01:
        regime = "ranging"
    else:
        regime = "weak_trend"

    strategies = {
        "volatile": {
            "regime": "volatile",
            "action": "REDUCE_SIZE",
            "confidence_reduction": 35,
            "position_multiplier": 0.25,
            "min_rr_ratio": 2.5,
            "reason": "Volatility is elevated, so the model is protecting capital.",
        },
        "strong_uptrend": {
            "regime": "strong_uptrend",
            "action": "TREND_FOLLOWING",
            "confidence_boost": 12,
            "position_multiplier": 1.0,
            "min_rr_ratio": 1.5,
            "reason": "Trend structure remains bullish with momentum support.",
        },
        "strong_downtrend": {
            "regime": "strong_downtrend",
            "action": "TREND_FOLLOWING",
            "confidence_boost": 12,
            "position_multiplier": 1.0,
            "min_rr_ratio": 1.5,
            "reason": "Trend structure remains bearish with downside control.",
        },
        "ranging": {
            "regime": "ranging",
            "action": "RANGE_TRADING",
            "confidence_reduction": 18,
            "position_multiplier": 0.7,
            "min_rr_ratio": 1.8,
            "reason": "Price is rotating inside a range, so breakout conviction is lower.",
        },
        "weak_trend": {
            "regime": "weak_trend",
            "action": "CAUTIOUS",
            "confidence_reduction": 10,
            "position_multiplier": 0.8,
            "min_rr_ratio": 1.8,
            "reason": "Trend direction is present but not yet strong enough for full conviction.",
        },
    }
    return strategies[regime]


def validate_strategy_robustness(df):
    if df.empty or len(df) < 200:
        return {"robust": False, "reason": "insufficient_data"}

    working = df.copy().reset_index(drop=True)
    period_size = len(working) // 4
    periods = [working.iloc[i:i + period_size].copy() for i in range(0, period_size * 4, period_size)]

    volatility_scores = []
    trend_scores = []

    for period in periods:
        if period.empty:
            continue
        period["volatility"] = ((period["high"] - period["low"]) / period["close"]) * 100
        volatility_scores.append(period["volatility"].mean())
        period["ema_20"] = period["close"].ewm(span=20).mean()
        period["ema_50"] = period["close"].ewm(span=50).mean()
        trend_strength = abs(period["ema_20"].iloc[-1] - period["ema_50"].iloc[-1]) / max(period["close"].iloc[-1], 1e-9)
        trend_scores.append(trend_strength)

    vol_std = pd.Series(volatility_scores).std()
    trend_std = pd.Series(trend_scores).std()
    is_diverse = (vol_std or 0) > 0.2 and (trend_std or 0) > 0.002
    return {
        "robust": bool(is_diverse),
        "volatility_std": round(vol_std if pd.notna(vol_std) else 0.0, 4),
        "trend_std": round(trend_std if pd.notna(trend_std) else 0.0, 4),
        "reason": "Data covers diverse market conditions" if is_diverse else "Signal robustness is limited by uniform price structure",
    }


class ProfitOptimizer:
    def __init__(self):
        self.trades = []
        self.win_rate = 0
        self.avg_win = 0
        self.avg_loss = 0
        self.profit_factor = 0

    def add_trade(self, entry, exit_price, signal_type, pnl_percent):
        self.trades.append(
            {
                "entry": entry,
                "exit": exit_price,
                "type": signal_type,
                "pnl_percent": pnl_percent,
                "profit": pnl_percent > 0,
            }
        )
        self._recalculate()

    def _recalculate(self):
        if not self.trades:
            return

        wins = [trade for trade in self.trades if trade["profit"]]
        losses = [trade for trade in self.trades if not trade["profit"]]
        self.win_rate = len(wins) / len(self.trades) * 100
        self.avg_win = sum(trade["pnl_percent"] for trade in wins) / len(wins) if wins else 0
        self.avg_loss = abs(sum(trade["pnl_percent"] for trade in losses) / len(losses)) if losses else 0
        gross_profit = sum(trade["pnl_percent"] for trade in wins) if wins else 0
        gross_loss = abs(sum(trade["pnl_percent"] for trade in losses)) if losses else 0
        self.profit_factor = gross_profit / (gross_loss + 1e-4)

    def get_optimal_settings(self):
        if len(self.trades) < 10:
            return {"recommendation": "insufficient_trades", "settings": {}}

        settings = {}
        if self.win_rate < 40:
            settings["action"] = "improve_entry"
            settings["reason"] = f"Win rate {self.win_rate:.1f}% is too low"
            settings["suggestion"] = "Add more confirmation before taking the setup."
        elif self.avg_loss > self.avg_win * 1.5:
            settings["action"] = "improve_stop_loss"
            settings["reason"] = f"Average loss {self.avg_loss:.2f}% is larger than average win {self.avg_win:.2f}%"
            settings["suggestion"] = "Tighten stop loss placement and keep ATR-based exits."
        elif self.profit_factor < 1.0:
            settings["action"] = "reduce_position_size"
            settings["reason"] = f"Profit factor {self.profit_factor:.2f} is below breakeven quality"
            settings["suggestion"] = "Scale down size and trade only higher-confidence signals."
        else:
            settings["action"] = "optimize"
            settings["reason"] = "Current settings are performing well"
            settings["suggestion"] = "Maintain the strategy and review sizing gradually."

        settings["stats"] = {
            "win_rate": round(self.win_rate, 2),
            "avg_win": round(self.avg_win, 4),
            "avg_loss": round(self.avg_loss, 4),
            "profit_factor": round(self.profit_factor, 2),
            "total_trades": len(self.trades),
        }
        return settings


def _load_closed_trade_history(username: str, limit: int = 80) -> pd.DataFrame:
    if not username:
        return pd.DataFrame()

    query = """
        SELECT symbol, timeframe, side, entry_price, exit_price, pnl_usd, pnl_pct,
               confidence, risk_reward_ratio, regime, setup_quality, closed_at, created_at
        FROM trade_history
        WHERE username=? AND status='closed'
        ORDER BY COALESCE(closed_at, created_at) DESC, rowid DESC
        LIMIT ?
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        history = pd.read_sql_query(query, conn, params=(username, int(limit or 80)))
    except Exception:
        history = pd.DataFrame()
    finally:
        conn.close()

    if history.empty:
        return history

    numeric_cols = [
        "entry_price",
        "exit_price",
        "pnl_usd",
        "pnl_pct",
        "confidence",
        "risk_reward_ratio",
    ]
    for column in numeric_cols:
        if column in history.columns:
            history[column] = pd.to_numeric(history[column], errors="coerce").fillna(0.0)

    for column in ["symbol", "timeframe", "side", "regime", "setup_quality"]:
        if column in history.columns:
            history[column] = history[column].fillna("").astype(str)
    return history


def _trade_slice_stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {
            "count": 0,
            "net_pnl_pct": 0.0,
            "net_pnl_usd": 0.0,
            "win_rate": 0.0,
            "avg_confidence": 0.0,
        }

    pnl_pct = pd.to_numeric(trades["pnl_pct"], errors="coerce").fillna(0.0)
    pnl_usd = pd.to_numeric(trades["pnl_usd"], errors="coerce").fillna(0.0)
    confidence = pd.to_numeric(trades.get("confidence"), errors="coerce").fillna(0.0)
    wins = pnl_pct[pnl_pct > 0]
    return {
        "count": int(len(trades)),
        "net_pnl_pct": round(float(pnl_pct.sum()), 4),
        "net_pnl_usd": round(float(pnl_usd.sum()), 4),
        "win_rate": round(float((len(wins) / len(trades)) * 100), 2) if len(trades) else 0.0,
        "avg_confidence": round(float(confidence.mean()), 2) if len(confidence) else 0.0,
    }


def _recent_losing_streak(trades: pd.DataFrame) -> int:
    if trades.empty:
        return 0

    streak = 0
    pnl_series = pd.to_numeric(trades["pnl_pct"], errors="coerce").fillna(0.0)
    for pnl_value in pnl_series.tolist():
        if pnl_value < 0:
            streak += 1
        else:
            break
    return streak


def _daily_loss_guard(trades: pd.DataFrame, current_balance: float = 0.0) -> dict:
    balance_value = max(_safe_float(current_balance, 0.0), 0.0)
    baseline_cap_usd = balance_value * 0.015 if balance_value > 0 else 0.0
    guard = {
        "today_net_usd": 0.0,
        "today_net_pct": 0.0,
        "cap_usd": round(baseline_cap_usd, 2),
        "cap_pct": round((baseline_cap_usd / balance_value) * 100, 2) if balance_value > 0 else 0.0,
        "warning": False,
        "cap_hit": False,
        "avg_red_day_usd": 0.0,
        "recent_red_days": 0,
    }
    if trades.empty:
        return guard

    working = trades.copy()
    closed_series = working["closed_at"].fillna("").astype(str).str.slice(0, 10)
    created_series = working["created_at"].fillna("").astype(str).str.slice(0, 10)
    working["closed_day"] = closed_series.where(closed_series.ne(""), created_series)
    working = working[working["closed_day"] != ""].copy()
    if working.empty:
        return guard

    daily = (
        working.groupby("closed_day", dropna=False)
        .agg(net_pnl_usd=("pnl_usd", "sum"), net_pnl_pct=("pnl_pct", "sum"), trades=("pnl_usd", "count"))
        .reset_index()
        .sort_values("closed_day", ascending=False)
    )
    if daily.empty:
        return guard

    today_key = datetime.now().date().isoformat()
    today_row = daily[daily["closed_day"] == today_key]
    if not today_row.empty:
        guard["today_net_usd"] = round(float(today_row.iloc[0]["net_pnl_usd"]), 4)
        guard["today_net_pct"] = round(float(today_row.iloc[0]["net_pnl_pct"]), 4)

    red_days = daily[daily["net_pnl_usd"] < 0].copy()
    guard["recent_red_days"] = int(len(red_days.head(7)))
    if not red_days.empty:
        avg_red_day = abs(float(red_days["net_pnl_usd"].mean()))
        guard["avg_red_day_usd"] = round(avg_red_day, 2)
        if balance_value > 0:
            baseline_cap_usd = max(baseline_cap_usd, avg_red_day * 1.1)
            baseline_cap_usd = min(baseline_cap_usd, balance_value * 0.03)
        else:
            baseline_cap_usd = avg_red_day * 1.1

    guard["cap_usd"] = round(max(baseline_cap_usd, 0.0), 2)
    guard["cap_pct"] = round((guard["cap_usd"] / balance_value) * 100, 2) if balance_value > 0 and guard["cap_usd"] > 0 else 0.0
    if guard["cap_usd"] > 0:
        guard["warning"] = guard["today_net_usd"] <= (-guard["cap_usd"] * 0.75)
        guard["cap_hit"] = guard["today_net_usd"] <= (-guard["cap_usd"])
    return guard


def get_adaptive_signal_profile(
    username: str,
    symbol: str = "",
    timeframe: str = "",
    limit: int = 80,
    current_balance: float = 0.0,
    trade_style: str = "",
) -> dict:
    style_profile = get_trade_style_profile(trade_style)
    base_min_confidence = int(style_profile.get("min_confidence", 55) or 55)
    base_min_rr = _safe_float(style_profile.get("min_rr_ratio"), 1.5)
    profile = {
        "ready": False,
        "action": "neutral",
        "suggestion": "Trade history is still building, so Finwise is using the base signal model.",
        "confidence_delta": 0,
        "size_multiplier": 1.0,
        "min_rr_ratio": base_min_rr,
        "min_confidence": base_min_confidence,
        "cooldown": False,
        "notes": [],
        "stats": {"total_trades": 0, "recent_trades": 0, "win_rate": 0.0, "profit_factor": 0.0},
        "recent": {"count": 0, "net_pnl_pct": 0.0, "net_pnl_usd": 0.0, "win_rate": 0.0, "avg_confidence": 0.0},
        "symbol_focus": {"count": 0, "net_pnl_pct": 0.0, "net_pnl_usd": 0.0, "win_rate": 0.0, "avg_confidence": 0.0},
        "timeframe_focus": {"count": 0, "net_pnl_pct": 0.0, "net_pnl_usd": 0.0, "win_rate": 0.0, "avg_confidence": 0.0},
        "daily_guard": {"today_net_usd": 0.0, "today_net_pct": 0.0, "cap_usd": 0.0, "cap_pct": 0.0, "warning": False, "cap_hit": False},
        "thresholds": {
            "symbol": {"min_confidence": base_min_confidence, "min_rr_ratio": base_min_rr, "status": "neutral"},
            "timeframe": {"min_confidence": base_min_confidence, "min_rr_ratio": base_min_rr, "status": "neutral"},
            "effective": {"min_confidence": base_min_confidence, "min_rr_ratio": base_min_rr},
        },
    }

    history = _load_closed_trade_history(username=username, limit=limit)
    if history.empty:
        return profile

    optimizer = ProfitOptimizer()
    for row in history.iloc[::-1].itertuples(index=False):
        optimizer.add_trade(
            _safe_float(getattr(row, "entry_price", 0.0)),
            _safe_float(getattr(row, "exit_price", 0.0)),
            str(getattr(row, "side", "") or "").upper(),
            _safe_float(getattr(row, "pnl_pct", 0.0)),
        )

    optimizer_settings = optimizer.get_optimal_settings()
    recent_trades = history.head(12).copy()
    symbol_focus = history[history["symbol"].str.upper() == str(symbol or "").upper()].head(12).copy() if symbol else pd.DataFrame()
    timeframe_focus = history[history["timeframe"] == str(timeframe or "")].head(12).copy() if timeframe else pd.DataFrame()
    losing_streak = _recent_losing_streak(history)

    profile["ready"] = len(history) >= 5
    profile["stats"] = {
        **optimizer_settings.get("stats", {}),
        "total_trades": int(len(history)),
        "recent_trades": int(len(recent_trades)),
    }
    profile["recent"] = _trade_slice_stats(recent_trades)
    profile["symbol_focus"] = _trade_slice_stats(symbol_focus)
    profile["timeframe_focus"] = _trade_slice_stats(timeframe_focus)
    profile["daily_guard"] = _daily_loss_guard(history, current_balance=current_balance)

    if optimizer_settings.get("recommendation") == "insufficient_trades":
        profile["notes"].append("Closed-trade sample is still small, so only light coaching is applied.")
    else:
        profile["action"] = optimizer_settings.get("action", "neutral")
        profile["suggestion"] = optimizer_settings.get("suggestion", profile["suggestion"])
        reason = optimizer_settings.get("reason", "")
        if reason:
            profile["notes"].append(reason)

    action = profile["action"]
    if action == "improve_entry":
        profile["confidence_delta"] -= 8
        profile["size_multiplier"] *= 0.82
        profile["min_rr_ratio"] = max(profile["min_rr_ratio"], round(base_min_rr + 0.2, 2))
        profile["min_confidence"] = max(profile["min_confidence"], base_min_confidence + 6)
    elif action == "improve_stop_loss":
        profile["confidence_delta"] -= 4
        profile["size_multiplier"] *= 0.88
        profile["min_rr_ratio"] = max(profile["min_rr_ratio"], round(base_min_rr + 0.15, 2))
        profile["min_confidence"] = max(profile["min_confidence"], base_min_confidence + 4)
    elif action == "reduce_position_size":
        profile["confidence_delta"] -= 6
        profile["size_multiplier"] *= 0.72
        profile["min_rr_ratio"] = max(profile["min_rr_ratio"], round(base_min_rr + 0.18, 2))
        profile["min_confidence"] = max(profile["min_confidence"], base_min_confidence + 5)
    elif action == "optimize":
        profile["confidence_delta"] += 3
        profile["size_multiplier"] *= 1.05
        profile["notes"].append("Recent execution quality supports normal sizing on stronger setups.")

    recent_stats = profile["recent"]
    if recent_stats["count"] >= 5 and recent_stats["net_pnl_pct"] < 0:
        profile["confidence_delta"] -= 4
        profile["size_multiplier"] *= 0.9
        profile["min_confidence"] = max(profile["min_confidence"], base_min_confidence + 3)
        profile["notes"].append("Recent closed trades are net negative, so the worker is filtering harder.")

    if losing_streak >= 3:
        profile["confidence_delta"] -= 6
        profile["size_multiplier"] *= 0.75
        profile["min_confidence"] = max(profile["min_confidence"], base_min_confidence + 6)
        profile["notes"].append(f"Current losing streak: {losing_streak}. Finwise is reducing size and demanding more confirmation.")
    if losing_streak >= 4 and recent_stats["net_pnl_pct"] <= -4:
        profile["cooldown"] = True
        profile["action"] = "cooldown"
        profile["notes"].append("Execution cooldown is active until trade quality recovers.")

    symbol_stats = profile["symbol_focus"]
    if symbol_stats["count"] >= 4 and symbol_stats["net_pnl_pct"] < 0:
        profile["confidence_delta"] -= 4
        profile["size_multiplier"] *= 0.85
        profile["thresholds"]["symbol"] = {
            "min_confidence": base_min_confidence + 5,
            "min_rr_ratio": round(base_min_rr + 0.25, 2),
            "status": "tightened",
        }
        profile["notes"].append(f"{symbol} has been underperforming in your journal, so this market is being treated more cautiously.")
    elif symbol_stats["count"] >= 5 and symbol_stats["net_pnl_pct"] > 0 and symbol_stats["win_rate"] >= 55:
        profile["confidence_delta"] += 2
        profile["size_multiplier"] *= 1.03
        profile["thresholds"]["symbol"] = {
            "min_confidence": base_min_confidence,
            "min_rr_ratio": base_min_rr,
            "status": "favored",
        }
        profile["notes"].append(f"{symbol} has been a relative strength market in your journal.")

    timeframe_stats = profile["timeframe_focus"]
    if timeframe_stats["count"] >= 4 and timeframe_stats["net_pnl_pct"] < 0:
        profile["confidence_delta"] -= 3
        profile["size_multiplier"] *= 0.9
        profile["thresholds"]["timeframe"] = {
            "min_confidence": base_min_confidence + 4,
            "min_rr_ratio": round(base_min_rr + 0.2, 2),
            "status": "tightened",
        }
        profile["notes"].append(f"Your {timeframe} executions have been soft recently, so the worker is tightening quality gates.")
    elif timeframe_stats["count"] >= 5 and timeframe_stats["net_pnl_pct"] > 0 and timeframe_stats["win_rate"] >= 55:
        profile["confidence_delta"] += 1
        profile["thresholds"]["timeframe"] = {
            "min_confidence": base_min_confidence,
            "min_rr_ratio": base_min_rr,
            "status": "favored",
        }

    daily_guard = profile["daily_guard"]
    if daily_guard.get("warning"):
        profile["confidence_delta"] -= 3
        profile["size_multiplier"] *= 0.84
        profile["min_confidence"] = max(profile["min_confidence"], base_min_confidence + 4)
        profile["min_rr_ratio"] = max(profile["min_rr_ratio"], round(base_min_rr + 0.25, 2))
        profile["notes"].append(
            f"Today's closed-trade drawdown is ${float(daily_guard.get('today_net_usd', 0) or 0):,.2f}, close to the learned daily loss cap."
        )
    if daily_guard.get("cap_hit"):
        profile["cooldown"] = True
        profile["action"] = "daily_loss_cap"
        profile["confidence_delta"] -= 6
        profile["size_multiplier"] *= 0.65
        profile["min_confidence"] = max(profile["min_confidence"], base_min_confidence + 8)
        profile["min_rr_ratio"] = max(profile["min_rr_ratio"], round(base_min_rr + 0.35, 2))
        profile["notes"].append(
            f"Daily loss cap reached: ${float(daily_guard.get('today_net_usd', 0) or 0):,.2f} vs cap ${float(daily_guard.get('cap_usd', 0) or 0):,.2f}."
        )

    profile["size_multiplier"] = round(max(0.35, min(1.2, profile["size_multiplier"])), 2)
    profile["confidence_delta"] = int(round(profile["confidence_delta"]))
    profile["min_rr_ratio"] = round(max(base_min_rr, min(max(2.4, base_min_rr + 0.6), profile["min_rr_ratio"])), 2)
    profile["min_confidence"] = int(max(base_min_confidence, min(min(80, base_min_confidence + 14), profile["min_confidence"])))
    profile["min_confidence"] = max(
        profile["min_confidence"],
        int(profile["thresholds"]["symbol"].get("min_confidence", 55)),
        int(profile["thresholds"]["timeframe"].get("min_confidence", 55)),
    )
    profile["min_rr_ratio"] = round(
        max(
            profile["min_rr_ratio"],
            float(profile["thresholds"]["symbol"].get("min_rr_ratio", 1.5)),
            float(profile["thresholds"]["timeframe"].get("min_rr_ratio", 1.5)),
        ),
        2,
    )
    profile["thresholds"]["effective"] = {
        "min_confidence": int(profile["min_confidence"]),
        "min_rr_ratio": float(profile["min_rr_ratio"]),
    }
    return profile


def ai_signal_for_user(
    username: str,
    df,
    symbol="BTCUSDT",
    current_balance=10000,
    timeframe: str = "",
    trade_style: str = "",
):
    normalized_trade_style = normalize_trade_style(trade_style)
    result = ai_signal(
        df,
        symbol=symbol,
        current_balance=current_balance,
        timeframe=timeframe,
        trade_style=normalized_trade_style,
    )
    profile = get_adaptive_signal_profile(
        username=username,
        symbol=symbol,
        timeframe=timeframe,
        current_balance=current_balance,
        trade_style=normalized_trade_style,
    )
    result["adaptive_profile"] = profile

    if not profile.get("ready"):
        return result

    base_confidence = _safe_float(result.get("confidence"), 0.0)
    adjusted_confidence = max(0, min(100, round(base_confidence + profile.get("confidence_delta", 0))))
    result["confidence_base"] = round(base_confidence, 2)
    result["confidence"] = adjusted_confidence

    position_size = dict(result.get("position_size", {}) or {})
    base_size_usd = _safe_float(position_size.get("position_size_usd"), 0.0)
    base_size_percent = _safe_float(position_size.get("size_percent"), 0.0)
    adaptive_multiplier = _safe_float(profile.get("size_multiplier"), 1.0)
    position_size["base_position_size_usd"] = round(base_size_usd, 2)
    position_size["base_size_percent"] = round(base_size_percent, 2)
    position_size["adaptive_multiplier"] = adaptive_multiplier
    position_size["position_size_usd"] = round(base_size_usd * adaptive_multiplier, 2)
    position_size["size_percent"] = round(base_size_percent * adaptive_multiplier, 2)
    position_size["adaptive_reason"] = profile.get("suggestion", "")
    result["position_size"] = position_size

    entry_exit = dict(result.get("entry_exit", {}) or {})
    rr_ratio = _safe_float(entry_exit.get("risk_reward_ratio"), 0.0)
    adaptive_min_rr = _safe_float(profile.get("min_rr_ratio"), 1.5)
    entry_exit["adaptive_min_rr_ratio"] = adaptive_min_rr
    entry_exit["passes_adaptive_rr"] = rr_ratio >= adaptive_min_rr
    if not entry_exit["passes_adaptive_rr"]:
        entry_exit["is_profitable_setup"] = False
    result["entry_exit"] = entry_exit

    base_signal = str(result.get("signal", "HOLD") or "HOLD").upper()
    hold_reasons = []
    daily_guard = profile.get("daily_guard") or {}
    if bool(daily_guard.get("cap_hit")):
        hold_reasons.append("your learned daily loss cap has been reached")
    elif profile.get("cooldown"):
        hold_reasons.append("recent closed trades triggered a temporary execution cooldown")
    if base_signal in {"BUY", "SELL"} and adjusted_confidence < _safe_float(profile.get("min_confidence"), 55):
        hold_reasons.append(
            f"adaptive confidence gate requires {int(profile.get('min_confidence', 55))}% but this setup is {adjusted_confidence}%"
        )
    if base_signal in {"BUY", "SELL"} and rr_ratio < adaptive_min_rr:
        hold_reasons.append(f"adaptive reward/risk gate requires {adaptive_min_rr:.2f}R but this setup is {rr_ratio:.2f}R")

    if hold_reasons:
        result["signal"] = "HOLD"
        result["trade_allowed"] = False
        result["reason"] = "Finwise AI is standing aside because " + "; ".join(hold_reasons) + "."
        summary = dict(result.get("summary", {}) or {})
        summary["setup_quality"] = "blocked" if profile.get("cooldown") else "cautious"
        result["summary"] = summary
    else:
        current_reason = str(result.get("reason", "") or "").strip()
        suggestion = str(profile.get("suggestion", "") or "").strip()
        if suggestion and suggestion.lower() not in current_reason.lower():
            result["reason"] = f"{current_reason} Adaptive note: {suggestion}".strip()

    return result


def fetch_bybit_klines(symbol="BTCUSDT", interval="1", limit=200):
    return fetch_market_klines(symbol=symbol, interval=interval, limit=limit)


def add_indicators(df, style_profile: dict | None = None):
    style_profile = style_profile or {}
    working = df.copy()
    ema_fast_span = max(3, int(style_profile.get("ema_fast_span", 20) or 20))
    ema_slow_span = max(ema_fast_span + 1, int(style_profile.get("ema_slow_span", 50) or 50))
    rsi_period = max(5, int(style_profile.get("rsi_period", 14) or 14))
    atr_period = max(7, min(21, rsi_period))
    momentum_window = max(2, int(style_profile.get("momentum_window", 5) or 5))
    volume_window = max(10, momentum_window * 4)

    working["ema_fast"] = working["close"].ewm(span=ema_fast_span).mean()
    working["ema_slow"] = working["close"].ewm(span=ema_slow_span).mean()

    delta = working["close"].diff()
    gain = delta.clip(lower=0).rolling(rsi_period).mean()
    loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
    rs = gain / loss.replace(0, 1e-9)
    working["rsi"] = 100 - (100 / (1 + rs))

    high_low = (working["high"] - working["low"]).abs()
    high_close = (working["high"] - working["close"].shift()).abs()
    low_close = (working["low"] - working["close"].shift()).abs()
    working["tr"] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    working["atr"] = working["tr"].rolling(atr_period).mean()
    working["volatility"] = ((working["high"] - working["low"]) / working["close"]) * 100
    working["momentum"] = working["close"].pct_change(momentum_window) * 100
    working["volume_ma"] = working["volume"].rolling(volume_window).mean()
    working["volume_ratio"] = working["volume"] / working["volume_ma"].replace(0, pd.NA)
    working["volume_ratio"] = pd.to_numeric(working["volume_ratio"], errors="coerce").fillna(1.0)
    working["trend_gap_pct"] = ((working["ema_fast"] - working["ema_slow"]) / working["ema_slow"].replace(0, 1e-9)) * 100
    working["price_to_fast_gap_pct"] = ((working["close"] - working["ema_fast"]) / working["ema_fast"].replace(0, 1e-9)) * 100
    return working


def _is_synthetic_symbol(symbol: str) -> bool:
    normalized = str(symbol or "").upper()
    synthetic_markers = ("R_", "1HZ", "BOOM", "CRASH", "STEP", "JD", "RB")
    return normalized.startswith(synthetic_markers) or any(marker in normalized for marker in synthetic_markers[1:])


def _structure_window(style_profile: dict) -> int:
    style_key = str(style_profile.get("style_key", "") or "")
    if style_key == "scalp":
        return 28
    if style_key == "day_trade":
        return 42
    return 64


def analyze_structure_context(df, signal: str, symbol: str = "", style_profile: dict | None = None) -> dict:
    style_profile = style_profile or {}
    if df is None or df.empty or len(df) < 40:
        return {
            "ready": False,
            "bias": "neutral",
            "score": 0,
            "patterns": [],
            "warnings": ["insufficient structure history"],
            "support": 0.0,
            "resistance": 0.0,
            "volatility_regime": "unknown",
            "reason": "Not enough candles for market-structure confirmation.",
        }

    working = df.copy().reset_index(drop=True)
    for column in ["open", "high", "low", "close", "atr", "ema_fast", "ema_slow", "volume", "volume_ma"]:
        if column not in working.columns:
            working[column] = 0.0
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working = working.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if len(working) < 40:
        return {
            "ready": False,
            "bias": "neutral",
            "score": 0,
            "patterns": [],
            "warnings": ["insufficient clean structure history"],
            "support": 0.0,
            "resistance": 0.0,
            "volatility_regime": "unknown",
            "reason": "Not enough clean candles for structure confirmation.",
        }

    signal = str(signal or "HOLD").upper()
    is_synthetic = _is_synthetic_symbol(symbol)
    window = min(_structure_window(style_profile), max(20, len(working) - 2))
    recent = working.tail(window)
    prior = working.iloc[max(0, len(working) - window - 10): max(1, len(working) - 5)]
    if prior.empty:
        prior = working.iloc[:-1]
    setup_levels = working.iloc[max(0, len(working) - window - 4): max(1, len(working) - 3)]
    if setup_levels.empty:
        setup_levels = prior

    last = working.iloc[-1]
    previous = working.iloc[-2]
    close = _safe_float(last.get("close"))
    open_value = _safe_float(last.get("open"))
    high = _safe_float(last.get("high"))
    low = _safe_float(last.get("low"))
    atr = max(_safe_float(last.get("atr")), close * 0.0012, 1e-9)
    ema_fast = _safe_float(last.get("ema_fast"))
    ema_slow = _safe_float(last.get("ema_slow"))

    support = _safe_float(recent["low"].iloc[:-1].min() if len(recent) > 1 else recent["low"].min(), close)
    resistance = _safe_float(recent["high"].iloc[:-1].max() if len(recent) > 1 else recent["high"].max(), close)
    prior_high = _safe_float(prior["high"].max(), resistance)
    prior_low = _safe_float(prior["low"].min(), support)
    retest_resistance = _safe_float(setup_levels["high"].max(), resistance)
    retest_support = _safe_float(setup_levels["low"].min(), support)
    prior_close = _safe_float(previous.get("close"), close)

    candle_range = max(high - low, 1e-9)
    body_ratio = abs(close - open_value) / candle_range
    upper_wick_ratio = (high - max(open_value, close)) / candle_range
    lower_wick_ratio = (min(open_value, close) - low) / candle_range
    distance_to_resistance_atr = (resistance - close) / atr
    distance_to_support_atr = (close - support) / atr
    price_to_fast_atr = abs(close - ema_fast) / atr if atr > 0 else 0.0

    recent_volatility = ((recent["high"] - recent["low"]) / recent["close"].replace(0, pd.NA) * 100).dropna()
    current_volatility = ((high - low) / max(close, 1e-9)) * 100
    avg_volatility = float(recent_volatility.tail(20).mean() or 0.0)
    vol_ratio = current_volatility / max(avg_volatility, 1e-9) if avg_volatility > 0 else 1.0
    if vol_ratio >= 2.8:
        volatility_regime = "extreme"
    elif vol_ratio >= 1.65:
        volatility_regime = "expanded"
    elif vol_ratio <= 0.45:
        volatility_regime = "compressed"
    else:
        volatility_regime = "normal"

    trend_bias = "bullish" if ema_fast > ema_slow and close > ema_fast else "bearish" if ema_fast < ema_slow and close < ema_fast else "neutral"
    market_structure_bias = "bullish" if close > prior_high else "bearish" if close < prior_low else trend_bias

    bullish_sweep = low < prior_low and close > prior_low
    bearish_sweep = high > prior_high and close < prior_high
    bullish_wick_rejection = lower_wick_ratio >= 0.36 and close > open_value and close > (low + candle_range * 0.55)
    bearish_wick_rejection = upper_wick_ratio >= 0.36 and close < open_value and close < (high - candle_range * 0.55)
    bullish_pullback = trend_bias == "bullish" and abs(close - ema_fast) <= atr * 0.9 and close >= ema_fast and close > open_value
    bearish_pullback = trend_bias == "bearish" and abs(close - ema_fast) <= atr * 0.9 and close <= ema_fast and close < open_value
    bullish_breakout_retest = prior_close > retest_resistance and low <= retest_resistance + atr * 0.25 and close > retest_resistance
    bearish_breakout_retest = prior_close < retest_support and high >= retest_support - atr * 0.25 and close < retest_support
    bullish_break_of_structure = close > prior_high
    bearish_break_of_structure = close < prior_low

    patterns = []
    warnings = []
    score = 0

    if signal == "BUY":
        if market_structure_bias == "bullish":
            score += 16
        elif market_structure_bias == "bearish":
            warnings.append("market structure is bearish")
            score -= 18
        if bullish_sweep:
            patterns.append("bullish liquidity sweep")
            score += 18
        if bullish_pullback:
            patterns.append("bullish pullback")
            score += 14
        if bullish_breakout_retest:
            patterns.append("bullish breakout retest")
            score += 18
        if bullish_wick_rejection:
            patterns.append("bullish wick rejection")
            score += 12
        if bullish_break_of_structure:
            patterns.append("bullish break of structure")
            score += 12
        if bearish_wick_rejection:
            warnings.append("latest candle rejects upside")
            score -= 14
        if distance_to_resistance_atr < 0.65 and not bullish_breakout_retest and not bullish_break_of_structure:
            warnings.append("buy is too close to resistance")
            score -= 18
        if price_to_fast_atr > (1.9 if is_synthetic else 2.4) and not bullish_sweep:
            warnings.append("buy entry is extended away from value")
            score -= 12
    elif signal == "SELL":
        if market_structure_bias == "bearish":
            score += 16
        elif market_structure_bias == "bullish":
            warnings.append("market structure is bullish")
            score -= 18
        if bearish_sweep:
            patterns.append("bearish liquidity sweep")
            score += 18
        if bearish_pullback:
            patterns.append("bearish pullback")
            score += 14
        if bearish_breakout_retest:
            patterns.append("bearish breakout retest")
            score += 18
        if bearish_wick_rejection:
            patterns.append("bearish wick rejection")
            score += 12
        if bearish_break_of_structure:
            patterns.append("bearish break of structure")
            score += 12
        if bullish_wick_rejection:
            warnings.append("latest candle rejects downside")
            score -= 14
        if distance_to_support_atr < 0.65 and not bearish_breakout_retest and not bearish_break_of_structure:
            warnings.append("sell is too close to support")
            score -= 18
        if price_to_fast_atr > (1.9 if is_synthetic else 2.4) and not bearish_sweep:
            warnings.append("sell entry is extended away from value")
            score -= 12
    else:
        warnings.append("no tradable direction to validate")

    if body_ratio < 0.14:
        warnings.append("latest candle body is too weak")
        score -= 8

    volume_ratio = _safe_float(last.get("volume_ratio"), 1.0)
    if not is_synthetic and volume_ratio < 0.65:
        warnings.append("volume confirmation is weak")
        score -= 8

    if volatility_regime == "extreme":
        warnings.append("volatility is extreme")
        score -= 18
    elif volatility_regime == "compressed":
        warnings.append("volatility is compressed; breakout may fail")
        score -= 6
    elif volatility_regime == "expanded" and patterns:
        score += 4

    if is_synthetic:
        synthetic_name = str(symbol or "").upper()
        if any(token in synthetic_name for token in ["BOOM", "CRASH", "JD"]):
            if not any("sweep" in pattern or "wick rejection" in pattern for pattern in patterns):
                warnings.append("spike synthetic needs sweep or wick confirmation")
                score -= 14
        elif not patterns:
            warnings.append("synthetic entry needs structure confirmation")
            score -= 12

    ready = bool(patterns) and score >= (18 if is_synthetic else 14) and not any(
        warning in warnings for warning in [
            "volatility is extreme",
            "market structure is bearish" if signal == "BUY" else "market structure is bullish",
        ]
    )

    return {
        "ready": ready,
        "bias": market_structure_bias,
        "trend_bias": trend_bias,
        "score": int(round(score)),
        "patterns": list(dict.fromkeys(patterns)),
        "warnings": list(dict.fromkeys(warnings)),
        "support": round(support, 8),
        "resistance": round(resistance, 8),
        "prior_high": round(prior_high, 8),
        "prior_low": round(prior_low, 8),
        "retest_resistance": round(retest_resistance, 8),
        "retest_support": round(retest_support, 8),
        "distance_to_resistance_atr": round(distance_to_resistance_atr, 3),
        "distance_to_support_atr": round(distance_to_support_atr, 3),
        "price_to_fast_atr": round(price_to_fast_atr, 3),
        "body_ratio": round(body_ratio, 3),
        "upper_wick_ratio": round(upper_wick_ratio, 3),
        "lower_wick_ratio": round(lower_wick_ratio, 3),
        "volatility_regime": volatility_regime,
        "volatility_ratio": round(vol_ratio, 3),
        "reason": (
            "Structure confirms entry via " + ", ".join(patterns)
            if patterns else
            "No liquidity sweep, pullback, breakout retest, or rejection entry is confirmed."
        ),
    }


def analyze_advanced_strategy_stack(
    df,
    signal: str,
    *,
    timeframe: str = "",
    style_profile: dict | None = None,
) -> dict:
    style_profile = style_profile or {}
    if df is None or df.empty or len(df) < 60:
        return {
            "ready": False,
            "score": 0,
            "directional_score": {"BUY": 0, "SELL": 0},
            "active": [],
            "warnings": ["insufficient history for advanced strategy stack"],
            "strategies": {},
            "reason": "Not enough candles to validate advanced strategy modules.",
        }

    working = df.copy().reset_index(drop=True)
    for column in ["open", "high", "low", "close", "volume"]:
        working[column] = pd.to_numeric(working.get(column), errors="coerce")
    working = working.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if len(working) < 60:
        return {
            "ready": False,
            "score": 0,
            "directional_score": {"BUY": 0, "SELL": 0},
            "active": [],
            "warnings": ["insufficient clean history for advanced strategy stack"],
            "strategies": {},
            "reason": "Not enough clean candles to validate advanced strategy modules.",
        }

    if "ema_fast" not in working.columns:
        working["ema_fast"] = working["close"].ewm(span=int(style_profile.get("ema_fast_span", 20) or 20)).mean()
    if "ema_slow" not in working.columns:
        working["ema_slow"] = working["close"].ewm(span=int(style_profile.get("ema_slow_span", 50) or 50)).mean()
    if "atr" not in working.columns:
        high_low = working["high"] - working["low"]
        high_close = (working["high"] - working["close"].shift()).abs()
        low_close = (working["low"] - working["close"].shift()).abs()
        working["atr"] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1).rolling(14).mean()
    if "volume_ma" not in working.columns:
        working["volume_ma"] = working["volume"].rolling(20).mean()
    if "rsi" not in working.columns:
        delta = working["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        working["rsi"] = 100 - (100 / (1 + (gain / (loss + 1e-9))))

    last = working.iloc[-1]
    previous = working.iloc[-2]
    close = _safe_float(last.get("close"))
    open_value = _safe_float(last.get("open"))
    high = _safe_float(last.get("high"))
    low = _safe_float(last.get("low"))
    atr = max(_safe_float(last.get("atr")), close * 0.0012, 1e-9)
    ema_fast = _safe_float(last.get("ema_fast"))
    ema_slow = _safe_float(last.get("ema_slow"))
    rsi = _safe_float(last.get("rsi"), 50.0)
    volume = _safe_float(last.get("volume"))
    volume_ma = max(_safe_float(last.get("volume_ma")), 1e-9)
    volume_ratio = volume / volume_ma if volume_ma > 0 else 1.0

    lookback = min(60, max(24, len(working) - 3))
    recent = working.tail(lookback)
    prior = working.iloc[max(0, len(working) - lookback - 12): max(1, len(working) - 2)]
    if prior.empty:
        prior = working.iloc[:-2]
    prior_high = _safe_float(prior["high"].max(), high)
    prior_low = _safe_float(prior["low"].min(), low)
    recent_high = _safe_float(recent["high"].iloc[:-1].max(), high)
    recent_low = _safe_float(recent["low"].iloc[:-1].min(), low)
    range_width = max(recent_high - recent_low, atr)
    range_width_pct = (range_width / max(close, 1e-9)) * 100

    candle_range = max(high - low, 1e-9)
    body = abs(close - open_value)
    body_ratio = body / candle_range
    upper_wick_ratio = (high - max(open_value, close)) / candle_range
    lower_wick_ratio = (min(open_value, close) - low) / candle_range
    previous_close = _safe_float(previous.get("close"), close)
    momentum_pct = ((close - _safe_float(working["close"].iloc[-6], close)) / max(_safe_float(working["close"].iloc[-6], close), 1e-9)) * 100

    typical_price = (working["high"] + working["low"] + working["close"]) / 3
    vwap_window = working.tail(min(48, len(working))).copy()
    vwap_volume = vwap_window["volume"].replace(0, pd.NA)
    vwap = float(((vwap_window["high"] + vwap_window["low"] + vwap_window["close"]) / 3 * vwap_volume).sum() / max(vwap_volume.sum(), 1e-9))
    previous_vwap = float(typical_price.tail(min(48, len(working))).mean())

    def _new_strategy(name: str) -> dict:
        return {"name": name, "direction": "NEUTRAL", "score": 0, "active": False, "reason": ""}

    strategies = {
        "break_of_structure": _new_strategy("Break Of Structure / CHoCH"),
        "liquidity_sweep": _new_strategy("Liquidity Sweep Reversal"),
        "fair_value_gap": _new_strategy("Fair Value Gap / Imbalance"),
        "order_block_retest": _new_strategy("Order Block Retest"),
        "trend_pullback": _new_strategy("Trend Pullback Continuation"),
        "range_breakout_retest": _new_strategy("Range Breakout With Retest"),
        "vwap_reclaim_rejection": _new_strategy("VWAP Reclaim / Rejection"),
        "momentum_ignition": _new_strategy("Momentum Ignition"),
        "mean_reversion_exhaustion": _new_strategy("Mean Reversion Exhaustion"),
        "multi_timeframe_confirmation": _new_strategy("Multi-Timeframe Confirmation"),
    }

    bullish_bos = close > prior_high and previous_close <= prior_high
    bearish_bos = close < prior_low and previous_close >= prior_low
    bullish_choch = bullish_bos and ema_fast < ema_slow
    bearish_choch = bearish_bos and ema_fast > ema_slow
    if bullish_bos or bullish_choch:
        strategies["break_of_structure"].update(direction="BUY", score=18 if bullish_choch else 14, active=True, reason="Price broke above recent structure.")
    elif bearish_bos or bearish_choch:
        strategies["break_of_structure"].update(direction="SELL", score=18 if bearish_choch else 14, active=True, reason="Price broke below recent structure.")

    bullish_sweep = low < prior_low and close > prior_low and lower_wick_ratio >= 0.30
    bearish_sweep = high > prior_high and close < prior_high and upper_wick_ratio >= 0.30
    if bullish_sweep:
        strategies["liquidity_sweep"].update(direction="BUY", score=16, active=True, reason="Price swept sell-side liquidity and reclaimed the range.")
    elif bearish_sweep:
        strategies["liquidity_sweep"].update(direction="SELL", score=16, active=True, reason="Price swept buy-side liquidity and rejected back inside the range.")

    bullish_fvg = len(working) >= 3 and _safe_float(working.iloc[-3].get("high")) < low and body_ratio >= 0.45
    bearish_fvg = len(working) >= 3 and _safe_float(working.iloc[-3].get("low")) > high and body_ratio >= 0.45
    if bullish_fvg:
        strategies["fair_value_gap"].update(direction="BUY", score=10, active=True, reason="Bullish displacement left a fair-value gap below price.")
    elif bearish_fvg:
        strategies["fair_value_gap"].update(direction="SELL", score=10, active=True, reason="Bearish displacement left a fair-value gap above price.")

    setup_slice = working.iloc[max(0, len(working) - 18): -1]
    bullish_displacement = close > open_value and body_ratio >= 0.55 and close > ema_fast
    bearish_displacement = close < open_value and body_ratio >= 0.55 and close < ema_fast
    bullish_blocks = setup_slice[setup_slice["close"] < setup_slice["open"]]
    bearish_blocks = setup_slice[setup_slice["close"] > setup_slice["open"]]
    if bullish_displacement and not bullish_blocks.empty:
        block = bullish_blocks.iloc[-1]
        block_low = _safe_float(block.get("low"))
        block_high = _safe_float(block.get("high"))
        retested = low <= block_high + atr * 0.35 and close >= block_low
        if retested:
            strategies["order_block_retest"].update(direction="BUY", score=13, active=True, reason="Bullish displacement retested the last bearish order block.")
    elif bearish_displacement and not bearish_blocks.empty:
        block = bearish_blocks.iloc[-1]
        block_low = _safe_float(block.get("low"))
        block_high = _safe_float(block.get("high"))
        retested = high >= block_low - atr * 0.35 and close <= block_high
        if retested:
            strategies["order_block_retest"].update(direction="SELL", score=13, active=True, reason="Bearish displacement retested the last bullish order block.")

    if ema_fast > ema_slow and abs(close - ema_fast) <= atr * 1.0 and close > open_value and rsi >= 48:
        strategies["trend_pullback"].update(direction="BUY", score=12, active=True, reason="Bullish EMA trend accepted a controlled pullback.")
    elif ema_fast < ema_slow and abs(close - ema_fast) <= atr * 1.0 and close < open_value and rsi <= 52:
        strategies["trend_pullback"].update(direction="SELL", score=12, active=True, reason="Bearish EMA trend accepted a controlled pullback.")

    compressed_range = range_width_pct <= 1.2 or range_width <= atr * 4.5
    bullish_range_breakout = compressed_range and previous_close > recent_high and low <= recent_high + atr * 0.3 and close > recent_high
    bearish_range_breakout = compressed_range and previous_close < recent_low and high >= recent_low - atr * 0.3 and close < recent_low
    if bullish_range_breakout:
        strategies["range_breakout_retest"].update(direction="BUY", score=15, active=True, reason="Compressed range broke upward and held a retest.")
    elif bearish_range_breakout:
        strategies["range_breakout_retest"].update(direction="SELL", score=15, active=True, reason="Compressed range broke downward and held a retest.")

    bullish_vwap = previous_close < previous_vwap and close > vwap and volume_ratio >= 0.9
    bearish_vwap = previous_close > previous_vwap and close < vwap and volume_ratio >= 0.9
    if bullish_vwap:
        strategies["vwap_reclaim_rejection"].update(direction="BUY", score=9, active=True, reason="Price reclaimed VWAP with participation.")
    elif bearish_vwap:
        strategies["vwap_reclaim_rejection"].update(direction="SELL", score=9, active=True, reason="Price rejected below VWAP with participation.")

    bullish_momentum = close > open_value and body_ratio >= 0.58 and volume_ratio >= 1.25 and momentum_pct > 0
    bearish_momentum = close < open_value and body_ratio >= 0.58 and volume_ratio >= 1.25 and momentum_pct < 0
    if bullish_momentum:
        strategies["momentum_ignition"].update(direction="BUY", score=11, active=True, reason="Bullish momentum expanded with stronger volume.")
    elif bearish_momentum:
        strategies["momentum_ignition"].update(direction="SELL", score=11, active=True, reason="Bearish momentum expanded with stronger volume.")

    stretched_above = close > ema_fast + atr * 2.2 and rsi >= 72 and upper_wick_ratio >= 0.25
    stretched_below = close < ema_fast - atr * 2.2 and rsi <= 28 and lower_wick_ratio >= 0.25
    if stretched_below:
        strategies["mean_reversion_exhaustion"].update(direction="BUY", score=8, active=True, reason="Downside stretch shows exhaustion and lower-wick rejection.")
    elif stretched_above:
        strategies["mean_reversion_exhaustion"].update(direction="SELL", score=8, active=True, reason="Upside stretch shows exhaustion and upper-wick rejection.")

    higher_window = working.tail(min(180, len(working))).copy()
    higher_fast = _safe_float(higher_window["close"].ewm(span=34).mean().iloc[-1])
    higher_slow = _safe_float(higher_window["close"].ewm(span=89).mean().iloc[-1])
    higher_bias = "BUY" if higher_fast > higher_slow and close > higher_fast else "SELL" if higher_fast < higher_slow and close < higher_fast else "NEUTRAL"
    if higher_bias in {"BUY", "SELL"}:
        strategies["multi_timeframe_confirmation"].update(
            direction=higher_bias,
            score=10,
            active=True,
            reason=f"Higher-window EMA bias confirms {higher_bias.lower()} pressure.",
        )

    directional_score = {"BUY": 0, "SELL": 0}
    active = []
    warnings = []
    requested_signal = str(signal or "HOLD").upper()
    for key, item in strategies.items():
        direction = item["direction"]
        if direction in directional_score and item["active"]:
            directional_score[direction] += int(item["score"])
            active.append({"key": key, **item})
            if requested_signal in {"BUY", "SELL"} and direction != requested_signal and item["score"] >= 10:
                warnings.append(f"{item['name']} points {direction} against the current {requested_signal} bias")

    net_score = directional_score.get(requested_signal, 0) - directional_score.get("SELL" if requested_signal == "BUY" else "BUY", 0)
    ready = bool(active) and net_score >= 10
    reason = "Advanced strategy stack confirms " + ", ".join(item["name"] for item in active[:4]) if active else "No advanced strategy module is active."

    return {
        "ready": ready,
        "score": int(net_score),
        "directional_score": directional_score,
        "active": active,
        "warnings": list(dict.fromkeys(warnings)),
        "strategies": strategies,
        "vwap": round(vwap, 8),
        "range_width_pct": round(range_width_pct, 4),
        "momentum_pct": round(momentum_pct, 4),
        "volume_ratio": round(volume_ratio, 3),
        "higher_bias": higher_bias,
        "timeframe": normalize_timeframe_label(timeframe),
        "reason": reason,
    }


def _simulate_replay_outcome(future_df, signal: str, entry_price: float, atr_value: float, reward_multiple: float = 2.0) -> dict:
    signal = str(signal or "").upper()
    entry_price = _safe_float(entry_price)
    atr_value = max(_safe_float(atr_value), entry_price * 0.0012, 1e-9)
    reward_multiple = max(1.0, _safe_float(reward_multiple, 2.0))
    if future_df is None or future_df.empty or signal not in {"BUY", "SELL"} or entry_price <= 0:
        return {"outcome": "no_data", "pnl_percent": 0.0, "bars_held": 0}

    stop_distance = atr_value * 1.6
    if signal == "BUY":
        stop_loss = entry_price - stop_distance
        take_profit = entry_price + (stop_distance * reward_multiple)
    else:
        stop_loss = entry_price + stop_distance
        take_profit = entry_price - (stop_distance * reward_multiple)

    exit_price = _safe_float(future_df.iloc[-1].get("close"), entry_price)
    outcome = "timeout"
    bars_held = len(future_df)
    for offset, (_, candle) in enumerate(future_df.iterrows(), start=1):
        high = _safe_float(candle.get("high"), entry_price)
        low = _safe_float(candle.get("low"), entry_price)
        if signal == "BUY":
            if low <= stop_loss:
                exit_price = stop_loss
                outcome = "stopped"
                bars_held = offset
                break
            if high >= take_profit:
                exit_price = take_profit
                outcome = "target_hit"
                bars_held = offset
                break
        else:
            if high >= stop_loss:
                exit_price = stop_loss
                outcome = "stopped"
                bars_held = offset
                break
            if low <= take_profit:
                exit_price = take_profit
                outcome = "target_hit"
                bars_held = offset
                break

    raw_pnl = ((exit_price - entry_price) / entry_price) * 100 if signal == "BUY" else ((entry_price - exit_price) / entry_price) * 100
    return {
        "outcome": outcome,
        "pnl_percent": round(raw_pnl - 0.2, 4),
        "bars_held": int(bars_held),
    }


def rate_signal_with_replay(
    df,
    signal: str,
    *,
    timeframe: str = "",
    style_profile: dict | None = None,
    lookback_bars: int = 180,
    lookahead_bars: int = 12,
) -> dict:
    style_profile = style_profile or {}
    signal = str(signal or "HOLD").upper()
    if df is None or df.empty or signal not in {"BUY", "SELL"}:
        return {"ready": False, "score": 0.0, "label": "Not Ready", "reason": "No tradable signal to replay."}

    working = df.copy().reset_index(drop=True)
    for column in ["open", "high", "low", "close", "volume"]:
        working[column] = pd.to_numeric(working.get(column), errors="coerce")
    working = working.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if len(working) < 90:
        return {"ready": False, "score": 0.0, "label": "Not Ready", "reason": "Need at least 90 candles for live replay rating."}

    start = max(60, len(working) - int(lookback_bars or 180))
    end = len(working) - int(lookahead_bars or 12) - 1
    if end <= start:
        return {"ready": False, "score": 0.0, "label": "Not Ready", "reason": "Not enough future bars for replay sampling."}

    reward_multiple = _safe_float(style_profile.get("reward_multiple"), 2.0)
    simulated = []
    skipped = 0
    sample_indexes = range(start, end, 3)
    for idx in sample_indexes:
        history = working.iloc[: idx + 1].copy()
        replay_stack = analyze_advanced_strategy_stack(
            history,
            signal,
            timeframe=timeframe,
            style_profile=style_profile,
        )
        if not replay_stack.get("ready") or _safe_float(replay_stack.get("score")) < 10:
            skipped += 1
            continue

        row = history.iloc[-1]
        entry_price = _safe_float(row.get("close"))
        atr_value = _safe_float(row.get("atr"), entry_price * 0.002)
        future_df = working.iloc[idx + 1: idx + 1 + int(lookahead_bars or 12)].copy()
        outcome = _simulate_replay_outcome(future_df, signal, entry_price, atr_value, reward_multiple=reward_multiple)
        simulated.append(
            {
                "score": int(replay_stack.get("score", 0) or 0),
                "outcome": outcome.get("outcome", "timeout"),
                "pnl_percent": float(outcome.get("pnl_percent", 0.0) or 0.0),
                "bars_held": int(outcome.get("bars_held", 0) or 0),
            }
        )
        if len(simulated) >= 32:
            break

    if not simulated:
        return {
            "ready": False,
            "score": 0.0,
            "label": "Not Ready",
            "reason": "Recent candles did not produce enough matching advanced-strategy replay setups.",
            "skipped_samples": int(skipped),
        }

    pnl_series = pd.Series([item["pnl_percent"] for item in simulated], dtype="float64")
    wins = pnl_series[pnl_series > 0]
    losses = pnl_series[pnl_series <= 0]
    total = len(simulated)
    win_rate = (len(wins) / total) * 100 if total else 0.0
    avg_pnl = float(pnl_series.mean()) if total else 0.0
    gross_profit = float(wins.sum()) if not wins.empty else 0.0
    gross_loss = abs(float(losses.sum())) if not losses.empty else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit
    target_hits = sum(1 for item in simulated if item["outcome"] == "target_hit")
    stops = sum(1 for item in simulated if item["outcome"] == "stopped")

    score = 4.0
    if total >= 24:
        score += 1.0
    elif total >= 12:
        score += 0.5
    else:
        score -= 0.5
    if win_rate >= 58:
        score += 1.25
    elif win_rate >= 50:
        score += 0.6
    elif win_rate < 42:
        score -= 1.0
    if profit_factor >= 1.5:
        score += 1.5
    elif profit_factor >= 1.15:
        score += 0.75
    elif profit_factor < 1.0:
        score -= 1.0
    if avg_pnl > 0.12:
        score += 1.0
    elif avg_pnl > 0:
        score += 0.4
    else:
        score -= 0.8
    if target_hits > stops:
        score += 0.6

    score = max(0.0, min(10.0, round(score, 1)))
    if score >= 8:
        label = "Strong"
    elif score >= 6.5:
        label = "Promising"
    elif score >= 5:
        label = "Cautious"
    else:
        label = "Weak"

    return {
        "ready": True,
        "score": score,
        "label": label,
        "reason": f"{total} replay setups, {win_rate:.1f}% win rate, profit factor {profit_factor:.2f}",
        "total_setups": int(total),
        "target_hits": int(target_hits),
        "stops": int(stops),
        "timeouts": int(sum(1 for item in simulated if item["outcome"] == "timeout")),
        "win_rate": round(win_rate, 2),
        "avg_pnl_percent": round(avg_pnl, 4),
        "profit_factor": round(profit_factor, 2),
        "lookback_bars": int(min(lookback_bars, len(working))),
        "lookahead_bars": int(lookahead_bars),
    }


def ai_signal(df, symbol="BTCUSDT", current_balance=10000, timeframe: str = "", trade_style: str = ""):
    style_profile = get_trade_style_profile(trade_style)
    preferred_timeframes_list = list(style_profile.get("preferred_timeframes", []) or [])
    required_rows = max(50, int(style_profile.get("ema_slow_span", 50) or 50) + 20)
    if df.empty or len(df) < required_rows:
        return _empty_signal(
            f"Insufficient data for {style_profile['label']} analysis",
            current_balance,
            {
                "trade_style": style_profile["label"],
                "style_profile": {
                    "key": style_profile["style_key"],
                    "label": style_profile["label"],
                    "description": style_profile["description"],
                    "preferred_timeframes": preferred_timeframes_list,
                    "timeframe_match": True,
                    "min_confidence": int(style_profile.get("min_confidence", 55) or 55),
                    "min_rr_ratio": _safe_float(style_profile.get("min_rr_ratio"), 1.5),
                },
                "summary": {
                    "bias": "neutral",
                    "trend_score": 0.0,
                    "momentum_score": 0.0,
                    "setup_quality": "blocked",
                    "trade_style": style_profile["label"],
                },
            },
        )

    working = add_indicators(df, style_profile=style_profile)
    last = working.iloc[-1]
    preferred_timeframes = set(preferred_timeframes_list)
    timeframe_value = normalize_timeframe_label(timeframe)
    timeframe_match = not timeframe_value or not preferred_timeframes or timeframe_value in preferred_timeframes

    black_swan = detect_black_swan_risk(working)
    regime_strategy = get_regime_strategy(working)
    robustness = validate_strategy_robustness(working)

    trend_gap_pct = _safe_float(last.get("trend_gap_pct"))
    rsi = _safe_float(last.get("rsi"))
    momentum_value = _safe_float(last.get("momentum"))
    volume_ratio = _safe_float(last.get("volume_ratio"), 1.0)
    price_to_fast_gap = abs(_safe_float(last.get("price_to_fast_gap_pct")))
    trend_gap_threshold = _safe_float(style_profile.get("trend_gap_threshold"), 0.3)
    momentum_threshold = _safe_float(style_profile.get("momentum_threshold"), 0.08)
    volume_confirmation_ratio = _safe_float(style_profile.get("volume_confirmation_ratio"), 1.0)
    pullback_tolerance_pct = _safe_float(style_profile.get("pullback_tolerance_pct"), 0.5)
    rsi_bull_floor = _safe_float(style_profile.get("rsi_bull_floor"), 52)
    rsi_bull_ceiling = _safe_float(style_profile.get("rsi_bull_ceiling"), 68)
    rsi_bear_floor = _safe_float(style_profile.get("rsi_bear_floor"), 32)
    rsi_bear_ceiling = _safe_float(style_profile.get("rsi_bear_ceiling"), 48)
    rsi_extreme_high = _safe_float(style_profile.get("rsi_extreme_high"), 75)
    rsi_extreme_low = _safe_float(style_profile.get("rsi_extreme_low"), 25)

    bullish_score = 0
    bearish_score = 0

    if last["close"] > last["ema_fast"]:
        bullish_score += 18
    else:
        bearish_score += 18

    if last["ema_fast"] > last["ema_slow"]:
        bullish_score += 22
    else:
        bearish_score += 22

    if trend_gap_pct > trend_gap_threshold:
        bullish_score += 16
    elif trend_gap_pct < -trend_gap_threshold:
        bearish_score += 16

    if rsi_bull_floor <= rsi <= rsi_bull_ceiling:
        bullish_score += 12
    elif rsi_bear_floor <= rsi <= rsi_bear_ceiling:
        bearish_score += 12
    elif rsi > rsi_extreme_high:
        bearish_score += 5
    elif rsi < rsi_extreme_low:
        bullish_score += 5

    if momentum_value > momentum_threshold:
        bullish_score += 14
    elif momentum_value < -momentum_threshold:
        bearish_score += 14

    if volume_ratio >= volume_confirmation_ratio:
        if bullish_score >= bearish_score:
            bullish_score += 6
        else:
            bearish_score += 6

    if price_to_fast_gap <= pullback_tolerance_pct:
        if last["close"] >= last["ema_fast"] and last["ema_fast"] > last["ema_slow"] and rsi >= 50:
            bullish_score += 6
        elif last["close"] <= last["ema_fast"] and last["ema_fast"] < last["ema_slow"] and rsi <= 50:
            bearish_score += 6

    signal = "BUY" if bullish_score >= bearish_score else "SELL"
    bias_score = max(bullish_score, bearish_score)
    dominance_score = abs(bullish_score - bearish_score)
    entry_exit = calculate_optimal_entry_exit(working, signal, last.get("atr", 0), style_profile=style_profile)
    position_sizing = calculate_dynamic_position_size(working, current_balance)
    structure_context = analyze_structure_context(working, signal, symbol=symbol, style_profile=style_profile)
    advanced_strategies = analyze_advanced_strategy_stack(
        working,
        signal,
        timeframe=timeframe_value,
        style_profile=style_profile,
    )
    signal_rating = rate_signal_with_replay(
        working,
        signal,
        timeframe=timeframe_value,
        style_profile=style_profile,
    )

    structure_required = bool(style_profile.get("requires_structure_confirmation", False))
    structure_score = _safe_float(structure_context.get("score"), 0.0)
    advanced_score = _safe_float(advanced_strategies.get("score"), 0.0)
    rating_score = _safe_float(signal_rating.get("score"), 0.0)

    confidence = _safe_float(style_profile.get("confidence_floor"), 40) + min(28, bias_score * 0.38) + min(16, dominance_score * 0.24)
    confidence += _safe_float(style_profile.get("style_confidence_boost"), 0.0)
    if structure_required:
        confidence += max(-24, min(18, structure_score * 0.38))
    else:
        confidence += max(-6, min(8, structure_score * 0.2))
    confidence += max(-10, min(12, advanced_score * 0.16))
    if structure_context.get("ready"):
        confidence += 8 if structure_required else 6
    else:
        confidence -= 14 if structure_required else 3
    if advanced_strategies.get("ready"):
        confidence += 4
    elif advanced_score < -8:
        confidence -= 5
    if signal_rating.get("ready"):
        confidence += max(-6, min(8, (rating_score - 5.0) * 1.25))
    regime_penalty_scale = _safe_float(style_profile.get("regime_penalty_scale"), 1.0)
    regime_boost_scale = _safe_float(style_profile.get("regime_boost_scale"), 1.0)
    if "confidence_reduction" in regime_strategy:
        confidence -= _safe_float(regime_strategy["confidence_reduction"]) * regime_penalty_scale
    if "confidence_boost" in regime_strategy:
        confidence += _safe_float(regime_strategy["confidence_boost"]) * regime_boost_scale
    if not robustness["robust"]:
        confidence -= _safe_float(style_profile.get("robustness_penalty"), 8)
    if black_swan["risk_level"] > 30:
        confidence -= black_swan["risk_level"] / max(_safe_float(style_profile.get("black_swan_penalty_divisor"), 6.0), 1.0)
    if not entry_exit["is_profitable_setup"]:
        confidence -= _safe_float(style_profile.get("profitability_penalty"), 18)
    if timeframe_value and not timeframe_match:
        confidence -= int(style_profile.get("timeframe_mismatch_penalty", 0) or 0)
    if structure_context.get("volatility_regime") == "extreme":
        confidence -= 12

    confidence = max(0, min(100, round(confidence)))

    style_min_confidence = int(style_profile.get("min_confidence", 55) or 55)
    if _is_synthetic_symbol(symbol):
        style_min_confidence = max(style_min_confidence, 68)
    setup_quality = "high"
    if confidence < style_min_confidence or not entry_exit["is_profitable_setup"]:
        setup_quality = "cautious"
    if not structure_context.get("ready"):
        setup_quality = "cautious"
    if advanced_strategies.get("ready") and confidence >= style_min_confidence and entry_exit["is_profitable_setup"]:
        setup_quality = "high"
    if signal_rating.get("ready") and rating_score < 5.0:
        setup_quality = "cautious"
    elif signal_rating.get("ready") and rating_score >= 8.0 and setup_quality != "blocked":
        setup_quality = "high"
    if advanced_score < -12:
        setup_quality = "cautious"
    if black_swan["risk_level"] >= 70:
        setup_quality = "blocked"
    if structure_context.get("volatility_regime") == "extreme":
        setup_quality = "blocked"

    style_min_rr = _safe_float(style_profile.get("min_rr_ratio"), 1.5)
    entry_exit["style_min_rr_ratio"] = style_min_rr
    entry_exit["passes_style_rr"] = _safe_float(entry_exit.get("risk_reward_ratio"), 0.0) >= style_min_rr
    if not entry_exit["passes_style_rr"]:
        entry_exit["is_profitable_setup"] = False

    position_sizing["base_style_size_percent"] = round(_safe_float(position_sizing.get("size_percent"), 0.0), 2)
    position_sizing["base_style_position_size_usd"] = round(_safe_float(position_sizing.get("position_size_usd"), 0.0), 2)
    style_size_multiplier = _safe_float(style_profile.get("size_multiplier"), 1.0)
    position_sizing["trade_style_multiplier"] = style_size_multiplier
    position_sizing["size_percent"] = round(_safe_float(position_sizing.get("size_percent"), 0.0) * style_size_multiplier, 2)
    position_sizing["position_size_usd"] = round(_safe_float(position_sizing.get("position_size_usd"), 0.0) * style_size_multiplier, 2)

    blocked_risk_level = int(style_profile.get("blocked_risk_level", 75) or 75)
    if black_swan["risk_level"] >= blocked_risk_level:
        return _empty_signal(
            "Risk conditions are elevated, so the model is standing aside.",
            current_balance,
            {
                "trade_style": style_profile["label"],
                "style_profile": {
                    "key": style_profile["style_key"],
                    "label": style_profile["label"],
                    "description": style_profile["description"],
                    "preferred_timeframes": preferred_timeframes_list,
                    "timeframe_match": timeframe_match,
                },
                "black_swan_risk": black_swan,
                "regime": regime_strategy,
                "structure_context": structure_context,
                "advanced_strategies": advanced_strategies,
                "signal_rating": signal_rating,
                "robustness": robustness,
                "summary": {
                    "bias": "neutral",
                    "trend_score": float(round(trend_gap_pct, 2)),
                    "momentum_score": float(round(momentum_value, 2)),
                    "advanced_strategy_score": int(advanced_strategies.get("score", 0) or 0),
                    "advanced_strategy_patterns": [
                        item.get("name", "")
                        for item in list(advanced_strategies.get("active") or [])[:5]
                    ],
                    "signal_rating": signal_rating,
                    "setup_quality": "blocked",
                    "trade_style": style_profile["label"],
                },
            },
        )

    structure_ready = bool(structure_context.get("ready"))
    structure_note = ""
    if not structure_ready:
        structure_warnings = list(structure_context.get("warnings") or [])
        structure_note = str(structure_context.get("reason") or "structure confirmation is light")
        if structure_warnings:
            structure_note = f"{structure_note}: " + "; ".join(structure_warnings[:3])

    style_notes = []
    hold_reasons = []
    if timeframe_value and not timeframe_match:
        preferred_text = ", ".join(preferred_timeframes_list)
        style_notes.append(f"{style_profile['label']} is cleaner on {preferred_text} timeframes")
        hold_reasons.append(f"timeframe is {timeframe_value} while this style prefers {preferred_text}")

    if confidence < style_min_confidence:
        hold_reasons.append(f"confidence is {confidence}% and {style_profile['label'].lower()} wants at least {style_min_confidence}%")
    if structure_required and not structure_ready:
        hold_reasons.append(structure_note)
    if structure_context.get("volatility_regime") == "extreme":
        hold_reasons.append("volatility regime is extreme")
    if not entry_exit["passes_style_rr"]:
        hold_reasons.append(
            f"reward/risk is {entry_exit.get('risk_reward_ratio', 0):.2f}R and the style gate is {style_min_rr:.2f}R"
        )
    if not robustness["robust"]:
        hold_reasons.append(str(robustness.get("reason", "signal robustness is limited")).replace("_", " "))
    if black_swan["risk_level"] >= max(45, blocked_risk_level - 18):
        hold_reasons.append(f"risk guard is elevated at {int(black_swan['risk_level'])}%")
    if dominance_score < 8:
        hold_reasons.append("directional conviction is still too weak")
    advanced_warnings = list(advanced_strategies.get("warnings") or [])
    if advanced_score < -8 and advanced_warnings:
        hold_reasons.append("; ".join(advanced_warnings[:2]))
    if signal_rating.get("ready") and rating_score < 4.5:
        hold_reasons.append(f"replay rating is weak at {rating_score:.1f}/10")

    final_signal = (
        signal
        if confidence >= style_min_confidence
        and entry_exit["is_profitable_setup"]
        and (structure_ready or not structure_required)
        else "HOLD"
    )
    trade_allowed = final_signal in {"BUY", "SELL"}
    reason = regime_strategy["reason"]
    if final_signal == "HOLD":
        if hold_reasons:
            reason = f"{style_profile['label']} is waiting because " + "; ".join(dict.fromkeys(hold_reasons)) + "."
        else:
            reason = f"{style_profile['label']} thresholds are not fully met yet, so the model is waiting."
    elif style_profile.get("style_reason"):
        reason = f"{reason} {style_profile['style_reason']}".strip()
        structure_patterns = ", ".join(structure_context.get("patterns") or [])
        if structure_patterns:
            reason = f"{reason} Structure confirmation: {structure_patterns}.".strip()
        elif structure_note:
            reason = f"{reason} Structure note: {structure_note}.".strip()
        advanced_names = [
            item.get("name", "")
            for item in list(advanced_strategies.get("active") or [])[:4]
            if item.get("name")
        ]
        if advanced_names:
            reason = f"{reason} Advanced confirmations: {', '.join(advanced_names)}.".strip()
        if signal_rating.get("ready"):
            reason = f"{reason} Replay rating: {signal_rating.get('label')} {rating_score:.1f}/10 from {signal_rating.get('reason')}.".strip()
    if style_notes:
        reason = f"{reason} {' '.join(style_notes)}".strip()

    return {
        "signal": final_signal,
        "confidence": confidence,
        "trade_allowed": trade_allowed,
        "trade_style": style_profile["label"],
        "style_profile": {
            "key": style_profile["style_key"],
            "label": style_profile["label"],
            "description": style_profile["description"],
            "preferred_timeframes": preferred_timeframes_list,
            "timeframe_match": timeframe_match,
            "min_confidence": style_min_confidence,
            "min_rr_ratio": style_min_rr,
        },
        "position_size": position_sizing,
        "entry_exit": entry_exit,
        "regime": regime_strategy,
        "structure_context": structure_context,
        "advanced_strategies": advanced_strategies,
        "signal_rating": signal_rating,
        "black_swan_risk": black_swan,
        "robustness": robustness,
        "reason": reason,
        "summary": {
            "bias": "bullish" if signal == "BUY" else "bearish",
            "trend_score": float(round(trend_gap_pct, 2)),
            "momentum_score": float(round(momentum_value, 2)),
            "structure_score": int(structure_context.get("score", 0) or 0),
            "advanced_strategy_score": int(advanced_strategies.get("score", 0) or 0),
            "advanced_strategy_patterns": [
                item.get("name", "")
                for item in list(advanced_strategies.get("active") or [])[:5]
            ],
            "advanced_strategy_warnings": list(advanced_strategies.get("warnings") or []),
            "signal_rating": signal_rating,
            "structure_bias": structure_context.get("bias", "neutral"),
            "entry_patterns": list(structure_context.get("patterns") or []),
            "structure_warnings": list(structure_context.get("warnings") or []),
            "support": structure_context.get("support", 0.0),
            "resistance": structure_context.get("resistance", 0.0),
            "volatility_regime": structure_context.get("volatility_regime", "unknown"),
            "setup_quality": setup_quality,
            "trade_style": style_profile["label"],
            "blocked_reasons": list(dict.fromkeys(hold_reasons)),
        },
    }


def _simulate_signal_outcome(future_df, signal, entry_price, stop_loss, take_profit, round_trip_cost_percent=0.2):
    if future_df.empty or entry_price <= 0:
        return {
            "outcome": "no_data",
            "exit_price": entry_price,
            "pnl_percent": 0.0,
            "bars_held": 0,
        }

    outcome = "timeout"
    exit_price = _safe_float(future_df.iloc[-1].get("close"), entry_price)
    bars_held = len(future_df)

    for offset, (_, candle) in enumerate(future_df.iterrows(), start=1):
        candle_high = _safe_float(candle.get("high"), entry_price)
        candle_low = _safe_float(candle.get("low"), entry_price)

        if signal == "BUY":
            hit_stop = stop_loss > 0 and candle_low <= stop_loss
            hit_take = take_profit > 0 and candle_high >= take_profit
            if hit_stop and hit_take:
                outcome = "stopped"
                exit_price = stop_loss
                bars_held = offset
                break
            if hit_stop:
                outcome = "stopped"
                exit_price = stop_loss
                bars_held = offset
                break
            if hit_take:
                outcome = "target_hit"
                exit_price = take_profit
                bars_held = offset
                break
        else:
            hit_stop = stop_loss > 0 and candle_high >= stop_loss
            hit_take = take_profit > 0 and candle_low <= take_profit
            if hit_stop and hit_take:
                outcome = "stopped"
                exit_price = stop_loss
                bars_held = offset
                break
            if hit_stop:
                outcome = "stopped"
                exit_price = stop_loss
                bars_held = offset
                break
            if hit_take:
                outcome = "target_hit"
                exit_price = take_profit
                bars_held = offset
                break

    if signal == "BUY":
        raw_pnl_percent = ((exit_price - entry_price) / entry_price) * 100
    else:
        raw_pnl_percent = ((entry_price - exit_price) / entry_price) * 100
    net_pnl_percent = raw_pnl_percent - round_trip_cost_percent

    return {
        "outcome": outcome,
        "exit_price": round(exit_price, 8),
        "pnl_percent": round(net_pnl_percent, 4),
        "bars_held": bars_held,
    }


def score_backtest_report(report: dict) -> dict:
    if not report.get("ready"):
        return {"score": 0.0, "label": "Not Ready", "reason": report.get("reason", "Backtest unavailable")}

    total_trades = int(report.get("total_trades", 0) or 0)
    win_rate = float(report.get("win_rate", 0) or 0)
    profit_factor = float(report.get("profit_factor", 0) or 0)
    expectancy = float(report.get("expectancy_percent", 0) or 0)
    max_drawdown = float(report.get("max_drawdown_percent", 0) or 0)
    avg_confidence = float(report.get("avg_confidence", 0) or 0)

    score = 4.0

    if total_trades >= 40:
        score += 1.0
    elif total_trades >= 20:
        score += 0.5
    else:
        score -= 0.75

    if profit_factor >= 1.4:
        score += 1.5
    elif profit_factor >= 1.15:
        score += 1.0
    elif profit_factor >= 1.0:
        score += 0.5
    else:
        score -= 1.25

    if win_rate >= 55:
        score += 1.0
    elif win_rate >= 50:
        score += 0.5
    elif win_rate < 45:
        score -= 0.75

    if expectancy >= 0.2:
        score += 1.0
    elif expectancy > 0:
        score += 0.5
    else:
        score -= 1.0

    if max_drawdown <= 8:
        score += 1.0
    elif max_drawdown <= 12:
        score += 0.5
    else:
        score -= 0.75

    if avg_confidence >= 75:
        score += 0.5

    score = max(0.0, min(10.0, round(score, 1)))
    if score >= 8:
        label = "Strong"
    elif score >= 6.5:
        label = "Promising"
    elif score >= 5:
        label = "Cautious"
    else:
        label = "Weak"

    return {
        "score": score,
        "label": label,
        "reason": f"{total_trades} simulated trades, {win_rate:.1f}% win rate, profit factor {profit_factor:.2f}",
    }


def backtest_ai_worker_strategy(
    df,
    symbol="BTCUSDT",
    current_balance=10000,
    warmup_bars=120,
    lookahead_bars=12,
    username: str = "",
    timeframe: str = "",
):
    if df is None or df.empty or len(df) < warmup_bars + lookahead_bars + 5:
        return {
            "ready": False,
            "reason": "Need more historical candles for a rolling backtest snapshot.",
        }

    simulated_trades = []
    hold_count = 0
    blocked_count = 0

    for idx in range(warmup_bars, len(df) - lookahead_bars):
        history = df.iloc[: idx + 1].copy()
        if username:
            result = ai_signal_for_user(
                username,
                history,
                symbol=symbol,
                current_balance=current_balance,
                timeframe=timeframe,
            )
        else:
            result = ai_signal(history, symbol=symbol, current_balance=current_balance)
        signal = result.get("signal", "HOLD")

        if signal not in {"BUY", "SELL"}:
            hold_count += 1
            continue

        entry_exit = result.get("entry_exit", {})
        entry_price = _safe_float(entry_exit.get("actual_entry") or entry_exit.get("entry_price"))
        stop_loss = _safe_float(entry_exit.get("stop_loss"))
        take_profit = _safe_float(entry_exit.get("take_profit"))
        if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
            blocked_count += 1
            continue

        future_df = df.iloc[idx + 1 : idx + 1 + lookahead_bars].copy()
        outcome = _simulate_signal_outcome(future_df, signal, entry_price, stop_loss, take_profit)
        simulated_trades.append(
            {
                "timestamp": str(df.iloc[idx].get("timestamp", "")),
                "signal": signal,
                "confidence": float(result.get("confidence", 0) or 0),
                "risk_reward_ratio": float(entry_exit.get("risk_reward_ratio", 0) or 0),
                "outcome": outcome["outcome"],
                "pnl_percent": float(outcome["pnl_percent"]),
                "bars_held": int(outcome["bars_held"]),
            }
        )

    if not simulated_trades:
        return {
            "ready": False,
            "reason": "No executable BUY/SELL signals were produced in the sampled history.",
            "hold_count": hold_count,
            "blocked_count": blocked_count,
        }

    pnl_series = pd.Series([trade["pnl_percent"] for trade in simulated_trades], dtype="float64")
    confidence_series = pd.Series([trade["confidence"] for trade in simulated_trades], dtype="float64")
    rr_series = pd.Series([trade["risk_reward_ratio"] for trade in simulated_trades], dtype="float64")
    wins = pnl_series[pnl_series > 0]
    losses = pnl_series[pnl_series <= 0]

    equity = 100.0
    peak = equity
    max_drawdown = 0.0
    for pnl_value in pnl_series:
        equity *= max(0.01, 1 + (float(pnl_value) / 100))
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, ((peak - equity) / peak) * 100)

    gross_profit = float(wins.sum()) if not wins.empty else 0.0
    gross_loss = abs(float(losses.sum())) if not losses.empty else 0.0
    report = {
        "ready": True,
        "symbol": symbol,
        "total_trades": int(len(simulated_trades)),
        "hold_count": int(hold_count),
        "blocked_count": int(blocked_count),
        "buy_trades": int(sum(1 for trade in simulated_trades if trade["signal"] == "BUY")),
        "sell_trades": int(sum(1 for trade in simulated_trades if trade["signal"] == "SELL")),
        "win_rate": round((len(wins) / len(simulated_trades)) * 100, 2),
        "avg_pnl_percent": round(float(pnl_series.mean()), 4),
        "expectancy_percent": round(float(pnl_series.mean()), 4),
        "median_pnl_percent": round(float(pnl_series.median()), 4),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else round(gross_profit, 2),
        "max_drawdown_percent": round(max_drawdown, 2),
        "avg_confidence": round(float(confidence_series.mean()), 2),
        "avg_risk_reward": round(float(rr_series.mean()), 2),
        "sample_size_bars": int(len(df)),
        "lookahead_bars": int(lookahead_bars),
    }
    report["rating"] = score_backtest_report(report)
    return report


def auto_trade_page(username, is_premium_user=False):
    from ai_worker_auto_trade import auto_trade_page as _auto_trade_page

    return _auto_trade_page(username, is_premium_user)


_all_ = [
    "fetch_bybit_klines",
    "add_indicators",
    "ai_signal",
    "backtest_ai_worker_strategy",
    "score_backtest_report",
    "detect_black_swan_risk",
    "auto_trade_page",
    "calculate_dynamic_position_size",
    "calculate_optimal_entry_exit",
    "get_regime_strategy",
    "analyze_advanced_strategy_stack",
    "rate_signal_with_replay",
    "validate_strategy_robustness",
    "ProfitOptimizer",
]
