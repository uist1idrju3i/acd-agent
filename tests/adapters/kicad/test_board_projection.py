"""Board projection regression tests."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Sequence

import pytest

from acd.adapters.kicad.board import _copper_zone, _silk_graphic, _silk_text
from acd.core.board_model import CopperZone
from acd.core.electrical import BoardView
from acd.core.sexpr import SExpr
from acd.core.silkscreen import SilkGraphicPartView, SilkGraphicView, SilkTextView


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


def test_copper_zone_emits_minimum_island_area_fill_settings() -> None:
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

    assert ["island_removal_mode", "2"] in fill
    assert ["island_area_min", "1.25"] in fill


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
