import json
import os
import time
from typing import Any, Dict, Optional

from backend.core.db_runtime import connect_database
from backend.auth.security_config import broker_secret_persistence_enabled, resolve_redirect_uri


DB_PATH = "finwise.db"


def _connect():
    conn = connect_database(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def ensure_broker_oauth_tables() -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_oauth_state (
            state TEXT PRIMARY KEY,
            username TEXT,
            broker_name TEXT,
            redirect_uri TEXT,
            metadata TEXT,
            created_at REAL,
            expires_at REAL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            broker_name TEXT,
            auth_method TEXT,
            access_token TEXT,
            refresh_token TEXT,
            token_expires_at REAL,
            api_key TEXT,
            api_secret TEXT,
            metadata TEXT,
            active INTEGER DEFAULT 1,
            created_at REAL,
            updated_at REAL
        )
        """
    )
    conn.commit()
    conn.close()


def save_broker_oauth_state(
    username: str,
    broker_name: str,
    state: str,
    redirect_uri: str,
    metadata: Optional[Dict[str, Any]] = None,
    ttl_seconds: int = 900,
) -> None:
    ensure_broker_oauth_tables()
    now = time.time()
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM broker_oauth_state WHERE expires_at < ?", (now,))
    cur.execute(
        """
        INSERT INTO broker_oauth_state (
            state, username, broker_name, redirect_uri, metadata, created_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(state) DO UPDATE SET
            username=excluded.username,
            broker_name=excluded.broker_name,
            redirect_uri=excluded.redirect_uri,
            metadata=excluded.metadata,
            created_at=excluded.created_at,
            expires_at=excluded.expires_at
        """,
        (
            state,
            username,
            broker_name,
            redirect_uri,
            json.dumps(metadata or {}),
            now,
            now + ttl_seconds,
        ),
    )
    conn.commit()
    conn.close()


def consume_broker_oauth_state(state: str) -> Optional[Dict[str, Any]]:
    ensure_broker_oauth_tables()
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT state, username, broker_name, redirect_uri, metadata, created_at, expires_at
        FROM broker_oauth_state
        WHERE state = ?
        """,
        (state,),
    )
    row = cur.fetchone()
    cur.execute("DELETE FROM broker_oauth_state WHERE state = ?", (state,))
    conn.commit()
    conn.close()
    if not row:
        return None
    now = time.time()
    if float(row[6] or 0) < now:
        return None
    return {
        "state": row[0],
        "username": row[1],
        "broker_name": row[2],
        "redirect_uri": row[3],
        "metadata": json.loads(row[4] or "{}"),
        "created_at": row[5],
        "expires_at": row[6],
    }


def save_broker_connection(
    username: str,
    broker_name: str,
    auth_method: str,
    access_token: str = "",
    refresh_token: str = "",
    token_expires_at: Optional[float] = None,
    api_key: str = "",
    api_secret: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    ensure_broker_oauth_tables()
    now = time.time()
    persist_sensitive_fields = broker_secret_persistence_enabled()
    metadata_payload = dict(metadata or {})
    if not persist_sensitive_fields:
        if access_token or refresh_token or api_key or api_secret:
            metadata_payload["credentials_persisted"] = False
            metadata_payload["reconnect_required"] = True
        access_token = ""
        refresh_token = ""
        api_key = ""
        api_secret = ""
        token_expires_at = None
    else:
        metadata_payload.setdefault("credentials_persisted", True)
        metadata_payload.setdefault("reconnect_required", False)
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE broker_connections SET active = 0, updated_at = ? WHERE username = ? AND broker_name = ?",
        (now, username, broker_name),
    )
    cur.execute(
        """
        INSERT INTO broker_connections (
            username, broker_name, auth_method, access_token, refresh_token,
            token_expires_at, api_key, api_secret, metadata, active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            username,
            broker_name,
            auth_method,
            access_token or "",
            refresh_token or "",
            token_expires_at,
            api_key or "",
            api_secret or "",
            json.dumps(metadata_payload),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()


def get_active_broker_connection(username: str, broker_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    ensure_broker_oauth_tables()
    conn = _connect()
    cur = conn.cursor()
    if broker_name:
        cur.execute(
            """
            SELECT username, broker_name, auth_method, access_token, refresh_token,
                   token_expires_at, api_key, api_secret, metadata, created_at, updated_at
            FROM broker_connections
            WHERE username = ? AND broker_name = ? AND active = 1
            ORDER BY updated_at DESC LIMIT 1
            """,
            (username, broker_name),
        )
    else:
        cur.execute(
            """
            SELECT username, broker_name, auth_method, access_token, refresh_token,
                   token_expires_at, api_key, api_secret, metadata, created_at, updated_at
            FROM broker_connections
            WHERE username = ? AND active = 1
            ORDER BY updated_at DESC LIMIT 1
            """,
            (username,),
        )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "username": row[0],
        "broker_name": row[1],
        "auth_method": row[2],
        "access_token": row[3],
        "refresh_token": row[4],
        "token_expires_at": row[5],
        "api_key": row[6],
        "api_secret": row[7],
        "metadata": json.loads(row[8] or "{}"),
        "created_at": row[9],
        "updated_at": row[10],
    }


def deactivate_broker_connection(username: str, broker_name: Optional[str] = None) -> None:
    ensure_broker_oauth_tables()
    conn = _connect()
    cur = conn.cursor()
    if broker_name:
        cur.execute(
            "UPDATE broker_connections SET active = 0, updated_at = ? WHERE username = ? AND broker_name = ?",
            (time.time(), username, broker_name),
        )
    else:
        cur.execute(
            "UPDATE broker_connections SET active = 0, updated_at = ? WHERE username = ?",
            (time.time(), username),
        )
    conn.commit()
    conn.close()


def resolve_broker_oauth_redirect_uri(default_port: int = 8501, broker_name: str = "") -> str:
    broker_key = str(broker_name or "").strip().upper()
    broker_specific_key = f"{broker_key}_OAUTH_REDIRECT_URI" if broker_key else ""
    explicit = (
        (os.getenv(broker_specific_key) if broker_specific_key else "")
        or os.getenv("BROKER_OAUTH_REDIRECT_URI")
        or os.getenv("BYBIT_OAUTH_REDIRECT_URI")
        or ""
    ).strip()
    return resolve_redirect_uri(explicit, default_port=default_port, service_name="Broker OAuth")
