"""Mechanical lane extraction and structural consistency tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd_core.electrical import GraphExtractionError
from acd_core.mechanical import extract_mechanical_lane
from acd_schema.design_graph import DesignGraph

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "golden-design-1" / "graph.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(json.loads(FIXTURE.read_text()))


def test_mechanical_lane_extracts_declared_sources_and_geometry() -> None:
    lane = extract_mechanical_lane(_graph())
    assert (lane.outline.width_mm, lane.outline.depth_mm) == (30.0, 25.0)
    assert len(lane.component_bodies) == 3
    assert lane.component_bodies[0].dimensions_source.startswith("Espressif")
    assert lane.connector_openings[0].dimensions_source.startswith("KiCad")


def test_mechanical_lane_rejects_missing_attribute() -> None:
    graph = _graph()
    nodes = [
        node.model_copy(
            update={"attrs": {key: value for key, value in node.attrs.items() if key != "unit"}}
        )
        if node.kind == "mechanical.enclosure"
        else node
        for node in graph.nodes
    ]
    with pytest.raises(GraphExtractionError, match="unit"):
        extract_mechanical_lane(graph.model_copy(update={"nodes": nodes}))


def test_mechanical_lane_rejects_outline_board_mismatch() -> None:
    graph = _graph()
    nodes = [
        node.model_copy(update={"attrs": {**node.attrs, "width_mm": 31.0}})
        if node.kind == "mechanical.outline"
        else node
        for node in graph.nodes
    ]
    with pytest.raises(GraphExtractionError, match="does not match"):
        extract_mechanical_lane(graph.model_copy(update={"nodes": nodes}))
