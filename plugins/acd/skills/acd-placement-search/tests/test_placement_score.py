"""Surrogate placement metric tests (skill asset, separate from the ACD core)."""

from __future__ import annotations

import math

import pytest

from acd.adapters.kicad.placement import Placement
from acd.core.board_model import FootprintShape, PadShape
from acd.core.electrical import (
    BoardView,
    ComponentView,
    ElectricalLane,
    LibraryPin,
    NetView,
    PinView,
)
from placement_score import (
    PlacementScoreError,
    min_component_gap_mm,
    min_edge_gap_mm,
    rank_candidates,
    score_placement,
)


def _board() -> BoardView:
    return BoardView(
        node_id="board-1",
        width_mm=20.0,
        height_mm=15.0,
        layers=2,
        thickness_mm=1.6,
        unit="mm",
        origin="board-upper-left",
        y_axis="down",
        min_track_mm=0.15,
        min_clearance_mm=0.15,
        via_drill_mm=0.3,
        via_diameter_mm=0.6,
        edge_copper_clearance_mm=0.3,
        antenna_keepout=False,
    )


def _pad(number: str, x: float) -> PadShape:
    return PadShape(number, x, 0.0, 0.0, "rect", 1.0, 1.0, False, None, True, False)


def _footprint() -> FootprintShape:
    return FootprintShape("Test:R", (_pad("1", -0.5), _pad("2", 0.5)))


def _component(refdes: str, node_id: str) -> ComponentView:
    return ComponentView(
        node_id=node_id,
        refdes=refdes,
        value="1k",
        mpn="MPN",
        lcsc="C1",
        jlcpcb_class="basic",
        assembly="fitted",
        library=LibraryPin(
            symbol="Device:R",
            symbol_file="lib.kicad_sym",
            symbol_source="kicad-official",
            symbol_source_ref="10.0.5",
            symbol_sha256="sha256:0",
            footprint="Resistor_SMD:R_0402",
            footprint_file="fp.kicad_mod",
            footprint_source="kicad-official",
            footprint_source_ref="10.0.5",
            footprint_sha256="sha256:0",
        ),
    )


def _lane() -> ElectricalLane:
    components = (_component("R1", "c1"), _component("R2", "c2"))
    nets = (
        NetView(
            node_id="n1",
            name="SIG",
            voltage_nominal_v=None,
            width_basis="signal",
            current_max_a=None,
            width_basis_source=None,
            manufacturing_minimum_mm=None,
            manufacturing_margin_mm=None,
        ),
    )
    pins = (
        PinView(node_id="p1", component_id="c1", pad="1", net_id="n1", no_connect=False),
        PinView(node_id="p2", component_id="c2", pad="1", net_id="n1", no_connect=False),
    )
    return ElectricalLane(components=components, nets=nets, pins=pins, board=_board())


def _footprints() -> dict[str, FootprintShape]:
    return {"R1": _footprint(), "R2": _footprint()}


def test_score_reports_wirelength_and_gaps() -> None:
    placements = (Placement("R1", 5.0, 5.0, 0.0), Placement("R2", 9.0, 8.0, 0.0))
    score = score_placement(_lane(), placements, _footprints())
    assert score.hpwl_mm == pytest.approx(7.0)
    assert score.min_component_gap_mm == pytest.approx(math.hypot(2.0, 2.0))
    assert score.min_edge_gap_mm == pytest.approx(4.0)


def test_shorter_wirelength_ranks_first() -> None:
    candidates = {
        "far": (Placement("R1", 3.0, 3.0, 0.0), Placement("R2", 17.0, 12.0, 0.0)),
        "near": (Placement("R1", 9.0, 7.0, 0.0), Placement("R2", 11.0, 8.0, 0.0)),
    }
    ranked = rank_candidates(_lane(), candidates, _footprints())
    assert [name for name, _score in ranked] == ["near", "far"]


def test_touching_components_report_zero_gap() -> None:
    placements = (Placement("R1", 5.0, 5.0, 0.0), Placement("R2", 7.0, 5.0, 0.0))
    assert min_component_gap_mm(placements, _footprints()) == pytest.approx(0.0)


def test_overhanging_placement_reports_negative_edge_gap() -> None:
    placements = (Placement("R1", 0.2, 5.0, 0.0),)
    assert min_edge_gap_mm(_board(), placements, _footprints()) < 0.0


def test_missing_geometry_fails_closed() -> None:
    placements = (Placement("R1", 5.0, 5.0, 0.0), Placement("R3", 9.0, 8.0, 0.0))
    with pytest.raises(PlacementScoreError):
        score_placement(_lane(), placements, _footprints())


def test_duplicate_placement_fails_closed() -> None:
    placements = (Placement("R1", 5.0, 5.0, 0.0), Placement("R1", 9.0, 8.0, 0.0))
    with pytest.raises(PlacementScoreError, match="duplicate placement"):
        score_placement(_lane(), placements, _footprints())
