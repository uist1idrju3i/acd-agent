"""Electrical-lane visual projection wiring after deterministic gates."""

from __future__ import annotations

import re
from pathlib import Path

from acd.adapters.kicad.gates import GateError
from acd.adapters.kicad.visual_projection import KicadVisualRenderer
from acd.core.board_model import BoardModel
from acd.core.electrical import ElectricalLane
from acd.schema.visual_projection import (
    ElectricalVisualProjectionGates,
    VisualProjectionSet,
)


def _assert_gates_passed(gates: ElectricalVisualProjectionGates) -> None:
    if gates.erc_errors != 0:
        raise GateError("visual projection gate erc_errors did not pass (fail-closed)")
    if gates.erc_unconnected != 0:
        raise GateError("visual projection gate erc_unconnected did not pass (fail-closed)")
    if not gates.routing_converged:
        raise GateError("visual projection gate routing_converged did not pass (fail-closed)")
    if gates.drc_errors != 0:
        raise GateError("visual projection gate drc_errors did not pass (fail-closed)")
    if gates.drc_unconnected != 0:
        raise GateError("visual projection gate drc_unconnected did not pass (fail-closed)")
    if not gates.independent_reload:
        raise GateError("visual projection gate independent_reload did not pass (fail-closed)")
    if gates.silkscreen_status != "measured_pass":
        raise GateError("visual projection gate silkscreen_status did not pass (fail-closed)")
    if gates.dfm_status != "pass":
        raise GateError("visual projection gate dfm_status did not pass (fail-closed)")
    if any(predicate.status != "pass" for predicate in gates.design_predicates):
        raise GateError("visual projection design predicates did not pass (fail-closed)")


def _declared_copper_layers(lane: ElectricalLane, board: BoardModel) -> tuple[str, ...]:
    explicit_layers = (
        board.copper_layers
        if board.copper_layers is not None
        else lane.board.copper_layers
    )
    if explicit_layers is not None:
        declarations = list(explicit_layers)
        if not declarations:
            raise ValueError("visual projection copper layer declaration is empty")
    else:
        declarations = list(lane.board.ground_plane_layers)
        for zone in board.copper_zones:
            declarations.extend(zone.layers)
    if not declarations:
        raise ValueError("visual projection copper layer declaration is missing")
    layers: list[str] = []
    for layer in declarations:
        if not layer.strip() or not layer.endswith(".Cu"):
            raise ValueError("visual projection copper layer declaration is invalid")
        if layer not in layers:
            layers.append(layer)
    if not layers:
        raise ValueError("visual projection copper layer declaration is empty")
    return tuple(layers)


def _node_id_fragment(value: str) -> str:
    fragment = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not fragment:
        raise ValueError("visual projection identifier declaration is invalid")
    return fragment


def generate_electrical_visual_projections(
    *,
    project_name: str,
    out_dir: Path,
    source_revision: str,
    schematic: Path,
    routed_board: Path,
    lane: ElectricalLane,
    board: BoardModel,
    gates: ElectricalVisualProjectionGates,
    renderer: KicadVisualRenderer | None = None,
) -> VisualProjectionSet:
    """Generate the electrical visual projection set after passing all gates."""
    _assert_gates_passed(gates)
    layers = _declared_copper_layers(lane, board)
    visual_dir = out_dir / "visual"
    visual_dir.mkdir(parents=True, exist_ok=True)
    renderer = renderer or KicadVisualRenderer()
    project_fragment = _node_id_fragment(project_name)
    records = [
        renderer.render(
            projection_id=f"{project_fragment}-schematic",
            projection_type="schematic_view",
            domain="electrical",
            source_revision=source_revision,
            source=schematic,
            output_path=visual_dir / f"{project_fragment}-schematic.svg",
            base_dir=out_dir,
        )
    ]
    for layer in layers:
        layer_fragment = _node_id_fragment(layer)
        records.append(
            renderer.render(
                projection_id=f"{project_fragment}-{layer_fragment}",
                projection_type="layered_layout_view",
                domain="electrical",
                source_revision=source_revision,
                source=routed_board,
                output_path=visual_dir / f"{project_fragment}-{layer_fragment}.svg",
                layer=layer,
                base_dir=out_dir,
            )
        )
    if not records:
        raise GateError("visual projection generation produced no records (fail-closed)")
    records.sort(key=lambda record: record.projection_id)
    projection_set = VisualProjectionSet(
        source_revision=source_revision,
        projections=records,
    )
    projection_set = projection_set.with_computed_hashes()
    output_path = out_dir / "visual-projections-electrical.json"
    output_path.write_text(
        projection_set.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return projection_set


__all__ = ["generate_electrical_visual_projections"]
