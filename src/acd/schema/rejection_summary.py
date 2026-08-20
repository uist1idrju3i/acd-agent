"""Contracts for non-authoritative hook rejection summaries."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    SchemaVersion,
)

RejectionSource = Literal["hook", "user", "unknown"]
RejectionSummaryStatus = Literal["pass", "unknown"]


class RejectionGroup(AcdModel):
    """Aggregated rejections that share a source, tool, and reason."""

    source: RejectionSource
    tool_name: NonEmptyStr
    reason: NonEmptyStr
    count: int = Field(ge=1)
    action_ids: list[NonEmptyStr] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_counts(self) -> RejectionGroup:
        if len(self.action_ids) != self.count:
            raise ValueError("rejection group count must match its action ids")
        if len(set(self.action_ids)) != len(self.action_ids):
            raise ValueError("rejection group action ids must be unique")
        if self.action_ids != sorted(self.action_ids):
            raise ValueError("rejection group action ids must be sorted")
        return self


class RejectionSummaryReport(AcdModel):
    """Non-authoritative summary of hook and confirmation rejections."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    status: RejectionSummaryStatus
    total: int = Field(default=0, ge=0)
    hook_blocked: int = Field(default=0, ge=0)
    user_rejected: int = Field(default=0, ge=0)
    unknown_source: int = Field(default=0, ge=0)
    groups: list[RejectionGroup] = Field(default_factory=list[RejectionGroup])
    reason: NonEmptyStr | None = None
    pass_evidence: Literal[False] = False

    @model_validator(mode="after")
    def validate_totals(self) -> RejectionSummaryReport:
        if self.status == "unknown":
            if self.reason is None:
                raise ValueError("unknown rejection summary requires a reason")
            return self
        if self.reason is not None:
            raise ValueError("a passing rejection summary must not carry a reason")
        if self.total != self.hook_blocked + self.user_rejected + self.unknown_source:
            raise ValueError("rejection totals must match their per-source counts")
        if self.total != sum(group.count for group in self.groups):
            raise ValueError("rejection totals must match the grouped counts")
        keys = [(group.source, group.tool_name, group.reason) for group in self.groups]
        if len(set(keys)) != len(keys):
            raise ValueError("rejection groups must be unique")
        if keys != sorted(keys):
            raise ValueError("rejection groups must be sorted")
        return self


__all__ = [
    "RejectionGroup",
    "RejectionSource",
    "RejectionSummaryReport",
    "RejectionSummaryStatus",
]
