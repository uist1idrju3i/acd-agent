#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@e8d0307410666e9ed11f794b9e46d0595a3528f3",
# ]
# ///
"""Run the opt-in DFT coverage gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.electrical.dft_coverage import evaluate_dft_coverage
from acd.core.electrical.electrical import extract_electrical_lane
from acd.schema import DesignGraph, DftPolicy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate(json.loads(args.graph.read_text(encoding="utf-8")))
        policy = DftPolicy.model_validate(json.loads(args.policy.read_text(encoding="utf-8")))
        if graph.graph_id != policy.graph_id or graph.revision != policy.revision:
            raise ValueError("DFT policy graph_id/revision does not match graph")
        result = evaluate_dft_coverage(graph, extract_electrical_lane(graph), policy)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "dft-coverage.json").write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"DFT input error: {error}", file=sys.stderr)
        return 2
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
