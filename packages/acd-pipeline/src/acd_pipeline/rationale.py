"""Rationale validation and deterministic review projection."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from acd_core.rationale import check_rationale_coverage
from acd_schema import DesignGraph, RationaleDocument, RationaleRecord


def validate_and_project_rationale(
    graph: DesignGraph,
    fixture_dir: Path,
    out_dir: Path,
) -> RationaleDocument:
    rationale_path = fixture_dir / "rationale.json"
    if not rationale_path.is_file():
        raise FileNotFoundError(f"rationale does not exist: {rationale_path}")
    document = RationaleDocument.model_validate(
        json.loads(rationale_path.read_text(encoding="utf-8"))
    )
    report = check_rationale_coverage(graph, document)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rationale-coverage.json").write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    if report.status != "pass":
        raise ValueError(
            "rationale coverage failed: "
            f"missing={len(report.missing)}, stale={len(report.stale)}, "
            f"orphan={len(report.orphan)}, conflicting={len(report.conflicting)}, "
            f"unknown_provenance={len(report.unknown_provenance)}, "
            f"untraceable={len(report.untraceable)}"
        )
    _write_rationale_markdown(document, out_dir / "rationale.md")
    return document


def _write_rationale_markdown(document: RationaleDocument, output_path: Path) -> None:
    grouped: defaultdict[str, list[RationaleRecord]] = defaultdict(list)
    for record in sorted(document.records, key=lambda item: item.rationale_id):
        grouped[record.decision_kind].append(record)
    lines = [
        "# Design rationale",
        "",
        f"- Graph: `{document.graph_id}`",
        f"- Revision: `{document.revision}`",
        "",
    ]
    for decision_kind in sorted(grouped):
        lines.extend([f"## {decision_kind}", ""])
        for record in grouped[decision_kind]:
            lines.extend(
                [
                    f"### {record.rationale_id}",
                    "",
                    f"- Subjects: {', '.join(f'`{node}`' for node in record.subject_nodes)}",
                    f"- Attributes: {', '.join(f'`{attr}`' for attr in record.subject_attrs)}",
                    f"- Decision: {record.decision}",
                    f"- Justification: {record.justification}",
                    "- Rejected alternatives:",
                ]
            )
            if record.rejected_alternatives:
                lines.extend(
                    f"  - `{alternative.option}`: {alternative.reason}"
                    for alternative in record.rejected_alternatives
                )
            else:
                lines.append(f"  - None recorded: {record.no_alternatives_reason}")
            lines.append(
                "- Driving requirements: "
                + (", ".join(f"`{item}`" for item in record.driving_requirements) or "None")
            )
            provenance = record.provenance
            lines.extend(
                [
                    f"- Provenance source: `{provenance.source}`",
                    f"- Skill: `{provenance.skill_name or 'not applicable'}`",
                    f"- Script hash: `{provenance.script_hash or 'not applicable'}`",
                    f"- Agent model: `{provenance.agent_model or 'not applicable'}`",
                    (
                        "- Conversation event ref: "
                        f"`{provenance.conversation_event_ref or 'not applicable'}`"
                    ),
                    f"- Recorded at: `{provenance.recorded_at.isoformat()}`",
                    "",
                ]
            )
    output_path.write_text("\n".join(lines), encoding="utf-8")
