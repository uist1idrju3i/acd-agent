"""Evaluate whether a declared workaround is deterministically salvageable."""

from __future__ import annotations

import json
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from acd.core.electrical.electrical import GraphExtractionError, extract_electrical_lane
from acd.core.knowledge.design_predicates import (
    PredicateResult,
    evaluate_design_predicates,
)
from acd.core.knowledge.rationale import (
    RationaleRefreshError,
    refresh_rationale_document,
    subject_hash_for,
)
from acd.core.manufacturing.rework_diff import DerivedGraph, ReworkDiffError, apply_rework_diff
from acd.core.mechanical.mechanical_preflight import check_mechanical_preflight
from acd.core.runtime.fileio import read_json, write_json
from acd.core.runtime.gate_evidence_run import external_gate_run
from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import DesignGraph
from acd.schema.rationale import RationaleDocument, RationaleRecord
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


def derive_rationale_document(
    *,
    base_graph: DesignGraph,
    base_document: RationaleDocument,
    derived: DerivedGraph,
    diff: ReworkDiff,
) -> RationaleDocument:
    """Derive revision-matched rationale while invalidating changed subjects."""
    if (
        base_document.graph_id != base_graph.graph_id
        or base_document.revision != base_graph.revision
    ):
        raise SalvageGateError("base rationale document does not match base graph")
    base_node_ids = {node.id for node in base_graph.nodes}
    derived_node_ids = {node.id for node in derived.graph.nodes}
    retained: list[RationaleRecord] = []
    retained_subjects: set[tuple[str, str]] = set()
    for record in base_document.records:
        if any(node_id not in base_node_ids for node_id in record.subject_nodes):
            raise SalvageGateError(
                f"rationale subject is missing from base graph: {record.rationale_id}"
            )
        present = [node_id in derived_node_ids for node_id in record.subject_nodes]
        if not any(present):
            continue
        if not all(present):
            raise SalvageGateError(f"rationale subject is partially removed: {record.rationale_id}")
        try:
            subject_hash_for(base_graph, record.subject_nodes, record.subject_attrs)
            derived_hash = subject_hash_for(
                derived.graph, record.subject_nodes, record.subject_attrs
            )
        except KeyError as exc:
            raise SalvageGateError(f"rationale subject is invalid: {record.rationale_id}") from exc
        if record.subject_hash != derived_hash:
            continue
        retained.append(record)
        retained_subjects.update(
            (node_id, attr) for node_id in record.subject_nodes for attr in record.subject_attrs
        )

    retained_document = RationaleDocument(
        graph_id=derived.graph.graph_id,
        revision=derived.graph.revision,
        records=retained,
    )
    try:
        refreshed_base = refresh_rationale_document(derived.graph, retained_document)
    except RationaleRefreshError as exc:
        raise SalvageGateError(str(exc)) from exc

    for record in diff.rationale_records:
        subjects = {
            (node_id, attr) for node_id in record.subject_nodes for attr in record.subject_attrs
        }
        if not subjects.isdisjoint(retained_subjects):
            try:
                unchanged = subject_hash_for(
                    base_graph, record.subject_nodes, record.subject_attrs
                ) == subject_hash_for(derived.graph, record.subject_nodes, record.subject_attrs)
            except KeyError:
                unchanged = False
            if unchanged:
                raise SalvageGateError(
                    f"rationale record conflicts with existing coverage: {record.rationale_id}"
                )

    workaround_document = RationaleDocument(
        graph_id=derived.graph.graph_id,
        revision=derived.graph.revision,
        records=list(diff.rationale_records),
    )
    try:
        refreshed_workaround = refresh_rationale_document(derived.graph, workaround_document)
    except RationaleRefreshError as exc:
        raise SalvageGateError(str(exc)) from exc
    try:
        return RationaleDocument(
            graph_id=derived.graph.graph_id,
            revision=derived.graph.revision,
            records=sorted(
                [*refreshed_base.records, *refreshed_workaround.records],
                key=lambda record: record.rationale_id,
            ),
        )
    except ValueError as exc:
        raise SalvageGateError(str(exc)) from exc


def _load_rationale_document(fixture_dir: Path) -> RationaleDocument:
    path = fixture_dir / "rationale.json"
    try:
        return RationaleDocument.model_validate(read_json(path))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SalvageGateError(f"rationale document is invalid: {path}: {exc}") from exc


def _write_derived_rationale(
    document: RationaleDocument,
    *,
    output_dir: Path,
    base_document: RationaleDocument,
    derived: DerivedGraph,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = document.model_dump(mode="json")
    rationale_path = output_dir / "derived-rationale.json"
    write_json(rationale_path, payload, mkdir=False)
    provenance = {
        "artifact_kind": "rework_derived_rationale",
        "pass_evidence": False,
        "record_class": "L3",
        "base_rationale_sha256": canonical_json_sha256(base_document.model_dump(mode="json")),
        "derived_rationale_sha256": canonical_json_sha256(payload),
        "derived_graph_sha256": canonical_json_sha256(derived.graph.model_dump(mode="json")),
        "derived_revision": derived.derived_revision,
        "tool": "acd.core.manufacturing.salvage_gate",
        "acd_version": "0.0.2",
    }
    write_json(output_dir / "derived-rationale.provenance.json", provenance, mkdir=False)


@contextmanager
def _derived_fixture(
    document: RationaleDocument,
    *,
    output_dir: Path | None,
    base_document: RationaleDocument,
    derived: DerivedGraph,
) -> Generator[Path, None, None]:
    if output_dir is not None:
        derived_fixture_dir = output_dir / "derived-fixture"
        derived_fixture_dir.mkdir(parents=True, exist_ok=True)
        _write_derived_rationale(
            document,
            output_dir=output_dir,
            base_document=base_document,
            derived=derived,
        )
        (derived_fixture_dir / "rationale.json").write_text(
            document.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        yield derived_fixture_dir
        return
    with TemporaryDirectory(prefix="acd-salvage-") as temporary:
        derived_fixture_dir = Path(temporary)
        (derived_fixture_dir / "rationale.json").write_text(
            document.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        yield derived_fixture_dir


def _aggregate_status(statuses: list[str]) -> GateStatus:
    if "unknown" in statuses:
        return "unknown"
    if "fail" in statuses:
        return "fail"
    return "pass"


def _validate_dfa(diff: ReworkDiff, dfa: ReworkDfaDeclaration) -> list[str]:
    if (
        dfa.workaround_id != diff.workaround_id
        or dfa.graph_id != diff.graph_id
        or dfa.base_revision != diff.base_revision
    ):
        raise SalvageGateError("DFA declaration does not match the rework diff")
    expected = set(range(len(diff.operations)))
    actual = {assessment.operation_index for assessment in dfa.assessments}
    if actual != expected:
        raise SalvageGateError("DFA assessments must cover every rework operation exactly once")
    by_index = {assessment.operation_index: assessment for assessment in dfa.assessments}
    blockers: list[str] = []
    for index, operation in enumerate(diff.operations):
        assessment = by_index[index]
        if assessment.tool_access != "yes":
            blockers.append(f"operation {index}: tool access is {assessment.tool_access}")
        if assessment.hand_solderable in {"no", "unknown"}:
            blockers.append(
                f"operation {index}: hand solderability is {assessment.hand_solderable}"
            )
        if assessment.hand_solderable == "not_applicable" and not isinstance(
            operation, ReworkMechanical
        ):
            blockers.append(f"operation {index}: hand solderability is not applicable")
        if assessment.enclosure_disassembly in {"destructive", "unknown"}:
            blockers.append(
                f"operation {index}: enclosure disassembly is {assessment.enclosure_disassembly}"
            )
    return blockers


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
    output_dir: Path | None = None,
) -> tuple[DerivedGraph, SalvageGateResult]:
    """Apply a workaround and evaluate all deterministic salvage conditions."""
    try:
        derived = apply_rework_diff(base_graph, diff)
    except ReworkDiffError as exc:
        raise SalvageGateError(f"workaround derivation failed: {exc}") from exc

    base_rationale = _load_rationale_document(fixture_dir)
    derived_rationale = derive_rationale_document(
        base_graph=base_graph,
        base_document=base_rationale,
        derived=derived,
        diff=diff,
    )
    dfa_blockers = _validate_dfa(diff, dfa)
    gate_runs: list[GateRun] = []
    reasons: list[str] = []

    with _derived_fixture(
        derived_rationale,
        output_dir=output_dir,
        base_document=base_rationale,
        derived=derived,
    ) as derived_fixture_dir:
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
                    detail=(
                        "design predicates were not evaluated because the electrical lane failed"
                    ),
                )
            )
        else:
            try:
                predicates: tuple[PredicateResult, ...] = evaluate_design_predicates(
                    derived.graph, lane, derived_fixture_dir
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

        preflight = check_mechanical_preflight(derived.graph, derived_fixture_dir)
        gate_runs.append(
            GateRun(
                gate="mechanical_preflight",
                status=preflight.status,
                source="computed",
                detail=(
                    "mechanical preflight passed"
                    if preflight.status == "pass"
                    else "; ".join(
                        f"{finding.code}: {finding.detail}" for finding in preflight.findings
                    )
                ),
            ),
        )
        gate_runs.extend(
            external_gate_run(
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
