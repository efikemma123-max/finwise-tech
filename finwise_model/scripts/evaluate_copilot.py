from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broker_ai_copilot import run_copilot_agent_turn
from finwise_model.sample_contexts import SyntheticContextSpec, build_context_from_spec


CONFIG_PATH = ROOT / "finwise_model" / "configs" / "copilot_eval_cases.json"


def _build_eval_contexts() -> dict[str, dict]:
    contexts = {
        "blocked_btc_3m": build_context_from_spec(
            SyntheticContextSpec(
                symbol="BTCUSDT",
                timeframe="3m",
                signal="BUY",
                broker_name="Bybit",
                connection_method="oauth",
                balance=12640.0,
                total_trades=18,
                drawdown=3.4,
                market_reason="Price is rotating inside a mixed range with no clean breakout confirmation yet.",
                setup_quality="building",
                connector_summary="Connector test passed with balance, pricing, and fee access confirmed.",
                route_status="blocked",
                confidence=58.0,
                risk_reward=1.34,
                projected_edge=0.31,
                black_swan_risk=24,
                last_price=81876.9,
            ),
            seed=11,
        ),
        "ready_eth_15m": build_context_from_spec(
            SyntheticContextSpec(
                symbol="ETHUSDT",
                timeframe="15m",
                signal="SELL",
                broker_name="Binance",
                connection_method="api",
                balance=9420.0,
                total_trades=27,
                drawdown=5.8,
                market_reason="Sellers are pressing the session highs and weakening rebound attempts.",
                setup_quality="strong",
                connector_summary="Connector test passed with balance, pricing, and fee access confirmed.",
                route_status="ready",
                confidence=73.0,
                risk_reward=2.14,
                projected_edge=1.22,
                black_swan_risk=18,
                last_price=3924.2,
            ),
            seed=21,
        ),
        "hold_btc_1m": build_context_from_spec(
            SyntheticContextSpec(
                symbol="BTCUSDT",
                timeframe="1m",
                signal="HOLD",
                broker_name="Finwise",
                connection_method="not_connected",
                balance=10000.0,
                total_trades=0,
                drawdown=0.0,
                market_reason="Order flow is stabilizing after a sharp impulse, but conviction is still uneven.",
                setup_quality="neutral",
                connector_summary="Connector test has not been run yet.",
                route_status="waiting",
                confidence=50.0,
                risk_reward=1.2,
                projected_edge=0.12,
                black_swan_risk=8,
                last_price=81710.0,
            ),
            seed=31,
        ),
        "disconnected_sol_5m": build_context_from_spec(
            SyntheticContextSpec(
                symbol="SOLUSDT",
                timeframe="5m",
                signal="BUY",
                broker_name="Finwise",
                connection_method="not_connected",
                balance=10000.0,
                total_trades=0,
                drawdown=0.0,
                market_reason="Momentum is compressing near intraday resistance while buyers still defend pullbacks.",
                setup_quality="fragile",
                connector_summary="Connector test is waiting for broker approval.",
                route_status="blocked",
                confidence=61.0,
                risk_reward=1.51,
                projected_edge=0.28,
                black_swan_risk=14,
                last_price=170.8,
            ),
            seed=41,
        ),
    }
    return contexts


def _load_cases() -> list[dict]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def _memory_matches(expected_memory: dict, actual_memory: dict) -> list[dict]:
    checks: list[dict] = []
    for key, expected_value in (expected_memory or {}).items():
        actual_value = actual_memory.get(key)
        checks.append(
            {
                "label": f"memory:{key}",
                "passed": actual_value == expected_value,
                "expected": expected_value,
                "actual": actual_value,
            }
        )
    return checks


def _evaluate_case(case: dict, contexts: dict[str, dict], *, use_model: bool) -> dict:
    context_id = str(case.get("context_id") or "")
    context = contexts[context_id]
    question = str(case.get("question") or "")
    scope = str(case.get("scope") or "copilot")
    starting_memory = case.get("memory") or {}
    result = run_copilot_agent_turn(
        question,
        context,
        [],
        scope=scope,
        memory=starting_memory,
        execute_actions=False,
        allow_model=use_model,
    )
    reply = str(result.get("reply") or "")
    plan = result.get("plan") or {}
    memory = result.get("memory") or {}
    checks: list[dict] = []

    for intent in case.get("expected_intents") or []:
        actual_intents = list(plan.get("intents") or [])
        checks.append(
            {
                "label": f"intent:{intent}",
                "passed": intent in actual_intents,
                "expected": intent,
                "actual": actual_intents,
            }
        )

    for action in case.get("expected_actions") or []:
        actual_actions = list(plan.get("actions") or [])
        checks.append(
            {
                "label": f"action:{action}",
                "passed": action in actual_actions,
                "expected": action,
                "actual": actual_actions,
            }
        )

    lowered_reply = reply.lower()
    for snippet in case.get("required_substrings") or []:
        checks.append(
            {
                "label": f"reply:{snippet}",
                "passed": str(snippet).lower() in lowered_reply,
                "expected": snippet,
                "actual": reply,
            }
        )

    checks.extend(_memory_matches(case.get("expected_memory") or {}, memory))
    passed = all(item["passed"] for item in checks) if checks else True
    return {
        "id": case.get("id"),
        "passed": passed,
        "mode_used": result.get("mode_used"),
        "reply": reply,
        "plan": plan,
        "memory": memory,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Finwise Copilot scenarios.")
    parser.add_argument("--case", dest="case_id", help="Run only one case id.")
    parser.add_argument("--use-model", action="store_true", help="Allow the live configured model path during evaluation.")
    parser.add_argument("--output", help="Optional JSON output path.")
    args = parser.parse_args()

    contexts = _build_eval_contexts()
    cases = _load_cases()
    if args.case_id:
        cases = [case for case in cases if str(case.get("id")) == args.case_id]
        if not cases:
            raise SystemExit(f"No eval case found for id: {args.case_id}")

    results = [_evaluate_case(case, contexts, use_model=args.use_model) for case in cases]
    passed = sum(1 for item in results if item["passed"])
    total = len(results)

    print(f"Finwise Copilot Eval: {passed}/{total} cases passed")
    for item in results:
        status = "PASS" if item["passed"] else "FAIL"
        print(f"[{status}] {item['id']} ({item['mode_used']})")
        if not item["passed"]:
            for check in item["checks"]:
                if not check["passed"]:
                    print(f"  - {check['label']} expected={check['expected']} actual={check['actual']}")

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote detailed results to {output_path}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
