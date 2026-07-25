from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from db_runtime import connect_database


DB_PATH = "finwise.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_text(payload: Any) -> str:
    try:
        return json.dumps(payload or {}, ensure_ascii=True, sort_keys=True)
    except TypeError:
        return json.dumps({"raw": str(payload)}, ensure_ascii=True, sort_keys=True)


def ensure_model_data_tables() -> None:
    conn = connect_database(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS copilot_chat_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                scope TEXT,
                mode_used TEXT,
                symbol TEXT,
                timeframe TEXT,
                broker_name TEXT,
                user_message TEXT,
                assistant_message TEXT,
                context_json TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                broker_name TEXT,
                event_type TEXT,
                event_status TEXT,
                symbol TEXT,
                timeframe TEXT,
                payload_json TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS copilot_user_memory (
                username TEXT PRIMARY KEY,
                memory_json TEXT,
                updated_at TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def log_copilot_turn(
    *,
    username: str,
    scope: str,
    mode_used: str,
    user_message: str,
    assistant_message: str,
    context: dict,
) -> None:
    ensure_model_data_tables()
    signal_meta = (context or {}).get("signal_meta") or {}
    conn = connect_database(DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO copilot_chat_turns (
                username, scope, mode_used, symbol, timeframe, broker_name,
                user_message, assistant_message, context_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                str(scope or "copilot"),
                str(mode_used or "unknown"),
                str(signal_meta.get("symbol") or ""),
                str(signal_meta.get("tf_label") or ""),
                str((context or {}).get("broker_name") or ""),
                str(user_message or ""),
                str(assistant_message or ""),
                _json_text(context),
                _utc_now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def log_model_event(
    *,
    username: str,
    broker_name: str,
    event_type: str,
    payload: dict,
    event_status: str = "",
    symbol: str = "",
    timeframe: str = "",
) -> None:
    ensure_model_data_tables()
    conn = connect_database(DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO model_event_log (
                username, broker_name, event_type, event_status, symbol, timeframe, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(username or ""),
                str(broker_name or ""),
                str(event_type or ""),
                str(event_status or ""),
                str(symbol or ""),
                str(timeframe or ""),
                _json_text(payload),
                _utc_now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_copilot_memory(username: str) -> dict:
    ensure_model_data_tables()
    if not str(username or "").strip():
        return {}
    conn = connect_database(DB_PATH)
    try:
        row = conn.execute(
            "SELECT memory_json FROM copilot_user_memory WHERE username = ?",
            (str(username).strip(),),
        ).fetchone()
        if not row:
            return {}
        raw = row[0]
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}
    finally:
        conn.close()


def save_copilot_memory(*, username: str, memory: dict) -> None:
    ensure_model_data_tables()
    if not str(username or "").strip():
        return
    conn = connect_database(DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO copilot_user_memory (username, memory_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                memory_json = excluded.memory_json,
                updated_at = excluded.updated_at
            """,
            (
                str(username).strip(),
                _json_text(memory),
                _utc_now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
