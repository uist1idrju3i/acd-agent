"""Deterministic fixture builder for arbitrary design specifications."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from acd.core.functional_blocks import load_functional_block_registry
from acd.core.naming import artifact_prefix
from acd.core.part_selection import PartSelectionError, select_part
from acd.core.rationale import (
    REQUIRED_RATIONALE_ATTRS,
    check_rationale_coverage,
    subject_hash_for,
)
from acd.core.requirements import validate_requirements
from acd.schema import (
    DesignFixtureSpec,
    DesignGraph,
    GraphNode,
    RationaleDocument,
    RationaleProvenance,
    RationaleRecord,
    RequirementDocument,
)
from acd.schema.design_graph import AttrValue
from acd.schema.parts_catalog import PartCplOrientation
from acd.schema.rationale import DecisionKind


class FixtureBuilderError(ValueError):
    """Raised when a design specification cannot produce a fixture safely."""


def _cpl_orientation_attrs(
    orientation: PartCplOrientation | None,
    graph_id: str,
    refdes: str,
) -> dict[str, AttrValue]:
    if orientation is None:
        return {}
    values = orientation.model_dump(mode="json", exclude_defaults=True)
    source = values.get("geometry_exception_source")
    if isinstance(source, str):
        try:
            values["geometry_exception_source"] = source.format(
                artifact_prefix=artifact_prefix(graph_id),
                refdes=refdes,
            )
        except (KeyError, ValueError) as exc:
            raise FixtureBuilderError(
                f"{refdes}: malformed CPL geometry evidence source"
            ) from exc
    return cast(
        dict[str, AttrValue],
        {
            "cpl_rotation_" + key: value
            for key, value in values.items()
        },
    )


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _decision_kind(kind: str) -> DecisionKind:
    mapping: dict[str, DecisionKind] = {
        "electrical.board": "stackup",
        "electrical.component": "part_selection",
        "electrical.net": "net_class",
        "firmware.pin_assignment": "firmware_pin",
        "mechanical.outline": "mechanical",
        "fab.order_intent": "fab_process",
    }
    return mapping.get(kind, "mechanical")


def build_graph(spec: DesignFixtureSpec) -> DesignGraph:
    """Build a graph without invoking external tools or mutating the source."""
    graph_id = spec.graph_id or spec.design_name
    nodes: list[GraphNode] = []
    requirement_ids = {record.requirement_id for record in spec.requirements}
    for record in sorted(spec.requirements, key=lambda item: item.requirement_id):
        nodes.append(
            GraphNode(
                id=f"req.{record.requirement_id}",
                kind="requirement",
                attrs={"text": record.statement},
            )
        )
    known_net_ids = {net.net_id for net in spec.nets}
    for net in sorted(spec.nets, key=lambda item: item.net_id):
        nodes.append(GraphNode(id=net.net_id, kind="electrical.net", attrs=net.attrs))
    component_ids: list[str] = []
    known_refs: set[str] = set()
    for component in sorted(spec.components, key=lambda item: item.refdes):
        if component.refdes in known_refs:
            raise FixtureBuilderError(f"duplicate component refdes: {component.refdes}")
        known_refs.add(component.refdes)
        component_id = f"comp.{component.refdes.lower()}"
        component_ids.append(component_id)
        component_attrs = {"refdes": component.refdes, **component.attrs}
        if component.part_request is not None:
            try:
                selection = select_part(component.part_request)
            except PartSelectionError as exc:
                raise FixtureBuilderError(str(exc)) from exc
            entry = selection.entry
            component_attrs.update(
                {
                    "part_number": entry.part_number,
                    "value": entry.value,
                    "package": entry.package,
                    **entry.library_ref.model_dump(mode="json"),
                    "parts_catalog_id": selection.catalog_id,
                    "parts_catalog_sha256": selection.catalog_hash,
                }
            )
            component_attrs.update(
                _cpl_orientation_attrs(entry.cpl_orientation, graph_id, component.refdes)
            )
        if component.library_ref is not None:
            component_attrs["library_ref"] = component.library_ref
        nodes.append(
            GraphNode(
                id=component_id,
                kind="electrical.component",
                attrs=component_attrs,
            )
        )
        for pad, net_id in sorted(component.pads.items(), key=lambda item: item[0]):
            if net_id is not None and net_id not in known_net_ids:
                raise FixtureBuilderError(
                    f"component {component.refdes} references unknown net: {net_id}"
                )
            nodes.append(
                GraphNode(
                    id=f"pin.{component.refdes.lower()}.{pad.lower()}",
                    kind="electrical.pin",
                    attrs={
                        "component": component_id,
                        "pad": pad,
                        "net": net_id,
                        "no_connect": net_id is None,
                    },
                    depends_on=[component_id] + ([net_id] if net_id else []),
                )
            )
    nodes.append(
        GraphNode(
            id=f"board.{graph_id}",
            kind="electrical.board",
            attrs=spec.board_attrs,
            depends_on=sorted(component_ids),
        )
    )
    for block in sorted(spec.functional_blocks, key=lambda item: item.block_id):
        unknown_requirements = sorted(set(block.requirement_ids) - requirement_ids)
        if unknown_requirements:
            raise FixtureBuilderError(
                f"functional block {block.block_id!r} references unknown requirements: "
                + ", ".join(unknown_requirements)
            )
        nodes.append(
            GraphNode(
                id=block.node_id or f"fb.{block.block_id}",
                kind="design.functional_block",
                attrs={"block_id": block.block_id},
                depends_on=[f"req.{item}" for item in sorted(block.requirement_ids)],
            )
        )
    for pin in sorted(spec.firmware_pin_assignments, key=lambda item: item.pin_id):
        if pin.net not in known_net_ids:
            raise FixtureBuilderError(f"firmware pin references unknown net: {pin.net}")
        nodes.append(
            GraphNode(
                id=pin.pin_id,
                kind="firmware.pin_assignment",
                attrs={"net": pin.net, "gpio": pin.gpio},
                depends_on=[pin.net],
            )
        )
    if spec.fab_profile_id is not None:
        nodes.append(
            GraphNode(
                id=f"fab.order_intent.{graph_id}",
                kind="fab.order_intent",
                attrs={"fab_profile": spec.fab_profile_id},
                depends_on=[f"board.{graph_id}"],
            )
        )
    return DesignGraph(graph_id=graph_id, revision=spec.revision, nodes=nodes)


def _rationale(graph: DesignGraph, spec: DesignFixtureSpec) -> RationaleDocument:
    requirement_ids = [f"req.{item.requirement_id}" for item in spec.requirements]
    records: list[RationaleRecord] = []
    for node in graph.nodes:
        required = REQUIRED_RATIONALE_ATTRS.get(node.kind, frozenset())
        attrs = sorted(required & set(node.attrs))
        if not attrs:
            continue
        records.append(
            RationaleRecord(
                rationale_id=f"fixture-{node.id}",
                decision_kind=_decision_kind(node.kind),
                subject_nodes=[node.id],
                subject_attrs=attrs,
                subject_hash=subject_hash_for(graph, [node.id], attrs),
                decision=f"Use the declared values for {node.id}.",
                justification="Declared by the deterministic design specification.",
                driving_requirements=requirement_ids,
                no_alternatives_reason="No alternatives are declared by the specification.",
                provenance=RationaleProvenance(
                    source="deterministic_tool",
                recorded_at=datetime(2025, 1, 1, tzinfo=UTC),
                ),
                target_revision=graph.revision,
            )
        )
    return RationaleDocument(
        graph_id=graph.graph_id,
        revision=graph.revision,
        records=records,
    )


def build_design_fixture(spec: DesignFixtureSpec, out_dir: Path) -> DesignGraph:
    """Build and atomically write graph, requirements, and rationale documents."""
    registry = load_functional_block_registry()
    known_blocks = {contract.block_id for contract in registry.contracts}
    unknown_blocks = sorted(
        {item.block_id for item in spec.functional_blocks if item.block_id not in known_blocks}
    )
    if unknown_blocks:
        raise FixtureBuilderError(
            "unknown functional blocks: " + ", ".join(unknown_blocks)
        )
    graph = build_graph(spec)
    requirements = RequirementDocument(
        graph_id=graph.graph_id,
        revision=graph.revision,
        records=spec.requirements,
    )
    validate_requirements(requirements, graph, registry)
    rationale = _rationale(graph, spec)
    coverage = check_rationale_coverage(graph, rationale)
    if coverage.status != "pass":
        raise FixtureBuilderError(
            "rationale coverage failed while building fixture: "
            + coverage.status
        )
    graph_content = _canonical(graph.model_dump(mode="json"))
    requirements_content = _canonical(requirements.model_dump(mode="json"))
    rationale_content = _canonical(rationale.model_dump(mode="json"))
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_atomic(out_dir / "graph.json", graph_content)
    _write_atomic(out_dir / "requirements.json", requirements_content)
    _write_atomic(out_dir / "rationale.json", rationale_content)
    return graph


__all__ = ["FixtureBuilderError", "build_design_fixture", "build_graph"]
