#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@e8d0307410666e9ed11f794b9e46d0595a3528f3",
# ]
# ///
"""Run the opt-in EMC/ESD design predicates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.electrical import extract_electrical_lane
from acd.core.emc_esd import evaluate_emc_esd
from acd.schema import DesignGraph, UseEnvironment


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--environment", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate(json.loads(args.graph.read_text(encoding="utf-8")))
        environment = UseEnvironment.model_validate(
            json.loads(args.environment.read_text(encoding="utf-8"))
        )
        if environment.graph_id != graph.graph_id or environment.revision != graph.revision:
            raise ValueError("use environment graph_id/revision does not match graph")
        result = evaluate_emc_esd(graph, extract_electrical_lane(graph), environment)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "emc-esd.json").write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"EMC/ESD input error: {error}", file=sys.stderr)
        return 2
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
