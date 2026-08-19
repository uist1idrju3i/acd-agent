"""GD1-NEG-001 through GD1-NEG-008 fail-closed regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd.adapters.kicad.board import load_board_footprints
from acd.adapters.kicad.fab import FabOutputError
from acd.adapters.kicad.fab.gerber import verify_ground_plane_gerbers
from acd.adapters.kicad.library import FootprintLibrary, LibraryPinError
from acd.core.board_model import RoutedDesign
from acd.core.design_predicates import (
    evaluate_i2c_pullup,
    evaluate_pin_firmware_alignment,
    evaluate_strapping_pin,
    evaluate_usb_cc,
)
from acd.core.electrical import GraphExtractionError, extract_electrical_lane
from tests.pipeline.gd1_negative_fixtures import (
    FIXTURE_DIR,
    conductor_region_with_stitch_flashes,
    extract_fixture_lane,
    inject_gd1_neg_001_led_to_strapping,
    inject_gd1_neg_002_ground_plane,
    inject_gd1_neg_003_remove_cc_resistor,
    inject_gd1_neg_004_remove_i2c_pullup,
    inject_gd1_neg_005_mismatch_firmware_gpio,
    inject_gd1_neg_006_library_hash_mismatch,
    inject_gd1_neg_006_remove_library_evidence,
    inject_gd1_neg_008_unknown_coordinate_unit,
    load_fixture_fab_profile,
    load_gd1_graph,
    normal_board_model,
)


def test_gd1_neg_001_led_to_strapping_fails_two_gates() -> None:
    graph = inject_gd1_neg_001_led_to_strapping(load_gd1_graph())
    lane = extract_fixture_lane(graph)
    assert evaluate_strapping_pin(graph, lane).status == "fail"
    assert evaluate_pin_firmware_alignment(graph, lane).status == "fail"


def test_gd1_neg_002_antenna_ground_plane_fails_keepout(tmp_path: Path) -> None:
    graph = load_gd1_graph()
    lane = extract_fixture_lane(graph)
    for component in lane.components:
        path = Path(component.library.footprint_file)
        if not path.is_absolute():
            path = FIXTURE_DIR / path
        if not path.is_file():
            pytest.skip(f"pinned KiCad library not present in this environment: {path}")
    model = inject_gd1_neg_002_ground_plane(normal_board_model(graph))
    stitch_points = (
        (0.600001, 0.600001),
        (29.399999, 0.600001),
        (29.399999, 24.399999),
        (0.600001, 24.399999),
    )
    content = conductor_region_with_stitch_flashes(
        width_mm=model.width_mm,
        height_mm=model.height_mm,
        inset_mm=model.edge_clearance_mm + model.via_diameter_mm / 2.0,
        stitch_points=stitch_points,
    )
    front = tmp_path / "F_Cu.gtl"
    back = tmp_path / "B_Cu.gbl"
    front.write_text(content, encoding="ascii")
    back.write_text(content, encoding="ascii")
    with pytest.raises(FabOutputError, match="copper inside antenna keepout"):
        verify_ground_plane_gerbers(
            front,
            back,
            model,
            stitch_points,
            RoutedDesign((), ()),
        )


def test_gd1_neg_003_missing_cc_resistor_fails_usb_cc() -> None:
    graph = inject_gd1_neg_003_remove_cc_resistor(load_gd1_graph())
    lane = extract_fixture_lane(graph)
    assert evaluate_usb_cc(graph, lane).status == "fail"


def test_gd1_neg_004_missing_i2c_pullup_fails_i2c_gate() -> None:
    graph = inject_gd1_neg_004_remove_i2c_pullup(load_gd1_graph())
    lane = extract_fixture_lane(graph)
    assert evaluate_i2c_pullup(graph, lane).status == "fail"


def test_gd1_neg_005_firmware_gpio_mismatch_fails_alignment() -> None:
    graph = inject_gd1_neg_005_mismatch_firmware_gpio(load_gd1_graph())
    lane = extract_fixture_lane(graph)
    assert evaluate_pin_firmware_alignment(graph, lane).status == "fail"


def test_gd1_neg_006_missing_library_evidence_is_rejected() -> None:
    graph = inject_gd1_neg_006_remove_library_evidence(load_gd1_graph())
    with pytest.raises(GraphExtractionError, match="footprint_sha256"):
        extract_fixture_lane(graph)


def test_gd1_library_hash_mismatch_is_rejected() -> None:
    graph = inject_gd1_neg_006_library_hash_mismatch(load_gd1_graph())
    lane = extract_fixture_lane(graph)
    for component in lane.components:
        path = Path(component.library.footprint_file)
        if not path.is_absolute():
            path = FIXTURE_DIR / path
        if not path.is_file():
            pytest.skip(f"pinned KiCad library not present in this environment: {path}")
    with pytest.raises(LibraryPinError, match="hash mismatch"):
        load_board_footprints(
            lane,
            FootprintLibrary(),
            FIXTURE_DIR,
            load_fixture_fab_profile(),
        )


def test_gd1_neg_008_unknown_coordinate_unit_stops_extraction() -> None:
    graph = inject_gd1_neg_008_unknown_coordinate_unit(load_gd1_graph())
    with pytest.raises(GraphExtractionError, match="unsupported coordinate system"):
        extract_electrical_lane(graph)
