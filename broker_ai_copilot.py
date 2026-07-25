from __future__ import annotations

import base64
from html import escape
import json
from functools import lru_cache
import os
from pathlib import Path
from textwrap import dedent

import requests
import streamlit as st
from finwise_model.live_data import load_copilot_memory, log_copilot_turn, save_copilot_memory

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _fmt_money(value) -> str:
    return f"${_safe_float(value):,.2f}"


def _fmt_price(value) -> str:
    return f"${_safe_float(value):,.4f}"


def _fmt_pct(value) -> str:
    return f"{_safe_float(value):.2f}%"


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _default_copilot_memory() -> dict:
    return {
        "preferred_symbols": [],
        "preferred_timeframes": [],
        "preferred_brokers": [],
        "response_style": "concise",
        "topic_counts": {},
        "action_counts": {},
        "recent_topics": [],
        "recent_actions": [],
        "notes": [],
        "last_scope": "",
        "last_symbol": "",
        "last_timeframe": "",
    }


def _recent_push(items: list[str], value: str, *, limit: int = 5) -> list[str]:
    value = _clean_text(value)
    if not value:
        return list(items or [])[:limit]
    normalized = [item for item in list(items or []) if _clean_text(item) and _clean_text(item) != value]
    return [value] + normalized[: max(0, limit - 1)]


def _counter_bump(counter: dict, key: str) -> dict:
    key = _clean_text(key)
    next_counter = {str(k): int(v) for k, v in (counter or {}).items() if _clean_text(k)}
    if key:
        next_counter[key] = int(next_counter.get(key, 0)) + 1
    return next_counter


def _memory_style_hint_from_text(text: str) -> str | None:
    lower = _clean_text(text).lower()
    if not lower:
        return None
    if any(token in lower for token in ["simple", "plain english", "easy to understand", "easier"]):
        return "simple"
    if any(token in lower for token in ["detailed", "deep", "full detail", "break it down"]):
        return "detailed"
    if any(token in lower for token in ["short", "brief", "quick answer", "keep it short", "concise"]):
        return "brief"
    return None


def _normalize_copilot_memory(memory: dict | None) -> dict:
    base = _default_copilot_memory()
    raw = memory if isinstance(memory, dict) else {}
    normalized = dict(base)
    for list_key in ["preferred_symbols", "preferred_timeframes", "preferred_brokers", "recent_topics", "recent_actions", "notes"]:
        values = raw.get(list_key)
        if isinstance(values, list):
            normalized[list_key] = [_clean_text(item) for item in values if _clean_text(item)][:8]
    for counter_key in ["topic_counts", "action_counts"]:
        values = raw.get(counter_key)
        if isinstance(values, dict):
            normalized[counter_key] = {
                _clean_text(key): max(0, _safe_int(value))
                for key, value in values.items()
                if _clean_text(key)
            }
    style = _clean_text(raw.get("response_style") or base["response_style"]).lower()
    normalized["response_style"] = style if style in {"brief", "concise", "simple", "detailed"} else "concise"
    for key in ["last_scope", "last_symbol", "last_timeframe"]:
        normalized[key] = _clean_text(raw.get(key))
    return normalized


def _update_copilot_memory(memory: dict | None, *, question: str, context: dict, plan: dict, scope: str) -> dict:
    memory_state = _normalize_copilot_memory(memory)
    style_hint = _memory_style_hint_from_text(question)
    if style_hint:
        memory_state["response_style"] = style_hint

    symbol, tf_label = plan.get("symbol_tf") or ("", "")
    broker_name = _clean_text((context or {}).get("broker_name"))
    if symbol:
        memory_state["preferred_symbols"] = _recent_push(memory_state.get("preferred_symbols", []), symbol, limit=4)
        memory_state["last_symbol"] = symbol
    if tf_label:
        memory_state["preferred_timeframes"] = _recent_push(memory_state.get("preferred_timeframes", []), tf_label, limit=4)
        memory_state["last_timeframe"] = tf_label
    if broker_name:
        memory_state["preferred_brokers"] = _recent_push(memory_state.get("preferred_brokers", []), broker_name, limit=3)

    intents = list(plan.get("intents") or [])
    actions = list(plan.get("actions") or [])
    for intent in intents:
        memory_state["topic_counts"] = _counter_bump(memory_state.get("topic_counts"), intent)
        memory_state["recent_topics"] = _recent_push(memory_state.get("recent_topics", []), intent, limit=5)
    for action in actions:
        memory_state["action_counts"] = _counter_bump(memory_state.get("action_counts"), action)
        memory_state["recent_actions"] = _recent_push(memory_state.get("recent_actions", []), action, limit=5)

    note_candidates: list[str] = []
    if symbol and tf_label:
        note_candidates.append(f"Often focuses on {symbol} on {tf_label}.")
    if broker_name:
        note_candidates.append(f"Usually checks broker context for {broker_name}.")
    if style_hint:
        note_candidates.append(f"Prefers {style_hint} replies.")
    for note in note_candidates:
        memory_state["notes"] = _recent_push(memory_state.get("notes", []), note, limit=5)

    memory_state["last_scope"] = _clean_text(scope)
    return memory_state


def _memory_summary_lines(memory: dict | None) -> list[str]:
    memory_state = _normalize_copilot_memory(memory)
    lines: list[str] = []
    if memory_state["preferred_symbols"]:
        focus = memory_state["preferred_symbols"][0]
        timeframe = memory_state["preferred_timeframes"][0] if memory_state["preferred_timeframes"] else ""
        if timeframe:
            lines.append(f"User usually focuses on {focus} on {timeframe}.")
        else:
            lines.append(f"User usually focuses on {focus}.")
    if memory_state["preferred_brokers"]:
        lines.append(f"User often works through {memory_state['preferred_brokers'][0]}.")
    style = memory_state.get("response_style")
    if style and style != "concise":
        lines.append(f"Preferred reply style: {style}.")
    if memory_state["recent_topics"]:
        lines.append("Recent topics: " + ", ".join(memory_state["recent_topics"][:3]) + ".")
    if memory_state["recent_actions"]:
        lines.append("Recent actions: " + ", ".join(memory_state["recent_actions"][:3]) + ".")
    return lines[:5]


def _memory_response_instruction(memory: dict | None) -> str:
    style = _normalize_copilot_memory(memory).get("response_style")
    if style == "brief":
        return "Keep replies extra tight: one short answer first, then one short follow-up sentence if needed."
    if style == "simple":
        return "Use very plain language. Prefer simpler words over trading jargon when possible."
    if style == "detailed":
        return "The user can handle more detail. Include a little more reasoning before the next-step advice."
    return "Keep replies concise and practical."


@lru_cache(maxsize=1)
def _copilot_logo_data_uri() -> str:
    for candidate in (PROJECT_ROOT / "fin-logo.jpeg", PROJECT_ROOT / "logo.png"):
        try:
            if candidate.exists():
                mime = "image/png" if candidate.suffix.lower() == ".png" else "image/jpeg"
                encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
                return f"data:{mime};base64,{encoded}"
        except OSError:
            continue
    return ""


@lru_cache(maxsize=1)
def _copilot_launcher_icon_data_uri() -> str:
    svg = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
      <defs>
        <linearGradient id="copilotBubble" x1="15" y1="12" x2="50" y2="50" gradientUnits="userSpaceOnUse">
          <stop stop-color="#A7FFF6"/>
          <stop offset="0.5" stop-color="#3BE7D8"/>
          <stop offset="1" stop-color="#0EA89D"/>
        </linearGradient>
        <filter id="copilotGlow" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="3.2" result="blur"/>
          <feColorMatrix
            in="blur"
            type="matrix"
            values="0 0 0 0 0.13 0 0 0 0 0.97 0 0 0 0 0.89 0 0 0 0.7 0"
            result="glow"
          />
          <feMerge>
            <feMergeNode in="glow"/>
            <feMergeNode in="SourceGraphic"/>
          </feMerge>
        </filter>
      </defs>
      <g filter="url(#copilotGlow)">
        <path
          d="M20 16.5H44C49.2467 16.5 53.5 20.7533 53.5 26V35C53.5 40.2467 49.2467 44.5 44 44.5H34.8L27.8 50.2C26.8047 51.0106 25.3276 50.3021 25.3276 49.0183V44.5H20C14.7533 44.5 10.5 40.2467 10.5 35V26C10.5 20.7533 14.7533 16.5 20 16.5Z"
          fill="url(#copilotBubble)"
        />
        <path
          d="M20 16.5H44C49.2467 16.5 53.5 20.7533 53.5 26V35C53.5 40.2467 49.2467 44.5 44 44.5H34.8L27.8 50.2C26.8047 51.0106 25.3276 50.3021 25.3276 49.0183V44.5H20C14.7533 44.5 10.5 40.2467 10.5 35V26C10.5 20.7533 14.7533 16.5 20 16.5Z"
          stroke="#DFFFFA"
          stroke-width="2.2"
          stroke-linejoin="round"
        />
        <circle cx="23" cy="30.5" r="2.5" fill="#F7FFFE"/>
        <circle cx="32" cy="30.5" r="2.5" fill="#F7FFFE"/>
        <circle cx="41" cy="30.5" r="2.5" fill="#F7FFFE"/>
      </g>
    </svg>
    """.strip()
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _signal_label(signal: str) -> str:
    normalized = _clean_text(signal).upper()
    if normalized in {"BUY", "SELL", "HOLD"}:
        return normalized
    return "HOLD"


def _context_fingerprint(context: dict) -> str:
    signal = context.get("signal") or {}
    signal_meta = context.get("signal_meta") or {}
    preview = context.get("preview") or {}
    connector = context.get("connector") or {}
    execution = context.get("execution") or {}
    payload = {
        "broker_name": context.get("broker_name", ""),
        "connection_method": context.get("connection_method", ""),
        "balance": round(_safe_float(context.get("balance")), 2),
        "status_text": context.get("status_text", ""),
        "signal": signal.get("signal", ""),
        "confidence": round(_safe_float(signal.get("confidence")), 2),
        "symbol": signal_meta.get("symbol", ""),
        "timeframe": signal_meta.get("tf_label", ""),
        "preview_status": preview.get("status", ""),
        "preview_reason": preview.get("reason", ""),
        "connector_summary": connector.get("summary", ""),
        "execution_status": execution.get("status", ""),
        "execution_message": execution.get("message", ""),
    }
    return json.dumps(payload, sort_keys=True)


def _secret_value(name: str, default: str = "") -> str:
    try:
        raw = st.secrets.get(name)
        if raw is not None:
            return str(raw).strip()
    except Exception:
        pass
    return str(os.getenv(name, default)).strip()


def _copilot_model_config() -> dict:
    timeout_seconds = max(6, min(90, _safe_int(_secret_value("FINWISE_COPILOT_TIMEOUT_SECONDS", "25"), 25)))
    max_history = max(2, min(10, _safe_int(_secret_value("FINWISE_COPILOT_MAX_HISTORY", "6"), 6)))
    openai_key = _secret_value("OPENAI_API_KEY")
    provider = (_secret_value("FINWISE_COPILOT_PROVIDER") or ("openai" if openai_key else "ollama")).lower()
    default_model = "gpt-4o-mini" if provider == "openai" else "llama3.1:8b"
    default_base_url = "https://api.openai.com/v1" if provider == "openai" else "http://127.0.0.1:11434"
    model = (
        _secret_value("FINWISE_COPILOT_MODEL")
        or _secret_value("OPENAI_MODEL")
        or default_model
    )
    return {
        "provider": provider,
        "api_key": openai_key,
        "model": model,
        "fallback_model": _secret_value("FINWISE_COPILOT_FALLBACK_MODEL"),
        "base_url": (_secret_value("FINWISE_COPILOT_BASE_URL") or default_base_url).rstrip("/"),
        "timeout_seconds": timeout_seconds,
        "max_history": max_history,
        "temperature": max(0.0, min(1.2, _safe_float(_secret_value("FINWISE_COPILOT_TEMPERATURE", "0.18"), 0.18))),
        "max_tokens": max(180, min(900, _safe_int(_secret_value("FINWISE_COPILOT_MAX_TOKENS", "520"), 520))),
        "ollama_num_ctx": max(2048, min(16384, _safe_int(_secret_value("FINWISE_COPILOT_OLLAMA_NUM_CTX", "8192"), 8192))),
    }


def _copilot_mode_label(config: dict | None = None) -> str:
    config = config or _copilot_model_config()
    if config.get("provider") == "ollama":
        return "Local model"
    if config.get("provider") == "openai" and config.get("api_key"):
        return "Model-backed"
    return "Finwise native"


@st.cache_data(show_spinner=False, ttl=20)
def _probe_copilot_runtime(provider: str, base_url: str, model: str, fallback_model: str, has_openai_key: bool) -> dict:
    if provider == "openai":
        if has_openai_key:
            return {
                "ready": True,
                "mode": "live AI model",
                "summary": f"{model} is configured and ready for cloud responses.",
                "active_model": model,
            }
        return {
            "ready": False,
            "mode": "Finwise native copilot",
            "summary": "No cloud AI key is configured, so Finwise will use native reasoning.",
            "active_model": "",
        }

    if provider == "ollama":
        try:
            response = requests.get(f"{base_url}/api/tags", timeout=4)
            response.raise_for_status()
            data = response.json()
            model_names = []
            for item in data.get("models") or []:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if name:
                        model_names.append(name)
            active_model = ""
            if model in model_names:
                active_model = model
            elif fallback_model and fallback_model in model_names:
                active_model = fallback_model
            if active_model:
                return {
                    "ready": True,
                    "mode": "local model",
                    "summary": f"{active_model} is live in your local Finwise runtime.",
                    "active_model": active_model,
                }
            return {
                "ready": False,
                "mode": "Finwise native copilot",
                "summary": f"Ollama is running, but neither {model} nor the configured fallback model is installed yet.",
                "active_model": "",
            }
        except requests.RequestException:
            return {
                "ready": False,
                "mode": "Finwise native copilot",
                "summary": "Local model runtime is offline, so Finwise will use native reasoning.",
                "active_model": "",
            }

    return {
        "ready": False,
        "mode": "Finwise native copilot",
        "summary": "No supported model runtime is configured, so Finwise will use native reasoning.",
        "active_model": "",
    }


def _copilot_runtime_status(config: dict | None = None) -> dict:
    config = config or _copilot_model_config()
    return _probe_copilot_runtime(
        str(config.get("provider") or "").strip().lower(),
        str(config.get("base_url") or "").strip(),
        str(config.get("model") or "").strip(),
        str(config.get("fallback_model") or "").strip(),
        bool(config.get("api_key")),
    )


def _json_safe(value, *, depth: int = 0):
    if depth > 4:
        return str(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item, depth=depth + 1)
            for key, item in list(value.items())[:40]
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item, depth=depth + 1) for item in list(value)[:16]]
    return str(value)


def _copilot_memory_snapshot(memory: dict | None) -> dict:
    memory_state = _normalize_copilot_memory(memory)
    return {
        "preferred_symbols": memory_state.get("preferred_symbols", [])[:3],
        "preferred_timeframes": memory_state.get("preferred_timeframes", [])[:3],
        "preferred_brokers": memory_state.get("preferred_brokers", [])[:2],
        "response_style": memory_state.get("response_style", "concise"),
        "recent_topics": memory_state.get("recent_topics", [])[:4],
        "recent_actions": memory_state.get("recent_actions", [])[:4],
        "notes": memory_state.get("notes", [])[:4],
    }


def _copilot_context_snapshot(context: dict, memory: dict | None = None, plan: dict | None = None) -> dict:
    signal = context.get("signal") or {}
    signal_meta = context.get("signal_meta") or {}
    preview = context.get("preview") or {}
    connector = context.get("connector") or {}
    execution = context.get("execution") or {}
    thresholds = context.get("bot_thresholds") or {}
    return {
        "broker": {
            "name": context.get("broker_name"),
            "connection_method": context.get("connection_method"),
            "balance": context.get("balance"),
            "total_trades": context.get("total_trades"),
            "drawdown_percent": context.get("drawdown"),
            "status_text": context.get("status_text"),
        },
        "market": {
            "symbol": signal_meta.get("symbol"),
            "timeframe": signal_meta.get("tf_label"),
            "signal": signal.get("signal"),
            "confidence": signal.get("confidence"),
            "reason": signal.get("reason"),
            "summary": _json_safe(signal.get("summary") or {}),
            "regime": _json_safe(signal.get("regime") or {}),
            "entry_exit": _json_safe(signal.get("entry_exit") or {}),
            "position_size": _json_safe(signal.get("position_size") or {}),
            "adaptive_profile": _json_safe(signal.get("adaptive_profile") or {}),
            "black_swan_risk": _json_safe(signal.get("black_swan_risk") or {}),
        },
        "route": _json_safe(preview),
        "connector": _json_safe(connector),
        "last_execution": _json_safe(execution),
        "bot_thresholds": _json_safe(thresholds),
        "user_memory": _json_safe(_copilot_memory_snapshot(memory)),
        "active_plan": _json_safe(
            {
                "intents": list((plan or {}).get("intents") or []),
                "actions": list((plan or {}).get("actions") or []),
                "question": _clean_text((plan or {}).get("question")),
            }
        ),
    }


def _build_model_context_packet(context: dict, memory: dict | None, plan: dict | None) -> dict:
    packet = _copilot_context_snapshot(context, memory, plan)
    packet["memory_summary_lines"] = _memory_summary_lines(memory)
    packet["answer_shape"] = {
        "lead": "Answer the user's question directly first.",
        "follow_up": "Then explain why it matters in Finwise terms.",
        "close": "End with the best next step when relevant.",
    }
    return packet


def _copilot_history_for_model(messages: list[dict], max_history: int) -> list[dict]:
    usable = []
    for message in messages[-max_history * 2 :]:
        role = str(message.get("role") or "").strip().lower()
        content = _clean_text(message.get("content"))
        if role in {"user", "assistant"} and content:
            usable.append({"role": role, "content": content[:1800]})
    return usable[-max_history * 2 :]


def _model_system_prompt(memory: dict | None, plan: dict | None) -> str:
    memory_lines = _memory_summary_lines(memory)
    memory_block = "\n".join(f"- {line}" for line in memory_lines) if memory_lines else "- No durable user memory yet."
    style_instruction = _memory_response_instruction(memory)
    requested_actions = ", ".join(list((plan or {}).get("actions") or [])) or "none"
    requested_intents = ", ".join(list((plan or {}).get("intents") or [])) or "general"
    return dedent(
        f"""
        You are Finwise Copilot, an in-app trading assistant inside the Finwise AI application.
        Use the provided Finwise live context as the source of truth.
        Your job is to explain what the market is doing, why the route is ready or blocked, what risk controls are active,
        and what the user should pay attention to next.

        Working style:
        - {style_instruction}
        - Answer like a sharp in-app teammate, not a dashboard.
        - Lead with the direct answer before supporting detail.
        - If the user asks multiple things, cover each one clearly in the same reply.
        - If an in-app action was requested, acknowledge the action naturally and then explain what matters.
        - Do not invent balances, prices, broker status, or executions that are not present in context.
        - If context is missing, say so clearly and tell the user what to run or open next.
        - Treat this as educational trading support, not guaranteed financial advice.
        - Prefer short paragraphs or a few flat bullets over long essays.

        Current turn focus:
        - Detected intents: {requested_intents}
        - Requested actions: {requested_actions}

        Durable user memory:
        {memory_block}
        """
    ).strip()


def _call_openai_copilot(question: str, context: dict, messages: list[dict], memory: dict | None = None, plan: dict | None = None) -> tuple[str | None, str | None]:
    config = _copilot_model_config()
    if config.get("provider") != "openai":
        return None, None
    if not config.get("api_key"):
        return None, None

    system_prompt = _model_system_prompt(memory, plan)
    context_payload = json.dumps(_build_model_context_packet(context, memory, plan), ensure_ascii=True)
    payload = {
        "model": str(_copilot_runtime_status(config).get("active_model") or config["model"]),
        "temperature": config["temperature"],
        "max_tokens": config["max_tokens"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": f"Live Finwise context JSON:\n{context_payload}"},
            *_copilot_history_for_model(messages, config["max_history"]),
            {"role": "user", "content": question},
        ],
    }

    try:
        response = requests.post(
            f"{config['base_url']}/chat/completions",
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=config["timeout_seconds"],
        )
        response.raise_for_status()
        data = response.json()
        choice = ((data.get("choices") or [{}])[0]).get("message") or {}
        content = choice.get("content")
        if isinstance(content, str) and _clean_text(content):
            return _clean_text(content), None
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content") or ""
                    if text:
                        parts.append(str(text))
            joined = _clean_text("\n".join(parts))
            if joined:
                return joined, None
        return None, "The model returned an empty reply."
    except requests.RequestException as exc:
        return None, f"Network error while reaching the copilot model: {exc}"
    except (ValueError, KeyError, TypeError) as exc:
        return None, f"Copilot model response could not be parsed: {exc}"


def _call_ollama_copilot(question: str, context: dict, messages: list[dict], memory: dict | None = None, plan: dict | None = None) -> tuple[str | None, str | None]:
    config = _copilot_model_config()
    if config.get("provider") != "ollama":
        return None, None
    runtime = _copilot_runtime_status(config)
    active_model = str(runtime.get("active_model") or config["model"])

    system_prompt = _model_system_prompt(memory, plan)
    context_payload = json.dumps(_build_model_context_packet(context, memory, plan), ensure_ascii=True)
    payload = {
        "model": active_model,
        "stream": False,
        "options": {
            "temperature": config["temperature"],
            "num_ctx": config["ollama_num_ctx"],
        },
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": f"Live Finwise context JSON:\n{context_payload}"},
            *_copilot_history_for_model(messages, config["max_history"]),
            {"role": "user", "content": question},
        ],
    }

    try:
        response = requests.post(
            f"{config['base_url']}/api/chat",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=config["timeout_seconds"],
        )
        response.raise_for_status()
        data = response.json()
        message = data.get("message") or {}
        content = _clean_text(message.get("content"))
        if content:
            return content, None
        return None, "The local model returned an empty reply."
    except requests.RequestException as exc:
        return None, f"Local model request failed: {exc}"
    except (ValueError, KeyError, TypeError) as exc:
        return None, f"Local model response could not be parsed: {exc}"


def _call_model_copilot(question: str, context: dict, messages: list[dict], memory: dict | None = None, plan: dict | None = None) -> tuple[str | None, str | None, str | None]:
    config = _copilot_model_config()
    provider = config.get("provider")
    if provider == "openai":
        reply, error = _call_openai_copilot(question, context, messages, memory, plan)
        return reply, error, "live AI model"
    if provider == "ollama":
        reply, error = _call_ollama_copilot(question, context, messages, memory, plan)
        return reply, error, "local model"
    return None, None, None


def _append_message(state_key: str, role: str, content: str) -> None:
    content = _clean_text(content)
    if not content:
        return
    messages = list(st.session_state.get(state_key, []))
    messages.append({"role": role, "content": content})
    st.session_state[state_key] = messages[-12:]


def _execution_gate_text(context: dict) -> str:
    thresholds = context.get("bot_thresholds") or {}
    preview = context.get("preview") or {}
    signal = context.get("signal") or {}
    entry_exit = signal.get("entry_exit") or {}

    rr_ratio = _safe_float(preview.get("profit_guard", {}).get("risk_reward_ratio") or entry_exit.get("risk_reward_ratio"))
    projected_edge = _safe_float(preview.get("profit_guard", {}).get("projected_profit_percent"))
    min_conf = _safe_float(thresholds.get("min_confidence"))
    min_rr = _safe_float(thresholds.get("min_rr"))
    min_edge = _safe_float(thresholds.get("min_edge"))
    confidence = _safe_float(signal.get("confidence"))

    if preview.get("status") == "ready":
        return (
            f"Auto trade is ready because confidence is {confidence:.0f}% against a {min_conf:.0f}% gate, "
            f"risk/reward is {rr_ratio:.2f}R against {min_rr:.2f}R, and projected edge is "
            f"{projected_edge:.2f}% against {min_edge:.2f}%."
        )

    if preview.get("status") == "blocked":
        failed_checks = preview.get("profit_guard", {}).get("failed_checks", []) or []
        if failed_checks:
            return "Auto trade is blocked because " + "; ".join(str(item) for item in failed_checks) + "."
        reason = _clean_text(preview.get("reason"))
        if reason:
            return f"Auto trade is blocked because {reason.rstrip('.')}."

    signal_label = _signal_label(signal.get("signal", "HOLD"))
    if signal_label == "HOLD":
        return "Finwise is not routing an order right now because the current setup is still in HOLD mode."

    return (
        f"The route is waiting on a fresh auto-trade test, but the current setup is {signal_label} with "
        f"{confidence:.0f}% confidence and {rr_ratio:.2f}R structure."
    )


def _market_text(context: dict) -> str:
    signal = context.get("signal") or {}
    signal_meta = context.get("signal_meta") or {}
    regime = signal.get("regime") or {}
    black_swan = signal.get("black_swan_risk") or {}
    summary = signal.get("summary") or {}

    symbol = _clean_text(signal_meta.get("symbol") or "the active market")
    timeframe = _clean_text(signal_meta.get("tf_label") or "current timeframe")
    reason = _clean_text(signal.get("reason") or regime.get("reason") or "Finwise is reading mixed structure.")
    setup_quality = _clean_text(summary.get("setup_quality") or "neutral")
    risk_level = _safe_int(black_swan.get("risk_level"))

    risk_line = (
        f"Black-swan risk is {risk_level}/100."
        if risk_level > 0
        else "No major shock condition is flagged right now."
    )
    return (
        f"Market-wise, {symbol} on {timeframe} looks {setup_quality}. "
        f"{reason} {risk_line}"
    )


def _market_review_text(context: dict) -> str:
    signal = context.get("signal") or {}
    signal_meta = context.get("signal_meta") or {}
    summary = signal.get("summary") or {}

    symbol = _clean_text(signal_meta.get("symbol") or "the active market")
    timeframe = _clean_text(signal_meta.get("tf_label") or "current timeframe")
    reason = _clean_text(signal.get("reason") or "Finwise is reading mixed structure.")
    setup_quality = _clean_text(summary.get("setup_quality") or "neutral")
    signal_label = _signal_label(signal.get("signal", "HOLD"))
    confidence = _safe_float(signal.get("confidence"))

    if signal:
        return (
            f"Today’s read on {symbol} for {timeframe} is this: {reason} "
            f"Right now the bias is {signal_label} with about {confidence:.0f}% confidence, so the setup still looks {setup_quality} rather than fully committed."
        )
    return f"Today’s read on {symbol} for {timeframe} is this: {reason}"


def _risk_text(context: dict) -> str:
    signal = context.get("signal") or {}
    thresholds = context.get("bot_thresholds") or {}
    profile = signal.get("adaptive_profile") or {}
    entry_exit = signal.get("entry_exit") or {}
    position_size = signal.get("position_size") or {}

    confidence = _safe_float(signal.get("confidence"))
    min_confidence = _safe_float(profile.get("min_confidence") or thresholds.get("min_confidence"))
    rr_ratio = _safe_float(entry_exit.get("risk_reward_ratio"))
    min_rr = _safe_float(entry_exit.get("adaptive_min_rr_ratio") or profile.get("min_rr_ratio") or thresholds.get("min_rr"))
    size_usd = _safe_float(position_size.get("position_size_usd"))
    stop_loss = _safe_float(entry_exit.get("stop_loss"))
    take_profit = _safe_float(entry_exit.get("take_profit"))

    return (
        f"On risk, Finwise is checking a {confidence:.0f}% confidence read against a {min_confidence:.0f}% minimum, "
        f"{rr_ratio:.2f}R structure against a {min_rr:.2f}R floor, and a planned size of {_fmt_money(size_usd)}. "
        f"The current map has stop loss near {_fmt_price(stop_loss)} and take profit near {_fmt_price(take_profit)}."
    )


def _trade_plan_text(context: dict) -> str:
    signal = context.get("signal") or {}
    signal_meta = context.get("signal_meta") or {}
    entry_exit = signal.get("entry_exit") or {}
    position_size = signal.get("position_size") or {}
    preview = context.get("preview") or {}

    symbol = _clean_text(signal_meta.get("symbol") or "the active market")
    timeframe = _clean_text(signal_meta.get("tf_label") or "current timeframe")
    signal_label = _signal_label(signal.get("signal", "HOLD"))
    confidence = _safe_float(signal.get("confidence"))
    entry_price = _safe_float(entry_exit.get("entry_price"))
    stop_loss = _safe_float(entry_exit.get("stop_loss"))
    take_profit = _safe_float(entry_exit.get("take_profit"))
    rr_ratio = _safe_float(entry_exit.get("risk_reward_ratio"))
    size_usd = _safe_float(position_size.get("position_size_usd"))
    quantity = _safe_float(position_size.get("quantity"))

    if not signal:
        return "I do not have a trade map yet. Run a fresh signal first so Finwise can calculate entry, stop, target, and size."

    if signal_label == "HOLD":
        return (
            f"Trade map for {symbol} on {timeframe}: Finwise is in HOLD, so there is no active entry to chase. "
            f"The safer move is to wait for a cleaner signal and rerun the setup after more candles print."
        )

    route_status = _clean_text(preview.get("status") or "waiting")
    route_line = (
        "The route is open."
        if route_status == "ready"
        else "The route is still blocked."
        if route_status == "blocked"
        else "The route has not cleared yet."
    )
    return (
        f"Trade map for {symbol} on {timeframe}: bias is {signal_label} at {confidence:.0f}% confidence. "
        f"Entry is around {_fmt_price(entry_price)}, stop loss is near {_fmt_price(stop_loss)}, take profit is near {_fmt_price(take_profit)}, "
        f"and the structure is {rr_ratio:.2f}R. Planned size is about {_fmt_money(size_usd)}"
        f"{f' ({quantity:g} units)' if quantity > 0 else ''}. {route_line} Treat it as a plan to review, not a guaranteed trade."
    )


def _next_step_text(context: dict) -> str:
    signal = context.get("signal") or {}
    preview = context.get("preview") or {}
    connector = context.get("connector") or {}
    signal_label = _signal_label(signal.get("signal", "HOLD"))

    if not signal:
        return "What I’d do next is run a fresh signal so I can explain the live market and execution path with real Finwise context."

    if connector and connector.get("status") not in {"ready", ""}:
        return "What I’d do next is finish the connector test cleanly so Finwise can confirm balance, pricing, and fees before routing anything."

    if preview.get("status") == "blocked":
        return "What I’d do next is wait for a cleaner setup or rerun the route test after the next candle so the gates can re-check confidence, reward, and edge."

    if preview.get("status") == "ready":
        return "What I’d do next is either execute with the connected broker if it still matches your plan, or keep monitoring if you want one more layer of confirmation."

    if signal_label == "HOLD":
        return "What I’d do next is stay patient and rerun the signal after more candles print. Finwise is still waiting for stronger confirmation."

    return "What I’d do next is run the auto-trade route test so Finwise can verify the exact execution gates for this setup."


def _broker_text(context: dict) -> str:
    broker_name = _clean_text(context.get("broker_name") or "your broker")
    connection_method = _clean_text(context.get("connection_method") or "connected")
    balance = _fmt_money(context.get("balance"))
    total_trades = _safe_int(context.get("total_trades"))
    drawdown = _fmt_pct(context.get("drawdown"))
    status_text = _clean_text(context.get("status_text"))

    if connection_method == "not_connected":
        reply = (
            f"On the broker side, {broker_name} is Not Connected. "
            f"Finwise is using a local balance basis of {balance}, total routed trades are {total_trades}, "
            f"and current drawdown is {drawdown}."
        )
    else:
        reply = (
            f"On the broker side, {broker_name} is connected through {connection_method.replace('_', ' ').title()}. "
            f"Finwise is working from a synced balance basis of {balance}, total routed trades are {total_trades}, "
            f"and current drawdown is {drawdown}."
        )
    if status_text:
        reply += f" Latest workspace update: {status_text}"
    return reply


def _execution_text(context: dict) -> str:
    execution = context.get("execution") or {}
    signal = context.get("signal") or {}

    if execution and execution.get("status") == "success":
        trade = execution.get("trade") or {}
        signal_type = _signal_label(trade.get("signal", signal.get("signal", "HOLD")))
        return (
            f"Finwise executed {signal_type} on {_clean_text(trade.get('symbol') or context.get('signal_meta', {}).get('symbol') or 'the selected market')} "
            f"because the setup cleared the hard guards. Entry was around {_fmt_price(trade.get('entry_price'))}, "
            f"projected edge was {_fmt_pct(trade.get('projected_profit_percent'))}, and the target price was "
            f"{_fmt_price(trade.get('target_profit_price'))}."
        )

    preview = context.get("preview") or {}
    signal_label = _signal_label(signal.get("signal", "HOLD"))
    gate_text = _execution_gate_text(context)

    if preview.get("status") == "blocked":
        return f"Right now the route is blocked. {gate_text}"
    if preview.get("status") == "ready":
        return f"Right now the route is open. {gate_text}"
    if signal_label == "HOLD":
        return f"Right now Finwise is waiting, not routing. {gate_text}"
    return gate_text


def _overview_text(context: dict) -> str:
    signal = context.get("signal") or {}
    signal_label = _signal_label(signal.get("signal", "HOLD"))
    confidence = _safe_float(signal.get("confidence"))
    parts = [
        _broker_text(context),
        _market_text(context),
    ]
    if signal:
        parts.append(f"The active Finwise signal is {signal_label} with {confidence:.0f}% confidence.")
    parts.append(_execution_text(context))
    parts.append(_next_step_text(context))
    return " ".join(part for part in parts if part)


def _welcome_text(context: dict) -> str:
    signal_meta = context.get("signal_meta") or {}
    symbol = _clean_text(signal_meta.get("symbol"))
    if symbol:
        return f"I’m Finwise Copilot. Ask me about {symbol}, the route, or what the market is doing."
    return "I’m Finwise Copilot. Ask me about the market, the route, or risk controls."


def _recent_user_turns(messages: list[dict], limit: int = 3) -> list[str]:
    turns: list[str] = []
    for message in reversed(messages):
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        content = _clean_text(message.get("content"))
        if content:
            turns.append(content)
        if len(turns) >= limit:
            break
    return list(reversed(turns))


def _expanded_question(question: str, messages: list[dict] | None = None) -> str:
    base = _clean_text(question)
    if not base or not messages:
        return base

    lower = base.lower()
    needs_history = (
        len(lower.split()) <= 8
        or any(
            token in lower
            for token in [
                "it",
                "that",
                "this",
                "they",
                "them",
                "again",
                "more",
                "why",
                "how so",
                "what about",
            ]
        )
    )
    if not needs_history:
        return base

    prior_turns = [turn for turn in _recent_user_turns(messages, limit=2) if _clean_text(turn).lower() != lower]
    if not prior_turns:
        return base
    return " ".join(prior_turns + [base])


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        cleaned = _clean_text(item)
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen


def _detect_agent_intents(expanded_lower: str) -> list[str]:
    intents: list[str] = []
    if any(token in expanded_lower for token in ["broker", "balance", "account", "connected", "connection"]):
        intents.append("broker")
    if any(token in expanded_lower for token in ["market", "trend", "regime", "volatility", "happening", "price", "review", "today", "chart", "structure"]):
        intents.append("market")
    if any(token in expanded_lower for token in ["risk", "confidence", "stop", "take profit", "reward", "rr", "loss", "drawdown", "size"]):
        intents.append("risk")
    if any(token in expanded_lower for token in ["trade map", "trade plan", "entry", "entry price", "target", "take this trade", "place this trade", "setup plan", "sl", "tp"]):
        intents.append("trade_plan")
    if any(token in expanded_lower for token in ["route", "execution", "execute", "auto trade", "blocked", "block", "trading this way", "trade this way", "gate"]):
        intents.append("route")
    if any(token in expanded_lower for token in ["next", "do now", "what should", "should i", "what now", "now what", "what to watch", "watch next"]):
        intents.append("next")
    if any(token in expanded_lower for token in ["overview", "summary", "recap", "what is going on", "what's going on", "update me"]):
        intents.append("overview")
    return _dedupe_preserve(intents)


def _detect_agent_actions(expanded_lower: str) -> list[str]:
    action_specs = [
        ("run_signal", ["run signal", "rerun signal", "fresh signal", "new signal", "generate signal", "refresh signal", "check signal"]),
        ("open_order_book", ["open order book", "open the order book", "show order book", "show the order book", "view order book", "show depth", "open depth", "open orderbook"]),
        ("open_signal_panel", ["open ai signal", "show ai signal", "open signal panel", "show signal panel"]),
        ("open_market_stats", ["open market stats", "show market stats", "open market overview", "show market overview", "open overview"]),
        ("open_controls", ["open controls", "show controls", "chart controls", "open indicators", "show indicators", "chart settings", "indicator settings"]),
        ("open_watchlist", ["open watchlist", "show watchlist", "view watchlist"]),
        ("open_broker_execution", ["open broker", "open broker execution", "open execution", "open broker workspace", "open trade desk", "go to trading desk", "take me to broker", "show broker execution"]),
        ("open_trade_journal", ["open journal", "open trade journal", "open trade history", "show journal", "show trade history", "open history"]),
        ("open_settings", ["open settings", "account settings", "app settings"]),
    ]
    actions = [name for name, patterns in action_specs if any(pattern in expanded_lower for pattern in patterns)]
    return _dedupe_preserve(actions)


def _active_market_focus(context: dict) -> tuple[str, str]:
    signal_meta = context.get("signal_meta") or {}
    symbol = (
        _clean_text(signal_meta.get("symbol"))
        or _clean_text(st.session_state.get("selected_symbol"))
        or _clean_text(st.session_state.get("market_analysis_pair_select"))
        or "BTCUSDT"
    ).upper()
    tf_label = (
        _clean_text(signal_meta.get("tf_label"))
        or _clean_text(st.session_state.get("market_analysis_tf_control"))
        or _clean_text(st.session_state.get("market_analysis_tf_radio"))
        or "1m"
    )
    return symbol, tf_label


def _normalize_agent_actions(actions: list[str]) -> list[str]:
    if not actions:
        return []
    if "run_signal" in actions:
        return ["run_signal"]
    for action in ["open_broker_execution", "open_trade_journal", "open_settings"]:
        if action in actions:
            return [action]
    for action in ["open_order_book", "open_signal_panel", "open_market_stats", "open_controls", "open_watchlist"]:
        if action in actions:
            return [action]
    return actions[:1]


def _plan_agent_turn(question: str, context: dict, messages: list[dict] | None = None) -> dict:
    raw = _clean_text(question)
    expanded = _expanded_question(raw, messages)
    lower = raw.lower()
    expanded_lower = expanded.lower()
    is_greeting = lower in {"hello", "hi", "hey", "helloo", "yo", "sup"}
    intents = _detect_agent_intents(expanded_lower)
    actions = _normalize_agent_actions(_detect_agent_actions(expanded_lower))
    if not intents and any(token in expanded_lower for token in ["blocked", "block", "route", "execution"]):
        intents.append("route")
    if not intents and any(token in expanded_lower for token in ["entry", "target", "take this trade", "trade plan", "trade map"]):
        intents.append("trade_plan")
    if not intents and any(token in expanded_lower for token in ["market", "review", "today", "price", "chart"]):
        intents.append("market")
    if not intents and any(token in expanded_lower for token in ["what's going on", "what is going on", "update me"]):
        intents.append("overview")
    wants_explanation = bool(intents) or any(
        token in expanded_lower
        for token in ["why", "what", "how", "explain", "review", "status", "doing", "happening", "?"]
    )
    return {
        "question": raw,
        "expanded_question": expanded,
        "expanded_lower": expanded_lower,
        "is_greeting": is_greeting,
        "intents": intents,
        "actions": actions,
        "wants_explanation": wants_explanation,
        "symbol_tf": _active_market_focus(context),
    }


def _route_market_focus(symbol: str, tf_label: str) -> None:
    st.session_state.nav_choice = "Market Analysis"
    st.session_state.market_analysis_pair_select = symbol
    st.session_state.selected_symbol = symbol
    st.session_state.market_analysis_tf_control = tf_label
    st.session_state.market_analysis_tf_radio = tf_label


def _execute_agent_actions(plan: dict, context: dict, scope: str, *, commit: bool = True) -> list[str]:
    del context, scope
    symbol, tf_label = plan.get("symbol_tf") or ("BTCUSDT", "1m")
    action_notes: list[str] = []
    for action in plan.get("actions", []):
        if action == "run_signal":
            if commit:
                _route_market_focus(symbol, tf_label)
            action_notes.append(f"I kicked off a fresh signal for {symbol} on {tf_label}.")
        elif action == "open_order_book":
            if commit:
                _route_market_focus(symbol, tf_label)
            action_notes.append(f"I opened the Order Book for {symbol} on {tf_label}.")
        elif action == "open_signal_panel":
            if commit:
                _route_market_focus(symbol, tf_label)
            action_notes.append(f"I opened the AI Signal panel for {symbol}.")
        elif action == "open_market_stats":
            if commit:
                _route_market_focus(symbol, tf_label)
            action_notes.append(f"I opened the Market Stats panel for {symbol}.")
        elif action == "open_controls":
            if commit:
                _route_market_focus(symbol, tf_label)
            action_notes.append("I opened the chart controls.")
        elif action == "open_watchlist":
            if commit:
                _route_market_focus(symbol, tf_label)
            action_notes.append("I opened the watchlist.")
        elif action == "open_broker_execution":
            if commit:
                st.session_state.trading_desk_view = "Broker & Execution"
                st.session_state.open_broker_execution = True
                st.session_state.nav_choice = "Trading Desk"
                st.session_state.auto_trade_status = f"Opening Broker & Execution for {symbol} on {tf_label}."
            action_notes.append("I opened Broker & Execution.")
        elif action == "open_trade_journal":
            if commit:
                st.session_state.nav_choice = "Trade Journal"
            action_notes.append("I opened Trade Journal.")
        elif action == "open_settings":
            if commit:
                st.session_state.nav_choice = "Account"
            action_notes.append("I opened Settings.")
    return _dedupe_preserve(action_notes)


def _answer_question(question: str, context: dict, messages: list[dict] | None = None, planned_intents: list[str] | None = None) -> str:
    raw = _clean_text(question)
    lower = raw.lower()
    expanded_lower = _expanded_question(raw, messages).lower()

    if not raw:
        return _welcome_text(context)

    if lower in {"hello", "hi", "hey", "helloo", "yo", "sup"}:
        return "Hey. I am here to help."

    planned_intents = planned_intents or _detect_agent_intents(expanded_lower)
    asks_broker = "broker" in planned_intents
    asks_market = "market" in planned_intents
    asks_risk = "risk" in planned_intents
    asks_trade_plan = "trade_plan" in planned_intents
    asks_route = "route" in planned_intents
    asks_next = "next" in planned_intents
    asks_overview = "overview" in planned_intents

    if asks_overview and not any([asks_market, asks_route, asks_risk, asks_broker, asks_next]):
        return _overview_text(context)

    responses: list[str] = []
    if asks_route:
        responses.append(_execution_text(context))
    if asks_market:
        responses.append(_market_review_text(context) if any(token in expanded_lower for token in ["review", "today"]) else _market_text(context))
    if asks_trade_plan:
        responses.append(_trade_plan_text(context))
    if asks_risk:
        responses.append(_risk_text(context))
    if asks_broker:
        responses.append(_broker_text(context))
    if asks_next:
        responses.append(_next_step_text(context))

    deduped: list[str] = []
    for item in responses:
        cleaned = _clean_text(item)
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)

    if deduped:
        return "\n\n".join(deduped)

    return (
        "I can help with the live market read, route status, risk gates, broker state, "
        "and what to do next. Try asking why the route is blocked or what the market is doing right now."
    )


def _build_agent_reply(plan: dict, context: dict, messages: list[dict], action_notes: list[str]) -> str:
    raw = _clean_text(plan.get("question"))
    if not raw:
        return _welcome_text(context)

    if plan.get("is_greeting"):
        if action_notes:
            return "\n\n".join(action_notes)
        return "Hey. I am here to help."

    reply_parts: list[str] = []
    if action_notes:
        reply_parts.extend(action_notes)

    if plan.get("wants_explanation") or not action_notes:
        core_reply = _answer_question(
            raw,
            context,
            messages,
            planned_intents=list(plan.get("intents") or []),
        )
        if core_reply:
            reply_parts.append(core_reply)

    if not reply_parts:
        reply_parts.append(_overview_text(context))

    return "\n\n".join(_dedupe_preserve(reply_parts))


def run_copilot_agent_turn(
    question: str,
    context: dict,
    messages: list[dict],
    *,
    scope: str = "copilot",
    memory: dict | None = None,
    execute_actions: bool = True,
    allow_model: bool = True,
) -> dict:
    plan = _plan_agent_turn(question, context, messages)
    action_notes = _execute_agent_actions(plan, context, scope, commit=execute_actions)
    runtime = _copilot_runtime_status()
    can_use_model = bool(
        allow_model
        and runtime.get("ready")
        and (plan.get("wants_explanation") or not action_notes)
    )
    model_reply = ""
    mode_used = "Finwise agent"
    if can_use_model:
        reply, error, mode_label = _call_model_copilot(
            plan.get("expanded_question") or question,
            context,
            messages,
            memory,
            plan,
        )
        if reply:
            model_reply = _clean_text(reply)
            mode_used = mode_label or "live AI model"
        elif error:
            mode_used = "Finwise agent"

    if model_reply:
        reply_parts = _dedupe_preserve(action_notes + [model_reply])
        final_reply = "\n\n".join(reply_parts)
    else:
        final_reply = _build_agent_reply(plan, context, messages, action_notes)

    updated_memory = _update_copilot_memory(memory, question=question, context=context, plan=plan, scope=scope)
    return {
        "reply": final_reply,
        "mode_used": mode_used,
        "plan": plan,
        "action_notes": action_notes,
        "memory": updated_memory,
    }


def _generate_copilot_reply(question: str, context: dict, messages: list[dict], *, scope: str = "copilot", memory: dict | None = None) -> tuple[str, str, dict]:
    result = run_copilot_agent_turn(question, context, messages, scope=scope, memory=memory)
    return str(result.get("reply") or ""), str(result.get("mode_used") or "Finwise agent"), result


def _render_message(role: str, content: str) -> None:
    row_class = "copilot-chat__row--user" if role == "user" else "copilot-chat__row--assistant"
    role_class = "copilot-chat__message--user" if role == "user" else "copilot-chat__message--assistant"
    label = "You" if role == "user" else "Finwise Copilot"
    st.markdown(
        dedent(
            f"""
            <div class="copilot-chat__row {row_class}">
                <div class="copilot-chat__message {role_class}">
                    <div class="copilot-chat__label">{escape(label)}</div>
                    <div class="copilot-chat__copy">{escape(content)}</div>
                </div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )


def render_finwise_broker_assistant(
    *,
    username: str,
    context: dict,
    scope: str = "copilot",
) -> None:
    state_key = f"finwise_copilot_messages_{username}"
    fingerprint_key = f"finwise_copilot_fingerprint_{username}"
    status_key = f"finwise_copilot_status_{username}"
    memory_key = f"finwise_copilot_memory_{username}"
    context_fingerprint = _context_fingerprint(context)

    if memory_key not in st.session_state:
        st.session_state[memory_key] = _normalize_copilot_memory(load_copilot_memory(username))

    st.markdown(
        """
        <style>
        .copilot-shell {
            background: linear-gradient(180deg, #0b1826 0%, #08131f 100%);
            border: 1px solid #173646;
            border-radius: 20px;
            padding: 16px 16px 14px;
            box-shadow: 0 22px 42px rgba(0,0,0,0.34);
            margin-top: 12px;
        }
        .copilot-top {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 10px;
        }
        .copilot-title {
            color: white;
            font-size: 20px;
            font-weight: 800;
        }
        .copilot-copy {
            color: #8ab4c8;
            font-size: 12px;
            line-height: 1.6;
            margin-top: 4px;
        }
        .copilot-badge {
            padding: 7px 10px;
            border-radius: 999px;
            background: #0e2731;
            border: 1px solid #1b4959;
            color: #74fbe6;
            font-size: 11px;
            font-weight: 800;
            white-space: nowrap;
        }
        .copilot-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
            margin: 12px 0;
        }
        .copilot-card {
            background: #0d1c2b;
            border: 1px solid #183244;
            border-radius: 15px;
            padding: 12px;
        }
        .copilot-card__label {
            color: #5f88a1;
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .copilot-card__value {
            color: white;
            font-size: 15px;
            font-weight: 800;
            margin-top: 6px;
        }
        .copilot-card__copy {
            color: #8ab4c8;
            font-size: 11px;
            line-height: 1.5;
            margin-top: 6px;
        }
        .copilot-quick {
            margin: 8px 0 4px;
        }
        .copilot-chat__row {
            display: flex;
            width: 100%;
            margin-top: 8px;
        }
        .copilot-chat__row--assistant {
            justify-content: flex-start;
        }
        .copilot-chat__row--user {
            justify-content: flex-end;
        }
        .copilot-chat__message {
            border-radius: 14px;
            padding: 10px 12px;
            max-width: 100%;
        }
        .copilot-chat__message--assistant {
            background: transparent;
            border: none;
            padding: 0;
        }
        .copilot-chat__message--user {
            background: #11253a;
            border: 1px solid #183244;
            display: inline-block;
            width: auto;
            min-width: 5.25rem;
            max-width: min(82%, 24rem);
        }
        .copilot-chat__label {
            color: #7cded2;
            font-size: 10px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 6px;
        }
        .copilot-chat__message--user .copilot-chat__label {
            color: #9cc0ff;
        }
        .copilot-chat__message--assistant .copilot-chat__label {
            margin-bottom: 4px;
        }
        .copilot-chat__copy {
            color: #e7f2fb;
            font-size: 12px;
            line-height: 1.6;
            white-space: pre-wrap;
        }
        @media (max-width: 640px) {
            .copilot-grid {
                grid-template-columns: 1fr;
            }
            .copilot-title {
                font-size: 18px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if st.session_state.get(fingerprint_key) != context_fingerprint:
        st.session_state[fingerprint_key] = context_fingerprint
        messages = list(st.session_state.get(state_key, []))
        if not messages:
            messages = [{"role": "assistant", "content": _welcome_text(context)}]
        st.session_state[state_key] = messages[-12:]

    broker_name = _clean_text(context.get("broker_name") or "Broker")
    signal = context.get("signal") or {}
    signal_meta = context.get("signal_meta") or {}
    preview = context.get("preview") or {}
    connector = context.get("connector") or {}

    current_signal = _signal_label(signal.get("signal", "HOLD")) if signal else "WAITING"
    signal_summary = (
        f"{_clean_text(signal_meta.get('symbol') or 'No symbol')} · {_clean_text(signal_meta.get('tf_label') or '--')}"
        if signal_meta
        else "Run a signal to populate live context"
    )
    route_summary = "Ready" if preview.get("status") == "ready" else "Blocked" if preview.get("status") == "blocked" else "Waiting"
    market_summary = _clean_text(signal.get("reason") or "No market explanation yet.")
    connector_summary = _clean_text(connector.get("summary") or "Connector test not run yet.")

    st.markdown(
        dedent(
            f"""
            <div class="copilot-shell">
                <div class="copilot-top">
                    <div>
                        <div class="copilot-title">Finwise Copilot</div>
                        <div class="copilot-copy">
                            Ask about the market, route status, or risk controls.
                        </div>
                    </div>
                    <div class="copilot-badge">{escape(broker_name)}</div>
                </div>
                <div class="copilot-grid">
                    <div class="copilot-card">
                        <div class="copilot-card__label">Current Signal</div>
                        <div class="copilot-card__value">{escape(current_signal)}</div>
                        <div class="copilot-card__copy">{escape(signal_summary)}</div>
                    </div>
                    <div class="copilot-card">
                        <div class="copilot-card__label">Route Status</div>
                        <div class="copilot-card__value">{escape(route_summary)}</div>
                        <div class="copilot-card__copy">{escape(_execution_gate_text(context))}</div>
                    </div>
                    <div class="copilot-card">
                        <div class="copilot-card__label">Market Read</div>
                        <div class="copilot-card__value">What Finwise Sees</div>
                        <div class="copilot-card__copy">{escape(market_summary)}</div>
                    </div>
                    <div class="copilot-card">
                        <div class="copilot-card__label">Broker Health</div>
                        <div class="copilot-card__value">{escape(_fmt_money(context.get("balance")))}</div>
                        <div class="copilot-card__copy">{escape(connector_summary)}</div>
                    </div>
                </div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )

    action_col_a, action_col_b = st.columns([0.8, 0.2])
    with action_col_a:
        st.markdown("**Quick prompts**")
    with action_col_b:
        if st.button("Reset Chat", key=f"copilot_reset_{username}", use_container_width=True):
            st.session_state[state_key] = [{"role": "assistant", "content": _welcome_text(context)}]
            st.session_state[status_key] = ""
            st.rerun()

    quick_cols = st.columns(3)
    quick_prompts = [
        ("Explain market", "What is happening in the market right now?"),
        ("Explain route", "Why is auto trade trading this way?"),
        ("Trade map", "Show me the trade plan for this setup."),
        ("Run signal", "Run a fresh signal for this market."),
        ("Open order book", "Open the order book."),
        ("Open broker", "Open Broker & Execution."),
        ("Explain risk", "What risk controls are active right now?"),
        ("What next?", "What should I do next?"),
    ]
    for idx, (label, prompt) in enumerate(quick_prompts):
        with quick_cols[idx % len(quick_cols)]:
            if st.button(label, key=f"copilot_quick_{username}_{idx}", use_container_width=True):
                prior_messages = list(st.session_state.get(state_key, []))
                current_memory = _normalize_copilot_memory(st.session_state.get(memory_key))
                _append_message(state_key, "user", prompt)
                with st.spinner("Finwise Copilot is thinking..."):
                    reply, mode_used, turn_result = _generate_copilot_reply(prompt, context, prior_messages, scope=scope, memory=current_memory)
                next_memory = _normalize_copilot_memory(turn_result.get("memory"))
                st.session_state[memory_key] = next_memory
                save_copilot_memory(username=username, memory=next_memory)
                _append_message(state_key, "assistant", reply)
                log_copilot_turn(
                    username=username,
                    scope=scope,
                    mode_used=mode_used,
                    user_message=prompt,
                    assistant_message=reply,
                    context=context,
                )
                st.session_state[status_key] = f"Reply mode: {mode_used}"
                st.rerun()

    messages = list(st.session_state.get(state_key, []))
    if messages:
        st.markdown("**Conversation**")
        for message in messages[-8:]:
            _render_message(message.get("role", "assistant"), message.get("content", ""))

    with st.form(f"finwise_copilot_form_{username}", clear_on_submit=True):
        prompt = st.text_area(
            "Ask Finwise Copilot",
            placeholder="Ask why the route is blocked, what the market is doing, or why the size changed.",
            label_visibility="collapsed",
            height=96,
        )
        submit = st.form_submit_button("Send", use_container_width=True)

    if submit and _clean_text(prompt):
        prior_messages = list(st.session_state.get(state_key, []))
        current_memory = _normalize_copilot_memory(st.session_state.get(memory_key))
        _append_message(state_key, "user", prompt)
        with st.spinner("Finwise Copilot is thinking..."):
            reply, mode_used, turn_result = _generate_copilot_reply(prompt, context, prior_messages, scope=scope, memory=current_memory)
        next_memory = _normalize_copilot_memory(turn_result.get("memory"))
        st.session_state[memory_key] = next_memory
        save_copilot_memory(username=username, memory=next_memory)
        _append_message(state_key, "assistant", reply)
        log_copilot_turn(
            username=username,
            scope=scope,
            mode_used=mode_used,
            user_message=prompt,
            assistant_message=reply,
            context=context,
        )
        st.session_state[status_key] = f"Reply mode: {mode_used}"
        st.rerun()


def render_copilot_drawer(
    *,
    username: str,
    context: dict,
    scope: str,
    state_key: str,
) -> None:
    scope_slug = "".join(ch if ch.isalnum() else "_" for ch in scope.lower()) or "copilot"
    drawer_key = f"copilot_drawer_{scope_slug}"
    toggle_id = f"finwise_copilot_toggle_{scope_slug}"
    icon_uri = _copilot_launcher_icon_data_uri()
    launcher_top = "5.15rem"
    drawer_top = "4.7rem"
    drawer_width = "min(30rem, 38vw)"
    drawer_right = "0.9rem"
    drawer_height = "calc(100dvh - 5.6rem)"
    launcher_icon_layer = f'url("{icon_uri}")'
    launcher_background_css = (
        f"background-image: radial-gradient(circle at 50% 50%, rgba(22, 255, 230, 0.13) 0%, rgba(22, 255, 230, 0.05) 54%, rgba(22, 255, 230, 0) 100%), {launcher_icon_layer};"
        "background-repeat: no-repeat, no-repeat;"
        "background-position: center center, center center;"
        "background-size: 2.12rem 2.12rem, 1.48rem 1.48rem;"
    )

    st.markdown(
        dedent(
            f"""
            <style>
            #{toggle_id} {{
                position: fixed;
                opacity: 0;
                pointer-events: none;
                width: 0;
                height: 0;
            }}
            label[for="{toggle_id}"] {{
                position: fixed;
                top: {launcher_top};
                right: {drawer_right};
                z-index: 10023;
                width: 2.55rem;
                max-width: 2.55rem;
                min-width: 2.55rem;
                min-height: 2.55rem;
                height: 2.55rem;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                border-radius: 0.92rem;
                border: 1px solid rgba(41, 240, 218, 0.18);
                background: #091826 !important;
                {launcher_background_css}
                box-shadow: 0 14px 34px rgba(0,0,0,0.28), 0 0 0 1px rgba(32,225,205,0.1), 0 0 18px rgba(29,231,209,0.2);
                color: transparent !important;
                font-size: 0 !important;
                line-height: 0 !important;
                overflow: hidden !important;
                transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
            }}
            label[for="{toggle_id}"]:hover {{
                border-color: rgba(89, 249, 232, 0.42);
                transform: translateY(-1px);
            }}
            label[for="{toggle_id}"]::after {{
                content: "";
                position: absolute;
                top: 0.72rem;
                right: 0.7rem;
                width: 0.22rem;
                height: 0.22rem;
                border-radius: 999px;
                background: rgba(236,255,255,0.92);
                box-shadow: 0 0 10px rgba(168,255,244,0.9);
            }}
            body:has(#{toggle_id}:checked) label[for="{toggle_id}"] {{
                border-color: rgba(41, 240, 218, 0.36);
                box-shadow: 0 18px 38px rgba(0,0,0,0.34), 0 0 0 1px rgba(32,225,205,0.14), 0 0 28px rgba(29,231,209,0.3);
            }}
            .st-key-{drawer_key} {{
                position: fixed;
                top: {drawer_top};
                right: {drawer_right};
                width: {drawer_width};
                max-width: calc(100vw - 1rem);
                max-height: {drawer_height};
                overflow-y: auto;
                overflow-x: hidden;
                z-index: 10021;
                padding: 0.82rem !important;
                margin: 0 !important;
                box-sizing: border-box;
                background: linear-gradient(180deg, #07111b 0%, #09131f 100%);
                border: 1px solid #173646;
                border-radius: 1.22rem;
                box-shadow: 0 26px 56px rgba(0,0,0,0.42);
                opacity: 0;
                pointer-events: none;
                transform: translateY(-0.35rem) scale(0.985);
                transition: opacity 160ms ease, transform 160ms ease;
            }}
            body:has(#{toggle_id}:checked) .st-key-{drawer_key} {{
                opacity: 1;
                pointer-events: auto;
                transform: translateY(0) scale(1);
            }}
            .st-key-{drawer_key} > div {{
                background: transparent !important;
            }}
            .st-key-{drawer_key} .copilot-shell {{
                margin-top: 0;
                box-shadow: none;
            }}
            </style>
            <input id="{toggle_id}" type="checkbox" aria-label="Toggle Finwise Copilot" />
            <label for="{toggle_id}" title="Toggle Finwise Copilot">Finwise Copilot</label>
            """
        ),
        unsafe_allow_html=True,
    )

    with st.container(key=drawer_key):
        render_finwise_broker_assistant(
            username=username,
            context=context,
            scope=scope,
        )
