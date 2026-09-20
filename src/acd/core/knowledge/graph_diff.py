"""Deterministic graph revision difference calculations."""

from __future__ import annotations

from acd.schema.design_graph import DesignGraph
from acd.schema.graph_diff import GraphDiff, GraphNodeDiff


class GraphDiffError(ValueError):
    """Raised when graph revisions cannot be compared."""


def _edge_keys(graph: DesignGraph) -> set[str]:
    return {f"{node.id}->{dependency}" for node in graph.nodes for dependency in node.depends_on}


def build_graph_diff(previous: DesignGraph, current: DesignGraph) -> GraphDiff:
    if previous.graph_id != current.graph_id:
        raise GraphDiffError(
            f"previous graph targets graph {previous.graph_id!r}, not {current.graph_id!r}"
        )
    if previous.revision == current.revision:
        raise GraphDiffError(f"previous graph has the same revision {current.revision!r}")
    previous_nodes = {node.id: node for node in previous.nodes}
    current_nodes = {node.id: node for node in current.nodes}
    changed: list[GraphNodeDiff] = []
    for node_id in sorted(set(previous_nodes) & set(current_nodes)):
        before = previous_nodes[node_id]
        after = current_nodes[node_id]
        fields: list[str] = []
        if before.kind != after.kind:
            fields.append("kind")
        fields.extend(
            f"attrs.{key}"
            for key in sorted(set(before.attrs) | set(after.attrs))
            if key not in before.attrs
            or key not in after.attrs
            or before.attrs[key] != after.attrs[key]
        )
        if fields:
            changed.append(GraphNodeDiff(id=node_id, changed_fields=sorted(fields)))
    previous_edges = _edge_keys(previous)
    current_edges = _edge_keys(current)
    return GraphDiff(
        schema_version=current.schema_version,
        graph_id=current.graph_id,
        status="computed",
        previous_revision=previous.revision,
        current_revision=current.revision,
        nodes_added=sorted(set(current_nodes) - set(previous_nodes)),
        nodes_removed=sorted(set(previous_nodes) - set(current_nodes)),
        nodes_changed=changed,
        edges_added=sorted(current_edges - previous_edges),
        edges_removed=sorted(previous_edges - current_edges),
    )


def unknown_graph_diff(current: DesignGraph, reason: str) -> GraphDiff:
    return GraphDiff(
        schema_version=current.schema_version,
        graph_id=current.graph_id,
        status="unknown",
        current_revision=current.revision,
        reason=reason,
    )


__all__ = ["GraphDiffError", "build_graph_diff", "unknown_graph_diff"]
