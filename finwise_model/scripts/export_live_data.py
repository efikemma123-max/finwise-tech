from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finwise_model.live_data import ensure_model_data_tables  # noqa: E402


DB_PATH = ROOT / "finwise.db"
SYSTEM_PROMPT = (
    "You are Finwise Copilot, a trading assistant inside Finwise AI. "
    "Reason conversationally but stay grounded in the provided live trading context. "
    "Do not invent balances, broker states, or market conditions that are not present."
)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _safe_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _trade_context(row: sqlite3.Row) -> dict:
    return {
        "trade": {
            "id": row["id"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "side": row["side"],
            "status": row["status"],
            "confidence": row["confidence"],
            "entry_price": row["entry_price"],
            "exit_price": row["exit_price"],
            "stop_loss": row["stop_loss"],
            "take_profit": row["take_profit"],
            "pnl_usd": row["pnl_usd"],
            "pnl_pct": row["pnl_pct"],
            "risk_reward_ratio": row["risk_reward_ratio"],
            "regime": row["regime"],
            "setup_quality": row["setup_quality"],
            "notes": row["notes"],
            "opened_at": row["opened_at"],
            "closed_at": row["closed_at"],
            "source": row["source"],
            "broker_name": row["broker_name"],
        }
    }


def _trade_summary(row: sqlite3.Row) -> str:
    status = str(row["status"] or "").strip() or "unknown"
    symbol = str(row["symbol"] or "unknown market")
    timeframe = str(row["timeframe"] or "--")
    side = str(row["side"] or "UNKNOWN")
    pnl_usd = float(row["pnl_usd"] or 0.0)
    rr = float(row["risk_reward_ratio"] or 0.0)
    setup_quality = str(row["setup_quality"] or "unknown")
    return (
        f"{side} {symbol} on {timeframe} is recorded as {status}. "
        f"Setup quality was {setup_quality}, risk-reward was {rr:.2f}R, and current realized P&L is ${pnl_usd:,.2f}."
    )


def _trade_review(row: sqlite3.Row) -> str:
    status = str(row["status"] or "").strip().lower()
    pnl = float(row["pnl_usd"] or 0.0)
    if status in {"open", "executed"}:
        return "This trade is still open, so review should focus on whether the original regime and risk plan still hold."
    if pnl > 0:
        return "This closed trade reflects a profitable outcome. Review whether the entry discipline and exit logic can be repeated consistently."
    if pnl < 0:
        return "This closed trade lost money. Review whether confidence, timing, or route quality were weaker than they first appeared."
    return "This trade closed flat. Review whether the setup lacked enough edge to justify the execution."


def _event_summary(row: sqlite3.Row, payload: dict) -> str:
    event_type = str(row["event_type"] or "event").replace("_", " ")
    status = str(row["event_status"] or "unknown")
    broker = str(row["broker_name"] or "Finwise")
    symbol = str(row["symbol"] or payload.get("symbol") or "selected market")
    summary = str(payload.get("summary") or payload.get("reason") or payload.get("message") or "").strip()
    base = f"{broker} {event_type} for {symbol} finished with status {status}."
    return f"{base} {summary}".strip()


def _event_review(row: sqlite3.Row, payload: dict) -> str:
    event_type = str(row["event_type"] or "").strip().lower()
    status = str(row["event_status"] or "").strip().lower()
    if event_type == "connector_test":
        if status == "ready":
            return "The connector is healthy enough for broker-assisted workflows, so the next focus should be route quality rather than access problems."
        return "The connector still needs attention before trusting routed execution, because broker access checks are not fully clean yet."
    if event_type == "route_preview":
        if status == "ready":
            return "The route preview passed, which means confidence, projected edge, and risk-reward were aligned at preview time."
        return "The route preview failed one or more quality gates, so this setup should not be treated as execution-ready."
    if event_type == "trade_execution":
        if status == "success":
            return "Execution succeeded, so review should now shift toward trade management and post-trade outcome analysis."
        return "Execution did not complete successfully, so the blocking reason should be reviewed before retrying."
    return str(payload.get("summary") or payload.get("reason") or "Review the event outcome in the context of the trading workflow.").strip()


def _connection_summary(row: sqlite3.Row, metadata: dict) -> str:
    broker = str(row["broker_name"] or "Broker")
    auth_method = str(row["auth_method"] or "unknown")
    active = bool(row["active"])
    account_hint = str(metadata.get("account_alias") or metadata.get("account_name") or "").strip()
    state = "active" if active else "inactive"
    suffix = f" Account hint: {account_hint}." if account_hint else ""
    return f"{broker} connection is {state} using {auth_method}.{suffix}".strip()


def _copilot_turn_row(row: sqlite3.Row) -> dict:
    context = _safe_json(row["context_json"])
    return {
        "id": f"live-chat-{row['id']}",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": "Live Finwise context JSON:\n" + json.dumps(context, ensure_ascii=True, sort_keys=True)},
            {"role": "user", "content": str(row["user_message"] or "")},
            {"role": "assistant", "content": str(row["assistant_message"] or "")},
        ],
        "metadata": {
            "source": "live_copilot_turn",
            "scope": row["scope"],
            "mode_used": row["mode_used"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "broker_name": row["broker_name"],
            "created_at": row["created_at"],
        },
    }


def export_live_data(output_dir: Path) -> dict[str, int]:
    ensure_model_data_tables()
    output_dir.mkdir(parents=True, exist_ok=True)
    live_sft_path = output_dir / "finwise_live_sft.jsonl"
    live_corpus_path = output_dir / "finwise_live_domain_corpus.jsonl"
    live_manifest_path = output_dir / "live_export_manifest.json"

    conn = _connect()
    try:
        trades = conn.execute(
            """
            SELECT *
            FROM trade_history
            ORDER BY COALESCE(closed_at, opened_at, created_at) DESC, id DESC
            """
        ).fetchall()
        broker_connections = conn.execute(
            """
            SELECT *
            FROM broker_connections
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
        events = conn.execute(
            """
            SELECT *
            FROM model_event_log
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
        chat_turns = conn.execute(
            """
            SELECT *
            FROM copilot_chat_turns
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
    finally:
        conn.close()

    sft_rows: list[dict] = []
    corpus_rows: list[dict] = []

    for row in chat_turns:
        sft_rows.append(_copilot_turn_row(row))
        corpus_rows.append(
            {
                "id": f"chat-corpus-{row['id']}",
                "text": dedent(
                    f"""
                    Finwise Copilot live chat transcript
                    Scope: {row['scope']}
                    Mode: {row['mode_used']}
                    Symbol: {row['symbol']}
                    Timeframe: {row['timeframe']}
                    Broker: {row['broker_name']}

                    User:
                    {row['user_message']}

                    Assistant:
                    {row['assistant_message']}
                    """
                ).strip(),
                "metadata": {
                    "source": "live_copilot_turn",
                    "scope": row["scope"],
                    "created_at": row["created_at"],
                },
            }
        )

    for row in trades:
        context = _trade_context(row)
        symbol = str(row["symbol"] or "")
        timeframe = str(row["timeframe"] or "")
        base_meta = {
            "source": "trade_history",
            "trade_id": row["id"],
            "symbol": symbol,
            "timeframe": timeframe,
            "status": row["status"],
        }
        trade_qa = [
            ("Summarize this trade journal entry.", _trade_summary(row)),
            ("What should Finwise review about this trade?", _trade_review(row)),
        ]
        for idx, (question, answer) in enumerate(trade_qa):
            sft_rows.append(
                {
                    "id": f"trade-sft-{row['id']}-{idx}",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "system", "content": "Live Finwise context JSON:\n" + json.dumps(context, ensure_ascii=True, sort_keys=True)},
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": answer},
                    ],
                    "metadata": base_meta,
                }
            )
        corpus_rows.append(
            {
                "id": f"trade-corpus-{row['id']}",
                "text": dedent(
                    f"""
                    Finwise trade journal record
                    Symbol: {symbol}
                    Timeframe: {timeframe}
                    Side: {row['side']}
                    Status: {row['status']}
                    Broker: {row['broker_name']}

                    Summary:
                    {_trade_summary(row)}

                    Review:
                    {_trade_review(row)}
                    """
                ).strip(),
                "metadata": base_meta,
            }
        )

    for row in events:
        payload = _safe_json(row["payload_json"])
        context = {
            "event": payload,
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "broker_name": row["broker_name"],
            "event_type": row["event_type"],
            "event_status": row["event_status"],
        }
        event_meta = {
            "source": "model_event_log",
            "event_id": row["id"],
            "event_type": row["event_type"],
            "status": row["event_status"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
        }
        qa_pairs = [
            ("Summarize this broker event.", _event_summary(row, payload)),
            ("What does this event mean for the workflow?", _event_review(row, payload)),
        ]
        for idx, (question, answer) in enumerate(qa_pairs):
            sft_rows.append(
                {
                    "id": f"event-sft-{row['id']}-{idx}",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "system", "content": "Live Finwise context JSON:\n" + json.dumps(context, ensure_ascii=True, sort_keys=True)},
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": answer},
                    ],
                    "metadata": event_meta,
                }
            )
        corpus_rows.append(
            {
                "id": f"event-corpus-{row['id']}",
                "text": dedent(
                    f"""
                    Finwise broker/runtime event
                    Broker: {row['broker_name']}
                    Type: {row['event_type']}
                    Status: {row['event_status']}
                    Symbol: {row['symbol']}
                    Timeframe: {row['timeframe']}

                    Summary:
                    {_event_summary(row, payload)}

                    Meaning:
                    {_event_review(row, payload)}
                    """
                ).strip(),
                "metadata": event_meta,
            }
        )

    for row in broker_connections:
        metadata = _safe_json(row["metadata"])
        summary = _connection_summary(row, metadata)
        context = {
            "connection": {
                "broker_name": row["broker_name"],
                "auth_method": row["auth_method"],
                "active": row["active"],
                "metadata": metadata,
            }
        }
        connection_meta = {
            "source": "broker_connections",
            "connection_id": row["id"],
            "broker_name": row["broker_name"],
            "auth_method": row["auth_method"],
            "active": row["active"],
        }
        sft_rows.append(
            {
                "id": f"connection-sft-{row['id']}",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "system", "content": "Live Finwise context JSON:\n" + json.dumps(context, ensure_ascii=True, sort_keys=True)},
                    {"role": "user", "content": "Summarize this broker connection state."},
                    {"role": "assistant", "content": summary},
                ],
                "metadata": connection_meta,
            }
        )
        corpus_rows.append(
            {
                "id": f"connection-corpus-{row['id']}",
                "text": dedent(
                    f"""
                    Finwise broker connection snapshot
                    Broker: {row['broker_name']}
                    Auth Method: {row['auth_method']}
                    Active: {row['active']}

                    Summary:
                    {summary}
                    """
                ).strip(),
                "metadata": connection_meta,
            }
        )

    with live_sft_path.open("w", encoding="utf-8") as sft_file:
        for row in sft_rows:
            sft_file.write(json.dumps(row, ensure_ascii=True) + "\n")

    with live_corpus_path.open("w", encoding="utf-8") as corpus_file:
        for row in corpus_rows:
            corpus_file.write(json.dumps(row, ensure_ascii=True) + "\n")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "live_chat_turns": len(chat_turns),
        "trade_rows": len(trades),
        "event_rows": len(events),
        "broker_connection_rows": len(broker_connections),
        "sft_examples": len(sft_rows),
        "pretrain_documents": len(corpus_rows),
        "files": {
            "sft": str(live_sft_path.relative_to(ROOT)),
            "pretrain": str(live_corpus_path.relative_to(ROOT)),
        },
    }
    live_manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Export real Finwise data into model-training datasets.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "finwise_model" / "datasets",
        help="Directory for exported live-data datasets.",
    )
    args = parser.parse_args()
    manifest = export_live_data(args.output_dir)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

