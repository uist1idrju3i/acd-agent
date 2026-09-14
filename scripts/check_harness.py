#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@f20514f94d938b73deeb47e6980bbb49501b03c9",
# ]
# ///
"""Run the opt-in deterministic wire-harness gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.electrical import extract_electrical_lane
from acd.core.harness import evaluate_harness
from acd.schema import DesignGraph, HarnessContract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--harness", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate(
            json.loads(args.graph.read_text(encoding="utf-8"))
        )
        contract = HarnessContract.model_validate(
            json.loads(args.harness.read_text(encoding="utf-8"))
        )
        if graph.graph_id != contract.graph_id or graph.revision != contract.revision:
            raise ValueError("harness graph_id/revision does not match graph")
        result = evaluate_harness(
            graph,
            extract_electrical_lane(graph),
            contract,
        )
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "harness-check.json").write_text(
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
        print(f"Harness input error: {error}", file=sys.stderr)
        return 2
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
