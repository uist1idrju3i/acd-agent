"""Board projection regression tests."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Sequence

import pytest

from acd.adapters.kicad.board import (
    _copper_zone,
    _silk_graphic,
    _silk_text,
    board_keepouts,
)
from acd.core.electrical.board_model import CopperZone, FootprintShape, PadShape
from acd.core.electrical.electrical import BoardView, ComponentView, ElectricalLane, LibraryPin
from acd.core.electrical.sexpr import SExpr
from acd.core.electrical.silkscreen import SilkGraphicPartView, SilkGraphicView, SilkTextView


def _text(layer: str) -> SilkTextView:
    return SilkTextView(
        "silk.text",
        "label",
        "DEV BOARD",
        5.0,
        6.0,
        layer,
        1.0,
        0.15,
        0.0,
        "test",
        "test",
        "SW1",
        0.25,
        1.0,
    )


def _effects(node: Sequence[SExpr]) -> list[SExpr]:
    for child in node:
        if isinstance(child, list) and child and child[0] == "effects":
            return child
    raise AssertionError("effects node missing")


def _zone_child(node: Sequence[SExpr], name: str) -> list[SExpr]:
    for child in node:
        if isinstance(child, list) and child and child[0] == name:
            return child
    raise AssertionError(f"{name} node missing")


def test_copper_zone_always_removes_isolated_islands() -> None:
    board = BoardView(
        node_id="board",
        width_mm=20.0,
        height_mm=15.0,
        layers=2,
        thickness_mm=1.6,
        unit="mm",
        origin="board_upper_left",
        y_axis="down",
        min_track_mm=0.15,
        min_clearance_mm=0.15,
        via_drill_mm=0.3,
        via_diameter_mm=0.6,
        edge_copper_clearance_mm=0.3,
        antenna_keepout=False,
    )
    zone = _copper_zone(CopperZone("GND", ("F.Cu", "B.Cu"), 0.3, 1.25), board, 1, 0)
    fill = _zone_child(zone, "fill")

    assert ["island_removal_mode", "0"] in fill
    assert not any(entry[0] == "island_area_min" for entry in fill)


def _rf_lane(
    pads: tuple[PadShape, ...],
) -> tuple[ElectricalLane, dict[str, FootprintShape]]:
    component = ComponentView(
        node_id="electrical.component.rf",
        refdes="U1",
        value="ESP32-C3-MINI-1",
        mpn="",
        lcsc="",
        jlcpcb_class="none",
        assembly="not_fitted",
        library=LibraryPin(
            symbol="RF:RF_Module",
            symbol_file="",
            symbol_source="",
            symbol_source_ref="",
            symbol_sha256="",
            footprint="Espressif:ESP32-C3-MINI-1",
            footprint_file="",
            footprint_source="",
            footprint_source_ref="",
            footprint_sha256="",
        ),
    )
    board = BoardView(
        node_id="board",
        width_mm=30.0,
        height_mm=25.0,
        layers=2,
        thickness_mm=1.6,
        unit="mm",
        origin="board_upper_left",
        y_axis="down",
        min_track_mm=0.15,
        min_clearance_mm=0.15,
        via_drill_mm=0.3,
        via_diameter_mm=0.6,
        edge_copper_clearance_mm=0.3,
        antenna_keepout=True,
    )
    lane = ElectricalLane(components=(component,), nets=(), pins=(), board=board)
    footprints = {"U1": FootprintShape("Espressif:ESP32-C3-MINI-1", pads)}
    return lane, footprints


def _rf_pad(y_mm: float) -> PadShape:
    return PadShape(
        number="1",
        x_mm=0.0,
        y_mm=y_mm,
        rotation_deg=0.0,
        shape="rect",
        size_x_mm=0.4,
        size_y_mm=0.4,
        through_hole=False,
        drill_mm=None,
        on_front=True,
        on_back=False,
    )


def test_antenna_keepout_skipped_when_module_anchors_off_board_edge() -> None:
    lane, footprints = _rf_lane((_rf_pad(-0.0),))

    assert board_keepouts(lane, footprints) == ()


def test_antenna_keepout_depth_tracks_module_pad_row() -> None:
    lane, footprints = _rf_lane((_rf_pad(3.0),))

    keepouts = board_keepouts(lane, footprints)

    assert len(keepouts) == 1
    rect = keepouts[0]
    assert rect.name == "antenna_keepout"
    assert (rect.x1_mm, rect.y1_mm, rect.x2_mm) == (8.0, 0.0, 22.0)
    assert rect.y2_mm == 2.5


def test_back_silkscreen_text_is_mirrored() -> None:
    effects = _effects(_silk_text(_text("B.SilkS")))
    assert ["justify", "mirror"] in effects


def test_front_silkscreen_text_is_not_mirrored() -> None:
    effects = _effects(_silk_text(_text("F.SilkS")))
    assert ["justify", "mirror"] not in effects


def test_filled_silkscreen_open_contour_fails_closed() -> None:
    graphic = SilkGraphicView(
        "filled",
        "filled",
        "B.SilkS",
        0.0,
        ((1.0, 1.0), (2.0, 1.0), (1.0, 2.0)),
        "test",
        "test",
        parts=(
            SilkGraphicPartView(
                (((1.0, 1.0), (2.0, 1.0), (1.0, 2.0)),),
                0.0,
                fill="solid",
            ),
        ),
    )
    with pytest.raises(ValueError, match="open contour"):
        _silk_graphic(graphic)
