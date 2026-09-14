"""Evaluate whether a declared workaround is deterministically salvageable."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

from acd.core.rework_diff import DerivedGraph, ReworkDiffError, apply_rework_diff
from acd.schema.design_graph import DesignGraph
from acd.schema.rework_diff import ReworkDiff, ReworkMechanical
from acd.schema.salvage import (
    GateRun,
    ReworkDfaDeclaration,
    SafetyApproval,
    SalvageGateResult,
)


class SalvageGateError(ValueError):
    """Raised when salvageability inputs cannot be evaluated fail-closed."""


GateStatus = Literal["pass", "fail", "unknown", "not_applicable"]
ApprovalStatus = Literal["not_required", "approved", "missing", "invalid"]


def _aggregate_status(statuses: list[str]) -> GateStatus:
    if "unknown" in statuses:
        return "unknown"
    if "fail" in statuses:
        return "fail"
    return "pass"


def _validate_dfa(
    diff: ReworkDiff, dfa: ReworkDfaDeclaration
) -> list[str]:
    if (
        dfa.workaround_id != diff.workaround_id
        or dfa.graph_id != diff.graph_id
        or dfa.base_revision != diff.base_revision
    ):
        raise SalvageGateError("DFA declaration does not match the rework diff")
    expected = set(range(len(diff.operations)))
    actual = {assessment.operation_index for assessment in dfa.assessments}
    if actual != expected:
        raise SalvageGateError(
            "DFA assessments must cover every rework operation exactly once"
        )
    by_index = {assessment.operation_index: assessment for assessment in dfa.assessments}
    blockers: list[str] = []
    for index, operation in enumerate(diff.operations):
        assessment = by_index[index]
        if assessment.tool_access != "yes":
            blockers.append(f"operation {index}: tool access is {assessment.tool_access}")
        if assessment.hand_solderable in {"no", "unknown"}:
            blockers.append(
                f"operation {index}: hand solderability is "
                f"{assessment.hand_solderable}"
            )
        if assessment.hand_solderable == "not_applicable" and not isinstance(
            operation, ReworkMechanical
        ):
            blockers.append(f"operation {index}: hand solderability is not applicable")
        if assessment.enclosure_disassembly in {"destructive", "unknown"}:
            blockers.append(
                f"operation {index}: enclosure disassembly is "
                f"{assessment.enclosure_disassembly}"
            )
    return blockers


def _external_gate_run(
    gate: str, path: Path | None, revision: str
) -> GateRun:
    if path is None:
        return GateRun(
            gate=gate,
            status="unknown",
            source="missing",
            detail=f"{gate} evidence is missing",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return GateRun(
            gate=gate,
            status="unknown",
            source="evidence_file",
            detail=f"{gate} evidence could not be read: {exc}",
            evidence_path=str(path),
        )
    if not isinstance(payload, dict):
        return GateRun(
            gate=gate,
            status="unknown",
            source="evidence_file",
            detail=f"{gate} evidence is not an object",
            evidence_path=str(path),
        )
    body = cast(dict[str, Any], payload)
    if body.get("target_revision") != revision:
        return GateRun(
            gate=gate,
            status="unknown",
            source="evidence_file",
            detail=f"{gate} evidence revision does not match {revision}",
            evidence_path=str(path),
        )
    if body.get("gate") != gate:
        return GateRun(
            gate=gate,
            status="unknown",
            source="evidence_file",
            detail=f"{gate} evidence declares a different gate",
            evidence_path=str(path),
        )
    status = body.get("status")
    if status not in {"pass", "fail", "unknown", "not_applicable"}:
        return GateRun(
            gate=gate,
            status="unknown",
            source="evidence_file",
            detail=f"{gate} evidence has an invalid status",
            evidence_path=str(path),
        )
    message = body.get("message")
    detail = message if isinstance(message, str) and message else f"{gate} evidence loaded"
    return GateRun(
        gate=gate,
        status=cast(GateStatus, status),
        source="evidence_file",
        detail=detail,
        evidence_path=str(path),
    )


def _result(
    *,
    diff: ReworkDiff,
    derived: DerivedGraph,
    gate_runs: list[GateRun],
    dfa_blockers: list[str],
    approval_status: ApprovalStatus,
    reasons: list[str],
) -> SalvageGateResult:
    if reasons or dfa_blockers or approval_status not in {"not_required", "approved"}:
        verdict = "not_salvageable"
    elif diff.degraded_functions:
        verdict = "constrained_salvage"
    else:
        verdict = "salvageable"
    return SalvageGateResult(
        workaround_id=diff.workaround_id,
        graph_id=diff.graph_id,
        base_revision=diff.base_revision,
        derived_revision=derived.derived_revision,
        verdict=verdict,
        gate_runs=sorted(gate_runs, key=lambda run: run.gate),
        dfa_blockers=dfa_blockers,
        safety_boundary_touched=derived.safety_boundary_touched,
        approval_status=approval_status,
        degraded_functions=diff.degraded_functions,
        reasons=[*reasons, *dfa_blockers],
    )


def evaluate_salvage(
    *,
    base_graph: DesignGraph,
    diff: ReworkDiff,
    dfa: ReworkDfaDeclaration,
    approval: SafetyApproval | None,
    fixture_dir: Path,
    external_evidence: Mapping[str, Path],
) -> tuple[DerivedGraph, SalvageGateResult]:
    """Apply a workaround and evaluate all deterministic salvage conditions."""
    from acd.core.design_predicates import evaluate_design_predicates
    from acd.core.electrical import GraphExtractionError, extract_electrical_lane
    from acd.core.mechanical_preflight import check_mechanical_preflight

    try:
        derived = apply_rework_diff(base_graph, diff)
    except ReworkDiffError as exc:
        raise SalvageGateError(f"workaround derivation failed: {exc}") from exc

    dfa_blockers = _validate_dfa(diff, dfa)
    gate_runs: list[GateRun] = []
    reasons: list[str] = []

    try:
        lane = extract_electrical_lane(derived.graph)
        gate_runs.append(
            GateRun(
                gate="electrical_lane",
                status="pass",
                source="computed",
                detail="electrical lane extraction passed",
            )
        )
    except GraphExtractionError as exc:
        lane = None
        gate_runs.append(
            GateRun(
                gate="electrical_lane",
                status="fail",
                source="computed",
                detail=f"electrical lane extraction failed: {exc}",
            )
        )

    if lane is None:
        gate_runs.append(
            GateRun(
                gate="design_predicates",
                status="unknown",
                source="computed",
                detail="design predicates were not evaluated because the electrical lane failed",
            )
        )
    else:
        try:
            predicates = evaluate_design_predicates(
                derived.graph, lane, fixture_dir
            )
            statuses = [predicate.status for predicate in predicates]
            status = _aggregate_status(statuses)
            detail = "; ".join(
                f"{predicate.name}={predicate.status}: {predicate.detail}"
                for predicate in predicates
            )
            gate_runs.append(
                GateRun(
                    gate="design_predicates",
                    status=status,
                    source="computed",
                    detail=detail,
                )
            )
        except Exception as exc:
            gate_runs.append(
                GateRun(
                    gate="design_predicates",
                    status="unknown",
                    source="computed",
                    detail=f"design predicates could not be evaluated: {exc}",
                )
            )

    preflight = check_mechanical_preflight(derived.graph, fixture_dir)
    gate_runs.append(
        GateRun(
            gate="mechanical_preflight",
            status=preflight.status,
            source="computed",
            detail=(
                "mechanical preflight passed"
                if preflight.status == "pass"
                else "; ".join(finding.detail for finding in preflight.findings)
            ),
        )
    )
    gate_runs.extend(
        _external_gate_run(
            gate,
            external_evidence.get(gate),
            derived.derived_revision,
        )
        for gate in ("erc", "drc")
    )

    for run in gate_runs:
        if run.status not in {"pass", "not_applicable"}:
            reasons.append(f"{run.gate}: {run.detail}")

    approval_status: ApprovalStatus
    approval_status: ApprovalStatus
    if derived.safety_boundary_touched:
        if approval is None:
            approval_status = "missing"
            reasons.append("safety boundary approval is missing")
        elif (
            approval.workaround_id != diff.workaround_id
            or approval.graph_id != diff.graph_id
            or approval.derived_revision != derived.derived_revision
        ):
            approval_status = "invalid"
            reasons.append("safety boundary approval does not match the derived graph")
        else:
            approval_status = "approved"
    else:
        approval_status = "not_required"

    result = _result(
        diff=diff,
        derived=derived,
        gate_runs=gate_runs,
        dfa_blockers=dfa_blockers,
        approval_status=approval_status,
        reasons=reasons,
    )
    return derived, result


__all__ = ["SalvageGateError", "evaluate_salvage"]
