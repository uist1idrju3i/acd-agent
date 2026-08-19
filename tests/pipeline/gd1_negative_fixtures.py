"""Deterministic GD1 negative-input injections used by regression tests."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from acd.adapters.kicad.board import generate_board
from acd.adapters.kicad.library import FootprintLibrary
from acd.adapters.kicad.placement import Placement
from acd.core.board_model import BoardModel, KeepoutRect
from acd.core.electrical import ElectricalLane, extract_electrical_lane
from acd.core.fab import FabProfile, load_fab_profile
from acd.schema import DesignGraph
from acd.schema.design_graph import GraphNode

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "fixtures" / "golden-design-1"
FAB_PROFILE_PATH = ROOT / "profiles" / "jlcpcb" / "fab-profile-jlcpcb-fr4-2l-1oz.json"


def load_gd1_graph() -> DesignGraph:
    return DesignGraph.model_validate(
        json.loads((FIXTURE_DIR / "graph.json").read_text(encoding="utf-8"))
    )


def _map_nodes(
    graph: DesignGraph, update: Callable[[GraphNode], GraphNode | None]
) -> DesignGraph:
    nodes: list[GraphNode] = []
    for node in graph.nodes:
        replacement = update(node)
        if replacement is not None:
            nodes.append(replacement)
    return graph.model_copy(update={"nodes": nodes})


def _attrs(node: GraphNode, **updates: object) -> GraphNode:
    return node.model_copy(update={"attrs": {**node.attrs, **updates}})


def inject_gd1_neg_001_led_to_strapping(graph: DesignGraph) -> DesignGraph:
    """Assign the existing LED firmware function to GPIO8."""
    return _map_nodes(
        graph,
        lambda node: _attrs(node, gpio=8)
        if node.id == "fw.pin.led"
        else node,
    )


def inject_gd1_neg_003_remove_cc_resistor(graph: DesignGraph) -> DesignGraph:
    """Remove the CC1 resistor and its two electrical pins."""
    removed = {"comp.r1", "pin.r1.1", "pin.r1.2"}
    return _map_nodes(graph, lambda node: None if node.id in removed else node)


def inject_gd1_neg_004_remove_i2c_pullup(graph: DesignGraph) -> DesignGraph:
    """Remove the I2C SDA pull-up and its two electrical pins."""
    removed = {"comp.r4", "pin.r4.1", "pin.r4.2"}
    return _map_nodes(graph, lambda node: None if node.id in removed else node)


def inject_gd1_neg_005_mismatch_firmware_gpio(graph: DesignGraph) -> DesignGraph:
    """Change the SDA firmware GPIO without changing the graph wiring."""
    return _map_nodes(
        graph,
        lambda node: _attrs(node, gpio=5)
        if node.id == "fw.pin.i2c_sda"
        else node,
    )


def inject_gd1_neg_006_remove_library_evidence(graph: DesignGraph) -> DesignGraph:
    """Replace one pinned library hash with an unverifiable value."""
    return _map_nodes(
        graph,
        lambda node: _attrs(node, footprint_sha256="sha256:" + "0" * 64)
        if node.id == "comp.u1"
        else node,
    )


def inject_gd1_neg_008_unknown_coordinate_unit(graph: DesignGraph) -> DesignGraph:
    """Make the board coordinate unit unknown."""
    return _map_nodes(
        graph,
        lambda node: _attrs(node, unit="unknown")
        if node.kind == "electrical.board"
        else node,
    )


def extract_fixture_lane(graph: DesignGraph) -> ElectricalLane:
    return extract_electrical_lane(graph)


def load_fixture_fab_profile() -> FabProfile:
    return load_fab_profile(FAB_PROFILE_PATH)


def _placements_from_graph(
    graph: DesignGraph, lane: ElectricalLane
) -> tuple[Placement, ...]:
    components = {
        str(node.attrs["refdes"]): node.attrs
        for node in graph.nodes
        if node.kind == "electrical.component" and "refdes" in node.attrs
    }
    placements: list[Placement] = []
    for component in lane.components:
        attrs = components[component.refdes]
        placements.append(
            Placement(
                component.refdes,
                _placement_number(attrs, "placement_x_mm", component.refdes),
                _placement_number(attrs, "placement_y_mm", component.refdes),
                _placement_number(attrs, "placement_rotation_deg", component.refdes),
            )
        )
    return tuple(placements)


def _placement_number(attrs: Mapping[str, object], key: str, refdes: str) -> float:
    value = attrs.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{refdes}: graph placement is malformed")
    return float(value)


def normal_board_model(graph: DesignGraph):
    """Build the normal GD1 board model before a physical injection."""
    lane = extract_electrical_lane(graph)
    projection = generate_board(
        lane,
        FootprintLibrary(),
        FIXTURE_DIR,
        load_fixture_fab_profile(),
        _placements_from_graph(graph, lane),
    )
    return projection.model


def inject_gd1_neg_002_ground_plane(model: BoardModel) -> BoardModel:
    """Place a GND copper region beneath the module antenna keepout."""
    return replace(
        model,
        keepouts=(KeepoutRect("antenna_keepout", 8.0, 0.0, 22.0, 4.6),),
    )


def conductor_region_with_stitch_flashes(
    *,
    width_mm: float,
    height_mm: float,
    inset_mm: float,
    stitch_points: tuple[tuple[float, float], ...],
) -> str:
    """Return a filled conductor region with deterministic perimeter flashes."""
    scale = 1_000_000
    x1 = int(inset_mm * scale)
    y1 = int(inset_mm * scale)
    x2 = int((width_mm - inset_mm) * scale)
    y2 = int((height_mm - inset_mm) * scale)
    result = (
        "%FSLAX46Y46*%\n%MOMM*%\n"
        "%ADD10C,0.6*%\n"
        "G04 #@! TA.AperFunction,Conductor*\nG36*\nG01*\n"
        f"X{x1}Y-{y1}D02*X{x2}Y-{y1}D01*X{x2}Y-{y2}D01*"
        f"X{x1}Y-{y2}D01*X{x1}Y-{y1}D01*G37*\n"
        "G04 #@! TD.AperFunction*\nD10*\n"
    )
    for x, y in stitch_points:
        result += f"X{int(x * scale)}Y-{int(y * scale)}D03*\n"
    return result + "M02*\n"
