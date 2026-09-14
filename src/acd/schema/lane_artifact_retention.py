"""Pydantic contracts for the declared per-lane retained artifact set."""

from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import Field, field_validator, model_validator

from acd.schema.common import AcdModel, NonEmptyStr, SchemaVersion

RetentionLaneId = NonEmptyStr


def _check_relative_glob(pattern: str) -> str:
    path = PurePosixPath(pattern)
    if path.is_absolute():
        raise ValueError("retention patterns must be relative to the lane output")
    if ".." in path.parts:
        raise ValueError("retention patterns must not traverse parent directories")
    return pattern


class MinimalArtifactPattern(AcdModel):
    """One glob pattern for a minimally retained lane artifact."""

    pattern: NonEmptyStr
    required: bool
    reason: NonEmptyStr

    _checked = field_validator("pattern")(_check_relative_glob)


class RegenerablePattern(AcdModel):
    """One glob pattern for an artifact that can be regenerated."""

    pattern: NonEmptyStr
    reason: NonEmptyStr

    _checked = field_validator("pattern")(_check_relative_glob)


class LaneArtifactRetention(AcdModel):
    """Declared retention contract of one deterministic lane."""

    lane_id: RetentionLaneId
    title: NonEmptyStr
    minimal_artifacts: list[MinimalArtifactPattern] = Field(min_length=1)
    regenerable: list[RegenerablePattern] = Field(
        default_factory=list[RegenerablePattern]
    )

    @model_validator(mode="after")
    def _validate_patterns(self) -> LaneArtifactRetention:
        patterns = [item.pattern for item in self.minimal_artifacts]
        if len(patterns) != len(set(patterns)):
            raise ValueError("minimal_artifacts patterns must be unique")
        regenerable: list[str] = [item.pattern for item in self.regenerable]
        if len(regenerable) != len(set(regenerable)):
            raise ValueError("regenerable patterns must be unique")
        return self


class LaneArtifactRetentionDocument(AcdModel):
    """The full declared retention surface of the lane runner."""

    schema_version: SchemaVersion
    declaration_id: NonEmptyStr
    lanes: list[LaneArtifactRetention] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_unique_lane_ids(self) -> LaneArtifactRetentionDocument:
        ids = [lane.lane_id for lane in self.lanes]
        if len(ids) != len(set(ids)):
            raise ValueError("lane retention lane_id values must be unique")
        return self
