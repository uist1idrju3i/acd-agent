"""Deterministic fixture builder for arbitrary design specifications."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Final

from acd.core.cpl_orientation import cpl_orientation_attrs
from acd.core.decoupling_placement import (
    DecouplingPlacementError,
    DecouplingPlacementReport,
    apply_decoupling_placements,
    solve_decoupling_placements,
)
from acd.core.electrical import GraphExtractionError
from acd.core.functional_blocks import load_functional_block_registry
from acd.core.library_assets import (
    LibraryAssetError,
    materialize_library_assets,
    verify_materialized_library_assets,
)
from acd.core.part_selection import PartSelectionError, select_part
from acd.core.pin_functions import pin_function_attrs
from acd.core.rationale import (
    REQUIRED_RATIONALE_ATTRS,
    check_rationale_coverage,
    subject_hash_for,
    summarize_rationale_coverage,
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
        "mechanical.component_body": "placement",
        "mechanical.connector_opening": "mechanical",
        "mechanical.board_edge_overhang": "mechanical",
        "mechanical.enclosure": "mechanical",
        "safety.boundary": "safety_scope",
        "mechanical.silk_text": "silkscreen",
        "mechanical.silk_graphic": "silkscreen",
        "fab.order_intent": "fab_process",
        "fab.process_allowance": "fab_process",
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
    nodes.extend(_enclosure_nodes(spec, graph_id, known_refs, requirement_ids))
    if spec.safety_boundary is not None:
        nodes.append(
            GraphNode(
                id=spec.safety_boundary.node_id or f"sb.{graph_id}",
                kind="safety.boundary",
                attrs=spec.safety_boundary.attrs,
            )
        )
    nodes.extend(_firmware_module_nodes(spec, graph_id, known_refs))
    if spec.fab_order_intent is not None and spec.fab_profile_id is None:
        raise FixtureBuilderError("fab_order_intent requires fab_profile_id")
    if spec.fab_profile_id is not None:
        order_intent = spec.fab_order_intent
        order_depends = [board_id]
        order_attrs: dict[str, AttrValue] = {"fab_profile": spec.fab_profile_id}
        if order_intent is not None:
            if order_intent.requirement_id is not None:
                if order_intent.requirement_id not in requirement_ids:
                    raise FixtureBuilderError(
                        "fab_order_intent references unknown requirement: "
                        f"{order_intent.requirement_id}"
                    )
                order_depends.append(f"req.{order_intent.requirement_id}")
            order_attrs.update(order_intent.attrs)
        nodes.append(
            GraphNode(
                id=f"fab.order_intent.{graph_id}",
                kind="fab.order_intent",
                attrs=order_attrs,
                depends_on=order_depends,
            )
        )
    if spec.fab_process_allowances and spec.fab_profile_id is None:
        raise FixtureBuilderError("fab_process_allowances require fab_profile_id")
    for allowance in spec.fab_process_allowances:
        if allowance.requirement_id not in requirement_ids:
            raise FixtureBuilderError(
                f"fab_process_allowances references unknown requirement: {allowance.requirement_id}"
            )
        requirement_node = f"req.{allowance.requirement_id}"
        nodes.append(
            GraphNode(
                id=f"fab.process_allowance.{allowance.rule_id}",
                kind="fab.process_allowance",
                attrs={
                    "rule_id": allowance.rule_id,
                    "reason": allowance.reason,
                    "requirement": requirement_node,
                    "impact_accepted": list(allowance.impact_accepted),
                },
                depends_on=[requirement_node, board_id],
            )
        )
    return DesignGraph(graph_id=graph_id, revision=spec.revision, nodes=nodes)


def _mechanical_nodes(spec: DesignFixtureSpec, graph_id: str, board_id: str) -> list[GraphNode]:
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


def _component_id_for(refdes: str, known_refs: set[str], context: str) -> str:
    if refdes not in known_refs:
        raise FixtureBuilderError(f"{context} references unknown component refdes: {refdes}")
    return f"comp.{refdes.lower()}"


def _enclosure_nodes(
    spec: DesignFixtureSpec, graph_id: str, known_refs: set[str], requirement_ids: set[str]
) -> list[GraphNode]:
    """Project declared bodies, openings, overhangs, and the enclosure without defaults."""
    nodes: list[GraphNode] = []
    for body in sorted(spec.component_bodies, key=lambda item: item.node_id):
        component_id = _component_id_for(body.refdes, known_refs, f"component body {body.node_id}")
        nodes.append(
            GraphNode(
                id=body.node_id,
                kind="mechanical.component_body",
                attrs=body.attrs,
                depends_on=[component_id],
            )
        )
    for opening in sorted(spec.connector_openings, key=lambda item: item.node_id):
        component_id = _component_id_for(
            opening.refdes, known_refs, f"connector opening {opening.node_id}"
        )
        nodes.append(
            GraphNode(
                id=opening.node_id,
                kind="mechanical.connector_opening",
                attrs={"connector": component_id, **opening.attrs},
                depends_on=[component_id],
            )
        )
    if spec.enclosure is not None:
        nodes.append(
            GraphNode(
                id=spec.enclosure.node_id or f"mechanical.enclosure.{graph_id}",
                kind="mechanical.enclosure",
                attrs=spec.enclosure.attrs,
                depends_on=[node.id for node in nodes],
            )
        )
    for overhang in sorted(spec.board_edge_overhangs, key=lambda item: item.node_id):
        component_id = _component_id_for(
            overhang.refdes, known_refs, f"board edge overhang {overhang.node_id}"
        )
        if overhang.requirement_id not in requirement_ids:
            raise FixtureBuilderError(
                f"board edge overhang {overhang.node_id} references unknown requirement: "
                f"{overhang.requirement_id}"
            )
        requirement_node = f"req.{overhang.requirement_id}"
        nodes.append(
            GraphNode(
                id=overhang.node_id,
                kind="mechanical.board_edge_overhang",
                attrs={
                    "component_refdes": overhang.refdes,
                    "requirement_id": requirement_node,
                    **overhang.attrs,
                },
                depends_on=[component_id, requirement_node],
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
                "firmware transition references unknown states: " + ", ".join(unknown_states)
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
        f"{key}={json.dumps(attrs[key], ensure_ascii=False, sort_keys=True)}" for key in keys
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
                    f"The design input declares a single {node.kind} option for {node.id}."
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
                            "attribute exists in the written graph but not in the design input"
                        ),
                    )
                )
    return conflicts


def _guard_manual_graph(out_dir: Path, generated: DesignGraph, overwrite: bool) -> None:
    graph_path = out_dir / "graph.json"
    if not graph_path.exists():
        return
    try:
        existing = DesignGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise FixtureBuilderError(
            f"existing graph at {graph_path} cannot be parsed; refusing to overwrite"
        ) from exc
    conflicts = _overwrite_conflicts(existing, generated)
    if not conflicts:
        return
    existing_text = graph_path.read_text(encoding="utf-8")
    report: dict[str, object] = {
        "graph_path": str(graph_path),
        "graph_id": existing.graph_id,
        "revision": existing.revision,
        "existing_content_hash": "sha256:"
        + hashlib.sha256(existing_text.encode("utf-8")).hexdigest(),
        "conflicts": [item.model_dump(mode="json") for item in conflicts],
    }
    if overwrite:
        # Explicit overwrite never destroys manually written data: the graph is
        # preserved verbatim next to the report so the dropped declarations stay
        # reviewable and the overwrite stays reversible.
        backup_path = out_dir / "graph.overwritten.json"
        _write_atomic(backup_path, existing_text)
        report["backup_path"] = str(backup_path)
    report_path = out_dir / "graph-overwrite-report.json"
    _write_atomic(report_path, _canonical(report))
    if not overwrite:
        raise FixtureBuilderError(
            f"existing graph at {graph_path} contains data that the design input "
            f"does not declare; see {report_path}"
        )


def _normalize_decoupling_placement(graph: DesignGraph, out_dir: Path) -> DesignGraph:
    """Place declared decoupling capacitors inside their pinned distance limits.

    The solver keeps a satisfied design input unchanged, so an existing fixture
    keeps its normalized graph hash. An unsatisfiable pair is reported and the
    build stops fail-closed rather than emitting a placement that the
    authoritative ``power_decoupling`` predicate rejects.
    """
    declared = any(
        node.kind == "electrical.component" and isinstance(node.attrs.get("decoupling_target"), str)
        for node in graph.nodes
    )
    if not declared:
        return graph
    try:
        report = solve_decoupling_placements(graph, out_dir)
    except (DecouplingPlacementError, GraphExtractionError, OSError, ValueError) as exc:
        raise FixtureBuilderError(f"decoupling placement could not be resolved: {exc}") from exc
    if not report.placements and not report.deficiencies:
        return graph
    _write_decoupling_report(out_dir, report)
    if report.deficiencies:
        reasons = "; ".join(
            f"{item.refdes}->{item.target_refdes}: {item.reason}" for item in report.deficiencies
        )
        raise FixtureBuilderError(
            "declared decoupling placement is not satisfiable: "
            + reasons
            + f"; see {out_dir / 'decoupling-placement-report.json'}"
        )
    return apply_decoupling_placements(graph, report)


def _write_decoupling_report(out_dir: Path, report: DecouplingPlacementReport) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_atomic(
        out_dir / "decoupling-placement-report.json",
        _canonical(report.as_payload()),
    )


def _copy_declared_overlays(graph: DesignGraph, spec_dir: Path | None, out_dir: Path) -> None:
    """Copy declared footprint overlays next to the graph, pinned by declared sha256."""
    for node in graph.nodes:
        if node.kind != "electrical.component":
            continue
        overlay_file = node.attrs.get("overlay_file")
        overlay_sha256 = node.attrs.get("overlay_sha256")
        if overlay_file is None and overlay_sha256 is None:
            continue
        if not isinstance(overlay_file, str) or not isinstance(overlay_sha256, str):
            raise FixtureBuilderError(
                f"{node.id}: overlay_file and overlay_sha256 must be declared together"
            )
        if spec_dir is None:
            raise FixtureBuilderError(
                f"{node.id}: overlay {overlay_file} requires the design input directory"
            )
        relative = Path(overlay_file)
        if relative.is_absolute() or ".." in relative.parts:
            raise FixtureBuilderError(f"{node.id}: overlay_file must be a relative path")
        source = spec_dir / relative
        if not source.is_file():
            raise FixtureBuilderError(f"{node.id}: overlay file missing: {source}")
        actual = f"sha256:{hashlib.sha256(source.read_bytes()).hexdigest()}"
        if actual != overlay_sha256:
            raise FixtureBuilderError(
                f"{node.id}: overlay hash mismatch for {source}: "
                f"declared {overlay_sha256}, got {actual}"
            )
        destination = out_dir / relative
        if source.resolve() == destination.resolve():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def build_design_fixture(
    spec: DesignFixtureSpec,
    out_dir: Path,
    *,
    overwrite: bool = False,
    spec_dir: Path | None = None,
) -> DesignGraph:
    """Build and atomically write graph, requirements, and rationale documents."""
    registry = load_functional_block_registry()
    known_blocks = {contract.block_id for contract in registry.contracts}
    unknown_blocks = sorted(
        {item.block_id for item in spec.functional_blocks if item.block_id not in known_blocks}
    )
    if unknown_blocks:
        raise FixtureBuilderError("unknown functional blocks: " + ", ".join(unknown_blocks))
    graph = build_graph(spec)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        materialize_library_assets(graph, out_dir)
    except LibraryAssetError as exc:
        raise FixtureBuilderError(
            f"declared library assets could not be materialized: {exc}"
        ) from exc
    graph = _normalize_decoupling_placement(graph, out_dir)
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
            + summarize_rationale_coverage(coverage)
            + "; next step: add rationale records in the design input "
            "(DesignFixtureSpec) for missing/stale subjects; unclassified attrs "
            "are not part of the rationale contract, so remove them from the "
            "design input or propose the contract change in a separate PR "
            "(see docs/operations.md rationale coverage)"
        )
    graph_content = _canonical(graph.model_dump(mode="json"))
    requirements_content = _canonical(requirements.model_dump(mode="json"))
    rationale_content = _canonical(rationale.model_dump(mode="json"))
    out_dir.mkdir(parents=True, exist_ok=True)
    _guard_manual_graph(out_dir, graph, overwrite)
    _write_atomic(out_dir / "graph.json", graph_content)
    _write_atomic(out_dir / "requirements.json", requirements_content)
    _write_atomic(out_dir / "rationale.json", rationale_content)
    _copy_declared_overlays(graph, spec_dir, out_dir)
    try:
        verify_materialized_library_assets(graph, out_dir)
    except LibraryAssetError as exc:
        raise FixtureBuilderError(
            f"generated fixture library assets are inconsistent: {exc}"
        ) from exc
    return graph


__all__ = [
    "GENERATOR_NAME",
    "DecouplingPlacementReport",
    "FixtureBuilderError",
    "GraphOverwriteConflict",
    "build_design_fixture",
    "build_graph",
]
