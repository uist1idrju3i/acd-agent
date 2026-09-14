"""Canonical contract for graph revision differences."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import AcdModel, NodeId, NonEmptyStr, Revision, SchemaVersion


class GraphNodeDiff(AcdModel):
    id: NodeId
    changed_fields: list[NonEmptyStr]

    @model_validator(mode="after")
    def validate_sorted_fields(self) -> GraphNodeDiff:
        if self.changed_fields != sorted(self.changed_fields):
            raise ValueError("node changed_fields must be sorted")
        return self


class GraphDiff(AcdModel):
    schema_version: SchemaVersion
    artifact_kind: Literal["graph_diff"] = "graph_diff"
    pass_evidence: Literal[False] = False
    status: Literal["computed", "unknown"]
    graph_id: NonEmptyStr
    current_revision: Revision
    previous_revision: Revision | None = None
    reason: NonEmptyStr | None = None
    nodes_added: list[NodeId] = Field(default_factory=list[NodeId])
    nodes_removed: list[NodeId] = Field(default_factory=list[NodeId])
    nodes_changed: list[GraphNodeDiff] = Field(
        default_factory=list[GraphNodeDiff]
    )
    edges_added: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    edges_removed: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])

    @model_validator(mode="after")
    def validate_status_contract(self) -> GraphDiff:
        lists = (
            self.nodes_added,
            self.nodes_removed,
            self.nodes_changed,
            self.edges_added,
            self.edges_removed,
        )
        if self.status == "computed":
            if self.previous_revision is None:
                raise ValueError("computed graph diff requires previous_revision")
            if self.reason is not None:
                raise ValueError("computed graph diff must not declare reason")
            if self.nodes_added != sorted(self.nodes_added):
                raise ValueError("nodes_added must be sorted")
            if self.nodes_removed != sorted(self.nodes_removed):
                raise ValueError("nodes_removed must be sorted")
            if self.nodes_changed != sorted(self.nodes_changed, key=lambda item: item.id):
                raise ValueError("nodes_changed must be sorted")
            if self.edges_added != sorted(self.edges_added):
                raise ValueError("edges_added must be sorted")
            if self.edges_removed != sorted(self.edges_removed):
                raise ValueError("edges_removed must be sorted")
        else:
            if self.reason is None:
                raise ValueError("unknown graph diff requires reason")
            if self.previous_revision is not None:
                raise ValueError("unknown graph diff must not declare previous_revision")
            if any(lists):
                raise ValueError("unknown graph diff must have empty diff lists")
        return self


__all__ = ["GraphDiff", "GraphNodeDiff"]
