"""Silkscreen graph extraction and fail-closed geometry tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.electrical import GraphExtractionError
from acd.core.silkscreen import extract_silkscreen_lane
from acd.schema.design_graph import DesignGraph

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "golden-design-1" / "graph.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_silkscreen_lane_extracts_declared_text_and_vector_logo() -> None:
    lane = extract_silkscreen_lane(_graph())
    assert {item.text for item in lane.texts} >= {"RST", "BOOT", "DEV BOARD"}
    assert len(lane.graphics) == 1
    assert lane.graphics[0].role == "vibebb_logo"
    assert all(item.placement_reference for item in lane.texts)


def test_silkscreen_declaration_missing_fails_closed() -> None:
    graph = _graph()
    nodes = tuple(node for node in graph.nodes if not node.kind.startswith("mechanical.silk"))
    with pytest.raises(GraphExtractionError, match="silkscreen declarations"):
        extract_silkscreen_lane(graph.model_copy(update={"nodes": nodes}))


def test_silkscreen_text_requires_board_dependency() -> None:
    graph = _graph()
    nodes = tuple(
        node.model_copy(update={"depends_on": []})
        if node.kind == "mechanical.silk_text"
        else node
        for node in graph.nodes
    )
    with pytest.raises(GraphExtractionError, match="must depend on board"):
        extract_silkscreen_lane(graph.model_copy(update={"nodes": nodes}))
