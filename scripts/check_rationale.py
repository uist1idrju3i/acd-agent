#!/usr/bin/env python3
"""Validate a deterministic design rationale document against a graph."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from acd.core import check_rationale_coverage
from acd.schema import DesignGraph, RationaleDocument


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--report")
    parser.add_argument("--if-present", action="store_true")
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args()
    graph_path = Path(args.graph)
    rationale_path = Path(args.rationale)
    graph_path_display = str(graph_path)
    revision = "unknown"
    if args.if_present and (not graph_path.is_file() or not rationale_path.is_file()):
        result: dict[str, Any] = {
            "status": "not_applicable",
            "graph_path": graph_path_display,
            "revision": "unknown",
        }
        print("Rationale validation not applicable; graph or rationale is not present.")
        if args.report:
            Path(args.report).write_text(
                json.dumps(result, indent=2) + "\n", encoding="utf-8"
            )
        return 0
    try:
        graph = DesignGraph.model_validate(json.loads(graph_path.read_text(encoding="utf-8")))
        graph_path_display = str(graph_path)
        revision = graph.revision
        document = RationaleDocument.model_validate(
            json.loads(rationale_path.read_text(encoding="utf-8"))
        )
        report = check_rationale_coverage(graph, document)
        result = report.model_dump(mode="json")
        result["graph_path"] = graph_path_display
        result["revision"] = revision
    except Exception as exc:
        result = {
            "status": "fail",
            "graph_path": graph_path_display,
            "revision": revision,
            "error": str(exc),
        }
        print(f"Rationale validation target: {graph_path_display}")
        print(f"Rationale validation revision: {revision}")
        print(f"Rationale validation failed: {exc}")
        if args.report:
            Path(args.report).write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return 0 if args.warn_only else 2
    print(f"Rationale validation target: {graph_path_display}")
    print(f"Rationale validation revision: {result['revision']}")
    if report.status == "pass":
        print(
            "Rationale coverage: pass "
            "(diagnostic only; this is not an L1 gate pass)"
        )
    else:
        print(f"Rationale coverage: {report.status}")
    for field in (
        "missing",
        "stale",
        "unknown_provenance",
        "orphan",
        "untraceable",
        "conflicting",
        "unclassified",
    ):
        values = result[field]
        if values:
            print(f"{field}: {json.dumps(values, ensure_ascii=False)}")
    if args.report:
        Path(args.report).write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 0 if report.status == "pass" or args.warn_only else 2


if __name__ == "__main__":
    raise SystemExit(main())
