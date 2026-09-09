# pyright: reportPrivateUsage=false
"""AA-15: CPL rotation offset mismatch diagnostics."""
from __future__ import annotations

from pathlib import Path

import pytest

from acd.core.electrical import (
    BoardView,
    ComponentView,
    ElectricalLane,
    LibraryPin,
)
from acd.pipeline.gd1_board import _check_rotation_offsets


def _board() -> BoardView:
    return BoardView(
        node_id="electrical-board",
        width_mm=30.0,
        height_mm=25.0,
        layers=2,
        thickness_mm=1.6,
        unit="mm",
        origin="upper-left",
        y_axis="down",
        min_track_mm=0.2,
        min_clearance_mm=0.2,
        via_drill_mm=0.3,
        via_diameter_mm=0.6,
        edge_copper_clearance_mm=0.3,
        antenna_keepout=False,
        ground_plane_layers=("F.Cu", "B.Cu"),
    )


def _component(
    refdes: str,
    *,
    offset: float | None = None,
    basis: str | None = None,
) -> ComponentView:
    return ComponentView(
        refdes,
        refdes,
        "10k",
        "RC0603FR-0710KL",
        "C25804",
        "basic",
        "fitted",
        LibraryPin(
            "Device:R",
            "symbol.kicad_sym",
            "fixture",
            "r1",
            "sha256:symbol",
            "Resistor_SMD:R_0603_1608Metric",
            "footprint.kicad_mod",
            "fixture",
            "r1",
            "sha256:footprint",
        ),
        cpl_rotation_offset_deg=offset,
        cpl_rotation_evidence_basis=basis,
    )


def test_rotation_offset_mismatch_reports_evidence_and_next_step(
    tmp_path: Path,
) -> None:
    lane = ElectricalLane(
        components=(
            _component("R1", offset=90.0, basis="estimated"),
        ),
        nets=(),
        pins=(),
        board=_board(),
    )
    with pytest.raises(ValueError) as excinfo:
        _check_rotation_offsets(
            lane,
            {"R1": 90.0},
            {"R1": 180.0},
            tmp_path / "evidence" / "test-cpl-orientation",
        )
    message = str(excinfo.value)
    assert "R1" in message
    assert "declared cpl_rotation_offset_deg=90.0" in message
    assert "effective offset applied to CPL=90.00" in message
    assert "LCSC Evidence offset=180.00" in message
    assert "cpl_rotation_evidence_basis='estimated'" in message
    assert "R1.json" in message
    assert "not_fitted" not in message
    assert "confirmed" in message
    assert "0.01" in message


def test_rotation_offset_within_tolerance_passes(tmp_path: Path) -> None:
    lane = ElectricalLane(
        components=(_component("R1", offset=0.0, basis="confirmed"),),
        nets=(),
        pins=(),
        board=_board(),
    )
    _check_rotation_offsets(
        lane,
        {"R1": 0.0},
        {"R1": 0.005},
        tmp_path / "evidence",
    )


def test_rotation_offset_mismatch_without_component_uses_none_defaults(
    tmp_path: Path,
) -> None:
    lane = ElectricalLane(components=(), nets=(), pins=(), board=_board())
    with pytest.raises(ValueError) as excinfo:
        _check_rotation_offsets(lane, {}, {"J2": 270.0}, tmp_path / "evidence")
    assert "declared cpl_rotation_offset_deg=None" in str(excinfo.value)
    assert "effective offset applied to CPL=0.00" in str(excinfo.value)
