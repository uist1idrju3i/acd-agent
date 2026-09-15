"""Graph diff core builder tests."""

from __future__ import annotations

import pytest

from acd.core.graph_diff import GraphDiffError, build_graph_diff, unknown_graph_diff
from acd.schema import DesignGraph, GraphNode


def _graph(revision: str, *, dependency: str = "node.a") -> DesignGraph:
    return DesignGraph(
        graph_id="demo",
        revision=revision,
        nodes=[
            GraphNode(id="node.a", kind="requirement", attrs={"text": "old"}),
            GraphNode(
                id="node.b",
                kind="electrical.net",
                attrs={"name": "net"},
                depends_on=[dependency],
            ),
        ],
    )


def test_build_graph_diff_compares_kind_attrs_and_edges() -> None:
    previous = _graph("r1")
    current = DesignGraph(
        graph_id="demo",
        revision="r2",
        nodes=[
            GraphNode(id="node.a", kind="requirement", attrs={"text": "new"}),
            GraphNode(
                id="node.b",
                kind="electrical.net",
                attrs={"name": "net"},
                depends_on=["node.a"],
            ),
            GraphNode(id="node.c", kind="requirement"),
        ],
    )
    diff = build_graph_diff(previous, current)
    assert diff.nodes_added == ["node.c"]
    assert diff.nodes_removed == []
    assert [node.model_dump(mode="json") for node in diff.nodes_changed] == [
        {"id": "node.a", "changed_fields": ["attrs.text"]}
    ]


def test_build_graph_diff_detects_edge_replacement_without_node_change() -> None:
    previous = _graph("r1", dependency="node.a")
    current = DesignGraph(
        graph_id="demo",
        revision="r2",
        nodes=[
            previous.nodes[0],
            GraphNode(
                id="node.b",
                kind="electrical.net",
                attrs={"name": "net"},
                depends_on=["node.c"],
            ),
            GraphNode(id="node.c", kind="requirement"),
        ],
    )
    diff = build_graph_diff(previous, current)
    assert diff.nodes_changed == []
    assert diff.edges_added == ["node.b->node.c"]
    assert diff.edges_removed == ["node.b->node.a"]


@pytest.mark.parametrize(
    "previous,current,match",
    [
        (_graph("r1"), DesignGraph(graph_id="other", revision="r2"), "graph"),
        (_graph("r1"), _graph("r1"), "same revision"),
    ],
)
def test_build_graph_diff_rejects_invalid_revisions(
    previous: DesignGraph, current: DesignGraph, match: str
) -> None:
    with pytest.raises(GraphDiffError, match=match):
        build_graph_diff(previous, current)


def test_unknown_graph_diff_is_explicit() -> None:
    diff = unknown_graph_diff(_graph("r2"), "previous revision not declared")
    assert diff.status == "unknown"
    assert diff.reason == "previous revision not declared"
    assert diff.nodes_added == []
