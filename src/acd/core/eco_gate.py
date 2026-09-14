"""Deterministic close gate for engineering-change records."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from acd.core.defect_records import check_defect_records
from acd.core.gate_evidence_run import external_gate_run
from acd.core.graph_diff import GraphDiffError, build_graph_diff
from acd.schema.defect_record import DefectDocument
from acd.schema.design_graph import DesignGraph
from acd.schema.eco import (
    EcoCheckResult,
    EcoDocument,
    EcoRecord,
)
from acd.schema.graph_diff import GraphDiff
from acd.schema.salvage import GateRun


class EcoGateError(ValueError):
    """Raised when ECO close-gate inputs cannot be evaluated."""


MINIMUM_GATES: dict[str, tuple[str, ...]] = {
    "electrical": ("erc", "design_predicates", "drc"),
    "mechanical": ("mechanical_preflight", "mechanical_interference"),
    "firmware": ("firmware_evidence",),
}
_ALL_LANES = frozenset(MINIMUM_GATES)
ImpactStatus = Literal["matched", "mismatched", "unknown"]
HorizontalStatus = Literal["complete", "incomplete", "unknown"]


def _lanes_for_kind(kind: str) -> frozenset[str]:
    if kind.startswith("electrical."):
        return frozenset({"electrical"})
    if kind.startswith("mechanical."):
        return frozenset({"mechanical"})
    if kind.startswith("firmware."):
        return frozenset({"firmware"})
    if (
        kind.startswith(("safety.", "fab.", "design."))
        or kind in {"requirement", "safety", "fab", "design"}
    ):
        return _ALL_LANES
    return _ALL_LANES


def _changed_node_kinds(
    from_graph: DesignGraph, to_graph: DesignGraph, diff: GraphDiff
) -> list[str]:
    from_nodes = {node.id: node for node in from_graph.nodes}
    to_nodes = {node.id: node for node in to_graph.nodes}
    kinds: list[str] = []
    for node_id in diff.nodes_added:
        kinds.append(to_nodes[node_id].kind)
    for node_id in diff.nodes_removed:
        kinds.append(from_nodes[node_id].kind)
    for node in diff.nodes_changed:
        kinds.append(to_nodes[node.id].kind)
    return kinds


def _impact_status(
    record: EcoRecord,
    from_graph: DesignGraph,
    to_graph: DesignGraph,
    diff: GraphDiff,
    reasons: list[str],
) -> tuple[ImpactStatus, frozenset[str]]:
    if diff.status == "unknown":
        reasons.append(f"graph diff is unknown: {diff.reason}")
        return "unknown", frozenset()
    actual = {
        "nodes_added": set(diff.nodes_added),
        "nodes_removed": set(diff.nodes_removed),
        "nodes_changed": {node.id for node in diff.nodes_changed},
    }
    declared = {
        "nodes_added": set(record.impact.nodes_added),
        "nodes_removed": set(record.impact.nodes_removed),
        "nodes_changed": set(record.impact.nodes_changed),
    }
    matched = True
    for label in actual:
        missing = sorted(actual[label] - declared[label])
        extra = sorted(declared[label] - actual[label])
        if missing:
            matched = False
            reasons.append(f"impact {label} is missing: {', '.join(missing)}")
        if extra:
            matched = False
            reasons.append(f"impact {label} has extras: {', '.join(extra)}")
    derived_lanes = frozenset(
        lane
        for kind in _changed_node_kinds(from_graph, to_graph, diff)
        for lane in _lanes_for_kind(kind)
    )
    missing_lanes = sorted(derived_lanes - set(record.impact.lanes))
    if missing_lanes:
        matched = False
        reasons.append(
            "impact lanes do not cover graph changes: " + ", ".join(missing_lanes)
        )
    return ("matched" if matched else "mismatched"), derived_lanes


def _gate_runs(
    record: EcoRecord,
    derived_lanes: frozenset[str],
    evidence_dir: Path,
    reasons: list[str],
) -> list[GateRun]:
    required = {
        gate
        for lane in derived_lanes
        for gate in MINIMUM_GATES[lane]
    }
    declared = {item.gate for item in record.reverification}
    for gate in sorted(required - declared):
        reasons.append(f"required gate is not declared: {gate}")
    runs = [
        external_gate_run(
            item.gate,
            evidence_dir / f"{item.gate}.json",
            record.to_revision,
        )
        for item in record.reverification
    ]
    for run in runs:
        if run.status not in {"pass", "not_applicable"}:
            reasons.append(f"{run.gate}: {run.detail}")
    return sorted(runs, key=lambda run: run.gate)


def _horizontal_status(
    record: EcoRecord,
    eco_document: EcoDocument,
    defects: DefectDocument,
    from_graph: DesignGraph,
    impact_nodes: frozenset[str],
    reasons: list[str],
) -> HorizontalStatus:
    target_ids = {
        reason.ref for reason in record.reasons if reason.kind == "defect"
    }
    if not target_ids:
        if record.horizontal_dispositions:
            reasons.append(
                "horizontal dispositions require a referenced defect reason"
            )
            return "incomplete"
        return "complete"
    by_id = {item.defect_id: item for item in defects.records}
    missing_defects = sorted(target_ids - set(by_id))
    if missing_defects:
        reasons.append(
            "ECO references unknown defects: " + ", ".join(missing_defects)
        )
        return "incomplete"
    defect_check = check_defect_records(from_graph, defects)
    target_findings = [
        finding
        for finding in defect_check.findings
        if finding.defect_id in target_ids
    ]
    if any(finding.code == "horizontal_unsearched" for finding in target_findings):
        reasons.extend(
            finding.message
            for finding in target_findings
            if finding.code == "horizontal_unsearched"
        )
        return "unknown"
    if target_findings:
        reasons.extend(finding.message for finding in target_findings)
        return "incomplete"

    dispositions = {
        (item.defect_id, item.node_id): item
        for item in record.horizontal_dispositions
    }
    expected: set[tuple[str, str]] = set()
    for defect_id in sorted(target_ids):
        defect = by_id[defect_id]
        for scope in defect.horizontal_scopes:
            if scope.search_status == "searched":
                expected.update(
                    (defect_id, node_id) for node_id in scope.matched_node_ids
                )
    missing = sorted(expected - set(dispositions))
    if missing:
        reasons.append(
            "horizontal dispositions are missing: "
            + ", ".join(f"{defect}:{node}" for defect, node in missing)
        )
    extra = sorted(set(dispositions) - expected)
    if extra:
        reasons.append(
            "horizontal dispositions are extra: "
            + ", ".join(f"{defect}:{node}" for defect, node in extra)
        )
    eco_ids = {eco.eco_id for eco in eco_document.ecos}
    status = "complete"
    if missing or extra:
        status = "incomplete"
    for key, disposition in dispositions.items():
        if key[0] not in target_ids:
            continue
        if disposition.disposition == "fixed_in_eco" and disposition.node_id not in impact_nodes:
            reasons.append(
                f"fixed_in_eco node is outside ECO impact: {disposition.node_id}"
            )
            status = "incomplete"
        if (
            disposition.disposition == "deferred"
            and disposition.deferred_to not in eco_ids
        ):
            reasons.append(
                f"deferred ECO is not in the document: {disposition.deferred_to}"
            )
            status = "incomplete"
    return status


def evaluate_eco(
    *,
    eco_document: EcoDocument,
    eco_id: str,
    from_graph: DesignGraph,
    to_graph: DesignGraph,
    defects: DefectDocument,
    evidence_dir: Path,
) -> EcoCheckResult:
    """Evaluate whether one ECO can be closed."""
    try:
        record = next(eco for eco in eco_document.ecos if eco.eco_id == eco_id)
    except StopIteration as exc:
        raise EcoGateError(f"ECO ID is not present: {eco_id}") from exc

    reasons: list[str] = []
    if from_graph.graph_id != to_graph.graph_id:
        reasons.append("from/to graphs have different graph IDs")
    if record.graph_id != from_graph.graph_id or record.graph_id != to_graph.graph_id:
        reasons.append("ECO graph_id does not match both graphs")
    if record.from_revision != from_graph.revision:
        reasons.append("ECO from_revision does not match from graph")
    if record.to_revision != to_graph.revision:
        reasons.append("ECO to_revision does not match to graph")

    impact_status: ImpactStatus = "unknown"
    derived_lanes = frozenset[str]()
    try:
        diff = build_graph_diff(from_graph, to_graph)
    except GraphDiffError as exc:
        diff = None
        reasons.append(f"graph diff could not be computed: {exc}")
    if diff is not None:
        if diff.status == "unknown":
            reasons.append(f"graph diff is unknown: {diff.reason}")
        else:
            impact_status, derived_lanes = _impact_status(
                record, from_graph, to_graph, diff, reasons
            )
    gate_runs = _gate_runs(record, derived_lanes, evidence_dir, reasons)
    impact_nodes = frozenset(
        record.impact.nodes_added
        + record.impact.nodes_removed
        + record.impact.nodes_changed
    )
    horizontal_status: HorizontalStatus = _horizontal_status(
        record,
        eco_document,
        defects,
        from_graph,
        impact_nodes,
        reasons,
    )
    verdict = "not_closable" if reasons else "closable"
    return EcoCheckResult(
        verdict=verdict,
        eco_id=record.eco_id,
        from_revision=record.from_revision,
        to_revision=record.to_revision,
        impact_status=impact_status,
        gate_runs=gate_runs,
        horizontal_status=horizontal_status,
        reasons=reasons,
        retires_workaround_ids=record.retires_workaround_ids,
    )


__all__ = ["MINIMUM_GATES", "EcoGateError", "evaluate_eco"]
