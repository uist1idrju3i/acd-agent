"""Tests for deterministic decoupling-aware placement normalization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.decoupling_placement import (
    PLACEMENT_SOURCE,
    apply_decoupling_placements,
    solve_decoupling_placements,
)
from acd.core.design_predicates import evaluate_power_decoupling
from acd.core.electrical import extract_electrical_lane
from acd.schema.design_graph import DesignGraph

FIXTURE_DIR = Path("fixtures/golden-design-1")


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(
        (FIXTURE_DIR / "graph.json").read_text(encoding="utf-8")
    )


def _footprint_library_is_present() -> bool:
    for component in extract_electrical_lane(_graph()).components:
        path = Path(component.library.footprint_file)
        if not path.is_absolute():
            path = FIXTURE_DIR / path
        if not path.is_file():
            return False
    return True


pytestmark = pytest.mark.skipif(
    not _footprint_library_is_present(),
    reason="pinned KiCad footprint library is not present in this environment",
)


def _moved(graph: DesignGraph, refdes: str, x_mm: float, y_mm: float) -> DesignGraph:
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
