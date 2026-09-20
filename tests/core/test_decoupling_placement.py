"""Tests for deterministic decoupling-aware placement normalization.

The minimal fixture under ``fixtures/decoupling-placement-minimal`` carries its
own footprint files, so the core regression runs on hosts without the pinned
KiCad library. The two GD1-based checks are gated by the
``pinned_footprint_library`` marker: they skip on hosts and fail closed in the
container-gates job where ``ACD_REQUIRE_PINNED_LIBRARY=1`` is set (see
``tests/conftest.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.adapters.kicad.library import FootprintLibrary
from acd.core.electrical.decoupling_placement import (
    PLACEMENT_SOURCE,
    apply_decoupling_placements,
    solve_decoupling_placements,
)
from acd.core.electrical.electrical import extract_electrical_lane
from acd.core.knowledge.design_predicates import evaluate_power_decoupling
from acd.schema.design_graph import DesignGraph

FIXTURE_DIR = Path("fixtures/decoupling-placement-minimal")
GD1_FIXTURE_DIR = Path("fixtures/golden-design-1")

# Fixed geometry of the minimal fixture: C2 pad 1 sits at x = -0.775 relative
# to the component origin, so the declared placement (25.075, 17.0) puts it at
# (24.3, 17.0), exactly 2.0 mm from U1 pad 3 at (22.3, 17.0).
EXPECTED_C2_PAD1_X_MM = -0.775
EXPECTED_C2_PAD2_X_MM = 0.775
EXPECTED_U1_PAD3_X_MM = 2.3
EXPECTED_U1_PAD3_Y_MM = -3.0
EXPECTED_C2_DISTANCE_MM = 2.0
EXPECTED_C2_LIMIT_MM = 3.0


def _graph(fixture_dir: Path = FIXTURE_DIR) -> DesignGraph:
    return DesignGraph.model_validate_json(
        (fixture_dir / "graph.json").read_text(encoding="utf-8")
    )


def _moved(
    graph: DesignGraph, refdes: str, x_mm: float, y_mm: float
) -> DesignGraph:
    nodes = [
        node.model_copy(
            update={
                "attrs": {
                    **node.attrs,
                    "placement_x_mm": x_mm,
                    "placement_y_mm": y_mm,
                }
            }
        )
        if node.kind == "electrical.component" and node.attrs.get("refdes") == refdes
        else node
        for node in graph.nodes
    ]
    return graph.model_copy(update={"nodes": nodes})


def test_minimal_fixture_pad_coordinates_and_distance_are_fixed() -> None:
    library = FootprintLibrary()
    c_pad_positions = {
        pad.number: (pad.x_mm, pad.y_mm)
        for pad in library.shape_from_raw(
            "MIN:C_0603",
            library.raw(FIXTURE_DIR / "footprints" / "C_0603.kicad_mod"),
        ).pads
    }
    reg_pad_positions = {
        pad.number: (pad.x_mm, pad.y_mm)
        for pad in library.shape_from_raw(
            "MIN:REG_SOT223",
            library.raw(FIXTURE_DIR / "footprints" / "REG_SOT223.kicad_mod"),
        ).pads
    }

    assert c_pad_positions["1"] == (EXPECTED_C2_PAD1_X_MM, 0.0)
    assert c_pad_positions["2"] == (EXPECTED_C2_PAD2_X_MM, 0.0)
    assert reg_pad_positions["3"] == (
        EXPECTED_U1_PAD3_X_MM,
        EXPECTED_U1_PAD3_Y_MM,
    )

    report = solve_decoupling_placements(_graph(), FIXTURE_DIR)

    placement = next(item for item in report.placements if item.refdes == "C2")
    assert placement.distance_mm == EXPECTED_C2_DISTANCE_MM
    assert placement.limit_mm == EXPECTED_C2_LIMIT_MM


def test_declared_fixture_placement_is_already_satisfied() -> None:
    graph = _graph()

    report = solve_decoupling_placements(graph, FIXTURE_DIR)

    assert report.status == "satisfied"
    assert report.deficiencies == ()
    assert report.placements
    assert all(not item.changed for item in report.placements)
    assert all(item.distance_mm <= item.limit_mm for item in report.placements)


def test_displaced_capacitor_is_moved_back_within_the_limit() -> None:
    graph = _graph()
    lane = extract_electrical_lane(graph)
    capacitor = next(
        item for item in lane.components if item.decoupling_target is not None
    )
    displaced = _moved(graph, capacitor.refdes, 30.0, 30.0)

    report = solve_decoupling_placements(displaced, FIXTURE_DIR)

    assert report.status == "adjusted"
    assert report.deficiencies == ()
    moved = next(item for item in report.placements if item.refdes == capacitor.refdes)
    assert moved.changed is True
    assert moved.distance_mm <= moved.limit_mm

    applied = apply_decoupling_placements(displaced, report)
    predicate = evaluate_power_decoupling(
        applied, extract_electrical_lane(applied), FIXTURE_DIR
    )
    assert predicate.status == "pass"


def test_applied_placement_records_deterministic_provenance() -> None:
    graph = _graph()
    displaced = _moved(graph, "C2", 28.0, 28.0)
    report = solve_decoupling_placements(displaced, FIXTURE_DIR)
    applied = apply_decoupling_placements(displaced, report)

    node = next(
        item
        for item in applied.nodes
        if item.kind == "electrical.component" and item.attrs.get("refdes") == "C2"
    )
    assert node.attrs["placement_source"] == PLACEMENT_SOURCE


def test_unresolvable_declaration_is_reported_without_authority() -> None:
    graph = _graph()
    nodes = [
        node.model_copy(
            update={
                "attrs": {**node.attrs, "decoupling_target": "U404"},
            }
        )
        if node.kind == "electrical.component"
        and node.attrs.get("refdes") == "C2"
        else node
        for node in graph.nodes
    ]
    broken = graph.model_copy(update={"nodes": nodes})

    report = solve_decoupling_placements(broken, FIXTURE_DIR)

    assert report.status == "deficient"
    assert any(item.refdes == "C2" for item in report.deficiencies)
    payload = report.as_payload()
    assert payload["pass_evidence"] is False
    assert payload["record_class"] == "L3"
    assert payload["status"] == "deficient"


def test_report_payload_is_json_serializable() -> None:
    report = solve_decoupling_placements(_graph(), FIXTURE_DIR)

    payload = json.loads(json.dumps(report.as_payload()))

    assert payload["artifact_kind"] == "decoupling_placement_report"


def test_unchanged_report_keeps_the_graph_identical() -> None:
    graph = _graph()
    report = solve_decoupling_placements(graph, FIXTURE_DIR)

    assert apply_decoupling_placements(graph, report) is graph


@pytest.mark.pinned_footprint_library
def test_gd1_declared_placement_is_already_satisfied() -> None:
    graph = _graph(GD1_FIXTURE_DIR)

    report = solve_decoupling_placements(graph, GD1_FIXTURE_DIR)

    assert report.status == "satisfied"
    assert report.deficiencies == ()
    assert report.placements
    assert all(not item.changed for item in report.placements)
    assert all(item.distance_mm <= item.limit_mm for item in report.placements)


@pytest.mark.pinned_footprint_library
def test_gd1_displaced_capacitor_is_moved_back_within_the_limit() -> None:
    graph = _graph(GD1_FIXTURE_DIR)
    lane = extract_electrical_lane(graph)
    capacitor = next(
        item for item in lane.components if item.decoupling_target is not None
    )
    displaced = _moved(graph, capacitor.refdes, 30.0, 30.0)

    report = solve_decoupling_placements(displaced, GD1_FIXTURE_DIR)

    assert report.status == "adjusted"
    assert report.deficiencies == ()
    moved = next(item for item in report.placements if item.refdes == capacitor.refdes)
    assert moved.changed is True
    assert moved.distance_mm <= moved.limit_mm

    applied = apply_decoupling_placements(displaced, report)
    predicate = evaluate_power_decoupling(
        applied, extract_electrical_lane(applied), GD1_FIXTURE_DIR
    )
    assert predicate.status == "pass"
