from __future__ import annotations

import argparse
import json
from pathlib import Path


def _validate_jsonl(path: Path, *, required_keys: list[str]) -> tuple[int, list[str]]:
    issues: list[str] = []
    count = 0
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        count += 1
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            issues.append(f"{path.name}:{line_number} invalid JSON: {exc}")
            continue
        for key in required_keys:
            if key not in payload:
                issues.append(f"{path.name}:{line_number} missing key `{key}`")
    return count, issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated Finwise model datasets.")
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path("finwise_model") / "datasets",
        help="Directory containing generated dataset JSONL files.",
    )
    args = parser.parse_args()
    dataset_dir = args.dataset_dir
    sft_path = dataset_dir / "finwise_copilot_sft.jsonl"
    corpus_path = dataset_dir / "finwise_domain_corpus.jsonl"
    manifest_path = dataset_dir / "dataset_manifest.json"
    live_sft_path = dataset_dir / "finwise_live_sft.jsonl"
    live_corpus_path = dataset_dir / "finwise_live_domain_corpus.jsonl"

    if not sft_path.exists() or not corpus_path.exists() or not manifest_path.exists():
        print("Missing generated dataset files. Run build_datasets.py first.")
        return 1

    sft_count, sft_issues = _validate_jsonl(sft_path, required_keys=["id", "messages", "metadata"])
    corpus_count, corpus_issues = _validate_jsonl(corpus_path, required_keys=["id", "text", "metadata"])
    issues = sft_issues + corpus_issues
    live_sft_count = 0
    live_corpus_count = 0
    if live_sft_path.exists():
        live_sft_count, live_sft_issues = _validate_jsonl(live_sft_path, required_keys=["id", "messages", "metadata"])
        issues.extend(live_sft_issues)
    if live_corpus_path.exists():
        live_corpus_count, live_corpus_issues = _validate_jsonl(live_corpus_path, required_keys=["id", "text", "metadata"])
        issues.extend(live_corpus_issues)
    if issues:
        for issue in issues:
            print(issue)
        return 1

    print(
        f"Validated {sft_count} synthetic SFT rows, {corpus_count} synthetic pretraining rows, "
        f"{live_sft_count} live SFT rows, and {live_corpus_count} live pretraining rows successfully."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
