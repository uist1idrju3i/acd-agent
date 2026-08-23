"""Canonical Pydantic design graph."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
)

NodeKind = Literal[
    "requirement",
    "electrical.net",
    "electrical.component",
    "electrical.pin",
    "electrical.board",
    "fab.order_intent",
    "fab.process_allowance",
    "mechanical.outline",
    "mechanical.component_body",
    "mechanical.connector_opening",
    "mechanical.board_edge_overhang",
    "mechanical.enclosure",
    "mechanical.silk_text",
    "mechanical.silk_graphic",
    "firmware.module",
    "firmware.state",
    "firmware.state_transition",
    "firmware.sequence_step",
    "firmware.pin_assignment",
    "design.functional_block",
    "safety.boundary",
    "evidence.anchor",
]

AttrValue = str | float | int | bool | list[str] | None


class GraphNode(AcdModel):
    id: NodeId
    kind: NodeKind
    attrs: dict[str, AttrValue] = Field(default_factory=dict)
    depends_on: list[NodeId] = Field(default_factory=list[NodeId])

    @model_validator(mode="after")
    def _unique_depends_on(self) -> GraphNode:
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("depends_on entries must be unique")
        if self.kind == "design.functional_block" and set(self.attrs) != {"block_id"}:
            raise ValueError("design.functional_block attrs must contain only block_id")
        return self


class DesignGraph(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    graph_id: NonEmptyStr
    revision: Revision
    nodes: list[GraphNode] = Field(default_factory=list[GraphNode])

    @model_validator(mode="after")
    def _validate_references(self) -> DesignGraph:
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("node ids must be unique")
        known = set(ids)
        for node in self.nodes:
            for dep in node.depends_on:
                if dep not in known:
                    raise ValueError(f"node {node.id!r} depends on unknown node {dep!r}")
        return self

    def node_by_id(self, node_id: str) -> GraphNode:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)
