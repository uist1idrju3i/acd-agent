from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from acd.core.qr_geometry import qr_module_matrix_from_svg
from acd.pipeline.gd1_fixture.svg_artwork import (  # pyright: ignore[reportMissingTypeStubs]
    load_svg,
    place_svg,
)

ROOT = Path(__file__).resolve().parents[2]


def test_svg_assets_exclude_board_preview_and_preserve_compound_qr() -> None:
    logo_viewbox, logo_parts = load_svg(ROOT / "assets/vibebb-silkscreen.svg")
    qr_viewbox, qr_parts = load_svg(ROOT / "assets/qr-repository-silkscreen.svg")

    assert logo_viewbox == (40.0, 18.0)
    assert qr_viewbox == (36.0, 36.0)
    assert len(logo_parts) == 42
    assert len(qr_parts) == 1
    assert len(qr_parts[0].contours) > 300
    assert qr_parts[0].fill_rule == "evenodd"


def test_backside_svg_placement_reflects_asymmetric_geometry() -> None:
    path = ROOT / "assets" / "vibebb-silkscreen.svg"
    front, _ = place_svg(
        path,
        board_width_mm=30.0,
        center_x_mm=10.0,
        center_y_mm=10.0,
        width_mm=12.0,
        layer="F.SilkS",
    )
    back, _ = place_svg(
        path,
        board_width_mm=30.0,
        center_x_mm=10.0,
        center_y_mm=10.0,
        width_mm=12.0,
        layer="B.SilkS",
    )
    front_contours = cast(list[list[list[float]]], front[1]["contours"])
    back_contours = cast(list[list[list[float]]], back[1]["contours"])
    front_point = front_contours[0][0]
    back_point = back_contours[0][0]
    assert back_point[0] == pytest.approx(20.0 - front_point[0])
    assert back_point[1] == pytest.approx(front_point[1])


def test_svg_stroke_below_profile_fails_without_clamping() -> None:
    with pytest.raises(ValueError, match="below the minimum silkscreen width"):
        place_svg(
            ROOT / "assets" / "vibebb-silkscreen.svg",
            board_width_mm=30.0,
            center_x_mm=6.3,
            center_y_mm=7.0,
            width_mm=12.0,
            minimum_stroke_width_mm=0.15,
        )


def test_rotated_logo_has_provenance_and_expected_size() -> None:
    parts, provenance = place_svg(
        ROOT / "assets" / "vibebb-silkscreen.svg",
        board_width_mm=30.0,
        center_x_mm=21.9,
        center_y_mm=8.3,
        width_mm=16.0,
        rotation_degrees=90.0,
        minimum_stroke_width_mm=0.15,
    )
    assert parts
    assert provenance["scale"] == "0.400000000"
    assert provenance["placed_size_mm"] == "7.200000000x16.000000000"
    assert provenance["rotation_degrees"] == "90.000000000"


def test_qr_source_matrix_has_version_5_grid_and_quiet_zone_pitch() -> None:
    matrix, pitch = qr_module_matrix_from_svg(
        ROOT / "assets" / "qr-repository-silkscreen.svg"
    )
    assert len(matrix) == 37
    assert all(len(row) == 37 for row in matrix)
    assert pitch == pytest.approx(0.8)
    assert sum(row.count("1") for row in matrix) == 686
