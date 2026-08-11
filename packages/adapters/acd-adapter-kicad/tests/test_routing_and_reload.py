"""Route injection and independent reload tests (fail-closed negatives)."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd_adapter_kicad.reload import ReloadError, normalized_hash, verify_board
from acd_adapter_kicad.routing import RouteInjectionError, inject_routes
from acd_core.board_model import RoutedDesign, RoutedVia, RoutedWire

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
