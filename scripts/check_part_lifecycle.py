#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@0ca3330c29872817ab9044d5377a0dcf46f848c4",
# ]
# ///
"""Run the opt-in part lifecycle and second-source gate."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from acd.core.electrical import extract_electrical_lane
from acd.core.part_lifecycle import evaluate_part_lifecycle
from acd.schema import DesignGraph, PartLifecycleRegistry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate(
            json.loads(args.graph.read_text(encoding="utf-8"))
        )
        registry = PartLifecycleRegistry.model_validate(
            json.loads(args.registry.read_text(encoding="utf-8"))
        )
        if args.as_of is not None:
            registry = registry.model_copy(update={"as_of": args.as_of})
        result = evaluate_part_lifecycle(
            graph,
            extract_electrical_lane(graph),
            registry,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
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
        print(f"Part lifecycle input error: {error}", file=sys.stderr)
        return 2
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
