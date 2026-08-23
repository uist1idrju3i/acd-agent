"""Route injection and independent reload tests (fail-closed negatives)."""

from __future__ import annotations

# pyright: reportMissingTypeStubs=false, reportPrivateImportUsage=false, reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownLambdaType=false
from pathlib import Path
from typing import Any, cast

import pytest

from acd.adapters.kicad.board import stitch_via_pitch
from acd.adapters.kicad.fab import (
    UncoveredGroundRegionsError,
    UncoveredStitchViasError,
)
from acd.adapters.kicad.fab.gerber import (
    _gerber_to_board_point,  # pyright: ignore[reportPrivateUsage]
)
from acd.adapters.kicad.reload import ReloadError, normalized_hash, verify_board
from acd.adapters.kicad.routing import (
    RouteInjectionError,
    inject_routes,
    inject_stitch_vias,
)
from acd.core.board_model import (
    BoardModel,
    BoardNet,
    ComponentPlacement,
    CopperZone,
    FootprintShape,
    PadShape,
    RoutedDesign,
    RoutedVia,
    RoutedWire,
)
from acd.core.electrical import BoardView
from acd.pipeline.stitch_candidate_evidence import summarize_stitch_candidate_report

_BOARD = '(kicad_pcb (version 20240108) (net 0 "") (net 1 "GND")\n)\n'


def _design(net: str = "GND", layer: str = "F.Cu") -> RoutedDesign:
    wire = RoutedWire(net=net, layer=layer, width_mm=0.15, points=((1.0, 1.0), (2.0, 1.0)))
    return RoutedDesign(wires=(wire,), vias=(RoutedVia(net=net, x_mm=1.5, y_mm=1.5),))


def test_inject_routes_appends_segments_and_vias() -> None:
    result = inject_routes(_BOARD, _design(), {"GND": 1}, 0.6, 0.3)
    assert "(segment (start 1 1) (end 2 1)" in result
    assert "(via (at 1.5 1.5)" in result
    assert result.rstrip().endswith(")")


def test_inject_routes_is_deterministic() -> None:
    first = inject_routes(_BOARD, _design(), {"GND": 1}, 0.6, 0.3)
    second = inject_routes(_BOARD, _design(), {"GND": 1}, 0.6, 0.3)
    assert first == second


def test_inject_routes_rejects_unknown_net() -> None:
    with pytest.raises(RouteInjectionError, match="unknown net"):
        inject_routes(_BOARD, _design(net="NOPE"), {"GND": 1}, 0.6, 0.3)


def test_inject_routes_rejects_unknown_layer() -> None:
    with pytest.raises(RouteInjectionError, match="unknown copper layer"):
        inject_routes(_BOARD, _design(layer="In1.Cu"), {"GND": 1}, 0.6, 0.3)


def test_stitch_pitch_requires_complete_basis() -> None:
    board = BoardView(
        "b", 20.0, 15.0, 2, 1.6, "mm", "board_upper_left", "down",
        0.15, 0.15, 0.3, 0.6, 0.3, False,
        stitch_via_max_frequency_hz=2.4e9,
    )
    with pytest.raises(ValueError, match="incomplete stitch-via basis"):
        stitch_via_pitch(board)


def test_stitch_vias_exclude_declared_keepout() -> None:
    from acd.core.board_model import KeepoutRect

    model = BoardModel(
        20.0, 15.0, 2, 0.15, 0.15, 0.3, 0.6, 0.0, (), (), (
            KeepoutRect("antenna", 5.0, 0.0, 15.0, 5.0),
        ),
        stitch_via_pitch_mm=3.0,
        stitch_via_net="GND",
    )
    result, vias, report = inject_stitch_vias(
        _BOARD, model, RoutedDesign((), ()), {"GND": 1}, 3.0, 0.6, 0.3
    )
    assert vias
    assert all(not (5.0 <= x <= 15.0 and 0.0 <= y <= 5.0) for x, y in vias)
    assert result.count("(via") == len(vias)
    assert report["candidate_total"] == len(report["candidates"])  # type: ignore[arg-type]


def test_stitch_candidate_report_records_exclusion_reasons() -> None:
    from acd.core.board_model import KeepoutRect

    model = BoardModel(
        20.0, 15.0, 2, 0.15, 0.15, 0.3, 0.6, 0.0, (), (), (
            KeepoutRect("antenna", 5.0, 0.0, 15.0, 5.0),
        ),
        stitch_via_pitch_mm=3.0,
        stitch_via_net="GND",
    )
    _, _, report = inject_stitch_vias(
        _BOARD,
        model,
        RoutedDesign((), ()),
        {"GND": 1},
        3.0,
        0.6,
        0.3,
    )
    candidate_total = report["candidate_total"]
    assert isinstance(candidate_total, int) and candidate_total > 0
    exclusions = report["exclusion_counts"]
    assert isinstance(exclusions, dict)
    assert set(cast(dict[str, object], exclusions)) == {
        "keepout",
        "footprint_body_or_courtyard",
        "pad",
        "wire",
        "via",
        "board_edge_inset",
        "inter_via_spacing",
    }
    candidates = report["candidates"]
    assert isinstance(candidates, list)
    typed_candidates = cast(list[dict[str, Any]], candidates)
    assert typed_candidates == sorted(
        typed_candidates,
        key=lambda item: (item["position_mm"][0], item["position_mm"][1]),
    )
    assert all(
        not item["exclusion_reasons"]
        for item in typed_candidates
        if item["selected"]
    )
    assert report["allowed_points_override"] is False
    assert report["fallback_used"] is False


def test_stitch_via_fallback_activates_after_primary_candidates_are_excluded() -> None:
    from acd.core.board_model import KeepoutRect

    keepouts = tuple(
        KeepoutRect(f"primary-{index}", x - 0.2, y - 0.2, x + 0.2, y + 0.2)
        for index, (x, y) in enumerate(
                (
                    (0.3, 3.3),
                    (0.3, 6.3),
                    (3.3, 0.3),
                    (3.3, 3.3),
                    (3.3, 6.3),
                    (3.3, 9.3),
                    (3.3, 9.7),
                    (6.3, 0.3),
                    (6.3, 3.3),
                    (6.3, 6.3),
                    (6.3, 9.3),
                    (6.3, 9.7),
                    (9.3, 0.3),
                    (9.3, 3.3),
                    (9.3, 6.3),
                    (9.3, 9.3),
                    (9.3, 9.7),
                    (9.7, 3.3),
                    (9.7, 6.3),
                    (4.8, 3.3),
                )
        )
    )
    model = BoardModel(
        10.0, 10.0, 2, 0.15, 0.15, 0.3, 0.6, 0.0, (), (), keepouts,
        stitch_via_pitch_mm=3.0,
        stitch_via_net="GND",
    )
    _, vias, report = inject_stitch_vias(
        _BOARD, model, RoutedDesign((), ()), {"GND": 1}, 3.0, 0.6, 0.3
    )
    assert report["fallback_used"] is True
    assert report["fallback_candidates"]
    assert report["fallback_excluded_candidates"]
    assert vias


def test_stitch_via_fallback_still_fails_closed_when_empty() -> None:
    from acd.core.board_model import KeepoutRect

    model = BoardModel(
        10.0, 10.0, 2, 0.15, 0.15, 0.3, 0.6, 0.0, (), (),
        (KeepoutRect("all", 0.0, 0.0, 10.0, 10.0),),
        stitch_via_pitch_mm=3.0,
        stitch_via_net="GND",
    )
    with pytest.raises(RouteInjectionError, match="no safe stitch-via locations"):
        inject_stitch_vias(
            _BOARD, model, RoutedDesign((), ()), {"GND": 1}, 3.0, 0.6, 0.3
        )


def test_stitch_via_region_fallback_is_scoped_when_primary_region_is_blocked() -> None:
    model = BoardModel(
        20.0,
        15.0,
        2,
        0.15,
        0.15,
        0.3,
        0.6,
        0.0,
        (),
        (),
        (),
        stitch_via_pitch_mm=3.0,
        stitch_via_net="GND",
    )
    routes = RoutedDesign(
        (
            RoutedWire("GND", "F.Cu", 0.15, ((3.3, 2.8), (3.3, 3.8))),
        ),
        (),
    )
    _, vias, report = inject_stitch_vias(
        _BOARD,
        model,
        routes,
        {"GND": 1},
        3.0,
        0.6,
        0.3,
        fallback_regions=(("F.Cu", (3.0, 3.0, 5.9, 5.9)),),
    )
    assert report["fallback_used"] is True
    assert report["fallback_scope"] == "uncovered_conductor_regions"
    summary = summarize_stitch_candidate_report(report)
    assert summary["fallback_region_count"] == 1
    regions = cast(list[object], report["fallback_region_reports"])
    assert len(regions) == 1
    region = cast(dict[str, Any], regions[0])
    assert region["layer"] == "F.Cu"
    assert region["selected_candidates"]
    assert vias
    primary_candidates = cast(list[dict[str, Any]], report["candidates"])
    assert any(
        candidate["position_mm"] == [3.3, 3.3]
        and "wire" in candidate["exclusion_reasons"]
        for candidate in primary_candidates
    )


def test_uncovered_stitch_via_error_preserves_structured_locations() -> None:
    locations = ((1.25, 2.5), (3.75, 4.0))
    error = UncoveredStitchViasError(locations)
    assert error.locations == locations
    assert "stitch vias lack copper coverage" in str(error)


def test_uncovered_ground_regions_error_preserves_layer_and_bbox() -> None:
    error = UncoveredGroundRegionsError(
        (("F.Cu", (1.0, 1.0, 1.5, 1.5)), ("B.Cu", (2.0, 2.0, 3.0, 3.0)))
    )
    assert error.regions == (
        ("F.Cu", (1.0, 1.0, 1.5, 1.5)),
        ("B.Cu", (2.0, 2.0, 3.0, 3.0)),
    )
    assert "bbox_mm" in str(error)


def test_gerber_uncovered_ground_region_is_structured(tmp_path: Path) -> None:
    from acd.adapters.kicad.fab import verify_ground_plane_gerbers
    from acd.core.board_model import CopperZone, KeepoutRect

    front = tmp_path / "front.gbr"
    back = tmp_path / "back.gbr"
    front.write_text(
        _gerber_region("Conductor", side=0.5)
        + _gerber_region("Conductor", x=9.0, y=9.0, side=4.0)
    )
    back.write_text(_gerber_region("Conductor", x=9.0, y=9.0, side=4.0))
    model = BoardModel(
        20.0,
        15.0,
        2,
        0.15,
        0.15,
        0.3,
        0.6,
        0.0,
        (),
        (BoardNet("GND", ()),),
        (KeepoutRect("antenna", 18.0, 10.0, 19.0, 11.0),),
        (CopperZone("GND", ("F.Cu", "B.Cu"), 0.3, 0.0),),
    )
    with pytest.raises(UncoveredGroundRegionsError) as error_info:
        verify_ground_plane_gerbers(
            front,
            back,
            model,
            ((10.0, 10.0),),
            RoutedDesign((), ()),
        )
    assert error_info.value.regions == (("F.Cu", (1.0, 1.0, 1.5, 1.5)),)


def test_gerber_y_axis_conversion_matches_board_frame() -> None:
    assert _gerber_to_board_point(2.0, -3.0) == (2.0, 3.0)
    assert _gerber_to_board_point(2.0, 3.0) == (2.0, -3.0)


def test_stitch_vias_rotate_asymmetric_pad_axes() -> None:
    placement = ComponentPlacement(
        "U2",
        FootprintShape(
            "test:U2",
            (
                PadShape("tab", 3.15, 0.0, 180.0, "rect", 3.8, 2.0, False, None, True, False),
            ),
        ),
        4.15,
        14.7,
        90.0,
    )
    model = BoardModel(
        30.0,
        25.0,
        2,
        0.15,
        0.15,
        0.3,
        0.6,
        0.3,
        (placement,),
        (BoardNet("GND", ()),),
        stitch_via_pitch_mm=3.011932521069266,
        stitch_via_net="GND",
    )
    _, vias, _ = inject_stitch_vias(
        _BOARD,
        model,
        RoutedDesign((), ()),
        {"GND": 1},
        model.stitch_via_pitch_mm,
        0.6,
        0.3,
    )
    assert (3.611932521069266, 9.635797563207797) not in vias


def test_stitch_vias_exclude_rotated_translated_body_bbox() -> None:
    placement = ComponentPlacement(
        "U2",
        FootprintShape(
            "test:U2",
            (),
            body_bbox_mm=(-1.0, -1.0, 1.0, 1.0),
        ),
        3.6,
        9.6,
        90.0,
    )
    model = BoardModel(
        30.0,
        25.0,
        2,
        0.15,
        0.15,
        0.3,
        0.6,
        0.3,
        (placement,),
        (BoardNet("GND", ()),),
        stitch_via_pitch_mm=3.0,
        stitch_via_net="GND",
    )
    _, vias, _ = inject_stitch_vias(
        _BOARD,
        model,
        RoutedDesign((), ()),
        {"GND": 1},
        model.stitch_via_pitch_mm,
        0.6,
        0.3,
    )
    assert (3.6, 9.6) not in vias


def test_missing_stitch_basis_fails_downstream() -> None:
    board = BoardView(
        "b",
        20.0,
        15.0,
        2,
        1.6,
        "mm",
        "board_upper_left",
        "down",
        0.15,
        0.15,
        0.3,
        0.6,
        0.3,
        False,
    )
    assert stitch_via_pitch(board) is None
    model = BoardModel(
        20.0,
        15.0,
        2,
        0.15,
        0.15,
        0.3,
        0.6,
        0.3,
        (),
        (BoardNet("GND", ()),),
        copper_zones=(CopperZone("GND", ("F.Cu", "B.Cu"), 0.3, 1.0),),
        stitch_via_net="GND",
    )
    _, vias, _ = inject_stitch_vias(
        _BOARD, model, RoutedDesign((), ()), {"GND": 1}, None, 0.6, 0.3
    )
    assert vias == ()
    from acd.adapters.kicad.fab import FabOutputError, verify_ground_plane_gerbers

    with pytest.raises(FabOutputError, match="no stitch vias"):
        verify_ground_plane_gerbers(
            Path("missing-f.gbr"),
            Path("missing-b.gbr"),
            model,
            vias,
            RoutedDesign((), ()),
        )


def test_filled_plane_verifier_rejects_missing_gerber(tmp_path: Path) -> None:
    from acd.adapters.kicad.fab import FabOutputError, verify_ground_plane_gerbers
    from acd.core.board_model import CopperZone

    model = BoardModel(
        20.0, 15.0, 2, 0.15, 0.15, 0.3, 0.6, 0.3, (), (), (),
        (CopperZone("GND", ("F.Cu", "B.Cu"), 0.3, 1.0),),
        stitch_via_pitch_mm=3.0,
        stitch_via_net="GND",
    )
    with pytest.raises(FabOutputError, match="copper Gerber parse failed"):
        verify_ground_plane_gerbers(
            tmp_path / "missing-f.gbr",
            tmp_path / "missing-b.gbr",
            model,
            ((1.0, 1.0),),
            RoutedDesign((), ()),
        )


def test_gerber_region_without_aperture_function_fails_closed(tmp_path: Path) -> None:
    from acd.adapters.kicad.fab import FabOutputError, verify_ground_plane_gerbers
    from acd.core.board_model import CopperZone, KeepoutRect

    content = _gerber_region("Unknown")
    front = tmp_path / "front.gbr"
    back = tmp_path / "back.gbr"
    front.write_text(content)
    back.write_text(_gerber_region("Conductor"))
    model = BoardModel(
        20.0, 15.0, 2, 0.15, 0.15, 0.3, 0.6, 0.3, (), (), (
            KeepoutRect("antenna", 18.0, 10.0, 19.0, 11.0),
        ),
        (CopperZone("GND", ("F.Cu", "B.Cu"), 0.3, 1.0),),
    )
    with pytest.raises(FabOutputError, match="unknown region AperFunction"):
        verify_ground_plane_gerbers(front, back, model, ((1.1, 1.1),), RoutedDesign((), ()))


def test_antenna_keepout_copper_fails_closed(tmp_path: Path) -> None:
    from acd.adapters.kicad.fab import FabOutputError, verify_ground_plane_gerbers
    from acd.core.board_model import CopperZone, KeepoutRect

    front = tmp_path / "front.gbr"
    back = tmp_path / "back.gbr"
    front.write_text(_gerber_region("Conductor", side=2.0))
    back.write_text(_gerber_region("Conductor", side=10.0))
    model = BoardModel(
        20.0,
        15.0,
        2,
        0.15,
        0.15,
        0.3,
        0.6,
        0.0,
        (),
        (BoardNet("GND", ()),),
        (KeepoutRect("antenna", 1.2, 1.2, 1.8, 1.8),),
        (CopperZone("GND", ("F.Cu", "B.Cu"), 0.3, 0.0),),
    )
    with pytest.raises(FabOutputError, match="measured_area_mm2"):
        verify_ground_plane_gerbers(
            front, back, model, ((2.0, 2.0),), RoutedDesign((), ())
        )


def test_prefill_gerbers_fail_closed(tmp_path: Path) -> None:
    from acd.adapters.kicad.fab import FabOutputError, verify_ground_plane_gerbers
    from acd.core.board_model import CopperZone

    front = tmp_path / "front.gbr"
    back = tmp_path / "back.gbr"
    empty = "%FSLAX46Y46*%\n%MOMM*%\n"
    front.write_text(empty)
    back.write_text(empty)
    model = BoardModel(
        20.0,
        15.0,
        2,
        0.15,
        0.15,
        0.3,
        0.6,
        0.0,
        (),
        (BoardNet("GND", ()),),
        (),
        (CopperZone("GND", ("F.Cu", "B.Cu"), 0.3, 1.0),),
    )
    with pytest.raises(FabOutputError, match="filled copper regions are absent"):
        verify_ground_plane_gerbers(
            front, back, model, ((1.1, 1.1),), RoutedDesign((), ())
        )


def test_small_zone_region_fails_but_pad_region_is_excluded(tmp_path: Path) -> None:
    from acd.adapters.kicad.fab import FabOutputError, verify_ground_plane_gerbers
    from acd.core.board_model import CopperZone, KeepoutRect

    front = tmp_path / "front.gbr"
    back = tmp_path / "back.gbr"
    front.write_text(_gerber_region("Conductor", side=0.5))
    back.write_text(_gerber_region("Conductor", side=10.0))
    model = BoardModel(
        20.0, 15.0, 2, 0.15, 0.15, 0.3, 0.6, 0.0,
        (), (BoardNet("GND", ()),), (
            KeepoutRect("antenna", 18.0, 10.0, 19.0, 11.0),
        ),
        (CopperZone("GND", ("F.Cu", "B.Cu"), 0.3, 1.0),),
    )
    with pytest.raises(FabOutputError, match="copper island"):
        verify_ground_plane_gerbers(front, back, model, ((1.1, 1.1),), RoutedDesign((), ()))


def _gerber_region(
    function: str,
    side: float = 0.5,
    *,
    x: float = 1.0,
    y: float = 1.0,
) -> str:
    start_x = int(x * 1_000_000)
    start_y = int(-y * 1_000_000)
    end_x = int((x + side) * 1_000_000)
    end_y = int(-(y + side) * 1_000_000)
    return (
        "%FSLAX46Y46*%\n%MOMM*%\n"
        f"G04 #@! TA.AperFunction,{function}*\nG36*\nG01*\n"
        f"X{start_x}Y{start_y}D02*X{end_x}Y{start_y}D01*X{end_x}Y{end_y}D01*"
        f"X{start_x}Y{end_y}D01*X{start_x}Y{start_y}D01*G37*\n"
        "G04 #@! TD.AperFunction*\n"
    )


def test_verify_board_detects_missing_net(tmp_path: Path) -> None:
    board = tmp_path / "b.kicad_pcb"
    board.write_text(inject_routes(_BOARD, _design(), {"GND": 1}, 0.6, 0.3))
    with pytest.raises(ReloadError, match="nets missing"):
        verify_board(board, {"GND", "MISSING"}, set())


def test_verify_board_detects_missing_routes(tmp_path: Path) -> None:
    board = tmp_path / "b.kicad_pcb"
    board.write_text(_BOARD)
    with pytest.raises(ReloadError, match="no routed segments"):
        verify_board(board, {"GND"}, set())


def test_normalized_hash_ignores_comment_timestamps(tmp_path: Path) -> None:
    a = tmp_path / "a.gbr"
    b = tmp_path / "b.gbr"
    a.write_text("G04 created 2026-01-01*\n%FSLAX46Y46*%\nX0Y0D02*\n")
    b.write_text("G04 created 2030-12-31*\n%FSLAX46Y46*%\nX0Y0D02*\n")
    assert normalized_hash(a) == normalized_hash(b)
    c = tmp_path / "c.gbr"
    c.write_text("G04 created 2026-01-01*\n%FSLAX46Y46*%\nX1Y0D02*\n")
    assert normalized_hash(a) != normalized_hash(c)
