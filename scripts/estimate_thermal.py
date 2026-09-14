#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@ad297005c98c54a07cb837ae3ea123eea84dfd11",
# ]
# ///
"""Run the opt-in simplified thermal estimate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.thermal import ThermalAnalysisError, estimate_thermal, thermal_markdown
from acd.schema import DesignGraph, ThermalRequest, UseEnvironment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--environment", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate(json.loads(args.graph.read_text(encoding="utf-8")))
        request = ThermalRequest.model_validate(
            json.loads(args.request.read_text(encoding="utf-8"))
        )
        environment = (
            UseEnvironment.model_validate(
                json.loads(args.environment.read_text(encoding="utf-8"))
            )
            if args.environment is not None
            else None
        )
        result = estimate_thermal(graph, request, environment)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                result.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        if args.out_md is not None:
            args.out_md.parent.mkdir(parents=True, exist_ok=True)
            args.out_md.write_text(thermal_markdown(result), encoding="utf-8")
    except (OSError, ValueError, TypeError, json.JSONDecodeError, ThermalAnalysisError) as exc:
        print(f"thermal input error: {exc}", file=sys.stderr)
        return 2
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
