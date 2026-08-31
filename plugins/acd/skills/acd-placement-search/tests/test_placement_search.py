"""Placement search tests (skill asset, separate from the ACD core)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.adapters.kicad.placement import (
    Placement,
    PlacementError,
    pad_position,
    placed_rect,
)
from acd.core.board_model import FootprintShape, PadShape
from acd.core.electrical import BoardView, ComponentView, LibraryPin
from acd.core.placement_constraints import PlacementCouplingConstraint
from placement_search import (
    compute_placements,
    compute_placements_from_json,
)


def _board(width: float = 20.0, height: float = 15.0) -> BoardView:
    return BoardView(
        node_id="board-1",
        width_mm=width,
        height_mm=height,
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


def _component(refdes: str, footprint: str = "Resistor_SMD:R_0603_1608Metric") -> ComponentView:
    return ComponentView(
        node_id=f"comp-{refdes}",
        refdes=refdes,
        value="10k",
        mpn="X",
        lcsc="C1",
        jlcpcb_class="basic",
        assembly="fitted",
        library=LibraryPin(
            symbol="Device:R",
            symbol_file="s",
            symbol_source="kicad-official",
            symbol_source_ref="10.0.6",
            symbol_sha256="sha256:0",
            footprint=footprint,
            footprint_file="f",
            footprint_source="kicad-official",
            footprint_source_ref="10.0.6",
            footprint_sha256="sha256:0",
        ),
    )


def _footprint() -> FootprintShape:
    pads = tuple(
        PadShape(
            number=str(i + 1),
            x_mm=float(i),
            y_mm=0.0,
            rotation_deg=0.0,
            shape="rect",
            size_x_mm=0.8,
            size_y_mm=0.9,
            through_hole=False,
            drill_mm=None,
            on_front=True,
            on_back=False,
        )
        for i in range(2)
    )
    return FootprintShape(library_ref="Resistor_SMD:R_0603_1608Metric", pads=pads)


def test_compute_placements_is_deterministic() -> None:
    components = tuple(_component(f"R{i}") for i in range(1, 6))
    footprints = {c.refdes: _footprint() for c in components}
    nets = (("R1", "R2"), ("R3", "R4"))
    first = compute_placements(_board(), components, footprints, (), nets)
    second = compute_placements(_board(), components, footprints, (), nets)
    assert first == second


def test_spacing_variant_zero_preserves_default_output() -> None:
    components = tuple(_component(f"R{i}") for i in range(1, 6))
    footprints = {c.refdes: _footprint() for c in components}
    assert compute_placements(_board(), components, footprints, ()) == compute_placements(
        _board(), components, footprints, (), spacing_variant=0
    )


@pytest.mark.skipif(
    not Path(
        "/usr/share/kicad/footprints/Connector_USB.pretty/"
        "USB_C_Receptacle_HRO_TYPE-C-31-M-12.kicad_mod"
    ).is_file(),
    reason="GD1 pinned KiCad libraries are unavailable",
)
def test_spacing_variants_change_gd1_placements() -> None:
    root = Path(__file__).resolve().parents[5]
    graph = json.loads(
        (root / "fixtures/golden-design-1/graph.json").read_text(encoding="utf-8")
    )
    payload: dict[str, object] = {
        "graph": graph,
        "fixture_dir": str(root / "fixtures/golden-design-1"),
        "fab_profile": str(root / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json"),
    }
    default = compute_placements_from_json(payload)
    variant_one = compute_placements_from_json({**payload, "spacing_variant": 1})
    variant_two = compute_placements_from_json({**payload, "spacing_variant": 2})
    assert variant_one != default
    assert variant_two != default


@pytest.mark.parametrize("spacing_variant", [-1, 3])
def test_spacing_variant_out_of_range_fails_closed(spacing_variant: int) -> None:
    components = (_component("R1"),)
    footprints = {"R1": _footprint()}
    with pytest.raises(PlacementError, match="invalid spacing variant"):
        compute_placements(
            _board(), components, footprints, (), spacing_variant=spacing_variant
        )


def test_connected_components_placed_near_each_other() -> None:
    components = tuple(_component(f"R{i}") for i in range(1, 4))
    footprints = {c.refdes: _footprint() for c in components}
    placements = {
        p.refdes: p
        for p in compute_placements(_board(), components, footprints, (), (("R1", "R3"),))
    }
    d_connected = abs(placements["R1"].x_mm - placements["R3"].x_mm) + abs(
        placements["R1"].y_mm - placements["R3"].y_mm
    )
    d_unconnected = abs(placements["R1"].x_mm - placements["R2"].x_mm) + abs(
        placements["R1"].y_mm - placements["R2"].y_mm
    )
    assert d_connected <= d_unconnected + 2 * 0.25 + 1e-9


def test_placement_fails_closed_when_board_is_too_small() -> None:
    components = tuple(_component(f"R{i}") for i in range(1, 30))
    footprints = {c.refdes: _footprint() for c in components}
    with pytest.raises(PlacementError, match="no placement found"):
        compute_placements(_board(width=4.0, height=4.0), components, footprints, ())


def test_edge_anchors_are_derived_from_footprint_geometry() -> None:
    components = (
        _component("J1", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12"),
        _component("U1", "Espressif:ESP32-C3-MINI-1"),
    )
    pads = (
        PadShape("1", 0.0, -4.045, 0.0, "rect", 0.5, 0.5, False, None, True, False),
        PadShape("2", 0.0, 7.6, 0.0, "rect", 0.5, 0.5, False, None, True, False),
    )
    footprints = {
        "J1": FootprintShape(
            components[0].library.footprint,
            pads[:1],
            body_bbox_mm=(-4.0, -3.65, 4.0, 3.65),
        ),
        "U1": FootprintShape(
            components[1].library.footprint,
            pads[1:],
            body_bbox_mm=(-6.6, -8.3, 6.6, 8.3),
            keepout_bboxes_mm=((-6.6, -8.3, 6.6, -2.9),),
        ),
    }
    placements = compute_placements(_board(width=30.0, height=25.0), components, footprints, ())
    by_refdes = {item.refdes: item for item in placements}
    assert by_refdes["J1"].y_mm == pytest.approx(21.35)
    assert by_refdes["U1"].y_mm == pytest.approx(2.9)


@pytest.mark.parametrize(
    ("rotation", "expected"),
    [
        (0.0, (7.3, 14.7)),
        (90.0, (4.15, 11.55)),
        (180.0, (1.0, 14.7)),
        (270.0, (4.15, 17.85)),
    ],
)
def test_tab_pad_position_uses_kicad_clockwise_rotation(
    rotation: float, expected: tuple[float, float]
) -> None:
    footprint = FootprintShape(
        "Package_SOT:SOT-223-3_TabPin2",
        (
            PadShape("2", 3.15, 0.0, 0.0, "rect", 2.0, 3.8, False, None, True, False),
        ),
    )
    assert pad_position(footprint, (4.15, 14.7), rotation, "2") == pytest.approx(expected)


def test_u2_asymmetric_pads_match_kicad_coordinates() -> None:
    footprint = FootprintShape(
        "Package_SOT:SOT-223-3_TabPin2",
        (
            PadShape("1", -3.15, -2.3, 0.0, "rect", 1.0, 1.0, False, None, True, False),
            PadShape("2", 3.15, 0.0, 0.0, "rect", 2.0, 3.8, False, None, True, False),
        ),
    )
    assert pad_position(footprint, (4.15, 14.7), 90.0, "1") == pytest.approx(
        (1.85, 17.85)
    )
    assert pad_position(footprint, (4.15, 14.7), 90.0, "2") == pytest.approx(
        (4.15, 11.55)
    )


def test_placed_rect_uses_kicad_clockwise_rotation() -> None:
    footprint = FootprintShape(
        "Package_SOT:SOT-223-3_TabPin2",
        (PadShape("2", 3.15, 0.0, 0.0, "rect", 2.0, 3.8, False, None, True, False),),
    )
    rect = placed_rect(footprint, 4.15, 14.7, 90.0)
    assert (rect.x1, rect.y1, rect.x2, rect.y2) == pytest.approx(
        (2.25, 10.55, 6.05, 12.55)
    )


def test_seeded_components_keep_their_pose_and_the_rest_is_placed_around_them() -> None:
    components = tuple(_component(f"R{i}") for i in range(1, 5))
    footprints = {c.refdes: _footprint() for c in components}
    seed = Placement("R2", 10.0, 7.5, 90.0)
    placements = {
        p.refdes: p
        for p in compute_placements(_board(), components, footprints, (), seeds=(seed,))
    }
    assert placements["R2"] == seed
    assert sorted(placements) == ["R1", "R2", "R3", "R4"]


def test_seeded_component_outside_the_design_fails_closed() -> None:
    components = (_component("R1"),)
    footprints = {"R1": _footprint()}
    with pytest.raises(PlacementError, match="seeded components are not in the design"):
        compute_placements(
            _board(), components, footprints, (), seeds=(Placement("R9", 5.0, 5.0, 0.0),)
        )


def test_seeded_component_violating_edge_clearance_fails_closed() -> None:
    components = (_component("R1"),)
    footprints = {"R1": _footprint()}
    with pytest.raises(PlacementError, match="edge clearance violated"):
        compute_placements(
            _board(), components, footprints, (), seeds=(Placement("R1", 0.05, 0.05, 0.0),)
        )


def test_coupling_group_keeps_members_within_declared_distance() -> None:
    components = tuple(_component(f"R{i}") for i in range(1, 4))
    footprints = {c.refdes: _footprint() for c in components}
    group = PlacementCouplingConstraint(
        group_id="group",
        primary_refdes="R1",
        coupled_refdes=("R2", "R3"),
        max_distance_mm=4.0,
        move_together=True,
    )
    placements = {
        item.refdes: item
        for item in compute_placements(
            _board(),
            components,
            footprints,
            (),
            coupling_groups=(group,),
        )
    }
    for member in ("R2", "R3"):
        distance = abs(placements["R1"].x_mm - placements[member].x_mm) + abs(
            placements["R1"].y_mm - placements[member].y_mm
        )
        assert distance <= 4.0 + 1e-9
