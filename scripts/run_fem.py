#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@ad297005c98c54a07cb837ae3ea123eea84dfd11",
# ]
# ///
"""Run or generate the opt-in CalculiX FEM estimate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.mechanical.fem import (
    FemAnalysisError,
    evaluate_fem,
    fem_markdown,
    generate_ccx_input,
    run_ccx,
)
from acd.core.mechanical.mechanical import extract_mechanical_lane
from acd.schema import DesignGraph, FemRequest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workdir", type=Path)
    parser.add_argument("--inp-only", action="store_true")
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate(json.loads(args.graph.read_text(encoding="utf-8")))
        request = FemRequest.model_validate(
            json.loads(args.request.read_text(encoding="utf-8"))
        )
        lane = extract_mechanical_lane(graph)
        width = lane.outline.width_mm + 2.0 * (
            lane.enclosure.internal_clearance_mm + lane.enclosure.wall_thickness_mm
        )
        depth = lane.outline.depth_mm + 2.0 * (
            lane.enclosure.internal_clearance_mm + lane.enclosure.wall_thickness_mm
        )
        height = lane.outline.thickness_mm + lane.enclosure.internal_clearance_mm + 2.0 * (
            lane.enclosure.wall_thickness_mm
        )
        dims = (width, depth, height, lane.enclosure.wall_thickness_mm)
        inp_text = generate_ccx_input(request, dims)
        if args.inp_only:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(inp_text, encoding="utf-8")
            return 0
        workdir = args.workdir or args.out.parent / "ccx-work"
        workdir.mkdir(parents=True, exist_ok=True)
        inp = workdir / "model.inp"
        inp.write_text(inp_text, encoding="utf-8")
        raw = run_ccx(inp, workdir, version_pin=request.ccx.version_pin)
        result = evaluate_fem(graph, request, raw)
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
            args.out_md.write_text(fem_markdown(result), encoding="utf-8")
    except (OSError, ValueError, TypeError, json.JSONDecodeError, FemAnalysisError) as exc:
        print(f"FEM input error: {exc}", file=sys.stderr)
        return 2
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
