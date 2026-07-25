from __future__ import annotations

import importlib.util
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from finwise_model.runtime_registry import LocalModel


class InferenceEngine(Protocol):
    def generate(self, prompt: str, *, model: LocalModel, context: dict[str, Any], options: dict[str, Any] | None = None) -> str:
        ...


def clean_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    return str(value or "").strip()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fmt_money(value: Any) -> str:
    return f"${safe_float(value):,.2f}"


def fmt_price(value: Any) -> str:
    return f"${safe_float(value):,.4f}"


def pct(value: Any) -> str:
    return f"{safe_float(value):.2f}%"


def render_prompt(model: LocalModel, prompt: str, context: dict[str, Any]) -> str:
    template = clean_text(model.template)
    if template:
        return (
            template.replace("{{ system }}", model.system_prompt)
            .replace("{{ context }}", str(context or {}))
            .replace("{{ prompt }}", prompt)
        )
    return f"{model.system_prompt}\n\nContext:\n{context}\n\nUser:\n{prompt}\n\nAssistant:"


class FinwiseRulesEngine:
    name = "finwise-rules"

    def generate(self, prompt: str, *, model: LocalModel, context: dict[str, Any], options: dict[str, Any] | None = None) -> str:
        del options
        prompt = clean_text(prompt)
        lower = prompt.lower()
        style = self._style_from_prompt(prompt, model)
        intents = self._detect_intents(lower)

        if self._is_greeting(lower):
            return self._shape_reply(
                ["Hey. I am here to help."],
                style=style,
                context=context,
                intents={"capability", "next"},
            )
        if "identity" in intents:
            return self._shape_reply([self._identity_reply(model)], style=style, context=context, intents=intents)
        if "capability" in intents:
            return self._shape_reply([self._capability_reply()], style=style, context=context, intents=intents)

        parts: list[str] = []
        if "overview" in intents:
            parts.append(self._overview_reply(context))
        if "broker" in intents:
            parts.append(self._broker_reply(context))
        if "market" in intents:
            parts.append(self._market_reply(context))
        if "route" in intents:
            parts.append(self._route_reply(context))
        if "trade_plan" in intents:
            parts.append(self._trade_plan_reply(context))
        if "risk" in intents:
            parts.append(self._risk_reply(context))
        if "diagnostics" in intents:
            parts.append(self._diagnostics_reply(context))
        if "next" in intents:
            parts.append(self._next_reply(context))
        if not parts:
            parts = [self._overview_reply(context)]
        return self._shape_reply(parts, style=style, context=context, intents=intents)

    def _detect_intents(self, lower: str) -> set[str]:
        intents: set[str] = set()
        checks = {
            "identity": ["who are you", "what are you", "your name"],
            "capability": ["what can you do", "help me", "features", "capabilities"],
            "overview": ["overview", "summary", "recap", "update me", "what is going on", "what's going on"],
            "broker": ["broker", "balance", "connected", "connection", "account"],
            "market": ["market", "trend", "price", "happening", "review", "signal", "regime", "structure"],
            "route": ["route", "blocked", "execution", "execute", "gate", "auto trade", "routing"],
            "trade_plan": ["trade plan", "trade map", "entry", "entry price", "stop", "target", "take profit", "tp", "sl"],
            "risk": ["risk", "confidence", "reward", "rr", "drawdown", "size", "loss"],
            "next": ["next", "should i", "what now", "do now", "what should", "can i take"],
            "diagnostics": ["diagnostic", "health", "engine", "runtime", "model status", "why fallback"],
        }
        for intent, tokens in checks.items():
            if any(token in lower for token in tokens):
                intents.add(intent)
        if "can i take" in lower or "should i trade" in lower:
            intents.update({"trade_plan", "route", "next"})
        return intents

    def _is_greeting(self, lower: str) -> bool:
        return lower in {"hello", "hi", "hey", "yo", "sup", "good morning", "good afternoon", "good evening"}

    def _style_from_prompt(self, prompt: str, model: LocalModel) -> str:
        lower = prompt.lower()
        if any(token in lower for token in ["short", "brief", "quick", "concise"]):
            return "brief"
        if any(token in lower for token in ["explain", "detail", "break it down", "deep"]):
            return "detailed"
        if "simple" in lower or "plain english" in lower:
            return "simple"
        if "concise" in model.system_prompt.lower():
            return "brief"
        return "normal"

    def _shape_reply(self, parts: list[str], *, style: str, context: dict[str, Any], intents: set[str]) -> str:
        deduped = list(dict.fromkeys(clean_text(part) for part in parts if clean_text(part)))
        if not deduped:
            deduped = ["I do not have enough Finwise context yet to give a full read."]
        explanation = self._explanation_reply(context, intents)
        suggestions = self._suggestions_reply(context, intents)
        if style == "brief":
            return "\n\n".join([deduped[0], explanation, suggestions])
        if style == "simple":
            body = "\n\n".join(self._plain_language(part) for part in deduped[:3])
            return "\n\n".join([body, self._plain_language(explanation), self._plain_language(suggestions)])
        if style == "detailed":
            return "\n\n".join([*deduped, explanation, self._context_notes_reply(context), suggestions])
        return "\n\n".join([*deduped, explanation, suggestions])

    def _plain_language(self, text: str) -> str:
        replacements = {
            "risk/reward": "reward compared to risk",
            "route": "trade path",
            "execution": "trade placement",
            "confidence": "strength",
            "projected edge": "expected advantage",
        }
        result = text
        for source, target in replacements.items():
            result = re.sub(source, target, result, flags=re.IGNORECASE)
        return result

    def _identity_reply(self, model: LocalModel) -> str:
        return (
            f"I am {model.name}, Finwise's local rules engine. "
            "I run inside your Finwise runtime and answer from Finwise context without calling Ollama, OpenAI, or llama.cpp."
        )

    def _capability_reply(self) -> str:
        return (
            "I can read the active Finwise context, explain the market, route status, broker state, risk map, trade plan, "
            "and next step. I am deterministic, local, and dependency-free when ENGINE is set to rules."
        )

    def _explanation_reply(self, context: dict[str, Any], intents: set[str]) -> str:
        market = context.get("market") or {}
        route = context.get("route") or {}
        broker = context.get("broker") or {}
        signal = clean_text(market.get("signal") or "HOLD").upper()
        route_status = clean_text(route.get("status") or "waiting")
        confidence = safe_float(market.get("confidence"))
        broker_connected = clean_text(broker.get("connection_method")).lower() not in {"", "not_connected", "not connected", "unknown"}

        reasons: list[str] = []
        if "market" in intents or "overview" in intents or not intents:
            reasons.append(f"market signal is {signal} with {confidence:.0f}% confidence")
        if "route" in intents or "trade_plan" in intents or "next" in intents:
            reasons.append(f"route status is {route_status}")
        if "broker" in intents:
            reasons.append("broker is connected" if broker_connected else "broker is not connected")
        if "risk" in intents or "trade_plan" in intents:
            reasons.append("risk controls are checking entry, stop, target, size, and setup quality")
        if not reasons:
            reasons.append("Finwise is using the available broker, market, and route context")
        return "Why this matters: " + "; ".join(reasons) + "."

    def _suggestions_reply(self, context: dict[str, Any], intents: set[str]) -> str:
        market = context.get("market") or {}
        route = context.get("route") or {}
        broker = context.get("broker") or {}
        signal = clean_text(market.get("signal") or "HOLD").upper()
        route_status = clean_text(route.get("status") or "waiting")
        broker_connected = clean_text(broker.get("connection_method")).lower() not in {"", "not_connected", "not connected", "unknown"}

        suggestions: list[str] = []
        if not broker_connected and ("broker" in intents or "route" in intents or "trade_plan" in intents):
            suggestions.append("connect or test the broker before trusting execution")
        if signal == "HOLD":
            suggestions.append("wait for a cleaner signal before taking a trade")
            suggestions.append("rerun the signal after more candles print")
        elif route_status == "ready":
            suggestions.append("review the trade plan against your risk limit before executing")
            suggestions.append("watch for a sudden change in confidence or spread")
        elif route_status == "blocked":
            suggestions.append("do not force the trade while route gates are blocked")
            suggestions.append("rerun the route test after the next candle")
        else:
            suggestions.append("run a fresh signal or route test to update the setup")
        if "risk" in intents or "trade_plan" in intents:
            suggestions.append("compare the stop distance with the planned position size")
        trimmed = list(dict.fromkeys(suggestions))[:3]
        return "Suggestions: " + "; ".join(trimmed) + "."

    def _context_notes_reply(self, context: dict[str, Any]) -> str:
        market = context.get("market") or {}
        route = context.get("route") or {}
        broker = context.get("broker") or {}
        return (
            "Context used: "
            f"symbol={clean_text(market.get('symbol') or 'unknown')}, "
            f"timeframe={clean_text(market.get('timeframe') or 'unknown')}, "
            f"route={clean_text(route.get('status') or 'unknown')}, "
            f"broker={clean_text(broker.get('name') or 'unknown')}."
        )

    def _market_reply(self, context: dict[str, Any]) -> str:
        market = context.get("market") or {}
        symbol = clean_text(market.get("symbol") or "the active market")
        timeframe = clean_text(market.get("timeframe") or "current timeframe")
        signal = clean_text(market.get("signal") or "HOLD").upper()
        confidence = safe_float(market.get("confidence"))
        reason = clean_text(market.get("reason") or "Finwise does not have a fresh market reason yet.")
        quality = clean_text((market.get("summary") or {}).get("setup_quality"))
        quality_text = f" Setup quality is {quality}." if quality else ""
        return f"{symbol} on {timeframe} is reading {signal} with about {confidence:.0f}% confidence. {reason}{quality_text}"

    def _route_reply(self, context: dict[str, Any]) -> str:
        route = context.get("route") or {}
        status = clean_text(route.get("status") or "waiting")
        reason = clean_text(route.get("reason") or "The route has not cleared all checks yet.")
        guard = route.get("profit_guard") or {}
        failed = guard.get("failed_checks") or []
        if status == "ready":
            return "The route is ready. Confidence, reward, and projected edge are aligned for this setup."
        if status == "blocked" and failed:
            return "The route is blocked because " + "; ".join(str(item) for item in failed) + "."
        return f"The route is {status}. {reason}"

    def _trade_plan_reply(self, context: dict[str, Any]) -> str:
        market = context.get("market") or {}
        entry = market.get("entry_exit") or {}
        size = market.get("position_size") or {}
        symbol = clean_text(market.get("symbol") or "the active market")
        timeframe = clean_text(market.get("timeframe") or "current timeframe")
        signal = clean_text(market.get("signal") or "HOLD").upper()
        if signal == "HOLD":
            return f"Trade plan for {symbol} on {timeframe}: HOLD. There is no active entry to chase right now."
        return (
            f"Trade plan for {symbol} on {timeframe}: {signal}. Entry around {fmt_price(entry.get('entry_price'))}, "
            f"stop near {fmt_price(entry.get('stop_loss'))}, target near {fmt_price(entry.get('take_profit'))}, "
            f"{safe_float(entry.get('risk_reward_ratio')):.2f}R structure, and planned size about {fmt_money(size.get('position_size_usd'))}."
        )

    def _risk_reply(self, context: dict[str, Any]) -> str:
        market = context.get("market") or {}
        entry = market.get("entry_exit") or {}
        size = market.get("position_size") or {}
        profile = market.get("adaptive_profile") or {}
        black_swan = market.get("black_swan_risk") or {}
        return (
            f"Risk map: entry around {fmt_price(entry.get('entry_price'))}, "
            f"stop near {fmt_price(entry.get('stop_loss'))}, target near {fmt_price(entry.get('take_profit'))}, "
            f"risk/reward about {safe_float(entry.get('risk_reward_ratio')):.2f}R, "
            f"planned size about {fmt_money(size.get('position_size_usd'))}, "
            f"minimum confidence {safe_float(profile.get('min_confidence')):.0f}%, "
            f"and black-swan risk {safe_float(black_swan.get('risk_level')):.0f}/100."
        )

    def _broker_reply(self, context: dict[str, Any]) -> str:
        broker = context.get("broker") or {}
        name = clean_text(broker.get("name") or "your broker")
        connection = clean_text(broker.get("connection_method") or "unknown").replace("_", " ").title()
        balance = fmt_money(broker.get("balance"))
        trades = int(safe_float(broker.get("total_trades")))
        if connection.lower() == "not connected":
            return f"{name} is Not Connected. Finwise is using {balance} as the local balance basis, with {trades} routed trades recorded."
        return f"{name} is connected through {connection}. Finwise is using {balance} as the balance basis, with {trades} routed trades recorded."

    def _overview_reply(self, context: dict[str, Any]) -> str:
        return " ".join(
            part
            for part in [
                self._market_reply(context),
                self._route_reply(context),
                self._risk_reply(context),
                self._next_reply(context),
            ]
            if part
        )

    def _diagnostics_reply(self, context: dict[str, Any]) -> str:
        broker = context.get("broker") or {}
        route = context.get("route") or {}
        market = context.get("market") or {}
        return (
            "Runtime diagnostic: ENGINE rules is dependency-free and local. "
            f"Context present: broker={bool(broker)}, market={bool(market)}, route={bool(route)}. "
            "If WEIGHTS is empty, Finwise will stay on the built-in rules engine."
        )

    def _next_reply(self, context: dict[str, Any]) -> str:
        market = context.get("market") or {}
        route = context.get("route") or {}
        signal = clean_text(market.get("signal") or "HOLD").upper()
        status = clean_text(route.get("status") or "waiting")
        if signal == "HOLD":
            return "Next step: wait. Finwise is in HOLD, so rerun the signal after more candles print."
        if status == "ready":
            return "Next step: review the trade map and execute only if it still matches your plan and risk limit."
        if status == "blocked":
            return "Next step: do not force it. Wait for a cleaner setup or rerun the route test after the next candle."
        return "Next step: run a fresh signal or route test so Finwise can confirm the current setup."


class LlamaCppEngine:
    name = "llama-cpp"

    def generate(self, prompt: str, *, model: LocalModel, context: dict[str, Any], options: dict[str, Any] | None = None) -> str:
        llm = _load_llama_cpp(model.weight_path)
        rendered = render_prompt(model, prompt, context)
        response = llm(
            rendered,
            max_tokens=int((options or {}).get("num_predict") or (options or {}).get("max_tokens") or 512),
            temperature=float((options or {}).get("temperature") or 0.2),
            stop=["User:", "\nUser:"],
        )
        choices = response.get("choices") or []
        return clean_text((choices[0] or {}).get("text")) if choices else ""


class TransformersEngine:
    name = "transformers"

    def generate(self, prompt: str, *, model: LocalModel, context: dict[str, Any], options: dict[str, Any] | None = None) -> str:
        tokenizer, pipeline = _load_transformers(model.weight_path)
        rendered = render_prompt(model, prompt, context)
        max_new_tokens = int((options or {}).get("num_predict") or (options or {}).get("max_tokens") or 256)
        output = pipeline(
            rendered,
            max_new_tokens=max_new_tokens,
            do_sample=float((options or {}).get("temperature") or 0.2) > 0,
            temperature=float((options or {}).get("temperature") or 0.2),
            pad_token_id=getattr(tokenizer, "eos_token_id", None),
        )
        text = clean_text((output[0] or {}).get("generated_text") if output else "")
        return clean_text(text.removeprefix(rendered))


@lru_cache(maxsize=2)
def _load_llama_cpp(weight_path: str):
    from llama_cpp import Llama

    return Llama(model_path=str(Path(weight_path)), n_ctx=4096, verbose=False)


@lru_cache(maxsize=2)
def _load_transformers(weight_path: str):
    from transformers import AutoTokenizer, pipeline

    tokenizer = AutoTokenizer.from_pretrained(weight_path, local_files_only=True)
    text_pipeline = pipeline("text-generation", model=weight_path, tokenizer=tokenizer, local_files_only=True)
    return tokenizer, text_pipeline


def engine_status(model: LocalModel) -> dict[str, Any]:
    weight_path = clean_text(model.weight_path)
    has_weights = bool(weight_path and Path(weight_path).exists())
    llama_available = bool(importlib.util.find_spec("llama_cpp"))
    transformers_available = bool(importlib.util.find_spec("transformers"))
    selected = select_engine(model).name
    return {
        "selected_engine": selected,
        "weight_path": weight_path,
        "weights_found": has_weights,
        "llama_cpp_available": llama_available,
        "transformers_available": transformers_available,
    }


def select_engine(model: LocalModel) -> InferenceEngine:
    requested_engine = clean_text(model.engine).lower()
    weight_path = clean_text(model.weight_path)
    if requested_engine in {"rules", "finwise-rules", "native"}:
        return FinwiseRulesEngine()
    if requested_engine in {"llama-cpp", "llama_cpp"} and weight_path and importlib.util.find_spec("llama_cpp"):
        return LlamaCppEngine()
    if requested_engine == "transformers" and weight_path and Path(weight_path).is_dir() and importlib.util.find_spec("transformers"):
        return TransformersEngine()
    if weight_path and requested_engine in {"", "auto"}:
        suffix = Path(weight_path).suffix.lower()
        if suffix == ".gguf" and importlib.util.find_spec("llama_cpp"):
            return LlamaCppEngine()
        if Path(weight_path).is_dir() and importlib.util.find_spec("transformers"):
            return TransformersEngine()
    return FinwiseRulesEngine()
