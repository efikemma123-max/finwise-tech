from __future__ import annotations

from dataclasses import dataclass
from itertools import product
import random


SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BTCUSDC"]
TIMEFRAMES = ["1m", "3m", "5m", "15m", "1h"]
SIGNALS = ["BUY", "SELL", "HOLD"]
BROKER_PROFILES = [
    {"broker_name": "Bybit", "connection_method": "oauth", "balance": 12500.0, "total_trades": 18, "drawdown": 3.4},
    {"broker_name": "Binance", "connection_method": "api", "balance": 9400.0, "total_trades": 27, "drawdown": 5.8},
    {"broker_name": "Finwise", "connection_method": "not_connected", "balance": 10000.0, "total_trades": 0, "drawdown": 0.0},
]
MARKET_REASONS = [
    "Momentum is compressing near intraday resistance while buyers still defend pullbacks.",
    "Price is rotating inside a mixed range with no clean breakout confirmation yet.",
    "Sellers are pressing the session highs and weakening rebound attempts.",
    "Order flow is stabilizing after a sharp impulse, but conviction is still uneven.",
]
SETUP_QUALITIES = ["strong", "building", "neutral", "fragile"]
CONNECTOR_SUMMARIES = [
    "Connector test passed with balance, pricing, and fee access confirmed.",
    "Connector test has not been run yet.",
    "Connector test is waiting for broker approval.",
]
FAILED_CHECK_GROUPS = [
    ["confidence is below the minimum execution gate"],
    ["projected edge is below the minimum route threshold"],
    ["risk reward does not meet the required floor"],
    ["confidence is below the minimum execution gate", "projected edge is below the minimum route threshold"],
]


@dataclass(frozen=True)
class SyntheticContextSpec:
    symbol: str
    timeframe: str
    signal: str
    broker_name: str
    connection_method: str
    balance: float
    total_trades: int
    drawdown: float
    market_reason: str
    setup_quality: str
    connector_summary: str
    route_status: str
    confidence: float
    risk_reward: float
    projected_edge: float
    black_swan_risk: int
    last_price: float


def _base_price(symbol: str) -> float:
    return {
        "BTCUSDT": 78240.0,
        "ETHUSDT": 3925.0,
        "SOLUSDT": 171.2,
        "XRPUSDT": 0.642,
        "BTCUSDC": 78210.0,
    }.get(symbol, 100.0)


def _route_status_for_signal(signal: str, broker_connected: bool, rng: random.Random) -> str:
    if signal == "HOLD":
        return "waiting"
    if not broker_connected:
        return "blocked"
    return "ready" if rng.random() > 0.45 else "blocked"


def _build_preview(route_status: str, confidence: float, risk_reward: float, projected_edge: float, rng: random.Random) -> dict:
    if route_status == "ready":
        return {
            "status": "ready",
            "reason": "Execution gates are aligned for this setup.",
            "profit_guard": {
                "risk_reward_ratio": round(risk_reward, 2),
                "projected_profit_percent": round(projected_edge, 2),
                "confidence_percent": round(confidence, 1),
                "quality_score": 4,
                "total_checks": 4,
                "failed_checks": [],
            },
        }
    if route_status == "blocked":
        failed = rng.choice(FAILED_CHECK_GROUPS)
        return {
            "status": "blocked",
            "reason": "One or more route quality gates failed.",
            "profit_guard": {
                "risk_reward_ratio": round(risk_reward, 2),
                "projected_profit_percent": round(projected_edge, 2),
                "confidence_percent": round(confidence, 1),
                "quality_score": max(1, 4 - len(failed)),
                "total_checks": 4,
                "failed_checks": failed,
            },
        }
    return {
        "status": "waiting",
        "reason": "Finwise is waiting for stronger confirmation before routing.",
        "profit_guard": {
            "risk_reward_ratio": round(risk_reward, 2),
            "projected_profit_percent": round(projected_edge, 2),
            "confidence_percent": round(confidence, 1),
            "quality_score": 2,
            "total_checks": 4,
            "failed_checks": [],
        },
    }


def build_context_from_spec(spec: SyntheticContextSpec, *, seed: int = 0) -> dict:
    rng = random.Random(seed)
    signal = spec.signal
    entry_price = spec.last_price
    stop_distance = entry_price * (0.004 + rng.random() * 0.004)
    take_distance = stop_distance * spec.risk_reward
    stop_loss = entry_price - stop_distance if signal != "SELL" else entry_price + stop_distance
    take_profit = entry_price + take_distance if signal != "SELL" else entry_price - take_distance
    quantity = max(0.001, round((spec.balance * 0.08) / max(entry_price, 1), 6))
    route_preview = _build_preview(spec.route_status, spec.confidence, spec.risk_reward, spec.projected_edge, rng)
    connector_ready = spec.connection_method != "not_connected" and "passed" in spec.connector_summary.lower()

    execution = {}
    if spec.route_status == "ready" and signal in {"BUY", "SELL"} and rng.random() > 0.65:
        execution = {
            "status": "success",
            "message": "Trade routed successfully.",
            "trade": {
                "symbol": spec.symbol,
                "signal": signal,
                "entry_price": round(entry_price, 4),
                "projected_profit_percent": round(spec.projected_edge, 2),
                "target_profit_price": round(take_profit, 4),
            },
        }

    return {
        "broker_name": spec.broker_name,
        "connection_method": spec.connection_method,
        "balance": round(spec.balance, 2),
        "total_trades": spec.total_trades,
        "drawdown": round(spec.drawdown, 2),
        "status_text": "Monitoring live setup." if spec.route_status != "ready" else "Route is armed for execution.",
        "signal_meta": {
            "symbol": spec.symbol,
            "tf_label": spec.timeframe,
        },
        "signal": {
            "signal": signal,
            "confidence": round(spec.confidence, 1),
            "reason": spec.market_reason,
            "summary": {
                "setup_quality": spec.setup_quality,
            },
            "regime": {
                "reason": spec.market_reason,
            },
            "entry_exit": {
                "entry_price": round(entry_price, 4),
                "stop_loss": round(stop_loss, 4),
                "take_profit": round(take_profit, 4),
                "risk_reward_ratio": round(spec.risk_reward, 2),
                "adaptive_min_rr_ratio": 1.6,
            },
            "position_size": {
                "position_size_usd": round(spec.balance * 0.08, 2),
                "quantity": quantity,
            },
            "adaptive_profile": {
                "min_confidence": 56,
                "min_rr_ratio": 1.6,
            },
            "black_swan_risk": {
                "risk_level": spec.black_swan_risk,
            },
        },
        "preview": route_preview,
        "connector": {
            "status": "ready" if connector_ready else "waiting",
            "summary": spec.connector_summary,
        },
        "execution": execution,
        "bot_thresholds": {
            "min_confidence": 56,
            "min_rr": 1.6,
            "min_edge": 0.45,
            "growth_goal": 12,
        },
    }


def iter_synthetic_contexts(limit: int = 120, *, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    contexts: list[dict] = []
    combos = product(SYMBOLS, TIMEFRAMES, SIGNALS, BROKER_PROFILES, MARKET_REASONS, SETUP_QUALITIES, CONNECTOR_SUMMARIES)
    for index, combo in enumerate(combos):
        if len(contexts) >= limit:
            break
        symbol, timeframe, signal, broker, market_reason, setup_quality, connector_summary = combo
        balance = float(broker["balance"])
        last_price = _base_price(symbol) * (1 + rng.uniform(-0.015, 0.015))
        confidence = 50.0 if signal == "HOLD" else rng.uniform(55, 83)
        risk_reward = 1.2 if signal == "HOLD" else rng.uniform(1.3, 3.1)
        projected_edge = 0.12 if signal == "HOLD" else rng.uniform(0.25, 2.1)
        route_status = _route_status_for_signal(signal, broker["connection_method"] != "not_connected", rng)
        spec = SyntheticContextSpec(
            symbol=symbol,
            timeframe=timeframe,
            signal=signal,
            broker_name=str(broker["broker_name"]),
            connection_method=str(broker["connection_method"]),
            balance=balance,
            total_trades=int(broker["total_trades"]),
            drawdown=float(broker["drawdown"]),
            market_reason=market_reason,
            setup_quality=setup_quality,
            connector_summary=connector_summary,
            route_status=route_status,
            confidence=confidence,
            risk_reward=risk_reward,
            projected_edge=projected_edge,
            black_swan_risk=rng.randint(0, 68),
            last_price=last_price,
        )
        contexts.append(build_context_from_spec(spec, seed=seed + index))
    return contexts


QUESTION_BANK = [
    "What is happening in the market right now?",
    "Why is auto trade trading this way?",
    "What risk controls are active right now?",
    "What should I do next?",
    "Explain the broker status for this setup.",
    "Summarize this setup for me.",
]

