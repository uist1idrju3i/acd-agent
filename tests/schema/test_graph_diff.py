"""Graph diff schema contract tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema import GraphDiff, GraphNodeDiff


def _computed(**overrides: object) -> GraphDiff:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "status": "computed",
        "graph_id": "demo",
        "previous_revision": "r1",
        "current_revision": "r2",
    }
    payload.update(overrides)
    return GraphDiff.model_validate(payload)


def test_computed_graph_diff_accepts_sorted_fields() -> None:
    diff = _computed(
        nodes_added=["node.a"],
        nodes_removed=["node.b"],
        nodes_changed=[GraphNodeDiff(id="node.c", changed_fields=["attrs.text"])],
        edges_added=["node.c->node.a"],
        edges_removed=["node.c->node.b"],
    )
    assert diff.pass_evidence is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"previous_revision": None},
        {"reason": "unexpected"},
        {"nodes_added": ["node.b", "node.a"]},
        {
            "nodes_changed": [
                GraphNodeDiff(id="node.b", changed_fields=[]),
                GraphNodeDiff(id="node.a", changed_fields=[]),
            ]
        },
    ],
)
def test_computed_graph_diff_rejects_invalid_contract(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _computed(**overrides)


def test_unknown_graph_diff_requires_empty_lists_and_reason() -> None:
    diff = GraphDiff(
        schema_version="1.0",
        status="unknown",
        graph_id="demo",
        current_revision="r2",
        reason="previous revision not declared",
    )
    assert diff.nodes_added == []
    with pytest.raises(ValidationError):
        GraphDiff(
            schema_version="1.0",
            status="unknown",
            graph_id="demo",
            current_revision="r2",
            reason="unknown",
            nodes_added=["node.a"],
        )
