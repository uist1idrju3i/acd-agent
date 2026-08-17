#!/usr/bin/env python3
"""Validate a deterministic design rationale document against a graph."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from acd_core import check_rationale_coverage
from acd_schema import DesignGraph, RationaleDocument


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", default="fixtures/golden-design-1/graph.json")
    parser.add_argument("--rationale", default="fixtures/golden-design-1/rationale.json")
    parser.add_argument("--report")
    parser.add_argument("--if-present", action="store_true")
    args = parser.parse_args()
    rationale_path = Path(args.rationale)
    if not rationale_path.is_file() and args.if_present:
        result: dict[str, Any] = {"status": "not_applicable"}
        print("Rationale not present; validation not applicable.")
        if args.report:
            Path(args.report).write_text(
                json.dumps(result, indent=2) + "\n", encoding="utf-8"
            )
        return 0
    try:
        graph = DesignGraph.model_validate(
            json.loads(Path(args.graph).read_text(encoding="utf-8"))
        )
        document = RationaleDocument.model_validate(
            json.loads(rationale_path.read_text(encoding="utf-8"))
        )
        report = check_rationale_coverage(graph, document)
        result = report.model_dump(mode="json")
    except Exception as exc:
        print(f"Rationale validation failed: {exc}")
        return 2
    print(f"Rationale coverage: {report.status}")
    for field in ("missing", "stale", "unknown_provenance", "orphan", "conflicting"):
        values = result[field]
        if values:
            print(f"{field}: {json.dumps(values, ensure_ascii=False)}")
    if args.report:
        Path(args.report).write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 0 if report.status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
