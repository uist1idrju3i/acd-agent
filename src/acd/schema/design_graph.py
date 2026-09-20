"""Canonical Pydantic design graph."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from acd.schema.common import (
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    VersionedAcdModel,
)
from acd.schema.node_attrs import KIND_ATTRS_MODELS, AttrsModel

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
        return self

    @model_validator(mode="after")
    def _validate_kind_attrs(self) -> GraphNode:
        model = KIND_ATTRS_MODELS.get(self.kind)
        if model is not None:
            try:
                model.model_validate(self.attrs)
            except ValidationError as error:
                raise ValueError(
                    f"{self.kind} attrs are invalid: {_summarize_errors(error)}"
                ) from error
        return self

    def typed_attrs(self, model: type[AttrsModel]) -> AttrsModel:
        """Return ``attrs`` as a kind-specific typed view.

        The view is re-validated so that callers reading a node built through a
        non-validating path (for example ``model_construct``) still fail closed.
        """
        return model.model_validate(self.attrs)


def _summarize_errors(error: ValidationError) -> str:
    parts: list[str] = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"])
        message = item["msg"]
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts)


class DesignGraph(VersionedAcdModel):
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
