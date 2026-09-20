"""Run the deterministic mechanical DFM gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.adapters.cad.mechanical_dfm import check_mechanical_dfm
from acd.adapters.cad.project import build_enclosure_shapes
from acd.core.mechanical.mechanical import extract_mechanical_lane
from acd.schema.design_graph import DesignGraph


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate_json(args.graph.read_text(encoding="utf-8"))
        lane = extract_mechanical_lane(graph)
        shell, lid = build_enclosure_shapes(lane)
        solids = (shell, lid)
        findings = check_mechanical_dfm(lane, solids)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"mechanical DFM extraction failed: {exc}", file=sys.stderr)
        return 2
    status = (
        "not_applicable"
        if not findings
        else "fail"
        if any(item.status == "fail" for item in findings)
        else "unknown"
        if any(item.status == "unknown" for item in findings)
        else "pass"
    )
    payload = {
        "schema_version": graph.schema_version,
        "graph_id": graph.graph_id,
        "revision": graph.revision,
        "gate_id": "mechanical_dfm",
        "status": status,
        "findings": [
            {
                "rule_id": item.rule_id,
                "status": item.status,
                "message": item.message,
                "measured": item.measured,
                "limit": item.limit,
                "face_center_mm": item.face_center_mm,
                "feature_id": item.feature_id,
            }
            for item in findings
        ],
    }
    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"mechanical DFM output failed: {exc}", file=sys.stderr)
        return 2
    return 0 if status in {"pass", "not_applicable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
