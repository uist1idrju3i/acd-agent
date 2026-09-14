# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@ca92d896f2b7888831a6b6edafdc97fb64772c68",
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
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from acd.schema.design_graph import DesignGraph
from acd.schema.evidence import Evidence
from acd.schema.rationale import (
    RationaleCoverageReport,
    RationaleDocument,
    RationaleRecord,
)
from doc_inputs import (
    DocumentGenerationError,
    DocumentInput,
    load_graph,
    nodes_of_kind,
    sha256_file,
    text_attr,
    write_document,
)

TEMPLATE_ID = "acd-quality-report-ja-v1"
DOCUMENT_NAME = "inspection-report.md"
TRACEABILITY_DOCUMENT_NAME = "traceability-report.md"
JSON_DOCUMENT_NAME = "quality-report.json"

DEFAULT_REQUIRED_LANES = ("electrical", "mechanical", "firmware")


@dataclass(frozen=True)
class LaneEvidence:
    """One lane's authoritative Evidence plus its lane name."""

    lane: str
    evidence: Evidence


@dataclass(frozen=True)
class PredicateObservation:
    """One design-predicate observation row."""

    name: str
    evaluation_stage: str
    status: str
    detail: str


@dataclass(frozen=True)
class DesignPredicates:
    """Parsed design-predicates gate observation."""

    target_revision: str
    status: str
    predicates: tuple[PredicateObservation, ...]


@dataclass(frozen=True)
class DfmFinding:
    """One DFM finding row."""

    rule_id: str
    message: str


@dataclass(frozen=True)
class DfmReport:
    """Parsed DFM report."""

    target_revision: str
    status: str
    profile_id: str
    findings: tuple[DfmFinding, ...]
    unknowns: dict[str, str]
    checks_not_implemented: tuple[DfmFinding, ...]


def _require_object(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise DocumentGenerationError(f"field {field!r} is not an object")
    return cast(dict[str, object], value)


def _require_str(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DocumentGenerationError(f"field {field!r} is missing or not text")
    return value


def _require_list(value: object, *, field: str) -> list[object]:
    if not isinstance(value, list):
        raise DocumentGenerationError(f"field {field!r} is not a list")
    return cast(list[object], value)


def _load_json_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DocumentGenerationError(f"{label} {path} is not valid: {exc}") from exc
    return _require_object(payload, field=label)


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


def load_design_predicates(path: Path, graph: DesignGraph) -> DesignPredicates:
    """Parse the design-predicates gate observation file."""
    data = _load_json_object(path, label="design predicates")
    observation = _require_object(data.get("observation"), field="observation")
    predicates = tuple(
        PredicateObservation(
            name=_require_str(item.get("name"), field="predicates[].name"),
            evaluation_stage=_require_str(
                item.get("evaluation_stage"), field="predicates[].evaluation_stage"
            ),
            status=_require_str(item.get("status"), field="predicates[].status"),
            detail=_require_str(item.get("detail"), field="predicates[].detail"),
        )
        for item in (
            _require_object(entry, field="predicates[]")
            for entry in _require_list(
                observation.get("predicates"), field="observation.predicates"
            )
        )
    )
    return DesignPredicates(
        target_revision=_require_str(
            data.get("target_revision"), field="target_revision"
        ),
        status=_require_str(data.get("status"), field="status"),
        predicates=predicates,
    )


def load_dfm_report(path: Path, graph: DesignGraph) -> DfmReport:
    """Parse the DFM report file."""
    data = _load_json_object(path, label="DFM report")
    findings = tuple(
        DfmFinding(
            rule_id=_require_str(item.get("rule_id"), field="findings[].rule_id"),
            message=_require_str(item.get("message"), field="findings[].message"),
        )
        for item in (
            _require_object(entry, field="findings[]")
            for entry in _require_list(data.get("findings"), field="findings")
        )
    )
    unknowns_raw = _require_object(data.get("unknowns"), field="unknowns")
    unknowns = {
        key: _require_str(
            _require_object(value, field=f"unknowns.{key}").get("reason"),
            field=f"unknowns.{key}.reason",
        )
        for key, value in unknowns_raw.items()
    }
    checks_not_implemented = tuple(
        DfmFinding(
            rule_id=_require_str(
                item.get("rule_id"), field="checks_not_implemented[].rule_id"
            ),
            message=_require_str(
                item.get("reason"), field="checks_not_implemented[].reason"
            ),
        )
        for item in (
            _require_object(entry, field="checks_not_implemented[]")
            for entry in _require_list(
                data.get("checks_not_implemented"), field="checks_not_implemented"
            )
        )
    )
    return DfmReport(
        target_revision=_require_str(
            data.get("target_revision"), field="target_revision"
        ),
        status=_require_str(data.get("status"), field="status"),
        profile_id=_require_str(data.get("profile_id"), field="profile_id"),
        findings=findings,
        unknowns=unknowns,
        checks_not_implemented=checks_not_implemented,
    )


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
        "| 対象ノード | 属性 | 値 | verified |",
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
) -> str:
    """Render the inspection report (検査成績書) Markdown body."""
    lane_map = {lane.lane: lane for lane in lanes}
    lines = [
        f"# 検査成績書: {graph.graph_id}",
        "",
        f"- Design Graph: `{graph.graph_id}`",
        f"- revision: `{graph.revision}`",
        "",
        "この文書はauthoritative Evidenceと決定論的観測から生成されたL3観測であり、"
        "合否判定のEvidenceではない。",
        "",
        "## Evidence一覧",
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
    lines += ["", "## ゲート結果", ""]

    if "electrical" in lane_map:
        lines += ["### 電気", "", *_claims_table(lane_map["electrical"]), ""]
    lines += ["### 設計predicate", "", "| name | stage | status | detail |", "|---|---|---|---|"]
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
        f"- findings: {len(dfm.findings)} 件",
    ]
    for finding in dfm.findings:
        lines.append(f"  - {finding.rule_id}: {finding.message}")
    if dfm.unknowns:
        lines.append("- unknowns:")
        for key in sorted(dfm.unknowns):
            lines.append(f"  - `{key}`: {dfm.unknowns[key]}")
    lines.append("")
    if "mechanical" in lane_map:
        lines += ["### 機械", "", *_claims_table(lane_map["mechanical"]), ""]
    if "firmware" in lane_map:
        lines += ["### FW", "", *_claims_table(lane_map["firmware"])]
        if any(
            claim.property == "measurement_class" and claim.value == "virtual"
            for claim in lane_map["firmware"].evidence.claims
        ):
            lines.append(
                "\n`measurement_class: virtual`はQEMU上の仮想検証であり、"
                "実機Evidenceではない。"
            )
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
            f"| `{path.name}` | {report.status} | {report.required_count} "
            f"| {report.covered_count} | {report.record_count} "
            f"| {len(report.missing)} | {len(report.stale)} "
            f"| {len(report.unknown_provenance)} | {len(report.orphan)} "
            f"| {len(report.untraceable)} | {len(report.conflicting)} "
            f"| {len(report.unclassified)} | {len(report.templated)} "
            f"| {len(report.generator_violations)} |"
        )
    lines += ["", "## 既知の未実装チェック", ""]
    if dfm.checks_not_implemented:
        for check in dfm.checks_not_implemented:
            lines.append(f"- `{check.rule_id}`: {check.message}")
    else:
        lines.append("なし。")
    lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


@dataclass(frozen=True)
class TraceabilityRow:
    """One requirement row of the traceability report."""

    requirement: str
    text: str
    design_nodes: tuple[tuple[str, str], ...]
    rationale_records: tuple[tuple[str, str, tuple[str, ...]], ...]
    claims: tuple[tuple[str, str, object, bool], ...]


def _build_traceability(
    graph: DesignGraph,
    lanes: tuple[LaneEvidence, ...],
    rationale: RationaleDocument,
) -> tuple[tuple[TraceabilityRow, ...], tuple[str, ...], tuple[str, ...]]:
    """Join requirements to design nodes, rationale records, and claims."""
    dependents: dict[str, list[tuple[str, str]]] = {}
    for node in graph.nodes:
        depends = node.attrs.get("depends_on")
        if not isinstance(depends, list):
            depends = []
        for dep in cast(list[object], depends):
            if not isinstance(dep, str):
                raise DocumentGenerationError(
                    f"depends_on of node {node.id!r} contains a non-string entry"
                )
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
                (lane, prop, value, verified) for lane, _, prop, value, verified in claims
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
        f"# トレーサビリティ報告書: {graph.graph_id}",
        "",
        f"- Design Graph: `{graph.graph_id}`",
        f"- revision: `{graph.revision}`",
        "",
        "この文書はgraph・rationale record・authoritative Evidenceから生成された"
        "L3観測であり、合否判定のEvidenceではない。",
        "",
    ]
    for row in rows:
        lines += [
            f"## {row.requirement}",
            "",
            f"{row.text}",
            "",
            "依存する設計ノード:",
        ]
        if row.design_nodes:
            for node_id, kind in row.design_nodes:
                lines.append(f"- `{node_id}`（{kind}）")
        else:
            lines.append("- なし")
        lines += ["", "根拠record:"]
        if row.rationale_records:
            for rationale_id, decision_kind, subjects in row.rationale_records:
                lines.append(
                    f"- `{rationale_id}`（{decision_kind}、対象: "
                    + ", ".join(f"`{subject}`" for subject in subjects)
                    + "）"
                )
        else:
            lines.append("- なし")
        lines += ["", "関連Evidence claim:"]
        if row.claims:
            lines += ["| lane | 属性 | 値 | verified |", "|---|---|---|---|"]
            for lane, prop, value, verified in row.claims:
                lines.append(f"| {lane} | {prop} | {value} | {verified} |")
        else:
            lines.append("- なし")
        lines.append("")
    lines += ["## 未追跡の要求", ""]
    if untraced:
        for requirement in untraced:
            lines.append(f"- `{requirement}`")
    else:
        lines.append("なし。")
    lines += ["", "## 根拠recordの被参照状況", ""]
    if no_requirement_records:
        lines.append(
            f"要求を持たない根拠record: {len(no_requirement_records)} 件"
        )
        for rationale_id in no_requirement_records:
            lines.append(f"- `{rationale_id}`")
    else:
        lines.append("すべての根拠recordが要求を参照する。")
    lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def build_quality_report(
    graph: DesignGraph,
    lanes: tuple[LaneEvidence, ...],
    coverages: tuple[tuple[Path, RationaleCoverageReport], ...],
    rationale: RationaleDocument,
    predicates: DesignPredicates,
    dfm: DfmReport,
    rows: tuple[TraceabilityRow, ...],
    untraced: tuple[str, ...],
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
                "file": path.name,
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
                    {"lane": lane, "property": prop, "value": value, "verified": verified}
                    for lane, prop, value, verified in row.claims
                ],
            }
            for row in rows
        ],
        "untraced_requirements": list(untraced),
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
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
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
    rows, untraced, no_requirement_records = _build_traceability(
        graph, tuple(lanes), rationale
    )

    inputs: list[DocumentInput] = [
        graph_input,
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
            _render_inspection(graph, tuple(lanes), coverages, predicates, dfm),
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
                    rationale,
                    predicates,
                    dfm,
                    rows,
                    untraced,
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
            out_dir=args.out_dir,
            document_name=document_name,
            template_id=TEMPLATE_ID,
            generator=Path(__file__).resolve(),
            graph=graph,
            inputs=inputs,
            base_dir=args.base_dir,
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
