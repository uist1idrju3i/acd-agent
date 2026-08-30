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
    "LanePreflightMissingNode",
    "LanePreflightReport",
    "LanePreflightStatus",
]
