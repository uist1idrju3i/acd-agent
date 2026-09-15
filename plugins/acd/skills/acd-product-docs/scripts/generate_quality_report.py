# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@99d03f7872721ea3e2d8e3d2d9ee9b4e9102cdb6",
# ]
# ///
"""Project the quality documents deterministically from authoritative Evidence.

The inspection report and traceability report join lane Evidence, rationale
coverage reports, design-predicate observations, and the DFM report with the
design graph. Only authoritative (container-context) Evidence is accepted;
provisional host Evidence and any inconsistency fail closed.
"""

from __future__ import annotations

import argparse
import json
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from acd.schema.design_graph import DesignGraph
from acd.schema.evidence import Evidence
from acd.schema.rationale import (
    RationaleCoverageReport,
    RationaleDocument,
    RationaleRecord,
)
from doc_inputs import (
    ANALYSIS_KIND_TEMPLATE_KEYS,
    ANALYSIS_STATUS_TEMPLATE_KEYS,
    AnalysisBundle,
    DesignPredicates,
    DfmFinding,
    DfmReport,
    DocumentGenerationError,
    DocumentInput,
    DocumentTemplate,
    PredicateObservation,
    analysis_summary,
    load_analysis_results,
    load_design_predicates,
    load_dfm_report,
    load_graph,
    load_json_object,
    load_template,
    nodes_of_kind,
    relative_path,
    require_list,
    require_object,
    require_str,
    sha256_file,
    text_attr,
    write_document,
)

DOCUMENT_NAME = "inspection-report.md"
TRACEABILITY_DOCUMENT_NAME = "traceability-report.md"
JSON_DOCUMENT_NAME = "quality-report.json"

_TEMPLATE: ContextVar[DocumentTemplate | None] = ContextVar(
    "quality_report_template", default=None
)


def t(key: str, **values: object) -> str:
    template = _TEMPLATE.get() or load_template("ja")
    return template.t(key, **values)

DEFAULT_REQUIRED_LANES = ("electrical", "mechanical", "firmware")

__all__ = [
    "DesignPredicates",
    "DfmFinding",
    "DfmReport",
    "DocumentGenerationError",
    "DocumentInput",
    "PredicateObservation",
    "load_design_predicates",
    "load_dfm_report",
    "load_graph",
    "load_json_object",
    "require_list",
    "require_object",
    "require_str",
]


@dataclass(frozen=True)
class LaneEvidence:
    """One lane's authoritative Evidence plus its lane name."""

    lane: str
    evidence: Evidence


def load_evidence(path: Path, graph: DesignGraph, *, lane: str) -> LaneEvidence:
    """Load one lane Evidence; only authoritative container Evidence is accepted."""
    try:
        evidence = Evidence.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DocumentGenerationError(
            f"{lane} evidence {path} is not valid: {exc}"
        ) from exc
    if evidence.target_revision != graph.revision:
        raise DocumentGenerationError(
            f"{lane} evidence {path} targets revision "
            f"{evidence.target_revision!r}, not {graph.revision!r}"
        )
    if evidence.status != "valid":
        raise DocumentGenerationError(
            f"{lane} evidence {path} has status {evidence.status!r}, not 'valid'"
        )
    if not evidence.supports_authoritative_pass(graph.revision):
        raise DocumentGenerationError(
            f"{lane} evidence {path} is not authoritative; this document "
            "requires authoritative Evidence (container execution)"
        )
    return LaneEvidence(lane=lane, evidence=evidence)


def load_coverage_report(path: Path, graph: DesignGraph) -> RationaleCoverageReport:
    """Load one rationale coverage report, fail-closed."""
    try:
        report = RationaleCoverageReport.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise DocumentGenerationError(
            f"rationale coverage {path} is not valid: {exc}"
        ) from exc
    if report.graph_id != graph.graph_id:
        raise DocumentGenerationError(
            f"rationale coverage {path} targets graph {report.graph_id!r}, "
            f"not {graph.graph_id!r}"
        )
    if report.revision != graph.revision:
        raise DocumentGenerationError(
            f"rationale coverage {path} targets revision {report.revision!r}, "
            f"not {graph.revision!r}"
        )
    if report.status != "pass":
        raise DocumentGenerationError(
            f"rationale coverage {path} has status {report.status!r}, not 'pass'"
        )
    return report


def load_rationale(path: Path, graph: DesignGraph) -> RationaleDocument:
    """Load the fixture rationale document, fail-closed."""
    try:
        document = RationaleDocument.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise DocumentGenerationError(
            f"rationale {path} is not valid: {exc}"
        ) from exc
    if document.graph_id != graph.graph_id:
        raise DocumentGenerationError(
            f"rationale {path} targets graph {document.graph_id!r}, "
            f"not {graph.graph_id!r}"
        )
    if document.revision != graph.revision:
        raise DocumentGenerationError(
            f"rationale {path} targets revision {document.revision!r}, "
            f"not {graph.revision!r}"
        )
    return document


def _guard_graph_references(
    graph: DesignGraph,
    lanes: tuple[LaneEvidence, ...],
    rationale: RationaleDocument,
) -> None:
    node_ids = {node.id for node in graph.nodes}
    for lane in lanes:
        for claim in lane.evidence.claims:
            if claim.subject_node not in node_ids:
                raise DocumentGenerationError(
                    f"{lane.lane} evidence claim subject_node "
                    f"{claim.subject_node!r} is not in the graph"
                )
    for record in rationale.records:
        for requirement in record.driving_requirements:
            if requirement not in node_ids:
                raise DocumentGenerationError(
                    f"rationale record {record.rationale_id!r} references "
                    f"requirement {requirement!r} not present in the graph"
                )


def _claims_table(lane: LaneEvidence) -> list[str]:
    lines = [
        t("quality.claims_header"),
        "|---|---|---|---|",
    ]
    for claim in lane.evidence.claims:
        lines.append(
            f"| `{claim.subject_node}` | {claim.property} | {claim.value} "
            f"| {claim.verified} |"
        )
    return lines


def _render_inspection(
    graph: DesignGraph,
    lanes: tuple[LaneEvidence, ...],
    coverages: tuple[tuple[Path, RationaleCoverageReport], ...],
    predicates: DesignPredicates,
    dfm: DfmReport,
    analyses: AnalysisBundle,
    base_dir: Path,
) -> str:
    """Render the inspection report () Markdown body."""
    lane_map = {lane.lane: lane for lane in lanes}
    lines = [
        t("quality.inspection_title", graph_id=graph.graph_id),
        "",
        f"- Design Graph: `{graph.graph_id}`",
        f"- revision: `{graph.revision}`",
        "",
        t("quality.inspection_paragraph"),
        "",
        t("quality.gate_results_heading"),
        "",
        "| lane | evidence_id | status | tool | context | image digest | source_revision |",
        "|---|---|---|---|---|---|---|",
    ]
    for lane in lanes:
        envelope = lane.evidence.envelope
        digest = envelope.container_image_digest or "unknown"
        lines.append(
            f"| {lane.lane} | {lane.evidence.evidence_id} | {lane.evidence.status} "
            f"| {envelope.tool_name} {envelope.tool_version} "
            f"| {envelope.execution_context} | `{digest}` | "
            f"{envelope.source_revision or 'unknown'} |"
        )
    lines += ["", t("quality.electrical_heading"), ""]

    if "electrical" in lane_map:
        lines += [t("quality.predicate_heading"), "", *_claims_table(lane_map["electrical"]), ""]
    lines += [
        t("quality.mechanical_heading"),
        "",
        "| name | stage | status | detail |",
        "|---|---|---|---|",
    ]
    for item in predicates.predicates:
        lines.append(
            f"| {item.name} | {item.evaluation_stage} | {item.status} | {item.detail} |"
        )
    lines += [
        "",
        "### DFM",
        "",
        f"- status: `{dfm.status}`",
        f"- profile_id: `{dfm.profile_id}`",
        t("quality.findings_sentence", count=len(dfm.findings)),
    ]
    for finding in dfm.findings:
        lines.append(f"  - {finding.rule_id}: {finding.message}")
    if dfm.unknowns:
        lines.append("- unknowns:")
        for key in sorted(dfm.unknowns):
            lines.append(f"  - `{key}`: {dfm.unknowns[key]}")
    lines.append("")
    if "mechanical" in lane_map:
        lines += [
            t("quality.virtual_measurement_note"),
            "",
            *_claims_table(lane_map["mechanical"]),
            "",
        ]
    if "firmware" in lane_map:
        lines += ["### FW", "", *_claims_table(lane_map["firmware"])]
        if any(
            claim.property == "measurement_class" and claim.value == "virtual"
            for claim in lane_map["firmware"].evidence.claims
        ):
            lines.append(
                t("quality.virtual_measurement_sentence")
            )
        lines.append("")

    summaries = [analysis_summary(item) for item in analyses.artifacts]
    statuses = [str(item["status"]) for item in summaries]
    overall = (
        "findings"
        if any(status in {"fail", "unknown"} for status in statuses)
        else "not_run"
        if all(status == "not_run" for status in statuses)
        else "pass"
    )
    lines += [
        t("quality.analysis_heading"),
        "",
        t("quality.analysis_sentence"),
        "",
        t(
            "quality.analysis_overall_sentence",
            status=t(ANALYSIS_STATUS_TEMPLATE_KEYS[overall]),
        ),
        "",
        t("quality.analysis_table_header"),
        "|---|---|---|---|---|---|---|",
    ]
    for summary in summaries:
        status = str(summary["status"])
        status_text = (
            t(ANALYSIS_STATUS_TEMPLATE_KEYS["not_run"])
            if status == "not_run"
            else status
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    t(ANALYSIS_KIND_TEMPLATE_KEYS[str(summary["kind"])]),
                    status_text,
                    str(summary["authority"]),
                    str(summary["measured"]),
                    str(summary["tool_versions"]),
                    str(summary["input_hashes"]),
                    str(summary["findings"]),
                ]
            )
            + " |"
        )
    stop_side = [
        summary
        for summary in summaries
        if summary["status"] in {"fail", "unknown"}
    ]
    lines += ["", t("quality.analysis_stop_heading"), ""]
    if stop_side:
        for summary in stop_side:
            lines.append(
                f"- {t(ANALYSIS_KIND_TEMPLATE_KEYS[str(summary['kind'])])}: "
                f"{summary['status']} — {summary['findings']}"
            )
    else:
        lines.append(t("quality.analysis_stop_none"))
    lines.append("")

    lines += [
        "## rationale coverage",
        "",
        "| file | status | required | covered | records | missing | stale "
        "| unknown_provenance | orphan | untraceable | conflicting "
        "| unclassified | templated | generator_violations |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for path, report in coverages:
        lines.append(
            f"| `{relative_path(path, base_dir)}` | {report.status} | {report.required_count} "
            f"| {report.covered_count} | {report.record_count} "
            f"| {len(report.missing)} | {len(report.stale)} "
            f"| {len(report.unknown_provenance)} | {len(report.orphan)} "
            f"| {len(report.untraceable)} | {len(report.conflicting)} "
            f"| {len(report.unclassified)} | {len(report.templated)} "
            f"| {len(report.generator_violations)} |"
        )
    lines += ["", t("quality.unimplemented_none"), ""]
    if dfm.checks_not_implemented:
        for check in dfm.checks_not_implemented:
            lines.append(f"- `{check.rule_id}`: {check.message}")
    else:
        lines.append(t("quality.traceability_intro"))
    lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


@dataclass(frozen=True)
class TraceabilityRow:
    """One requirement row of the traceability report."""

    requirement: str
    text: str
    design_nodes: tuple[tuple[str, str], ...]
    rationale_records: tuple[tuple[str, str, tuple[str, ...]], ...]
    claims: tuple[tuple[str, str, str, object, bool], ...]


def _build_traceability(
    graph: DesignGraph,
    lanes: tuple[LaneEvidence, ...],
    rationale: RationaleDocument,
) -> tuple[tuple[TraceabilityRow, ...], tuple[str, ...], tuple[str, ...]]:
    """Join requirements to design nodes, rationale records, and claims."""
    dependents: dict[str, list[tuple[str, str]]] = {}
    for node in graph.nodes:
        for dep in node.depends_on:
            dependents.setdefault(dep, []).append((node.id, node.kind))
    records_by_requirement: dict[str, list[RationaleRecord]] = {}
    for record in rationale.records:
        for requirement in record.driving_requirements:
            records_by_requirement.setdefault(requirement, []).append(record)
    all_claims = [
        (lane.lane, claim)
        for lane in lanes
        for claim in lane.evidence.claims
    ]
    rows: list[TraceabilityRow] = []
    untraced: list[str] = []
    requirements = sorted(
        nodes_of_kind(graph, "requirement"), key=lambda node: node.id
    )
    for node in requirements:
        design_nodes = tuple(sorted(dependents.get(node.id, [])))
        records = tuple(
            sorted(

                    (
                        record.rationale_id,
                        record.decision_kind,
                        tuple(record.subject_nodes),
                    )
                    for record in records_by_requirement.get(node.id, [])

            )
        )
        subjects = {item[0] for item in design_nodes} | {
            subject for _, _, subject_nodes in records for subject in subject_nodes
        }
        claims = tuple(
            sorted(
                (
                    (lane, claim.subject_node, claim.property, claim.value, claim.verified)
                    for lane, claim in all_claims
                    if claim.subject_node in subjects
                )
            )
        )
        row = TraceabilityRow(
            requirement=node.id,
            text=text_attr(node, "text"),
            design_nodes=design_nodes,
            rationale_records=records,
            claims=tuple(
                (lane, subject, prop, value, verified)
                for lane, subject, prop, value, verified in claims
            ),
        )
        rows.append(row)
        if not records and not claims:
            untraced.append(node.id)
    no_requirement_records = tuple(
        sorted(
            record.rationale_id
            for record in rationale.records
            if not record.driving_requirements
        )
    )
    return tuple(rows), tuple(untraced), no_requirement_records


def _render_traceability(
    graph: DesignGraph,
    rows: tuple[TraceabilityRow, ...],
    untraced: tuple[str, ...],
    no_requirement_records: tuple[str, ...],
) -> str:
    """Render the traceability report Markdown body."""
    lines = [
        t("quality.traceability_title", graph_id=graph.graph_id),
        "",
        f"- Design Graph: `{graph.graph_id}`",
        f"- revision: `{graph.revision}`",
        "",
        t("quality.dependent_nodes_note"),
        "",
    ]
    for row in rows:
        lines += [
            f"## {row.requirement}",
            "",
            f"{row.text}",
            "",
            t("quality.rationale_heading"),
        ]
        if row.design_nodes:
            for node_id, kind in row.design_nodes:
                lines.append(f"- `{node_id}`（{kind}）")
        else:
            lines.append(t("quality.rationale_none"))
        lines += ["", t("quality.claims_heading")]
        if row.rationale_records:
            for rationale_id, decision_kind, subjects in row.rationale_records:
                lines.append(
                    t(
                        "quality.rationale_record_row",
                        rationale_id=rationale_id,
                        decision_kind=decision_kind,
                        subjects=", ".join(f"`{subject}`" for subject in subjects),
                    )
                )
        else:
            lines.append(t("quality.traceability_claims_header"))
        lines += ["", t("quality.claims_none")]
        if row.claims:
            lines += [
                t("quality.untraced_heading"),
                "|---|---|---|---|---|",
            ]
            for lane, subject, prop, value, verified in row.claims:
                lines.append(
                    f"| {lane} | `{subject}` | {prop} | {value} | {verified} |"
                )
        else:
            lines.append(t("quality.untraced_none"))
        lines.append("")
    lines += [t("quality.rationale_coverage_heading"), ""]
    if untraced:
        for requirement in untraced:
            lines.append(f"- `{requirement}`")
    else:
        lines.append(t("quality.all_records_traced"))
    lines += ["", t("quality.inspection_title_legacy"), ""]
    if no_requirement_records:
        lines.append(
            t(
                "quality.orphan_record_sentence",
                count=len(no_requirement_records),
            )
        )
        for rationale_id in no_requirement_records:
            lines.append(f"- `{rationale_id}`")
    else:
        lines.append(t("quality.traceability_title_legacy"))
    lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def build_quality_report(
    graph: DesignGraph,
    lanes: tuple[LaneEvidence, ...],
    coverages: tuple[tuple[Path, RationaleCoverageReport], ...],
    base_dir: Path,
    rationale: RationaleDocument,
    predicates: DesignPredicates,
    dfm: DfmReport,
    rows: tuple[TraceabilityRow, ...],
    untraced: tuple[str, ...],
    analyses: AnalysisBundle,
) -> dict[str, object]:
    """Build the machine-readable quality report body."""
    return {
        "schema_version": 1,
        "artifact_kind": "quality_report",
        "record_class": "L3",
        "pass_evidence": False,
        "graph_id": graph.graph_id,
        "target_revision": graph.revision,
        "evidence": [
            {
                "lane": lane.lane,
                "evidence_id": lane.evidence.evidence_id,
                "status": lane.evidence.status,
                "tool_name": lane.evidence.envelope.tool_name,
                "tool_version": lane.evidence.envelope.tool_version,
                "execution_context": lane.evidence.envelope.execution_context,
                "container_image_digest": lane.evidence.envelope.container_image_digest
                or "unknown",
                "source_revision": lane.evidence.envelope.source_revision or "unknown",
                "claims": [
                    {
                        "subject_node": claim.subject_node,
                        "property": claim.property,
                        "value": claim.value,
                        "verified": claim.verified,
                    }
                    for claim in lane.evidence.claims
                ],
            }
            for lane in lanes
        ],
        "design_predicates": [
            {
                "name": item.name,
                "evaluation_stage": item.evaluation_stage,
                "status": item.status,
                "detail": item.detail,
            }
            for item in predicates.predicates
        ],
        "dfm": {
            "status": dfm.status,
            "profile_id": dfm.profile_id,
            "findings": [
                {"rule_id": finding.rule_id, "message": finding.message}
                for finding in dfm.findings
            ],
            "unknowns": dfm.unknowns,
            "checks_not_implemented": [
                {"rule_id": check.rule_id, "reason": check.message}
                for check in dfm.checks_not_implemented
            ],
        },
        "rationale_coverage": [
            {
                "file": relative_path(path, base_dir),
                "status": report.status,
                "required_count": report.required_count,
                "covered_count": report.covered_count,
                "record_count": report.record_count,
                "missing": len(report.missing),
                "stale": len(report.stale),
                "unknown_provenance": len(report.unknown_provenance),
                "orphan": len(report.orphan),
                "untraceable": len(report.untraceable),
                "conflicting": len(report.conflicting),
                "unclassified": len(report.unclassified),
                "templated": len(report.templated),
                "generator_violations": len(report.generator_violations),
            }
            for path, report in coverages
        ],
        "traceability": [
            {
                "requirement": row.requirement,
                "text": row.text,
                "design_nodes": [
                    {"id": node_id, "kind": kind}
                    for node_id, kind in row.design_nodes
                ],
                "rationale_ids": [
                    rationale_id for rationale_id, _, _ in row.rationale_records
                ],
                "claims": [
                    {
                        "lane": lane,
                        "subject_node": subject,
                        "property": prop,
                        "value": value,
                        "verified": verified,
                    }
                    for lane, subject, prop, value, verified in row.claims
                ],
            }
            for row in rows
        ],
        "untraced_requirements": list(untraced),
        "analysis": [analysis_summary(item) for item in analyses.artifacts],
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument(
        "--evidence",
        type=Path,
        action="append",
        required=True,
        help="lane evidence JSON (evidence-<lane>.json); repeatable",
    )
    parser.add_argument(
        "--require-lane",
        dest="require_lane",
        action="append",
        default=None,
        help="lane name that must have an evidence file; repeatable",
    )
    parser.add_argument(
        "--rationale-coverage",
        dest="rationale_coverage",
        type=Path,
        action="append",
        required=True,
        help="rationale-coverage.json; repeatable",
    )
    parser.add_argument("--rationale", type=Path, required=True)
    parser.add_argument("--design-predicates", type=Path, required=True)
    parser.add_argument("--dfm-report", type=Path, required=True)
    parser.add_argument(
        "--analysis",
        type=Path,
        action="append",
        default=None,
        help="analysis result file or directory; repeatable",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    parser.add_argument("--lang", choices=("ja", "en"), default="ja")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    template = load_template(args.lang)
    _TEMPLATE.set(template)
    graph, graph_input = load_graph(args.graph)

    evidence_paths = {path.name: path for path in args.evidence}
    required_lanes = (
        tuple(args.require_lane)
        if args.require_lane
        else DEFAULT_REQUIRED_LANES
    )
    lanes: list[LaneEvidence] = []
    for lane in required_lanes:
        name = f"evidence-{lane}.json"
        path = evidence_paths.get(name)
        if path is None:
            raise DocumentGenerationError(
                f"required lane {lane!r} evidence {name} was not supplied"
            )
        lanes.append(load_evidence(path, graph, lane=lane))
    coverages = tuple(
        (path, load_coverage_report(path, graph))
        for path in args.rationale_coverage
    )
    rationale = load_rationale(args.rationale, graph)
    predicates = load_design_predicates(args.design_predicates, graph)
    if predicates.target_revision != graph.revision:
        raise DocumentGenerationError(
            f"design predicates {args.design_predicates} targets revision "
            f"{predicates.target_revision!r}, not {graph.revision!r}"
        )
    dfm = load_dfm_report(args.dfm_report, graph)
    if dfm.target_revision != graph.revision:
        raise DocumentGenerationError(
            f"DFM report {args.dfm_report} targets revision "
            f"{dfm.target_revision!r}, not {graph.revision!r}"
        )
    _guard_graph_references(graph, tuple(lanes), rationale)
    analyses = load_analysis_results(
        args.analysis or [],
        graph_id=graph.graph_id,
        revision=graph.revision,
    )
    rows, untraced, no_requirement_records = _build_traceability(
        graph, tuple(lanes), rationale
    )

    inputs: list[DocumentInput] = [
        graph_input,
        *analyses.inputs(),
        *(
            DocumentInput(path=path, content_hash=sha256_file(path))
            for path in args.evidence
        ),
        *(
            DocumentInput(path=path, content_hash=sha256_file(path))
            for path in args.rationale_coverage
        ),
        DocumentInput(path=args.rationale, content_hash=sha256_file(args.rationale)),
        DocumentInput(
            path=args.design_predicates,
            content_hash=sha256_file(args.design_predicates),
        ),
        DocumentInput(
            path=args.dfm_report, content_hash=sha256_file(args.dfm_report)
        ),
    ]

    outputs = (
        (
            "inspection_report",
            _render_inspection(
                graph,
                tuple(lanes),
                coverages,
                predicates,
                dfm,
                analyses,
                args.base_dir,
            ),
            DOCUMENT_NAME,
        ),
        (
            "traceability_report",
            _render_traceability(graph, rows, untraced, no_requirement_records),
            TRACEABILITY_DOCUMENT_NAME,
        ),
        (
            "quality_report_json",
            json.dumps(
                build_quality_report(
                    graph,
                    tuple(lanes),
                    coverages,
                    args.base_dir,
                    rationale,
                    predicates,
                    dfm,
                    rows,
                    untraced,
                    analyses,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            JSON_DOCUMENT_NAME,
        ),
    )
    for document_kind, body, document_name in outputs:
        document_path, provenance_path = write_document(
            document_kind=document_kind,
            body=body,
            out_dir=args.out_dir if args.lang == "ja" else args.out_dir / args.lang,
            document_name=document_name,
            template_id=f"acd-quality-report-{args.lang}-v1",
            generator=Path(__file__).resolve(),
            graph=graph,
            inputs=inputs,
            base_dir=args.base_dir,
            template=template,
            analysis_provenance=[
                {
                    "artifact_kind": artifact.artifact_kind,
                    "path": relative_path(artifact.path, args.base_dir),
                    "sha256": artifact.content_hash,
                }
                for artifact in analyses.artifacts
                if artifact.path is not None
            ],
        )
        print(f"generated {document_path}")
        print(f"provenance {provenance_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DocumentGenerationError as error:
        print(f"quality report generation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
