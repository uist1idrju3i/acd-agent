"""DSN export tests: coordinate frame, duplicate pad ids, hole keepouts."""

from __future__ import annotations

from acd_adapter_freerouting.dsn import export_dsn
from acd_core.board_model import (
    BoardModel,
    BoardNet,
    ComponentPlacement,
    FootprintShape,
    PadShape,
)


def _pad(number: str, x: float = 0.0, drill: float | None = None) -> PadShape:
    return PadShape(
        number=number,
        x_mm=x,
        y_mm=0.0,
        rotation_deg=0.0,
        shape="rect",
        size_x_mm=1.0,
        size_y_mm=1.0,
        through_hole=drill is not None,
        drill_mm=drill,
        on_front=True,
        on_back=drill is not None,
    )


def _model(footprint: FootprintShape) -> BoardModel:
    return BoardModel(
        width_mm=20.0,
        height_mm=10.0,
        layers=2,
        min_track_mm=0.15,
        min_clearance_mm=0.15,
        via_drill_mm=0.3,
        via_diameter_mm=0.6,
        edge_clearance_mm=0.3,
        placements=(
            ComponentPlacement(
                refdes="R1", footprint=footprint, x_mm=5.0, y_mm=2.0, rotation_deg=0.0
            ),
        ),
        nets=(BoardNet(name="A", pads=(("R1", "1"),)),),
    )


def test_export_dsn_flips_y_and_uses_micrometres() -> None:
    footprint = FootprintShape(library_ref="Lib:R", pads=(_pad("1"), _pad("2", x=2.0)))
    dsn = export_dsn(_model(footprint), "t1")
    # placement at (5.0, 2.0) mm -> (5000, -2000) um with Y-up.
    assert "5000 -2000" in dsn


def test_export_dsn_disambiguates_duplicate_pad_numbers() -> None:
    footprint = FootprintShape(
        library_ref="Lib:SOT", pads=(_pad("1"), _pad("2", x=2.0), _pad("2", x=4.0))
    )
    dsn = export_dsn(_model(footprint), "t2")
    assert "2@1" in dsn


def test_export_dsn_emits_hole_keepouts_for_unnumbered_drills() -> None:
    footprint = FootprintShape(library_ref="Lib:H", pads=(_pad("1"), _pad("", x=3.0, drill=2.2)))
    dsn = export_dsn(_model(footprint), "t3")
    assert "keepout" in dsn
