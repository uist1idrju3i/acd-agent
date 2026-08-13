"""Route injection and independent reload tests (fail-closed negatives)."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd_adapter_kicad.board import stitch_via_pitch
from acd_adapter_kicad.reload import ReloadError, normalized_hash, verify_board
from acd_adapter_kicad.routing import (
    RouteInjectionError,
    inject_routes,
    inject_stitch_vias,
)
from acd_core.board_model import BoardModel, RoutedDesign, RoutedVia, RoutedWire
from acd_core.electrical import BoardView

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
    from acd_core.board_model import KeepoutRect

    model = BoardModel(
        20.0, 15.0, 2, 0.15, 0.15, 0.3, 0.6, 0.0, (), (), (
            KeepoutRect("antenna", 5.0, 0.0, 15.0, 5.0),
        ),
        stitch_via_pitch_mm=3.0,
        stitch_via_net="GND",
    )
    result, vias = inject_stitch_vias(
        _BOARD, model, RoutedDesign((), ()), {"GND": 1}, 3.0, 0.6, 0.3
    )
    assert vias
    assert all(not (5.0 <= x <= 15.0 and 0.0 <= y <= 5.0) for x, y in vias)
    assert result.count("(via") == len(vias)


def test_filled_plane_verifier_rejects_missing_gerber(tmp_path: Path) -> None:
    from acd_adapter_kicad.fab import FabOutputError, verify_ground_plane_gerbers
    from acd_core.board_model import CopperZone

    model = BoardModel(
        20.0, 15.0, 2, 0.15, 0.15, 0.3, 0.6, 0.3, (), (), (),
        (CopperZone("GND", ("F.Cu", "B.Cu"), 0.3, 1.0),),
        stitch_via_pitch_mm=3.0,
        stitch_via_net="GND",
    )
    with pytest.raises(FabOutputError, match="copper Gerber parse failed"):
        verify_ground_plane_gerbers(
            tmp_path / "missing-f.gbr", tmp_path / "missing-b.gbr", model, ((1.0, 1.0),)
        )


def test_gerber_region_without_aperture_function_fails_closed(tmp_path: Path) -> None:
    from acd_adapter_kicad.fab import FabOutputError, verify_ground_plane_gerbers
    from acd_core.board_model import CopperZone, KeepoutRect

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
        verify_ground_plane_gerbers(front, back, model, ((1.1, 1.1),))


def test_small_zone_region_fails_but_pad_region_is_excluded(tmp_path: Path) -> None:
    from acd_adapter_kicad.fab import FabOutputError, verify_ground_plane_gerbers
    from acd_core.board_model import CopperZone, KeepoutRect

    front = tmp_path / "front.gbr"
    back = tmp_path / "back.gbr"
    front.write_text(_gerber_region("Conductor", side=0.5))
    back.write_text(_gerber_region("Conductor", side=10.0))
    model = BoardModel(
        20.0, 15.0, 2, 0.15, 0.15, 0.3, 0.6, 0.0, (), (), (
            KeepoutRect("antenna", 18.0, 10.0, 19.0, 11.0),
        ),
        (CopperZone("GND", ("F.Cu", "B.Cu"), 0.3, 1.0),),
    )
    with pytest.raises(FabOutputError, match="copper island"):
        verify_ground_plane_gerbers(front, back, model, ((1.1, 1.1),))


def _gerber_region(function: str, side: float = 0.5) -> str:
    end = int((1.0 + side) * 10000)
    return (
        "%FSLAX46Y46*%\n%MOMM*%\n"
        f"G04 #@! TA.AperFunction,{function}*\nG36*\nG01*\n"
        f"X10000Y-10000D02*X{end}Y-10000D01*X{end}Y-{end}D01*"
        f"X10000Y-{end}D01*X10000Y-10000D01*G37*\n"
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
