#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@31ea95ed97a4663ee1106b01b0b1e8cbb612dede",
# ]
# ///
"""Run the opt-in reliability-test mapping gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.electrical import extract_electrical_lane
from acd.core.reliability_test import evaluate_reliability_test_plan
from acd.schema import DesignGraph, ReliabilityTestPlan, UseEnvironment


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--environment", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--emc-result", type=Path)
    parser.add_argument("--structural-result", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate(
            json.loads(args.graph.read_text(encoding="utf-8"))
        )
        environment = UseEnvironment.model_validate(
            json.loads(args.environment.read_text(encoding="utf-8"))
        )
        plan = ReliabilityTestPlan.model_validate(
            json.loads(args.plan.read_text(encoding="utf-8"))
        )
        predicate_results: list[object] = []
        for result_path in (args.emc_result, args.structural_result):
            if result_path is not None:
                predicate_results.append(
                    json.loads(result_path.read_text(encoding="utf-8"))
                )
        result = evaluate_reliability_test_plan(
            graph,
            extract_electrical_lane(graph),
            environment,
            plan,
            predicate_results or None,
        )
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "reliability-test-result.json").write_text(
            json.dumps(
                result.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"Reliability test input error: {error}", file=sys.stderr)
        return 2
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
