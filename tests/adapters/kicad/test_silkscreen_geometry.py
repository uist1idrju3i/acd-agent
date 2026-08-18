"""Independent silkscreen geometry negative controls."""

# These tests intentionally exercise adapter-private geometry primitives.
# pyright: reportPrivateUsage=false, reportPrivateImportUsage=false, reportUnknownMemberType=false, reportUnknownLambdaType=false

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from acd.adapters.kicad import fab
from acd.adapters.kicad.fab import (
    BoardMeasurement,
    FabOutputError,
    FootprintMeasurement,
)
from acd.adapters.kicad.fab.routed_board import parse_routed_board
from acd.adapters.kicad.fab.silkscreen import (
    _local_silk_bounds,
    _same_side,
    _silk_objects_overlap,
    _silk_overlaps_rect,
    _SilkObject,
    _text_attribution_overflow,
    _text_model_size,
)
from acd.core.fab import FabProfile
from acd.core.silkscreen import SilkGraphicView, SilkscreenLane, SilkTextView


def _line(x1: float, y1: float, x2: float, y2: float) -> _SilkObject:
    return _SilkObject(
        "Line",
        "F.SilkS",
        (min(x1, x2) - 0.075, min(y1, y2) - 0.075, max(x1, x2) + 0.075, max(y1, y2) + 0.075),
        1.0,
        0.15,
        (x1, y1),
        (x2, y2),
    )


def test_silk_on_pad_is_rejected() -> None:
    assert _silk_overlaps_rect(_line(1.0, 1.0, 2.0, 1.0), (1.2, 0.8, 1.8, 1.2))


def test_opposite_side_pad_is_ignored_by_gate() -> None:
    assert not _same_side("F.SilkS", ("B.Cu",))


def test_through_hole_pad_is_an_obstacle_on_both_sides() -> None:
    assert _same_side("F.SilkS", ("F.Cu", "B.Cu"))
    assert _same_side("B.SilkS", ("F.Cu", "B.Cu"))


def test_silk_over_mask_flash_is_rejected() -> None:
    silk = _line(1.0, 1.0, 2.0, 1.0)
    mask = _SilkObject(
        "Flash",
        "F.Mask",
        (1.4, 0.8, 1.6, 1.2),
        0.1,
        0.4,
        center_mm=(1.5, 1.0),
        radius_mm=0.2,
    )
    assert _silk_objects_overlap(silk, mask)


def test_rotated_text_height_uses_declared_local_coordinates() -> None:
    silk = _line(1.0, 1.0, 2.0, 1.0)
    local_bbox = _local_silk_bounds((silk,), (1.5, 1.0), 90.0)
    assert local_bbox[3] - local_bbox[1] == pytest.approx(1.0)


def test_stroke_font_self_ink_fits_attribution_upper_bound() -> None:
    text = SilkTextView(
        "text",
        "label",
        "RESET",
        1.0,
        1.0,
        "F.SilkS",
        1.0,
        0.15,
        0.0,
        "test",
        "test",
        "SW1",
        0.25,
        1.0,
    )
    assert _text_attribution_overflow(text, 4.34, 1.15) == ()


def test_ink_beyond_attribution_upper_bound_fails_closed() -> None:
    text = SilkTextView(
        "text",
        "label",
        "RESET",
        1.0,
        1.0,
        "F.SilkS",
        1.0,
        0.15,
        0.0,
        "test",
        "test",
        "SW1",
        0.25,
        1.0,
    )
    overflow = _text_attribution_overflow(text, 5.3, 1.15)
    assert overflow
    assert overflow[0]["dimension"] == "length"


def test_descender_text_uses_extended_orthogonal_upper_bound() -> None:
    _, descender_height = _text_model_size("golden", 1.0, 0.15)
    _, uppercase_height = _text_model_size("BOOT", 1.0, 0.15)
    assert descender_height == pytest.approx(1.6)
    assert uppercase_height == pytest.approx(1.15)


def test_descender_self_ink_fits_extended_attribution_bound() -> None:
    text = SilkTextView(
        "text",
        "label",
        "golden",
        1.0,
        1.0,
        "B.SilkS",
        1.0,
        0.15,
        0.0,
        "test",
        "test",
        "board.gd1",
        0.25,
        1.0,
    )
    assert _text_attribution_overflow(text, 5.0, 1.388) == ()


def test_graphic_below_capability_is_not_treated_as_pass() -> None:
    graphic = _SilkObject(
        "Line",
        "F.SilkS",
        (1.0, 1.45, 2.0, 1.55),
        0.01,
        0.1,
        (1.0, 1.5),
        (2.0, 1.5),
    )
    profile = FabProfile(
        {
            "capabilities": {
                "min_silk_width": {"value": 0.15},
                "min_silk_height": {"value": 1.0},
            }
        }
    )
    original = fab._gerber_silk_objects
    fab._gerber_silk_objects = lambda _path, _layer: (graphic,)
    try:
        with pytest.raises(FabOutputError, match="below fab capability"):
            fab.measure_silkscreen(
                {"F.SilkS": Path("silk.gto")},
                {"F.Mask": Path("mask.gts")},
                Path("edge.gm1"),
                BoardMeasurement((), (), None, None, None, (0.0, 0.0, 3.0, 3.0), (), 0),
                SilkscreenLane(
                    "board.gd1",
                    (),
                    (
                        SilkGraphicView(
                            "graphic",
                            "logo",
                            "F.SilkS",
                            0.1,
                            ((1.0, 1.0), (2.0, 1.0), (2.0, 2.0)),
                            "test",
                            "test",
                        ),
                    ),
                ),
                profile,
            )
    finally:
        fab._gerber_silk_objects = original


def test_same_side_courtyard_overlap_is_rejected() -> None:
    profile = FabProfile(
        {
            "capabilities": {
                "min_silk_width": {"value": 0.15},
                "min_silk_height": {"value": 1.0},
            }
        }
    )
    silk = _line(1.0, 1.0, 2.0, 1.0)
    edge = _line(0.0, 0.0, 3.0, 0.0)
    original = fab._gerber_silk_objects
    fab._gerber_silk_objects = (
        lambda _path, layer: (silk,)
        if layer == "F.SilkS"
        else (edge,)
        if layer == "Edge.Cuts"
        else ()
    )
    try:
        with pytest.raises(FabOutputError, match="courtyard=1"):
            fab.measure_silkscreen(
                {"F.SilkS": Path("silk.gto")},
                {"F.Mask": Path("mask.gts")},
                Path("edge.gm1"),
                BoardMeasurement(
                    (
                        FootprintMeasurement(
                            "U1",
                            1.5,
                            1.0,
                            0.0,
                            "F.Cu",
                            (),
                            courtyard_bbox_mm=(0.5, 0.5, 2.5, 1.5),
                        ),
                    ),
                    (),
                    None,
                    None,
                    None,
                    (0.0, 0.0, 3.0, 3.0),
                    (),
                    0,
                ),
                SilkscreenLane(
                    "board.gd1",
                    (),
                    (
                        SilkGraphicView(
                            "graphic",
                            "logo",
                            "F.SilkS",
                            0.15,
                            ((1.0, 1.0), (2.0, 1.0), (2.0, 2.0)),
                            "test",
                            "test",
                        ),
                    ),
                ),
                profile,
            )
    finally:
        fab._gerber_silk_objects = original


def test_routed_board_layers_reach_silkscreen_fail_conditions(tmp_path: Path) -> None:
    board_path = tmp_path / "minimal.kicad_pcb"
    board_path.write_text(
        """(kicad_pcb
  (version 20240108)
  (generator pcbnew)
  (general (thickness 1.6))
  (paper "A4")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal)
    (36 "B.SilkS" user "b.silkscreen") (37 "F.SilkS" user "f.silkscreen")
    (44 "Edge.Cuts" user))
  (setup (pad_to_mask_clearance 0))
  (net 0 "")
  (footprint "Test:U1"
    (layer "F.Cu")
    (at 5 5)
    (fp_text reference "U1" (at 0 0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (fp_rect (start -1 -1) (end 1 1)
      (stroke (width 0.1) (type default)) (fill none) (layer "F.Fab"))
    (fp_rect (start -1.5 -1.5) (end 1.5 1.5)
      (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))
  )
  (footprint "Test:U2"
    (layer "B.Cu")
    (at 8 8)
    (fp_text reference "U2" (at 0 0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
  )
  (gr_rect (start 0 0) (end 10 10)
    (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts"))
)""",
        encoding="utf-8",
    )
    measurement = parse_routed_board(board_path)
    assert {fp.layer for fp in measurement.footprints} == {"F.Cu", "B.Cu"}

    profile = FabProfile(
        {
            "capabilities": {
                "min_silk_width": {"value": 0.15},
                "min_silk_height": {"value": 1.0},
            }
        }
    )
    silk = _SilkObject("Region", "F.SilkS", (4.0, 4.5, 6.0, 5.5), 2.0, 0.15)
    edge = _line(0.0, 0.0, 10.0, 0.0)
    original = fab._gerber_silk_objects
    fab._gerber_silk_objects = (
        lambda _path, layer: (silk,)
        if layer == "F.SilkS"
        else (edge,)
        if layer == "Edge.Cuts"
        else ()
    )
    try:
        context = fab.build_silkscreen_context(
            {"F.SilkS": Path("silk.gto")},
            {"F.Mask": Path("mask.gts")},
            Path("edge.gm1"),
            measurement,
            SilkscreenLane(
                "board.gd1",
                (
                    SilkTextView(
                        "text",
                        "label",
                        "BOOT",
                        5.0,
                        5.0,
                        "F.SilkS",
                        1.0,
                        0.15,
                        0.0,
                        "test",
                        "test",
                        "U1",
                        0.25,
                        1.0,
                    ),
                ),
                (),
            ),
            profile,
        )
    finally:
        fab._gerber_silk_objects = original

    assert context["status"] == "measured_fail"
    fail_conditions = cast(dict[str, object], context["fail_conditions"])
    assert fail_conditions["body_overlap"]
    assert fail_conditions["courtyard_overlap"]


def test_declared_text_without_ink_is_rejected() -> None:
    profile = FabProfile(
        {
            "capabilities": {
                "min_silk_width": {"value": 0.15},
                "min_silk_height": {"value": 1.0},
            }
        }
    )
    original = fab._gerber_silk_objects
    far_ink = _line(20.0, 20.0, 21.0, 20.0)
    fab._gerber_silk_objects = lambda _path, _layer: (far_ink,)
    try:
        with pytest.raises(FabOutputError, match="no nearby ink"):
            fab.measure_silkscreen(
                {"F.SilkS": Path("silk.gto")},
                {"F.Mask": Path("mask.gts")},
                Path("edge.gm1"),
                BoardMeasurement((), (), None, None, None, (0.0, 0.0, 30.0, 25.0), (), 0),
                SilkscreenLane(
                    "board.gd1",
                    (
                        SilkTextView(
                            "text",
                            "label",
                            "RESET",
                            1.0,
                            1.0,
                            "F.SilkS",
                            1.5,
                            0.15,
                            0.0,
                                "test",
                                "test",
                                "SW1",
                                0.25,
                                1.0,
                            ),
                    ),
                    (),
                ),
                profile,
            )
    finally:
        fab._gerber_silk_objects = original
