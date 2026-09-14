"""Deterministic responsibility-assignment gate CLI (ADR-0049 §7)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.responsibility_gate import (
    ResponsibilityGateError,
    check_responsibility,
    load_responsibility_declaration,
)
from acd.pipeline.gate_evidence import write_gate_evidence
from acd.schema.design_graph import DesignGraph


def _load_graph(path: Path) -> DesignGraph:
    try:
        return DesignGraph.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ResponsibilityGateError(
            f"design graph {path} is not valid: {exc}"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the responsibility-assignment gate on a design graph "
        "and a responsibility declaration."
    )
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--declaration", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        graph = _load_graph(args.graph)
        declaration = load_responsibility_declaration(args.declaration)
    except ResponsibilityGateError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    result = check_responsibility(graph, declaration)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.out_dir / "responsibility-gate.json"
    result_path.write_text(
        result.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )

    evidence_path = write_gate_evidence(
        args.out_dir,
        "responsibility-assignment.json",
        target_revision=graph.revision,
        gate="responsibility_assignment",
        status=result.status,
        message=(
            "all declared functions are assigned to declared, capable domains"
            if result.status == "pass"
            else f"{len(result.findings)} responsibility finding(s)"
        ),
        observation={
            "graph_id": graph.graph_id,
            "assignment_count": len(result.assignments),
            "findings": [
                finding.model_dump(mode="json")
                for finding in result.findings
            ],
        },
    )

    output = {
        "gate": "responsibility_assignment",
        "status": result.status,
        "result": str(result_path),
        "evidence": str(evidence_path),
        "finding_count": len(result.findings),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
