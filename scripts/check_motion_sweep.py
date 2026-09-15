"""Run the deterministic mechanism motion-sweep gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.adapters.cad.motion_sweep import check_motion_sweep
from acd.adapters.cad.project import build_enclosure_shapes
from acd.core.mechanical import extract_mechanical_lane
from acd.schema.design_graph import DesignGraph


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        graph = DesignGraph.model_validate_json(
            args.graph.read_text(encoding="utf-8")
        )
        lane = extract_mechanical_lane(graph)
        shell, lid = build_enclosure_shapes(lane)
        findings = check_motion_sweep(lane, shell, lid)
        status = (
            "not_applicable"
            if not findings
            else (
                "fail"
                if any(item.status == "fail" for item in findings)
                else "unknown"
                if any(item.status == "unknown" for item in findings)
                else "pass"
            )
        )
        payload = {
            "schema_version": graph.schema_version,
            "graph_id": graph.graph_id,
            "revision": graph.revision,
            "gate_id": "motion_sweep",
            "status": status,
            "findings": [
                {
                    "feature_id": item.feature_id,
                    "poses_checked": item.poses_checked,
                    "worst_pose": item.worst_pose,
                    "worst_interference_mm3": item.worst_interference_mm3,
                    "colliding_ids": list(item.colliding_ids),
                    "status": item.status,
                }
                for item in findings
            ],
        }
        args.out.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0 if status in {"pass", "not_applicable"} else 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"motion sweep check failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
