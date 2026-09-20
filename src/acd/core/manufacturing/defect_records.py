"""Load and mechanically check defect records against a design graph.

The same-rule horizontal search only inspects ``rule_ids`` and
``applied_rules`` list attributes. If neither attribute appears in the graph,
the search is still considered searched and returns no matches.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pydantic import Field

from acd.core.runtime.fileio import read_json
from acd.schema.common import (
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    canonical_json_sha256,
)
from acd.schema.defect_record import (
    DefectDocument,
    DefectRecord,
    HorizontalCriterion,
)
from acd.schema.design_graph import DesignGraph, GraphNode


class DefectRecordError(ValueError):
    """Raised when a defect document cannot be loaded or validated."""


@dataclass(frozen=True)
class LoadedDefectDocument:
    document: DefectDocument
    document_hash: str
    path: Path


def load_defect_document(path: Path) -> LoadedDefectDocument:
    """Load and validate a defect record document."""
    try:
        document = DefectDocument.model_validate(read_json(path))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise DefectRecordError(f"defect document is invalid: {path}: {exc}") from exc
    return LoadedDefectDocument(
        document=document,
        document_hash=canonical_json_sha256(document.model_dump(mode="json")),
        path=path,
    )


DefectFindingCode = Literal[
    "graph_id_mismatch",
    "revision_mismatch",
    "unknown_node",
    "root_cause_unknown",
    "horizontal_unsearched",
    "horizontal_incomplete",
    "horizontal_extra",
    "units_unknown",
]


class DefectFinding(AcdModel):
    """One fail-closed defect-record finding."""

    defect_id: NonEmptyStr
    code: DefectFindingCode
    message: NonEmptyStr
    node_ids: list[NodeId] = Field(default_factory=list[NodeId])


class DefectCheckResult(AcdModel):
    """Mechanical defect-record gate result."""

    status: Literal["pass", "fail"]
    pass_evidence: Literal[False] = False
    graph_id: NonEmptyStr
    revision: Revision
    record_count: int = Field(ge=0)
    workaround_eligible: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    blocked: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    findings: list[DefectFinding] = Field(default_factory=list[DefectFinding])


def _attrs_contain_string(attrs: object, values: set[str]) -> bool:
    if isinstance(attrs, str):
        return attrs in values
    if isinstance(attrs, dict):
        mapping = cast(dict[object, object], attrs)
        return any(_attrs_contain_string(value, values) for value in mapping.values())
    if isinstance(attrs, list):
        items = cast(list[object], attrs)
        return any(_attrs_contain_string(value, values) for value in items)
    return False


def _anchor_nodes(graph: DesignGraph, record: DefectRecord) -> list[GraphNode]:
    anchors = {
        node_id
        for candidate in record.root_cause_candidates
        if candidate.status == "identified"
        for node_id in candidate.node_ids
    }
    return [node for node in graph.nodes if node.id in anchors]


def compute_horizontal_scope(
    graph: DesignGraph, record: DefectRecord, criterion: HorizontalCriterion
) -> list[NodeId]:
    """Compute one deterministic horizontal scope, excluding root-cause anchors."""
    anchors = _anchor_nodes(graph, record)
    anchor_ids = {node.id for node in anchors}
    matches: list[GraphNode] = []
    if criterion == "same_component_mpn":
        mpns = {
            value
            for node in anchors
            if node.kind == "electrical.component"
            for value in [node.attrs.get("mpn")]
            if isinstance(value, str)
        }
        matches = [
            node
            for node in graph.nodes
            if node.id not in anchor_ids
            and node.kind == "electrical.component"
            and isinstance(node.attrs.get("mpn"), str)
            and node.attrs.get("mpn") in mpns
        ]
    elif criterion == "same_node_kind":
        kinds = {node.kind for node in anchors}
        matches = [node for node in graph.nodes if node.id not in anchor_ids and node.kind in kinds]
    elif criterion == "same_rule":
        rule_ids = {
            rule_id
            for candidate in record.root_cause_candidates
            if candidate.status == "identified"
            for rule_id in candidate.rule_ids
        }
        matches = [
            node
            for node in graph.nodes
            if node.id not in anchor_ids
            and any(
                isinstance(node.attrs.get(attribute), list)
                and rule_id in cast(list[str], node.attrs[attribute])
                for attribute in ("rule_ids", "applied_rules")
                for rule_id in rule_ids
            )
        ]
    elif criterion == "same_fixture":
        matches = [
            node
            for node in graph.nodes
            if node.id not in anchor_ids
            and node.kind in {"fab.order_intent", "fab.process_allowance", "electrical.board"}
            and _attrs_contain_string(node.attrs, set(record.fixture_refs))
        ]
    else:
        matches = [
            node
            for node in graph.nodes
            if node.id not in anchor_ids
            and node.kind in {"fab.order_intent", "fab.process_allowance", "electrical.board"}
            and _attrs_contain_string(node.attrs, set(record.profile_refs))
        ]
    return sorted((node.id for node in matches), key=str)


def _finding(
    defect_id: str,
    code: DefectFindingCode,
    message: str,
    node_ids: list[str] | None = None,
) -> DefectFinding:
    return DefectFinding(
        defect_id=defect_id,
        code=code,
        message=message,
        node_ids=sorted(set(node_ids or [])),
    )


def check_defect_records(graph: DesignGraph, document: DefectDocument) -> DefectCheckResult:
    """Run the deterministic fail-closed defect-record gate."""
    findings: list[DefectFinding] = []
    if document.graph_id != graph.graph_id:
        findings.extend(
            _finding(
                record.defect_id,
                "graph_id_mismatch",
                f"defect document targets graph {document.graph_id!r}, "
                f"but graph is {graph.graph_id!r}",
            )
            for record in document.records
        )
    if document.revision != graph.revision:
        findings.extend(
            _finding(
                record.defect_id,
                "revision_mismatch",
                f"defect document targets revision {document.revision!r}, "
                f"but graph is {graph.revision!r}",
            )
            for record in document.records
        )
    if findings:
        return DefectCheckResult(
            status="fail",
            graph_id=graph.graph_id,
            revision=graph.revision,
            record_count=len(document.records),
            blocked=[record.defect_id for record in document.records],
            findings=findings,
        )

    known_nodes = {node.id for node in graph.nodes}
    eligible: list[str] = []
    blocked: list[str] = []
    for record in document.records:
        record_findings: list[DefectFinding] = []
        referenced = {
            node_id for candidate in record.root_cause_candidates for node_id in candidate.node_ids
        }
        referenced.update(
            node_id for scope in record.horizontal_scopes for node_id in scope.matched_node_ids
        )
        referenced.update(
            exclusion.node_id for scope in record.horizontal_scopes for exclusion in scope.excluded
        )
        unknown_nodes = sorted(referenced - known_nodes)
        if unknown_nodes:
            record_findings.append(
                _finding(
                    record.defect_id,
                    "unknown_node",
                    "defect record references unknown graph nodes: " + ", ".join(unknown_nodes),
                    unknown_nodes,
                )
            )
        if any(candidate.status == "unknown" for candidate in record.root_cause_candidates):
            record_findings.append(
                _finding(
                    record.defect_id,
                    "root_cause_unknown",
                    "at least one root-cause candidate is unknown",
                )
            )
        if record.affected_units.scope_status == "unknown":
            record_findings.append(
                _finding(
                    record.defect_id,
                    "units_unknown",
                    "affected unit scope is unknown",
                )
            )
        for scope in record.horizontal_scopes:
            if scope.search_status == "unsearched":
                record_findings.append(
                    _finding(
                        record.defect_id,
                        "horizontal_unsearched",
                        f"horizontal scope {scope.criterion} was not searched",
                    )
                )
                continue
            computed = set(compute_horizontal_scope(graph, record, scope.criterion))
            declared = set(scope.matched_node_ids) | {
                exclusion.node_id for exclusion in scope.excluded
            }
            missing = sorted(computed - declared)
            extra = sorted(declared - computed)
            if missing:
                record_findings.append(
                    _finding(
                        record.defect_id,
                        "horizontal_incomplete",
                        f"horizontal scope {scope.criterion} omitted computed nodes: "
                        + ", ".join(missing),
                        missing,
                    )
                )
            if extra:
                record_findings.append(
                    _finding(
                        record.defect_id,
                        "horizontal_extra",
                        f"horizontal scope {scope.criterion} declared nodes not "
                        "found by the search: " + ", ".join(extra),
                        extra,
                    )
                )
        findings.extend(record_findings)
        if record_findings:
            blocked.append(record.defect_id)
        else:
            eligible.append(record.defect_id)
    return DefectCheckResult(
        status="pass" if not findings else "fail",
        graph_id=graph.graph_id,
        revision=graph.revision,
        record_count=len(document.records),
        workaround_eligible=eligible,
        blocked=blocked,
        findings=findings,
    )


__all__ = [
    "DefectCheckResult",
    "DefectFinding",
    "DefectRecordError",
    "LoadedDefectDocument",
    "check_defect_records",
    "compute_horizontal_scope",
    "load_defect_document",
]
