"""Deterministic placement tests."""

from __future__ import annotations

import pytest

from acd_adapter_kicad.placement import PlacementError, compute_placements
from acd_core.board_model import FootprintShape, PadShape
from acd_core.electrical import BoardView, ComponentView, LibraryPin


def _board(width: float = 20.0, height: float = 15.0) -> BoardView:
    return BoardView(
        node_id="board-1",
        width_mm=width,
        height_mm=height,
        layers=2,
        thickness_mm=1.6,
        unit="mm",
        origin="board-upper-left",
        y_axis="down",
        min_track_mm=0.15,
        min_clearance_mm=0.15,
        via_drill_mm=0.3,
        via_diameter_mm=0.6,
        edge_copper_clearance_mm=0.3,
        antenna_keepout=False,
    )


def _component(refdes: str) -> ComponentView:
    return ComponentView(
        node_id=f"comp-{refdes}",
        refdes=refdes,
        value="10k",
        mpn="X",
        lcsc="C1",
        jlcpcb_class="basic",
        assembly="fitted",
        library=LibraryPin(
            symbol="Device:R",
            symbol_file="s",
            symbol_source="kicad-official",
            symbol_source_ref="10.0.5",
            symbol_sha256="sha256:0",
            footprint="Resistor_SMD:R_0603_1608Metric",
            footprint_file="f",
            footprint_source="kicad-official",
            footprint_source_ref="10.0.5",
            footprint_sha256="sha256:0",
        ),
    )


def _footprint() -> FootprintShape:
    pads = tuple(
        PadShape(
            number=str(i + 1),
            x_mm=float(i),
            y_mm=0.0,
            rotation_deg=0.0,
            shape="rect",
            size_x_mm=0.8,
            size_y_mm=0.9,
            through_hole=False,
            drill_mm=None,
            on_front=True,
            on_back=False,
        )
        for i in range(2)
    )
    return FootprintShape(library_ref="Resistor_SMD:R_0603_1608Metric", pads=pads)


def test_compute_placements_is_deterministic() -> None:
    components = tuple(_component(f"R{i}") for i in range(1, 6))
    footprints = {c.refdes: _footprint() for c in components}
    nets = (("R1", "R2"), ("R3", "R4"))
    first = compute_placements(_board(), components, footprints, (), nets)
    second = compute_placements(_board(), components, footprints, (), nets)
    assert first == second


def test_connected_components_placed_near_each_other() -> None:
    components = tuple(_component(f"R{i}") for i in range(1, 4))
    footprints = {c.refdes: _footprint() for c in components}
    placements = {
        p.refdes: p
        for p in compute_placements(_board(), components, footprints, (), (("R1", "R3"),))
    }
    d_connected = abs(placements["R1"].x_mm - placements["R3"].x_mm) + abs(
        placements["R1"].y_mm - placements["R3"].y_mm
    )
    d_unconnected = abs(placements["R1"].x_mm - placements["R2"].x_mm) + abs(
        placements["R1"].y_mm - placements["R2"].y_mm
    )
    assert d_connected <= d_unconnected + 1e-9


def test_placement_fails_closed_when_board_is_too_small() -> None:
    components = tuple(_component(f"R{i}") for i in range(1, 30))
    footprints = {c.refdes: _footprint() for c in components}
    with pytest.raises(PlacementError, match="no placement found"):
        compute_placements(_board(width=4.0, height=4.0), components, footprints, ())
