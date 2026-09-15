#!/usr/bin/env python3
"""Run the opt-in graph-derived SPICE estimate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from acd.core.spice import (
    SpiceNetlistError,
    evaluate_spice,
    extract_power_netlist,
    run_ngspice,
)
from acd.schema import DesignGraph, SpiceAnalysisRequest


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workdir", type=Path)
    parser.add_argument("--netlist-only", action="store_true")
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate(_read_json(args.graph))
        request = SpiceAnalysisRequest.model_validate(_read_json(args.request))
        netlist = extract_power_netlist(graph, request)
    except (OSError, json.JSONDecodeError, ValidationError, SpiceNetlistError) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.netlist_only:
        args.out.write_text(netlist.text, encoding="utf-8")
        return 0
    workdir = args.workdir or args.out.parent / "spice-work"
    raw = run_ngspice(netlist, workdir)
    result = evaluate_spice(graph, request, raw)
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
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
