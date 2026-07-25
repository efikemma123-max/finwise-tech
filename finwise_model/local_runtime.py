from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from finwise_model.runtime_engine import engine_status, select_engine
from finwise_model.runtime_registry import (
    DEFAULT_MODEL_NAME,
    copy_model,
    delete_model as delete_registered_model,
    list_models,
    load_model,
    parse_modelfile,
    save_model,
)


app = FastAPI(
    title="Finwise Local Runtime",
    description="A small Ollama-compatible runtime owned by Finwise.",
    version="0.1.0",
)


class ChatMessage(BaseModel):
    role: str = "user"
    content: Any = ""


class ChatRequest(BaseModel):
    model: str = DEFAULT_MODEL_NAME
    messages: list[ChatMessage] = Field(default_factory=list)
    stream: bool = False
    options: dict[str, Any] = Field(default_factory=dict)


class GenerateRequest(BaseModel):
    model: str = DEFAULT_MODEL_NAME
    prompt: str = ""
    stream: bool = False
    options: dict[str, Any] = Field(default_factory=dict)


class CreateRequest(BaseModel):
    model: str = DEFAULT_MODEL_NAME
    name: str = ""
    modelfile: str = ""
    stream: bool = False


class CopyRequest(BaseModel):
    source: str
    destination: str


class DeleteRequest(BaseModel):
    name: str = ""
    model: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any) -> str:
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt_money(value: Any) -> str:
    return f"${_safe_float(value):,.2f}"


def _fmt_price(value: Any) -> str:
    return f"${_safe_float(value):,.4f}"


def _extract_context(messages: list[ChatMessage]) -> dict[str, Any]:
    marker = "Live Finwise context JSON:"
    for message in messages:
        content = _clean_text(message.content)
        if marker not in content:
            continue
        raw_json = content.split(marker, 1)[1].strip()
        try:
            parsed = json.loads(raw_json)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _last_user_message(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role.lower() == "user":
            content = _clean_text(message.content)
            if content:
                return content
    return ""


def _market_reply(context: dict[str, Any]) -> str:
    market = context.get("market") or {}
    symbol = _clean_text(market.get("symbol") or "the active market")
    timeframe = _clean_text(market.get("timeframe") or "current timeframe")
    signal = _clean_text(market.get("signal") or "HOLD").upper()
    confidence = _safe_float(market.get("confidence"))
    reason = _clean_text(market.get("reason") or "Finwise does not have a fresh market reason yet.")
    return f"{symbol} on {timeframe} is reading {signal} with about {confidence:.0f}% confidence. {reason}"


def _route_reply(context: dict[str, Any]) -> str:
    route = context.get("route") or {}
    status = _clean_text(route.get("status") or "waiting")
    reason = _clean_text(route.get("reason") or "The route has not cleared all checks yet.")
    guard = route.get("profit_guard") or {}
    failed = guard.get("failed_checks") or []
    if status == "ready":
        return "The route is ready. Confidence, reward, and projected edge are aligned for this setup."
    if status == "blocked" and failed:
        return "The route is blocked because " + "; ".join(str(item) for item in failed) + "."
    return f"The route is {status}. {reason}"


def _risk_reply(context: dict[str, Any]) -> str:
    market = context.get("market") or {}
    entry = market.get("entry_exit") or {}
    size = market.get("position_size") or {}
    return (
        f"Risk map: entry around {_fmt_price(entry.get('entry_price'))}, "
        f"stop near {_fmt_price(entry.get('stop_loss'))}, target near {_fmt_price(entry.get('take_profit'))}, "
        f"risk/reward about {_safe_float(entry.get('risk_reward_ratio')):.2f}R, "
        f"and planned size about {_fmt_money(size.get('position_size_usd'))}."
    )


def _broker_reply(context: dict[str, Any]) -> str:
    broker = context.get("broker") or {}
    name = _clean_text(broker.get("name") or "your broker")
    connection = _clean_text(broker.get("connection_method") or "unknown").replace("_", " ").title()
    balance = _fmt_money(broker.get("balance"))
    trades = int(_safe_float(broker.get("total_trades")))
    if connection.lower() == "not connected":
        return f"{name} is Not Connected. Finwise is using {balance} as the local balance basis, with {trades} routed trades recorded."
    return f"{name} is connected through {connection}. Finwise is using {balance} as the balance basis, with {trades} routed trades recorded."


def _next_reply(context: dict[str, Any]) -> str:
    market = context.get("market") or {}
    route = context.get("route") or {}
    signal = _clean_text(market.get("signal") or "HOLD").upper()
    status = _clean_text(route.get("status") or "waiting")
    if signal == "HOLD":
        return "Next step: wait. Finwise is in HOLD, so rerun the signal after more candles print."
    if status == "ready":
        return "Next step: review the trade map and execute only if it still matches your plan and risk limit."
    if status == "blocked":
        return "Next step: do not force it. Wait for a cleaner setup or rerun the route test after the next candle."
    return "Next step: run a fresh signal or route test so Finwise can confirm the current setup."


def _scratch_reply(question: str, context: dict[str, Any]) -> str:
    lower = question.lower()
    parts: list[str] = []
    if any(token in lower for token in ["broker", "balance", "connected", "account"]):
        parts.append(_broker_reply(context))
    if any(token in lower for token in ["market", "trend", "price", "happening", "review", "signal"]):
        parts.append(_market_reply(context))
    if any(token in lower for token in ["route", "blocked", "execution", "execute", "gate"]):
        parts.append(_route_reply(context))
    if any(token in lower for token in ["risk", "entry", "stop", "target", "take profit", "size", "trade plan", "trade map"]):
        parts.append(_risk_reply(context))
    if any(token in lower for token in ["next", "should i", "what now", "do now"]):
        parts.append(_next_reply(context))
    if not parts:
        parts = [_market_reply(context), _route_reply(context), _next_reply(context)]
    return "\n\n".join(dict.fromkeys(part for part in parts if part))


def _json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _chunk_text(text: str, *, chunk_size: int = 28) -> list[str]:
    if not text:
        return [""]
    chunks: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = f"{current} {word}".strip()
        if len(candidate) > chunk_size and current:
            chunks.append(current + " ")
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _stream_chat(model_name: str, content: str):
    for chunk in _chunk_text(content):
        yield _json_line(
            {
                "model": model_name,
                "created_at": _now_iso(),
                "message": {"role": "assistant", "content": chunk},
                "done": False,
            }
        )
    yield _json_line({"model": model_name, "created_at": _now_iso(), "message": {"role": "assistant", "content": ""}, "done": True})


def _stream_generate(model_name: str, content: str):
    for chunk in _chunk_text(content):
        yield _json_line({"model": model_name, "created_at": _now_iso(), "response": chunk, "done": False})
    yield _json_line({"model": model_name, "created_at": _now_iso(), "response": "", "done": True})


@app.get("/api/tags")
def tags() -> dict[str, Any]:
    return {"models": [model.to_ollama_tag() for model in list_models()]}


@app.post("/api/show")
def show(request: dict[str, Any]) -> dict[str, Any]:
    model_name = _clean_text(request.get("name") or request.get("model") or DEFAULT_MODEL_NAME)
    model = load_model(model_name)
    return {
        "license": "Finwise-owned local model descriptor.",
        "modelfile": model.template,
        "parameters": model.parameter_size,
        "template": model.template,
        "system": model.system_prompt,
        "details": model.to_ollama_tag().get("details", {}),
        "model_info": {
            "name": model.name,
            "weight_path": model.weight_path,
            "digest": model.digest,
        },
        "engine": engine_status(model),
    }


@app.post("/api/chat")
def chat(request: ChatRequest):
    model = load_model(request.model or DEFAULT_MODEL_NAME)
    context = _extract_context(request.messages)
    question = _last_user_message(request.messages)
    content = select_engine(model).generate(question, model=model, context=context, options=request.options)
    if request.stream:
        return StreamingResponse(_stream_chat(model.name, content), media_type="application/x-ndjson")
    return {
        "model": model.name,
        "created_at": _now_iso(),
        "message": {"role": "assistant", "content": content},
        "done": True,
    }


@app.post("/api/generate")
def generate(request: GenerateRequest):
    model = load_model(request.model or DEFAULT_MODEL_NAME)
    content = select_engine(model).generate(request.prompt, model=model, context={}, options=request.options)
    if request.stream:
        return StreamingResponse(_stream_generate(model.name, content), media_type="application/x-ndjson")
    return {
        "model": model.name,
        "created_at": _now_iso(),
        "response": content,
        "done": True,
    }


@app.post("/api/create")
def create_model(request: CreateRequest):
    model_name = _clean_text(request.name or request.model or DEFAULT_MODEL_NAME)
    modelfile = _clean_text(request.modelfile)
    if not modelfile:
        raise HTTPException(status_code=400, detail="modelfile is required")
    model = parse_modelfile(modelfile, default_name=model_name)
    if model.name != model_name:
        model = model.__class__(**{**model.__dict__, "name": model_name})
    save_model(model)
    status = {"status": f"created {model.name}", "digest": model.digest}
    if request.stream:
        return StreamingResponse(iter([_json_line(status), _json_line({"status": "success"})]), media_type="application/x-ndjson")
    return status


@app.post("/api/copy")
def copy_registered(request: CopyRequest) -> dict[str, Any]:
    source = _clean_text(request.source)
    destination = _clean_text(request.destination)
    if not source or not destination:
        raise HTTPException(status_code=400, detail="source and destination are required")
    copied = copy_model(source, destination)
    return {"status": "success", "source": source, "destination": copied.name}


@app.delete("/api/delete")
def delete_model(request: DeleteRequest) -> dict[str, Any]:
    model_name = _clean_text(request.name or request.model)
    if not model_name:
        raise HTTPException(status_code=400, detail="name is required")
    if not delete_registered_model(model_name):
        raise HTTPException(status_code=404, detail=f"model not found: {model_name}")
    return {"status": "success"}


@app.get("/api/ps")
def running_models() -> dict[str, Any]:
    return {
        "models": [
            {
                **model.to_ollama_tag(),
                "expires_at": _now_iso(),
                "size_vram": 0,
            }
            for model in list_models()
        ]
    }


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "Finwise Local Runtime",
        "model": DEFAULT_MODEL_NAME,
        "ollama_compatible": "/api/tags, /api/show, /api/chat, /api/generate, /api/create, /api/copy, /api/delete, and /api/ps",
    }
