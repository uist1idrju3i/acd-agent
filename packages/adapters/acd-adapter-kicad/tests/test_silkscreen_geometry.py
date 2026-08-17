"""Independent silkscreen geometry negative controls."""

# These tests intentionally exercise adapter-private geometry primitives.
# pyright: reportPrivateUsage=false, reportPrivateImportUsage=false, reportUnknownMemberType=false, reportUnknownLambdaType=false

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from acd_adapter_kicad import fab
from acd_adapter_kicad.fab import (
    BoardMeasurement,
    FabOutputError,
    FootprintMeasurement,
)
from acd_adapter_kicad.fab.silkscreen import (
    _local_silk_bounds,
    _silk_objects_overlap,
    _silk_overlaps_rect,
    _SilkObject,
)
from acd_core.fab import FabProfile
from acd_core.silkscreen import SilkGraphicView, SilkscreenLane, SilkTextView


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


def test_courtyard_overlap_is_evidence_only() -> None:
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
        evidence = fab.measure_silkscreen(
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
        assert cast(int, evidence["courtyard_overlap_count"]) > 0
        assert evidence["status"] == "measured_pass"
    finally:
        fab._gerber_silk_objects = original


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
