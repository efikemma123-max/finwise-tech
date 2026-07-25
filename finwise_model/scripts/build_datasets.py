from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broker_ai_copilot import (  # noqa: E402
    _answer_question,
    _execution_text,
    _market_text,
    _next_step_text,
    _overview_text,
    _risk_text,
)
from finwise_model.sample_contexts import QUESTION_BANK, iter_synthetic_contexts  # noqa: E402


SYSTEM_PROMPT = (
    "You are Finwise Copilot, a trading assistant inside Finwise AI. "
    "Reason conversationally but stay grounded in the provided live trading context. "
    "Do not invent balances, broker states, or market conditions that are not present."
)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _pretrain_document(context: dict) -> str:
    signal_meta = context.get("signal_meta") or {}
    broker = context.get("broker_name") or "Finwise"
    symbol = signal_meta.get("symbol") or "UNKNOWN"
    timeframe = signal_meta.get("tf_label") or "--"
    overview = _overview_text(context)
    market = _market_text(context)
    execution = _execution_text(context)
    risk = _risk_text(context)
    next_step = _next_step_text(context)
    return dedent(
        f"""
        Finwise Copilot domain note
        Broker: {broker}
        Market: {symbol}
        Timeframe: {timeframe}

        Overview:
        {overview}

        Market Read:
        {market}

        Execution Logic:
        {execution}

        Risk Controls:
        {risk}

        Next Step:
        {next_step}
        """
    ).strip()


def _sft_messages(context: dict, question: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": "Live Finwise context JSON:\n" + json.dumps(context, ensure_ascii=True, sort_keys=True),
        },
        {"role": "user", "content": question},
        {"role": "assistant", "content": _answer_question(question, context)},
    ]


def build_datasets(limit: int, output_dir: Path) -> dict[str, int]:
    contexts = iter_synthetic_contexts(limit=limit)
    sft_path = output_dir / "finwise_copilot_sft.jsonl"
    pretrain_path = output_dir / "finwise_domain_corpus.jsonl"
    manifest_path = output_dir / "dataset_manifest.json"
    _ensure_parent(sft_path)

    sft_count = 0
    with sft_path.open("w", encoding="utf-8") as sft_file:
        for index, context in enumerate(contexts):
            for question in QUESTION_BANK:
                row = {
                    "id": f"sft-{index:05d}-{sft_count:05d}",
                    "messages": _sft_messages(context, question),
                    "metadata": {
                        "symbol": (context.get("signal_meta") or {}).get("symbol"),
                        "timeframe": (context.get("signal_meta") or {}).get("tf_label"),
                        "signal": (context.get("signal") or {}).get("signal"),
                        "route_status": (context.get("preview") or {}).get("status"),
                    },
                }
                sft_file.write(json.dumps(row, ensure_ascii=True) + "\n")
                sft_count += 1

    pretrain_count = 0
    with pretrain_path.open("w", encoding="utf-8") as corpus_file:
        for index, context in enumerate(contexts):
            row = {
                "id": f"corpus-{index:05d}",
                "text": _pretrain_document(context),
                "metadata": {
                    "symbol": (context.get("signal_meta") or {}).get("symbol"),
                    "timeframe": (context.get("signal_meta") or {}).get("tf_label"),
                    "signal": (context.get("signal") or {}).get("signal"),
                },
            }
            corpus_file.write(json.dumps(row, ensure_ascii=True) + "\n")
            pretrain_count += 1

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "context_count": len(contexts),
        "sft_examples": sft_count,
        "pretrain_documents": pretrain_count,
        "files": {
            "sft": str(sft_path.relative_to(ROOT)),
            "pretrain": str(pretrain_path.relative_to(ROOT)),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"contexts": len(contexts), "sft": sft_count, "pretrain": pretrain_count}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Finwise Copilot training datasets.")
    parser.add_argument("--limit", type=int, default=180, help="Number of synthetic Finwise contexts to generate.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "finwise_model" / "datasets",
        help="Directory for generated dataset files.",
    )
    args = parser.parse_args()
    counts = build_datasets(limit=max(12, args.limit), output_dir=args.output_dir)
    print(
        f"Generated {counts['contexts']} contexts, {counts['sft']} SFT rows, "
        f"and {counts['pretrain']} pretraining documents in {args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

