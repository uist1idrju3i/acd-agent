"""Conversation-derived requirement contracts."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
)
from acd.schema.design_graph import NodeKind


class RequirementRecord(AcdModel):
    """A machine-linked requirement declaration."""

    requirement_id: NonEmptyStr
    statement: NonEmptyStr
    drives_functional_blocks: list[NonEmptyStr] = Field(
        default_factory=list[NonEmptyStr]
    )
    constrains_node_ids: list[NodeId] = Field(default_factory=list[NodeId])
    constrains_node_kinds: list[NodeKind] = Field(default_factory=list[NodeKind])
    expectation: dict[str, Any] | None = None
    graph_anchored: bool = True

    @property
    def text(self) -> str:
        """Return the graph-node text spelling used by existing fixtures."""
        return self.statement

    @model_validator(mode="after")
    def _unique_links(self) -> RequirementRecord:
        if len(set(self.drives_functional_blocks)) != len(self.drives_functional_blocks):
            raise ValueError("drives_functional_blocks entries must be unique")
        if len(set(self.constrains_node_ids)) != len(self.constrains_node_ids):
            raise ValueError("constrains_node_ids entries must be unique")
        if len(set(self.constrains_node_kinds)) != len(self.constrains_node_kinds):
            raise ValueError("constrains_node_kinds entries must be unique")
        return self


class RequirementDocument(AcdModel):
    """Requirements attached to one design graph."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    graph_id: NonEmptyStr
    revision: Revision
    records: list[RequirementRecord] = Field(default_factory=list[RequirementRecord])

    @model_validator(mode="after")
    def _unique_requirement_ids(self) -> RequirementDocument:
        ids = [record.requirement_id for record in self.records]
        if len(set(ids)) != len(ids):
            raise ValueError("requirement_id entries must be unique")
        return self


__all__ = ["RequirementDocument", "RequirementRecord"]
