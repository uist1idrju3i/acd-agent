"""Electrical-lane visual projection wiring after deterministic gates."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from acd.adapters.kicad.gates import GateError
from acd.adapters.kicad.visual_projection import KicadVisualRenderer
from acd.core.board_model import BoardModel
from acd.core.design_predicates import PredicateResult
from acd.core.electrical import ElectricalLane
from acd.schema.visual_projection import VisualProjectionSet

_PREDICATE_COUNT = 6
_MISSING = object()


def _require_zero(gates: Mapping[str, object], key: str) -> None:
    value = gates.get(key, _MISSING)
    if isinstance(value, bool) or not isinstance(value, int) or value != 0:
        raise GateError(f"visual projection gate {key} did not pass (fail-closed)")


def _require_true(gates: Mapping[str, object], key: str) -> None:
    if gates.get(key, _MISSING) is not True:
        raise GateError(f"visual projection gate {key} did not pass (fail-closed)")


def _require_status(gates: Mapping[str, object], key: str, expected: str) -> None:
    if gates.get(key, _MISSING) != expected:
        raise GateError(f"visual projection gate {key} did not pass (fail-closed)")


def _assert_gates_passed(gates: Mapping[str, object]) -> None:
    _require_zero(gates, "erc_errors")
    _require_zero(gates, "erc_unconnected")
    _require_true(gates, "routing_converged")
    _require_zero(gates, "drc_errors")
    _require_zero(gates, "drc_unconnected")
    _require_true(gates, "independent_reload")
    _require_status(gates, "silkscreen_status", "measured_pass")
    _require_status(gates, "dfm_status", "pass")
    _require_status(gates, "order_readiness_status", "ready")
    predicates_value = gates.get("design_predicates", _MISSING)
    if not isinstance(predicates_value, tuple):
        raise GateError("visual projection design predicates are incomplete (fail-closed)")
    predicates = cast(tuple[object, ...], predicates_value)
    if len(predicates) != _PREDICATE_COUNT:
        raise GateError("visual projection design predicates are incomplete (fail-closed)")
    if not all(
        isinstance(predicate, PredicateResult) and predicate.status == "pass"
        for predicate in predicates
    ):
        raise GateError("visual projection design predicates did not pass (fail-closed)")


def _declared_copper_layers(lane: ElectricalLane, board: BoardModel) -> tuple[str, ...]:
    declarations: list[str] = list(lane.board.ground_plane_layers)
    for zone in board.copper_zones:
        declarations.extend(zone.layers)
    if not declarations:
        raise GateError("visual projection copper layer declaration is missing (fail-closed)")
    layers: list[str] = []
    for layer in declarations:
        if not layer.strip() or not layer.endswith(".Cu"):
            raise GateError("visual projection copper layer declaration is invalid (fail-closed)")
        if layer not in layers:
            layers.append(layer)
    if not layers:
        raise GateError("visual projection copper layer declaration is empty (fail-closed)")
    return tuple(layers)


def _node_id_fragment(value: str) -> str:
    fragment = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not fragment:
        raise GateError("visual projection identifier declaration is invalid (fail-closed)")
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
    gates: Mapping[str, object],
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
    projection_set = VisualProjectionSet.model_validate(
        {
            **projection_set.model_dump(mode="json"),
            "identity_hash": projection_set.computed_identity_hash(),
        }
    )
    projection_set = VisualProjectionSet.model_validate(
        {
            **projection_set.model_dump(mode="json"),
            "canonical_hash": projection_set.computed_canonical_hash(),
        }
    )
    output_path = out_dir / "visual-projections-electrical.json"
    output_path.write_text(
        projection_set.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return projection_set


__all__ = ["generate_electrical_visual_projections"]
