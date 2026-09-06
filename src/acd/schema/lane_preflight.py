"""Schema for the diagnostic lane preflight report.

The preflight report is diagnostic only. It never replaces an L1 gate judgment,
and `declarations_complete` is not design success.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from acd.schema.common import AcdModel, NonEmptyStr, Revision

LanePreflightStatus = Literal[
    "declarations_complete",
    "declarations_incomplete",
]


class LanePreflightMissingNode(AcdModel):
    kind: NonEmptyStr
    required_count: int
    present_count: int
    reason: NonEmptyStr


class LanePreflightMissingAttr(AcdModel):
    node_id: NonEmptyStr
    kind: NonEmptyStr
    attr: NonEmptyStr
    reason: NonEmptyStr


class LanePreflightMissingDeclaration(AcdModel):
    """One declaration set the design input must add for a lane.

    `spec_path` names where the node kind is declared in the design input
    (DesignFixtureSpec). `missing_count` is the number of nodes still to declare
    (`present_count` is None when enough nodes exist); `missing_attrs` lists
    attributes absent from nodes that already exist.
    """

    lane: NonEmptyStr
    kind: NonEmptyStr
    spec_path: NonEmptyStr
    required_count: int
    present_count: int | None
    missing_count: int
    required_attrs: list[str] = Field(default_factory=list[str])
    missing_attrs: list[LanePreflightMissingAttr] = Field(
        default_factory=list[LanePreflightMissingAttr]
    )


class LanePreflightLaneReport(AcdModel):
    lane: NonEmptyStr
    status: LanePreflightStatus
    missing_nodes: list[LanePreflightMissingNode] = Field(
        default_factory=list[LanePreflightMissingNode]
    )
    missing_attrs: list[LanePreflightMissingAttr] = Field(
        default_factory=list[LanePreflightMissingAttr]
    )


class LanePreflightReport(AcdModel):
    graph_id: NonEmptyStr
    revision: Revision
    status: LanePreflightStatus
    # Restated in the artifact so a reader cannot mistake it for a gate result.
    diagnostic_only: Literal[True] = True
    record_class: Literal["L3"] = "L3"
    checked_predicates: list[str]
    unchecked_predicates: list[str]
    lanes: list[LanePreflightLaneReport] = Field(
        default_factory=list[LanePreflightLaneReport]
    )


__all__ = [
    "LanePreflightLaneReport",
    "LanePreflightMissingAttr",
    "LanePreflightMissingDeclaration",
    "LanePreflightMissingNode",
    "LanePreflightReport",
    "LanePreflightStatus",
]
