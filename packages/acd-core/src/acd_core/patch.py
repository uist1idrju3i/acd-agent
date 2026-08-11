"""Graph patch application.

A patch targets one specific revision and produces the next revision.
Applying a patch to any other revision raises (fail-closed); patches are
never merged semantically.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from acd_core.revision import next_revision
from acd_schema import AcdModel, DesignGraph, GraphNode
from acd_schema.common import NodeId, Revision
from acd_schema.design_graph import AttrValue


class AddNode(AcdModel):
    op: Literal["add_node"] = "add_node"
    node: GraphNode


class RemoveNode(AcdModel):
    op: Literal["remove_node"] = "remove_node"
    node_id: NodeId


class SetAttrs(AcdModel):
    op: Literal["set_attrs"] = "set_attrs"
    node_id: NodeId
    attrs: dict[str, AttrValue]


PatchOp = AddNode | RemoveNode | SetAttrs


class GraphPatch(AcdModel):
    base_revision: Revision
    ops: list[PatchOp] = Field(min_length=1)

    def changed_node_ids(self) -> set[str]:
        changed: set[str] = set()
        for op in self.ops:
            if isinstance(op, AddNode):
                changed.add(op.node.id)
            else:
                changed.add(op.node_id)
        return changed


class RevisionMismatchError(ValueError):
    """Raised when a patch targets a revision other than the graph's current one."""


def apply_patch(graph: DesignGraph, patch: GraphPatch) -> DesignGraph:
    if patch.base_revision != graph.revision:
        raise RevisionMismatchError(
            f"patch targets {patch.base_revision!r} but graph is at {graph.revision!r}"
        )
    nodes: dict[str, GraphNode] = {node.id: node for node in graph.nodes}
    for op in patch.ops:
        if isinstance(op, AddNode):
            if op.node.id in nodes:
                raise ValueError(f"node already exists: {op.node.id!r}")
            nodes[op.node.id] = op.node
        elif isinstance(op, RemoveNode):
            if op.node_id not in nodes:
                raise ValueError(f"node does not exist: {op.node_id!r}")
            del nodes[op.node_id]
        else:
            if op.node_id not in nodes:
                raise ValueError(f"node does not exist: {op.node_id!r}")
            current = nodes[op.node_id]
            nodes[op.node_id] = current.model_copy(
                update={"attrs": {**current.attrs, **op.attrs}}
            )
    return DesignGraph(
        schema_version=graph.schema_version,
        graph_id=graph.graph_id,
        revision=next_revision(graph.revision),
        nodes=list(nodes.values()),
    )
