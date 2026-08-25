"""Deterministic fixture builder for arbitrary design specifications."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Final

from acd.core.cpl_orientation import cpl_orientation_attrs
from acd.core.functional_blocks import load_functional_block_registry
from acd.core.part_selection import PartSelectionError, select_part
from acd.core.pin_functions import pin_function_attrs
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
from acd.schema.common import AcdModel, NonEmptyStr
from acd.schema.design_graph import AttrValue
from acd.schema.rationale import DecisionKind

# Generator identity recorded in rationale provenance. The deterministic
# rationale coverage check only accepts known generators.
GENERATOR_NAME: Final = "acd.pipeline.fixture_builder"


class FixtureBuilderError(ValueError):
    """Raised when a design specification cannot produce a fixture safely."""


class GraphOverwriteConflict(AcdModel):
    """A generated graph would drop data that exists in the written graph."""

    node_id: NonEmptyStr
    attr: NonEmptyStr | None = None
    reason: NonEmptyStr


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
        "firmware.module": "firmware_pin",
        "firmware.state": "firmware_pin",
        "firmware.state_transition": "firmware_pin",
        "firmware.sequence_step": "firmware_pin",
        "firmware.pin_assignment": "firmware_pin",
        "mechanical.outline": "mechanical",
        "mechanical.silk_text": "silkscreen",
        "mechanical.silk_graphic": "silkscreen",
        "fab.order_intent": "fab_process",
    }
    return mapping.get(kind, "mechanical")


def _generator_script_hash() -> str:
    source = Path(__file__).read_bytes()
    return f"sha256:{hashlib.sha256(source).hexdigest()}"


def _generator_version() -> str:
    try:
        return version("acd")
    except PackageNotFoundError as exc:  # pragma: no cover - packaging failure
        raise FixtureBuilderError(
            "the ACD distribution version is unavailable; rationale provenance "
            "cannot identify the generator"
        ) from exc


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
                pin_function_attrs(
                    entry.cpl_orientation,
                    selection.catalog_id,
                    selection.catalog_hash,
                )
            )
            component_attrs.update(
                cpl_orientation_attrs(
                    entry.cpl_orientation,
                    component.cpl_orientation_evidence,
                    graph_id,
                    spec.revision,
                    component.refdes,
                )
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
    board_id = f"board.{graph_id}"
    nodes.append(
        GraphNode(
            id=board_id,
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
    nodes.extend(_mechanical_nodes(spec, graph_id, board_id))
    nodes.extend(_firmware_module_nodes(spec, graph_id, known_refs))
    if spec.fab_profile_id is not None:
        nodes.append(
            GraphNode(
                id=f"fab.order_intent.{graph_id}",
                kind="fab.order_intent",
                attrs={"fab_profile": spec.fab_profile_id},
                depends_on=[board_id],
            )
        )
    return DesignGraph(graph_id=graph_id, revision=spec.revision, nodes=nodes)


def _mechanical_nodes(
    spec: DesignFixtureSpec, graph_id: str, board_id: str
) -> list[GraphNode]:
    """Project declared mechanical and silkscreen declarations without defaults."""
    nodes: list[GraphNode] = []
    outline = spec.mechanical_outline
    if outline is not None:
        nodes.append(
            GraphNode(
                id=outline.node_id or f"mechanical.outline.{graph_id}",
                kind="mechanical.outline",
                attrs=outline.attrs,
                depends_on=[board_id],
            )
        )
    for text in sorted(spec.silk_texts, key=lambda item: item.node_id):
        nodes.append(
            GraphNode(
                id=text.node_id,
                kind="mechanical.silk_text",
                attrs=text.attrs,
                depends_on=sorted(text.depends_on) or [board_id],
            )
        )
    for graphic in sorted(spec.silk_graphics, key=lambda item: item.node_id):
        nodes.append(
            GraphNode(
                id=graphic.node_id,
                kind="mechanical.silk_graphic",
                attrs=graphic.attrs,
                depends_on=sorted(graphic.depends_on) or [board_id],
            )
        )
    return nodes


def _firmware_module_nodes(
    spec: DesignFixtureSpec, graph_id: str, known_refs: set[str]
) -> list[GraphNode]:
    """Project the declared firmware module, states, transitions, and sequence."""
    module = spec.firmware_module
    if module is None:
        return []
    module_id = module.node_id or f"firmware.module.{graph_id}"
    mcu_component = module.attrs.get("mcu_component")
    if isinstance(mcu_component, str):
        refdes = mcu_component.removeprefix("comp.")
        if refdes.upper() not in {item.upper() for item in known_refs}:
            raise FixtureBuilderError(
                f"firmware module references unknown component: {mcu_component}"
            )
    state_ids = sorted(state.node_id for state in module.states)
    nodes = [
        GraphNode(
            id=module_id,
            kind="firmware.module",
            attrs=module.attrs,
            depends_on=sorted(
                {*state_ids, *([mcu_component] if isinstance(mcu_component, str) else [])}
            ),
        )
    ]
    for state in sorted(module.states, key=lambda item: item.node_id):
        nodes.append(
            GraphNode(
                id=state.node_id,
                kind="firmware.state",
                attrs=state.attrs,
                depends_on=[module_id],
            )
        )
    for transition in sorted(module.transitions, key=lambda item: item.node_id):
        endpoints = [
            transition.attrs.get("from_state"),
            transition.attrs.get("to_state"),
        ]
        declared = sorted({item for item in endpoints if isinstance(item, str)})
        unknown_states = [item for item in declared if item not in state_ids]
        if unknown_states:
            raise FixtureBuilderError(
                "firmware transition references unknown states: "
                + ", ".join(unknown_states)
            )
        nodes.append(
            GraphNode(
                id=transition.node_id,
                kind="firmware.state_transition",
                attrs=transition.attrs,
                depends_on=declared,
            )
        )
    for step in sorted(module.sequence_steps, key=lambda item: item.node_id):
        endpoints = [step.attrs.get("actor"), step.attrs.get("target")]
        declared = sorted({item for item in endpoints if isinstance(item, str)})
        nodes.append(
            GraphNode(
                id=step.node_id,
                kind="firmware.sequence_step",
                attrs=step.attrs,
                depends_on=declared,
            )
        )
    return nodes


def _driving_requirements(spec: DesignFixtureSpec, node_id: str) -> list[str]:
    constraining = [
        f"req.{record.requirement_id}"
        for record in spec.requirements
        if node_id in record.constrains_node_ids
    ]
    if constraining:
        return constraining
    return [f"req.{record.requirement_id}" for record in spec.requirements]


def _attr_summary(attrs: dict[str, AttrValue], keys: list[str]) -> str:
    return ", ".join(
        f"{key}={json.dumps(attrs[key], ensure_ascii=False, sort_keys=True)}"
        for key in keys
    )


def _rationale(
    graph: DesignGraph, spec: DesignFixtureSpec, recorded_at: datetime
) -> RationaleDocument:
    provenance = RationaleProvenance(
        source="deterministic_tool",
        tool_name=GENERATOR_NAME,
        tool_version=_generator_version(),
        script_hash=_generator_script_hash(),
        recorded_at=recorded_at,
    )
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
                decision=(
                    f"Adopt the declared {node.kind} values for {node.id}: "
                    + _attr_summary(node.attrs, attrs)
                ),
                justification=(
                    f"The design input declares these {node.kind} values for "
                    f"{node.id}; the generator projects them without inventing "
                    "or defaulting any value."
                ),
                driving_requirements=_driving_requirements(spec, node.id),
                no_alternatives_reason=(
                    f"The design input declares a single {node.kind} option for "
                    f"{node.id}."
                ),
                provenance=provenance,
                target_revision=graph.revision,
            )
        )
    return RationaleDocument(
        graph_id=graph.graph_id,
        revision=graph.revision,
        records=records,
    )


def _overwrite_conflicts(
    existing: DesignGraph, generated: DesignGraph
) -> list[GraphOverwriteConflict]:
    """Report existing graph data that regeneration would drop."""
    generated_nodes = {node.id: node for node in generated.nodes}
    conflicts: list[GraphOverwriteConflict] = []
    for node in existing.nodes:
        target = generated_nodes.get(node.id)
        if target is None:
            conflicts.append(
                GraphOverwriteConflict(
                    node_id=node.id,
                    reason="node exists in the written graph but not in the design input",
                )
            )
            continue
        for attr in sorted(node.attrs):
            if attr not in target.attrs:
                conflicts.append(
                    GraphOverwriteConflict(
                        node_id=node.id,
                        attr=attr,
                        reason=(
                            "attribute exists in the written graph but not in the "
                            "design input"
                        ),
                    )
                )
    return conflicts


def _guard_manual_graph(
    out_dir: Path, generated: DesignGraph, overwrite: bool
) -> None:
    graph_path = out_dir / "graph.json"
    if not graph_path.exists():
        return
    try:
        existing = DesignGraph.model_validate_json(
            graph_path.read_text(encoding="utf-8")
        )
    except ValueError as exc:
        raise FixtureBuilderError(
            f"existing graph at {graph_path} cannot be parsed; refusing to overwrite"
        ) from exc
    conflicts = _overwrite_conflicts(existing, generated)
    if not conflicts:
        return
    report_path = out_dir / "graph-overwrite-report.json"
    _write_atomic(
        report_path,
        _canonical(
            {
                "graph_path": str(graph_path),
                "graph_id": existing.graph_id,
                "revision": existing.revision,
                "conflicts": [item.model_dump(mode="json") for item in conflicts],
            }
        ),
    )
    if not overwrite:
        raise FixtureBuilderError(
            f"existing graph at {graph_path} contains data that the design input "
            f"does not declare; see {report_path}"
        )


def build_design_fixture(
    spec: DesignFixtureSpec,
    out_dir: Path,
    *,
    overwrite: bool = False,
) -> DesignGraph:
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
    recorded_at = spec.rationale_recorded_at or datetime.now(UTC)
    rationale = _rationale(graph, spec, recorded_at)
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
    _guard_manual_graph(out_dir, graph, overwrite)
    _write_atomic(out_dir / "graph.json", graph_content)
    _write_atomic(out_dir / "requirements.json", requirements_content)
    _write_atomic(out_dir / "rationale.json", rationale_content)
    return graph


__all__ = [
    "GENERATOR_NAME",
    "FixtureBuilderError",
    "GraphOverwriteConflict",
    "build_design_fixture",
    "build_graph",
]
