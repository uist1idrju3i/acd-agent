"""Machine-readable preflight checks for mechanical lane declarations."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from acd.core.electrical import GraphExtractionError, extract_electrical_lane
from acd.core.mechanical import REQUIRED_MECHANICAL_ATTRS, extract_mechanical_lane
from acd.core.rationale import check_rationale_coverage
from acd.schema.common import CURRENT_SCHEMA_VERSION, AcdModel, NonEmptyStr, Revision, SchemaVersion
from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.rationale import RationaleDocument

RequirementCode = Literal[
    "mechanical.node.missing",
    "mechanical.node.duplicated",
    "mechanical.attribute.missing",
    "mechanical.attribute.invalid",
    "mechanical.reference.unresolved",
    "mechanical.extraction.failed",
    "rationale.coverage.missing",
    "rationale.coverage.stale",
    "rationale.coverage.orphan",
    "rationale.coverage.conflicting",
    "rationale.coverage.unknown_provenance",
    "rationale.coverage.untraceable",
    "rationale.coverage.unclassified",
]


class RequirementFinding(AcdModel):
    """One deterministic machine-readable mechanical requirement finding."""

    code: RequirementCode
    node_kind: str
    node_id: str
    attribute: str
    detail: NonEmptyStr


class MechanicalPreflightReport(AcdModel):
    """Complete fail-closed mechanical preflight result."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    graph_id: NonEmptyStr
    revision: Revision
    status: Literal["pass", "fail"]
    findings: list[RequirementFinding]


def _finding(
    code: RequirementCode,
    detail: str,
    *,
    node_kind: str = "",
    node_id: str = "",
    attribute: str = "",
) -> RequirementFinding:
    return RequirementFinding(
        code=code,
        node_kind=node_kind,
        node_id=node_id,
        attribute=attribute,
        detail=detail,
    )


def _node_kind(graph: DesignGraph, node_id: str) -> str:
    for node in graph.nodes:
        if node.id == node_id:
            return node.kind
    return ""


def _rationale_findings(
    graph: DesignGraph, fixture_dir: Path
) -> list[RequirementFinding]:
    rationale_path = fixture_dir / "rationale.json"
    if not rationale_path.is_file():
        return [
            _finding(
                "rationale.coverage.missing",
                f"rationale does not exist: {rationale_path}",
            )
        ]
    try:
        document = RationaleDocument.model_validate(
            json.loads(rationale_path.read_text(encoding="utf-8"))
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        return [
            _finding(
                "rationale.coverage.missing",
                f"rationale could not be parsed: {exc}",
            )
        ]

    report = check_rationale_coverage(graph, document)
    findings: list[RequirementFinding] = []
    if not report.graph_id_match:
        findings.append(
            _finding(
                "rationale.coverage.unknown_provenance",
                f"rationale graph_id {document.graph_id!r} does not match {graph.graph_id!r}",
            )
        )
    if not report.revision_match:
        findings.append(
            _finding(
                "rationale.coverage.unknown_provenance",
                f"rationale revision {document.revision!r} does not match {graph.revision!r}",
            )
        )
    findings.extend(
        _finding(
            "rationale.coverage.missing",
            "required rationale subject is missing",
            node_kind=_node_kind(graph, item.node_id),
            node_id=item.node_id,
            attribute=item.attr,
        )
        for item in report.missing
    )
    findings.extend(
        _finding(
            "rationale.coverage.stale",
            "rationale subject is stale",
            node_kind=_node_kind(graph, item.subject.node_id),
            node_id=item.subject.node_id,
            attribute=item.subject.attr,
        )
        for item in report.stale
    )
    findings.extend(
        _finding(
            "rationale.coverage.orphan",
            item.reason,
            node_kind=_node_kind(graph, item.subject.node_id),
            node_id=item.subject.node_id,
            attribute=item.subject.attr,
        )
        for item in report.orphan
    )
    findings.extend(
        _finding(
            "rationale.coverage.conflicting",
            "multiple rationale records cover the same subject",
            node_kind=_node_kind(graph, item.subject.node_id),
            node_id=item.subject.node_id,
            attribute=item.subject.attr,
        )
        for item in report.conflicting
    )
    findings.extend(
        _finding(
            "rationale.coverage.unknown_provenance",
            "rationale provenance script hash is unknown",
        )
        for _ in report.unknown_provenance
    )
    findings.extend(
        _finding(
            "rationale.coverage.untraceable",
            "rationale has no driving requirement or requirement reference",
        )
        for _ in report.untraceable
    )
    findings.extend(
        _finding(
            "rationale.coverage.unclassified",
            item.reason,
            node_kind=item.node_kind,
            node_id=item.node_id,
            attribute=item.attr,
        )
        for item in report.unclassified
    )
    findings.extend(
        _finding(
            "rationale.coverage.unclassified",
            f"rationale record is not admissible: {item.reason}",
        )
        for item in [*report.templated, *report.generator_violations]
    )
    return findings


def _attribute_kind_valid(attribute: str, value: object) -> bool:
    if attribute in {
        "body_type",
        "component_refdes",
        "dimensions_checked_at",
        "dimensions_source",
        "dimensions_source_ref",
        "edge",
        "face",
        "fastener_method",
        "material",
        "mounting_side",
        "origin",
        "position_source",
        "position_source_ref",
        "requirement_id",
        "tolerance_source",
        "tolerance_source_ref",
        "unit",
        "y_axis",
    }:
        return isinstance(value, str) and bool(value)
    if attribute == "mount_hole_count":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, int | float) and not isinstance(value, bool)


def _mechanical_findings(graph: DesignGraph) -> list[RequirementFinding]:
    findings: list[RequirementFinding] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    def add(finding: RequirementFinding) -> None:
        key = (
            finding.code,
            finding.node_kind,
            finding.node_id,
            finding.attribute,
            finding.detail,
        )
        if key not in seen:
            seen.add(key)
            findings.append(finding)

    try:
        electrical = extract_electrical_lane(graph)
        component_ids = {component.node_id for component in electrical.components}
        board_id = electrical.board.node_id
    except GraphExtractionError as exc:
        component_ids = {
            node.id for node in graph.nodes if node.kind == "electrical.component"
        }
        board_id = next(
            (node.id for node in graph.nodes if node.kind == "electrical.board"),
            "",
        )
        add(
            _finding(
                "mechanical.extraction.failed",
                f"electrical lane could not be extracted: {exc}",
            )
        )

    nodes_by_kind: dict[str, list[GraphNode]] = defaultdict(list)
    for node in graph.nodes:
        if node.kind in REQUIRED_MECHANICAL_ATTRS:
            nodes_by_kind[node.kind].append(node)

    for kind in ("mechanical.outline", "mechanical.enclosure"):
        nodes = nodes_by_kind[kind]
        if not nodes:
            add(
                _finding(
                    "mechanical.node.missing",
                    f"required {kind} node is missing",
                    node_kind=kind,
                )
            )
        elif len(nodes) > 1:
            for node in nodes:
                add(
                    _finding(
                        "mechanical.node.duplicated",
                        f"expected exactly one {kind} node, got {len(nodes)}",
                        node_kind=kind,
                        node_id=node.id,
                    )
                )

    bodies_by_component: dict[str, list[GraphNode]] = defaultdict(list)
    for node in nodes_by_kind["mechanical.component_body"]:
        depended = [dependency for dependency in node.depends_on if dependency in component_ids]
        if len(depended) != 1:
            add(
                _finding(
                    "mechanical.reference.unresolved",
                    "component_body must depend on exactly one electrical component",
                    node_kind=node.kind,
                    node_id=node.id,
                )
            )
        else:
            bodies_by_component[depended[0]].append(node)
    for component_id in sorted(component_ids):
        bodies = bodies_by_component[component_id]
        if not bodies:
            add(
                _finding(
                    "mechanical.node.missing",
                    f"electrical component {component_id!r} has no mechanical.component_body",
                    node_kind="mechanical.component_body",
                )
            )
        elif len(bodies) > 1:
            for node in bodies:
                add(
                    _finding(
                        "mechanical.node.duplicated",
                        "electrical component "
                        f"{component_id!r} has {len(bodies)} component_body nodes",
                        node_kind=node.kind,
                        node_id=node.id,
                    )
                )

    for node in graph.nodes:
        if node.kind == "mechanical.outline" and (
            not board_id or node.depends_on.count(board_id) != 1
        ):
            add(
                _finding(
                    "mechanical.reference.unresolved",
                    "outline must depend on exactly one electrical board",
                    node_kind=node.kind,
                    node_id=node.id,
                )
            )
        elif node.kind in {
            "mechanical.connector_opening",
            "mechanical.board_edge_overhang",
        }:
            depended = [dependency for dependency in node.depends_on if dependency in component_ids]
            if len(depended) != 1:
                add(
                    _finding(
                        "mechanical.reference.unresolved",
                        "mechanical node must depend on exactly one electrical component",
                        node_kind=node.kind,
                        node_id=node.id,
                    )
                )
            elif (
                node.kind == "mechanical.board_edge_overhang"
                and not bodies_by_component[depended[0]]
            ):
                add(
                    _finding(
                        "mechanical.reference.unresolved",
                        "overhang depends on a component without mechanical.component_body",
                        node_kind=node.kind,
                        node_id=node.id,
                    )
                )

    for node in graph.nodes:
        required = REQUIRED_MECHANICAL_ATTRS.get(node.kind)
        if required is None:
            continue
        required_attrs = list(required)
        if node.kind == "mechanical.outline":
            count = node.attrs.get("mount_hole_count")
            if isinstance(count, int) and not isinstance(count, bool) and count >= 1:
                for index in range(1, count + 1):
                    required_attrs.extend(
                        (
                            f"mount_hole_{index}_x_mm",
                            f"mount_hole_{index}_y_mm",
                            f"mount_hole_{index}_diameter_mm",
                        )
                    )
        for attribute in sorted(set(required_attrs)):
            if attribute not in node.attrs:
                add(
                    _finding(
                        "mechanical.attribute.missing",
                        f"required attribute {attribute!r} is missing",
                        node_kind=node.kind,
                        node_id=node.id,
                        attribute=attribute,
                    )
                )
                continue
            value = node.attrs[attribute]
            if attribute == "mount_hole_count" and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
            ):
                add(
                    _finding(
                        "mechanical.attribute.invalid",
                        f"attribute {attribute!r} has an invalid value",
                        node_kind=node.kind,
                        node_id=node.id,
                        attribute=attribute,
                    )
                )
            elif not _attribute_kind_valid(attribute, value):
                add(
                    _finding(
                        "mechanical.attribute.missing",
                        f"required attribute {attribute!r} has the wrong type",
                        node_kind=node.kind,
                        node_id=node.id,
                        attribute=attribute,
                    )
                )
    try:
        extract_mechanical_lane(graph)
    except GraphExtractionError as exc:
        add(
            _finding(
                "mechanical.extraction.failed",
                f"mechanical lane could not be extracted: {exc}",
            )
        )
    return findings


def check_mechanical_preflight(
    graph: DesignGraph, fixture_dir: Path
) -> MechanicalPreflightReport:
    """Return all mechanical and rationale preflight findings without raising."""
    findings = [*_rationale_findings(graph, fixture_dir), *_mechanical_findings(graph)]
    findings.sort(
        key=lambda item: (
            item.code,
            item.node_kind,
            item.node_id,
            item.attribute,
            item.detail,
        )
    )
    return MechanicalPreflightReport(
        graph_id=graph.graph_id,
        revision=graph.revision,
        status="pass" if not findings else "fail",
        findings=findings,
    )
