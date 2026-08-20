"""Graph-derived output naming tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.naming import firmware_project_name, output_prefix, subject_node_id
from acd.schema.design_graph import DesignGraph, GraphNode

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "golden-design-1" / "graph.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_output_prefix_is_derived_from_the_graph_id() -> None:
    graph = _graph()
    assert graph.graph_id == "golden-design-1"
    assert output_prefix(graph.graph_id) == "golden-design-1"


@pytest.mark.parametrize(
    ("graph_id", "expected"),
    [("GD 1", "gd-1"), ("golden_design_1", "golden-design-1"), ("a/b", "a-b")],
)
def test_output_prefix_normalizes_separators(graph_id: str, expected: str) -> None:
    assert output_prefix(graph_id) == expected


@pytest.mark.parametrize("graph_id", ["", "   ", "---", "..", "/"])
def test_unusable_graph_id_fails_closed(graph_id: str) -> None:
    with pytest.raises(ValueError, match="output prefix"):
        output_prefix(graph_id)


def test_firmware_project_name_is_a_c_identifier() -> None:
    assert firmware_project_name("golden-design-1") == "acd_golden_design_1_fw"


def test_subject_node_is_taken_from_the_graph() -> None:
    graph = _graph()
    assert subject_node_id(graph, "electrical.board") == "board.gd1"
    assert subject_node_id(graph, "mechanical.enclosure") == "mechanical.enclosure.gd1"


def test_missing_subject_node_fails_closed() -> None:
    graph = _graph()
    without_board = graph.model_copy(
        update={"nodes": [node for node in graph.nodes if node.kind != "electrical.board"]}
    )
    with pytest.raises(ValueError, match="Evidence subject node"):
        subject_node_id(without_board, "electrical.board")


def test_ambiguous_subject_node_fails_closed() -> None:
    graph = _graph()
    board = next(node for node in graph.nodes if node.kind == "electrical.board")
    duplicated: GraphNode = board.model_copy(update={"id": "board.gd1-copy"})
    ambiguous = graph.model_copy(update={"nodes": [*graph.nodes, duplicated]})
    with pytest.raises(ValueError, match="Evidence subject node"):
        subject_node_id(ambiguous, "electrical.board")
