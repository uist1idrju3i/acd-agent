"""Canonical Pydantic design graph."""

from __future__ import annotations

from typing import Literal, cast

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
    "electrical.placement_group",
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
        if self.kind == "electrical.placement_group":
            required = {"primary_refdes", "coupled_refdes"}
            allowed = {
                "primary_refdes",
                "coupled_refdes",
                "max_distance_mm",
                "move_together",
            }
            if set(self.attrs) - allowed or not required <= set(self.attrs):
                raise ValueError(
                    "electrical.placement_group attrs must declare primary_refdes "
                    "and coupled_refdes"
                )
            coupled = cast(object, self.attrs.get("coupled_refdes"))
            primary = self.attrs.get("primary_refdes")
            if not isinstance(primary, str) or not primary:
                raise ValueError(
                    "electrical.placement_group primary_refdes must be a non-empty string"
                )
            if not isinstance(coupled, list) or not coupled:
                raise ValueError(
                    "electrical.placement_group coupled_refdes must be a non-empty string list"
                )
            coupled_values = cast(list[object], coupled)
            if any(
                not isinstance(item, str) or not item for item in coupled_values
            ):
                raise ValueError(
                    "electrical.placement_group coupled_refdes must be a non-empty string list"
                )
            move_together = self.attrs.get("move_together")
            max_distance = self.attrs.get("max_distance_mm")
            if move_together is not None and not isinstance(move_together, bool):
                raise ValueError(
                    "electrical.placement_group move_together must be boolean"
                )
            if max_distance is not None and (
                isinstance(max_distance, bool)
                or not isinstance(max_distance, int | float)
                or max_distance <= 0
            ):
                raise ValueError(
                    "electrical.placement_group max_distance_mm must be positive"
                )
            if max_distance is None:
                raise ValueError(
                    "electrical.placement_group requires explicit max_distance_mm"
                )
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
