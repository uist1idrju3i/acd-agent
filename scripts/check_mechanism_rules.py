#!/usr/bin/env python3
"""Check opt-in enclosure mechanism design rules."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.mechanical import extract_mechanical_lane
from acd.core.mechanism_rules import check_mechanism_features
from acd.schema.design_graph import DesignGraph


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate_json(args.graph.read_text(encoding="utf-8"))
        lane = extract_mechanical_lane(graph)
        findings = check_mechanism_features(lane)
    except (OSError, ValueError, TypeError) as exc:
        print(f"mechanism extraction failed: {exc}", file=sys.stderr)
        return 2
    payload = {
        "schema_version": 1,
        "graph_id": graph.graph_id,
        "revision": graph.revision,
        "gate_id": "mechanism_rules",
        "status": (
            "not_applicable"
            if not findings
            else "fail"
            if any(item.status == "fail" for item in findings)
            else "unknown"
            if any(item.status == "unknown" for item in findings)
            else "pass"
        ),
        "findings": [
            {
                "node_id": item.node_id,
                "feature_type": item.feature_type,
                "rule_id": item.rule_id,
                "status": item.status,
                "message": item.message,
                "measured": item.measured,
                "limit": item.limit,
            }
            for item in findings
        ],
    }
    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"mechanism output failed: {exc}", file=sys.stderr)
        return 2
    return 0 if payload["status"] in {"pass", "not_applicable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
