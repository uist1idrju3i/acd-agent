# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@13fcb5cc5edba6b90f6e7ff28944b440d64c2d8e",
# ]
# ///
"""Plan and evaluate fail-closed workaround candidates."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Literal

from acd.core.defect_records import (
    DefectRecordError,
    LoadedDefectDocument,
    check_defect_records,
    load_defect_document,
)
from acd.core.rework_diff import load_rework_diff, safety_related_node_ids, write_derived_graph
from acd.core.salvage_gate import SalvageGateError, evaluate_salvage
from acd.schema.defect_record import DefectDocument, DefectRecord
from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.rework_diff import (
    FirmwareChange,
    ReworkCut,
    ReworkDiff,
    ReworkOperation,
    ReworkReplace,
)
from acd.schema.salvage import ReworkDfaDeclaration, SafetyApproval
from acd.schema.workaround import (
    SkillProvenance,
    WorkaroundCandidate,
    WorkaroundEvaluation,
    WorkaroundProposalSet,
    WorkaroundStrategy,
)


class WorkaroundError(ValueError):
    """Raised when workaround inputs cannot be safely processed."""


STRATEGIES = ("firmware_only", "rework_only", "combined")


def _sha256_file(path: Path) -> str:
    try:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    except OSError as exc:
        raise WorkaroundError(f"cannot read {path}: {exc}") from exc


def _load_graph(path: Path) -> DesignGraph:
    try:
        return DesignGraph.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise WorkaroundError(f"design graph is invalid: {path}: {exc}") from exc


def _load_defects(path: Path) -> LoadedDefectDocument:
    try:
        return load_defect_document(path)
    except DefectRecordError as exc:
        raise WorkaroundError(str(exc)) from exc


def _provenance(graph_path: Path, defects_path: Path) -> SkillProvenance:
    try:
        acd_version = importlib.metadata.version("acd")
    except importlib.metadata.PackageNotFoundError:
        acd_version = "0.0.2"
    return SkillProvenance(
        script_sha256=_sha256_file(Path(__file__)),
        acd_version=acd_version,
        graph_sha256=_sha256_file(graph_path),
        defects_sha256=_sha256_file(defects_path),
    )


def _node_map(graph: DesignGraph) -> dict[str, GraphNode]:
    return {node.id: node for node in graph.nodes}


def _anchor_nodes(graph: DesignGraph, record: DefectRecord) -> list[GraphNode]:
    ids = sorted(
        {
            node_id
            for candidate in record.root_cause_candidates
            if candidate.status == "identified"
            for node_id in candidate.node_ids
        }
    )
    nodes = _node_map(graph)
    missing = sorted(set(ids) - set(nodes))
    if missing:
        raise WorkaroundError("root-cause anchors are missing from graph: " + ", ".join(missing))
    return [nodes[node_id] for node_id in ids]


def _component_pins(graph: DesignGraph, component_id: str) -> list[GraphNode]:
    return sorted(
        (
            node
            for node in graph.nodes
            if node.kind == "electrical.pin"
            and node.attrs.get("component") == component_id
            and isinstance(node.attrs.get("net"), str)
            and node.attrs.get("no_connect") is False
        ),
        key=lambda node: node.id,
    )


def _firmware_assignments(graph: DesignGraph, anchor_ids: set[str]) -> list[GraphNode]:
    nodes = _node_map(graph)
    nets: set[str] = set()
    for anchor_id in anchor_ids:
        node = nodes[anchor_id]
        net = node.attrs.get("net")
        if node.kind == "electrical.pin" and isinstance(net, str):
            nets.add(net)
    for anchor_id in anchor_ids:
        node = nodes[anchor_id]
        if node.kind == "electrical.component":
            nets.update(
                str(pin.attrs["net"])
                for pin in _component_pins(graph, anchor_id)
                if isinstance(pin.attrs.get("net"), str)
            )
    return sorted(
        (
            node
            for node in graph.nodes
            if node.kind == "firmware.pin_assignment"
            and node.attrs.get("net") in nets
        ),
        key=lambda node: node.id,
    )


def _template(
    graph: DesignGraph,
    defect_id: str,
    anchor: GraphNode,
    operations: list[ReworkOperation],
    firmware_changes: list[FirmwareChange],
) -> ReworkDiff:
    safety = bool({anchor.id} & safety_related_node_ids(graph))
    return ReworkDiff(
        workaround_id="WA-000",
        graph_id=graph.graph_id,
        base_revision=graph.revision,
        defect_ids=[defect_id],
        operations=operations,
        touches_safety_boundary=safety,
        firmware_changes=firmware_changes,
    )


def _candidate(
    candidate_id: str,
    strategy: WorkaroundStrategy,
    defect_id: str,
    anchor: GraphNode,
    rationale: str,
    template: ReworkDiff | None,
    *,
    status: Literal["proposed", "not_applicable"] = "proposed",
    not_applicable_reason: str | None = None,
) -> WorkaroundCandidate:
    return WorkaroundCandidate(
        candidate_id=candidate_id,
        strategy=strategy,
        defect_ids=[defect_id],
        anchor_node_ids=[anchor.id],
        rationale=rationale,
        rework_template=template,
        status=status,
        not_applicable_reason=not_applicable_reason,
    )


def derive_candidates(
    graph: DesignGraph, defect_id: str, record: DefectRecord
) -> list[WorkaroundCandidate]:
    anchors = _anchor_nodes(graph, record)
    component = next(
        (anchor for anchor in anchors if anchor.kind == "electrical.component"),
        None,
    )
    pin = next(
        (
            anchor
            for anchor in anchors
            if anchor.kind == "electrical.pin"
            and isinstance(anchor.attrs.get("net"), str)
            and anchor.attrs.get("no_connect") is False
        ),
        None,
    )
    anchor = component or pin
    assignments = _firmware_assignments(graph, {item.id for item in anchors})
    firmware = (
        [
            FirmwareChange(
                change_id="FW-000",
                kind="pin_reassignment",
                description="Reassign the affected firmware pin assignment.",
                affected_functions=[node.id for node in assignments],
            )
        ]
        if assignments
        else []
    )
    candidates: list[WorkaroundCandidate] = []
    candidate_number = 1

    if component is not None:
        attrs = {
            key: component.attrs[key]
            for key in ("value", "mpn")
            if key in component.attrs
        }
        template = _template(
            graph,
            defect_id,
            component,
            [
                ReworkReplace(
                    component_id=component.id,
                    attrs=attrs,
                    reason="Replace the root-cause component after selecting changed attributes.",
                )
            ],
            [],
        )
        candidates.append(
            _candidate(
                f"WC-{candidate_number:03d}",
                "rework_only",
                defect_id,
                component,
                "Replace the identified component while preserving the agent-completed change.",
                template,
            )
        )
        candidate_number += 1
    elif pin is not None:
        template = _template(
            graph,
            defect_id,
            pin,
            [ReworkCut(pin_id=pin.id, reason="Disconnect the identified signal pin.")],
            [],
        )
        candidates.append(
            _candidate(
                f"WC-{candidate_number:03d}",
                "rework_only",
                defect_id,
                pin,
                "Cut the identified signal pin to isolate the root cause.",
                template,
            )
        )
        candidate_number += 1

    if anchor is not None and firmware:
        template = _template(
            graph,
            defect_id,
            anchor,
            [],
            firmware,
        )
        candidates.append(
            _candidate(
                f"WC-{candidate_number:03d}",
                "firmware_only",
                defect_id,
                anchor,
                "Reassign firmware pins to steer around the identified root cause.",
                template,
            )
        )
        candidate_number += 1
        if component is not None or pin is not None:
            if component is not None:
                rework_template: list[ReworkOperation] = [
                    ReworkReplace(
                        component_id=component.id,
                        attrs={
                            key: component.attrs[key]
                            for key in ("value", "mpn")
                            if key in component.attrs
                        },
                        reason=(
                            "Complete the component replacement together with "
                            "firmware reassignment."
                        ),
                    )
                ]
            else:
                assert pin is not None
                rework_template = [
                    ReworkCut(
                        pin_id=pin.id,
                        reason=(
                            "Complete the pin cut with firmware reassignment."
                        ),
                    )
                ]
            template = _template(
                graph,
                defect_id,
                anchor,
                rework_template,
                firmware,
            )
            candidates.append(
                _candidate(
                    f"WC-{candidate_number:03d}",
                    "combined",
                    defect_id,
                    anchor,
                    "Combine the physical workaround with firmware pin reassignment.",
                    template,
                )
            )
            candidate_number += 1

    present = {candidate.strategy for candidate in candidates}
    for strategy in STRATEGIES:
        if strategy not in present:
            candidates.append(
                WorkaroundCandidate(
                    candidate_id=f"WC-{candidate_number:03d}",
                    strategy=strategy,
                    defect_ids=[defect_id],
                    anchor_node_ids=[],
                    rationale=f"No applicable {strategy} anchor was identified.",
                    status="not_applicable",
                    not_applicable_reason=f"No applicable {strategy} anchor was identified.",
                )
            )
            candidate_number += 1
    return candidates


def build_proposal(
    graph_path: Path, defects_path: Path, defect_id: str
) -> WorkaroundProposalSet:
    graph = _load_graph(graph_path)
    loaded = _load_defects(defects_path)
    result = check_defect_records(graph, loaded.document)
    record = next(
        (item for item in loaded.document.records if item.defect_id == defect_id),
        None,
    )
    if record is None:
        raise WorkaroundError(f"defect_id is not present: {defect_id}")
    provenance = _provenance(graph_path, defects_path)
    if defect_id in result.blocked:
        return WorkaroundProposalSet(
            graph_id=graph.graph_id,
            revision=graph.revision,
            defect_id=defect_id,
            defect_check_status="blocked",
            candidates=[],
            provenance=provenance,
        )
    if defect_id not in result.workaround_eligible:
        raise WorkaroundError(f"defect check did not classify {defect_id} as eligible")
    return WorkaroundProposalSet(
        graph_id=graph.graph_id,
        revision=graph.revision,
        defect_id=defect_id,
        defect_check_status="workaround_eligible",
        candidates=derive_candidates(graph, defect_id, record),
        provenance=provenance,
    )


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_proposal(path: Path) -> WorkaroundProposalSet:
    try:
        return WorkaroundProposalSet.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise WorkaroundError(f"workaround candidates are invalid: {path}: {exc}") from exc


def _touched_for_anchor(
    graph: DesignGraph, diff: ReworkDiff, anchor: GraphNode
) -> bool:
    for operation in diff.operations:
        if isinstance(operation, ReworkCut) and operation.pin_id == anchor.id:
            return True
        if isinstance(operation, ReworkReplace) and operation.component_id == anchor.id:
            return True
        if getattr(operation, "component_id", None) == anchor.id:
            return True
        if getattr(operation, "target_id", None) == anchor.id:
            return True
        added = getattr(operation, "node", None)
        if added is not None and (
            added.id == anchor.id or anchor.id in added.depends_on
        ):
            return True
    if not diff.firmware_changes:
        return False
    related: set[str] = {anchor.id}
    related.update(
        assignment.id
        for assignment in _firmware_assignments(graph, {anchor.id})
    )
    if anchor.kind == "electrical.component":
        related.update(
            str(pin.attrs["net"])
            for pin in _component_pins(graph, anchor.id)
            if isinstance(pin.attrs.get("net"), str)
        )
    return bool(
        related
        & {
            function
            for change in diff.firmware_changes
            for function in change.affected_functions
        }
    )


def validate_completed(
    graph: DesignGraph,
    proposal: WorkaroundProposalSet,
    candidate_id: str,
    diff: ReworkDiff,
    defects: DefectDocument,
) -> WorkaroundCandidate:
    if proposal.defect_check_status != "workaround_eligible":
        raise WorkaroundError("blocked proposal set cannot be checked")
    candidate = next(
        (item for item in proposal.candidates if item.candidate_id == candidate_id),
        None,
    )
    if candidate is None or candidate.status != "proposed":
        raise WorkaroundError(f"candidate is not a proposed candidate: {candidate_id}")
    if diff.workaround_id == "WA-000":
        raise WorkaroundError("completed rework must not use placeholder WA-000")
    if diff.graph_id != graph.graph_id or diff.base_revision != graph.revision:
        raise WorkaroundError("completed rework does not match the graph")
    if not set(diff.defect_ids).issubset(candidate.defect_ids):
        raise WorkaroundError("completed rework defect_ids are outside the candidate")
    fresh = check_defect_records(graph, defects)
    if any(defect_id not in fresh.workaround_eligible for defect_id in diff.defect_ids):
        raise WorkaroundError("completed rework references an ineligible defect")
    if candidate.strategy == "firmware_only" and (
        diff.operations or not diff.firmware_changes
    ):
        raise WorkaroundError("firmware_only requires firmware changes and no operations")
    if candidate.strategy == "rework_only" and diff.firmware_changes:
        raise WorkaroundError("rework_only must not contain firmware changes")
    if candidate.strategy == "combined" and (
        not diff.operations or not diff.firmware_changes
    ):
        raise WorkaroundError("combined requires operations and firmware changes")
    template = candidate.rework_template
    if template is not None:
        for template_operation, completed_operation in zip(
            template.operations, diff.operations, strict=False
        ):
            if isinstance(template_operation, ReworkReplace) and isinstance(
                completed_operation, ReworkReplace
            ) and template_operation.attrs == completed_operation.attrs:
                raise WorkaroundError(
                    "completed component replacement must change an attribute"
                )
    nodes = _node_map(graph)
    anchors = [nodes[node_id] for node_id in candidate.anchor_node_ids if node_id in nodes]
    if len(anchors) != len(candidate.anchor_node_ids) or any(
        not _touched_for_anchor(graph, diff, anchor) for anchor in anchors
    ):
        raise WorkaroundError("completed rework does not touch every candidate anchor")
    return candidate


def evaluate_completed(
    *,
    graph_path: Path,
    defects_path: Path,
    proposal_path: Path,
    candidate_id: str,
    rework_path: Path,
    dfa_path: Path,
    fixture_dir: Path,
    out_dir: Path,
    approval_path: Path | None = None,
    erc_path: Path | None = None,
    drc_path: Path | None = None,
) -> WorkaroundEvaluation:
    graph = _load_graph(graph_path)
    loaded_defects = _load_defects(defects_path)
    proposal = load_proposal(proposal_path)
    if proposal.graph_id != graph.graph_id or proposal.revision != graph.revision:
        raise WorkaroundError("candidate set does not match the graph")
    loaded_diff = load_rework_diff(rework_path)
    try:
        dfa = ReworkDfaDeclaration.model_validate_json(dfa_path.read_text(encoding="utf-8"))
        approval = (
            SafetyApproval.model_validate_json(approval_path.read_text(encoding="utf-8"))
            if approval_path is not None
            else None
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise WorkaroundError(f"completed workaround input is invalid: {exc}") from exc
    candidate = validate_completed(
        graph, proposal, candidate_id, loaded_diff.diff, loaded_defects.document
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        derived, salvage = evaluate_salvage(
            base_graph=graph,
            diff=loaded_diff.diff,
            dfa=dfa,
            approval=approval,
            fixture_dir=fixture_dir,
            external_evidence={
                name: path
                for name, path in (("erc", erc_path), ("drc", drc_path))
                if path is not None
            },
            output_dir=out_dir,
        )
    except SalvageGateError as exc:
        raise WorkaroundError(str(exc)) from exc
    write_derived_graph(derived, out_dir)
    rejection_reasons = (
        list(salvage.reasons) if salvage.verdict == "not_salvageable" else []
    )
    evaluation = WorkaroundEvaluation(
        candidate_id=candidate.candidate_id,
        workaround_id=loaded_diff.diff.workaround_id,
        graph_id=graph.graph_id,
        base_revision=graph.revision,
        derived_revision=derived.derived_revision,
        defect_check_status="workaround_eligible",
        salvage=salvage,
        rejection_reasons=rejection_reasons,
        alternatives=sorted(
            item.candidate_id
            for item in proposal.candidates
            if item.status == "proposed" and item.candidate_id != candidate.candidate_id
        ),
        provenance=_provenance(graph_path, defects_path),
    )
    write_json(out_dir / "workaround-evaluation.json", evaluation.model_dump(mode="json"))
    return evaluation


__all__ = [
    "WorkaroundError",
    "build_proposal",
    "derive_candidates",
    "evaluate_completed",
    "load_proposal",
    "validate_completed",
    "write_json",
]
