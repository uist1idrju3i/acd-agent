"""Deterministic defect-record horizontal-scope gate CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.manufacturing.defect_records import (
    DefectRecordError,
    check_defect_records,
    load_defect_document,
)
from acd.pipeline.gate_evidence import write_gate_evidence
from acd.schema.design_graph import DesignGraph


def _load_graph(path: Path) -> DesignGraph:
    try:
        return DesignGraph.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DefectRecordError(f"design graph {path} is not valid: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the defect-record horizontal-scope gate."
    )
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--defects", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        graph = _load_graph(args.graph)
        loaded = load_defect_document(args.defects)
    except DefectRecordError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    result = check_defect_records(graph, loaded.document)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.out_dir / "defect-record-check.json"
    result_path.write_text(
        result.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    evidence_path = write_gate_evidence(
        args.out_dir,
        "defect-record.json",
        target_revision=graph.revision,
        gate="defect_record",
        status=result.status,
        message=(
            "defect records are mechanically searchable and workaround-eligible"
            if result.status == "pass"
            else f"{len(result.findings)} defect-record finding(s)"
        ),
        observation={
            "graph_id": graph.graph_id,
            "findings": [
                finding.model_dump(mode="json") for finding in result.findings
            ],
            "workaround_eligible": result.workaround_eligible,
            "blocked": result.blocked,
        },
    )
    output = {
        "gate": "defect_record",
        "status": result.status,
        "result": str(result_path),
        "evidence": str(evidence_path),
        "finding_count": len(result.findings),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
