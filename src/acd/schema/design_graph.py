"""Canonical Pydantic design graph."""

from __future__ import annotations

from typing import Any, Literal, cast

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
    "electrical.stackup",
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
    "mechanism_feature",
    "mechanical.silk_text",
    "mechanical.silk_graphic",
    "firmware.module",
    "firmware.state",
    "firmware.state_transition",
    "firmware.sequence_step",
    "firmware.pin_assignment",
    "design.functional_block",
    "design.responsibility",
    "safety.boundary",
    "safety.redundant_group",
    "evidence.anchor",
]

AttrScalar = str | float | int | bool | None
AttrValue = AttrScalar | list[Any] | dict[str, Any]


class GraphNode(AcdModel):
    id: NodeId
    kind: NodeKind
    attrs: dict[str, AttrValue] = Field(default_factory=dict)
    depends_on: list[NodeId] = Field(default_factory=list[NodeId])

    @model_validator(mode="after")
    def _unique_depends_on(self) -> GraphNode:
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("depends_on entries must be unique")
        if self.kind == "design.functional_block" and set(self.attrs) - {
            "block_id",
            "parent_block_id",
        }:
            raise ValueError(
                "design.functional_block attrs must contain only block_id and parent_block_id"
            )
        if self.kind == "design.functional_block":
            for attr in ("block_id", "parent_block_id"):
                value = self.attrs.get(attr)
                if value is not None and (not isinstance(value, str) or not value):
                    raise ValueError(
                        f"design.functional_block {attr} must be a non-empty string"
                    )
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
        if self.kind == "electrical.net":
            signal_class = self.attrs.get("signal_class")
            if signal_class is not None and signal_class not in {
                "safety_extra_low_voltage",
                "mains",
                "analog_sensitive",
                "high_speed",
                "power",
                "digital",
            }:
                raise ValueError("electrical.net signal_class is invalid")
            critical = self.attrs.get("critical")
            if critical is not None and not isinstance(critical, bool):
                raise ValueError("electrical.net critical must be boolean")
            off_board = self.attrs.get("off_board")
            if off_board is not None and not isinstance(off_board, bool):
                raise ValueError("electrical.net off_board must be boolean")
            intended = self.attrs.get("intended_coupling")
            if intended is not None and (
                not isinstance(intended, list)
                or any(not isinstance(item, str) or not item for item in intended)
            ):
                raise ValueError("electrical.net intended_coupling must be a string list")
        if self.kind == "electrical.component":
            protection_role = self.attrs.get("protection_role")
            if protection_role is not None and protection_role not in {
                "fuse",
                "efuse",
                "polyfuse",
                "tvs",
                "current_limit",
            }:
                raise ValueError("electrical.component protection_role is invalid")
        if self.kind == "safety.redundant_group":
            allowed = {"members", "resources_shared_forbidden"}
            if set(self.attrs) - allowed or not allowed <= set(self.attrs):
                raise ValueError(
                    "safety.redundant_group requires members and resources_shared_forbidden"
                )
            for attr in allowed:
                value = self.attrs.get(attr)
                if not isinstance(value, list) or any(
                    not isinstance(item, str) or not item for item in value
                ):
                    raise ValueError(
                        f"safety.redundant_group {attr} must be a string list"
                    )
            resources = cast(list[object], self.attrs["resources_shared_forbidden"])
            if any(
                item
                not in {
                    "connector",
                    "harness",
                    "power_bus",
                    "ic",
                    "via",
                    "thermal_path",
                    "protection_device",
                }
                for item in resources
            ):
                raise ValueError(
                    "safety.redundant_group resources_shared_forbidden contains "
                    "an unsupported resource"
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
        blocks = {
            node.id: node
            for node in self.nodes
            if node.kind == "design.functional_block"
        }
        for node in blocks.values():
            parent = node.attrs.get("parent_block_id")
            if parent is not None and (
                not isinstance(parent, str)
                or parent not in blocks
            ):
                raise ValueError(
                    f"functional block {node.id!r} references unknown parent block"
                )
        for node_id in blocks:
            seen: set[str] = set()
            current = node_id
            while current in blocks:
                if current in seen:
                    raise ValueError("functional block parent hierarchy contains a cycle")
                seen.add(current)
                parent = blocks[current].attrs.get("parent_block_id")
                if not isinstance(parent, str):
                    break
                current = parent
        return self

    def node_by_id(self, node_id: str) -> GraphNode:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)
