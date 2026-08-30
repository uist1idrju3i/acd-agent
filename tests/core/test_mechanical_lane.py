"""Mechanical lane extraction and structural consistency tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.electrical import GraphExtractionError
from acd.core.mechanical import extract_mechanical_lane
from acd.schema.design_graph import DesignGraph, GraphNode

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "golden-design-1" / "graph.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_mechanical_lane_extracts_declared_sources_and_geometry() -> None:
    lane = extract_mechanical_lane(_graph())
    assert (lane.outline.width_mm, lane.outline.depth_mm) == (30.0, 25.0)
    assert len(lane.component_bodies) == 30
    assert lane.component_bodies[0].dimensions_source.startswith("Espressif")
    assert lane.connector_openings[0].dimensions_source.startswith("KiCad")
    assert sum(body.body_type == "none" for body in lane.component_bodies) == 11
    assert len(lane.board_edge_overhangs) == 1
    assert lane.board_edge_overhangs[0].component_refdes == "U1"
    assert lane.board_edge_overhangs[0].edge == "top"
    assert lane.board_edge_overhangs[0].overhang_mm == 5.4
    assert lane.board_edge_overhangs[0].requirement_id == "req.gd1-req-015"
    assert lane.enclosure.fastener_method == "self_tapping_screw_m2"
    assert lane.enclosure.standoff_pilot_hole_diameter_mm == 1.6
    assert lane.enclosure.lid_screw_hole_diameter_mm == 2.2


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


def test_mechanical_lane_rejects_missing_component_body() -> None:
    graph = _graph()
    nodes = [
        node
        for node in graph.nodes
        if node.id != "mechanical.component_body.30"
    ]
    with pytest.raises(GraphExtractionError, match=r"missing mechanical\.component_body"):
        extract_mechanical_lane(graph.model_copy(update={"nodes": nodes}))


@pytest.mark.parametrize(
    ("attr", "value", "message"),
    [
        ("edge", "diagonal", "edge"),
        ("component_refdes", "U2", "component_refdes"),
        ("requirement_id", "", "requirement_id"),
    ],
)
def test_mechanical_lane_rejects_invalid_overhang_declaration(
    attr: str, value: object, message: str
) -> None:
    graph = _graph()
    nodes = [
        node.model_copy(update={"attrs": {**node.attrs, attr: value}})
        if node.kind == "mechanical.board_edge_overhang"
        else node
        for node in graph.nodes
    ]
    with pytest.raises(GraphExtractionError, match=message):
        extract_mechanical_lane(graph.model_copy(update={"nodes": nodes}))


def test_mechanical_lane_rejects_overhang_without_solid_body() -> None:
    graph = _graph()
    nodes = [
        node.model_copy(
            update={
                "attrs": {
                    **node.attrs,
                    "body_type": "none",
                    "height_mm": 0.0,
                }
            }
        )
        if node.id == "mechanical.component_body.1"
        else node
        for node in graph.nodes
    ]
    with pytest.raises(GraphExtractionError, match="body must be solid"):
        extract_mechanical_lane(graph.model_copy(update={"nodes": nodes}))


def test_mechanical_lane_rejects_rotated_overhang_body() -> None:
    graph = _graph()
    nodes = [
        node.model_copy(update={"attrs": {**node.attrs, "rotation_deg": 90.0}})
        if node.id == "mechanical.component_body.1"
        else node
        for node in graph.nodes
    ]
    with pytest.raises(GraphExtractionError, match="rotation"):
        extract_mechanical_lane(graph.model_copy(update={"nodes": nodes}))


def test_mechanical_lane_rejects_duplicate_overhang_edge() -> None:
    graph = _graph()
    duplicate = GraphNode(
        id="mechanical.board_edge_overhang.duplicate",
        kind="mechanical.board_edge_overhang",
        attrs={
            "component_refdes": "U1",
            "edge": "top",
            "overhang_mm": 1.0,
            "requirement_id": "req.gd1-req-015",
        },
        depends_on=["comp.u1"],
    )
    with pytest.raises(GraphExtractionError, match="duplicate"):
        extract_mechanical_lane(graph.model_copy(update={"nodes": [*graph.nodes, duplicate]}))


@pytest.mark.parametrize(
    "attr",
    [
        "fastener_method",
        "standoff_pilot_hole_diameter_mm",
        "lid_screw_hole_diameter_mm",
    ],
)
def test_mechanical_lane_rejects_missing_new_enclosure_attribute(attr: str) -> None:
    graph = _graph()
    nodes = [
        node.model_copy(
            update={"attrs": {key: value for key, value in node.attrs.items() if key != attr}}
        )
        if node.kind == "mechanical.enclosure"
        else node
        for node in graph.nodes
    ]
    with pytest.raises(GraphExtractionError, match=attr):
        extract_mechanical_lane(graph.model_copy(update={"nodes": nodes}))


def test_mechanical_lane_rejects_unsupported_fastener_method() -> None:
    graph = _graph()
    nodes = [
        node.model_copy(
            update={"attrs": {**node.attrs, "fastener_method": "heat_set_insert_m2"}}
        )
        if node.kind == "mechanical.enclosure"
        else node
        for node in graph.nodes
    ]
    with pytest.raises(GraphExtractionError, match="fastener_method"):
        extract_mechanical_lane(graph.model_copy(update={"nodes": nodes}))


def test_mechanical_lane_rejects_oversized_pilot_hole() -> None:
    graph = _graph()
    nodes = [
        node.model_copy(
            update={"attrs": {**node.attrs, "standoff_pilot_hole_diameter_mm": 2.0}}
        )
        if node.kind == "mechanical.enclosure"
        else node
        for node in graph.nodes
    ]
    with pytest.raises(GraphExtractionError, match=r"annulus|min_wall"):
        extract_mechanical_lane(graph.model_copy(update={"nodes": nodes}))


def test_mechanical_lane_rejects_lid_hole_smaller_than_pilot() -> None:
    graph = _graph()
    nodes = [
        node.model_copy(
            update={"attrs": {**node.attrs, "lid_screw_hole_diameter_mm": 1.5}}
        )
        if node.kind == "mechanical.enclosure"
        else node
        for node in graph.nodes
    ]
    with pytest.raises(GraphExtractionError, match="at least the pilot"):
        extract_mechanical_lane(graph.model_copy(update={"nodes": nodes}))
