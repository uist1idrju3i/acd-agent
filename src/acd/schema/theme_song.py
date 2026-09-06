"""Contracts for the theme-song projection (an L3 audio artifact of a design)."""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    HashOrUnknown,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
    canonical_json_sha256,
)

ThemeSongMediaType = Literal["audio/midi", "text/javascript"]
ThemeSongRegenerationStatus = Literal["reproduced", "not_reproduced", "unknown"]


def _relative_path(value: str, field_name: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or any(part == ".." for part in path.parts)
        or normalized in {".", ".."}
    ):
        raise ValueError(f"{field_name} must be a relative path")
    return normalized


class ThemeSongArtifactInput(AcdModel):
    path: NonEmptyStr
    content_hash: Sha256

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _relative_path(value, "input path")


class ThemeSongArtifact(AcdModel):
    path: NonEmptyStr
    media_type: ThemeSongMediaType
    content_hash: Sha256

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _relative_path(value, "artifact path")


class ThemeSongRegenerationCheck(AcdModel):
    status: ThemeSongRegenerationStatus
    first_hash: HashOrUnknown
    second_hash: HashOrUnknown
    reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_comparison(self) -> ThemeSongRegenerationCheck:
        if self.status == "reproduced" and (
            self.first_hash == "unknown"
            or self.second_hash == "unknown"
            or self.first_hash != self.second_hash
        ):
            raise ValueError("reproduced regeneration requires matching concrete hashes")
        if self.status == "not_reproduced" and self.first_hash == self.second_hash:
            raise ValueError("not_reproduced regeneration requires different hashes")
        return self


class ThemeSongProjection(AcdModel):
    """Recorded theme song of one design revision. Never pass Evidence."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["theme_song_projection"] = "theme_song_projection"
    record_class: Literal["L3"] = "L3"
    pass_evidence: Literal[False] = False
    projection_id: NodeId
    graph_id: NonEmptyStr
    source_revision: Revision
    graph_input: ThemeSongArtifactInput
    skill_name: Literal["acd-theme-song"] = "acd-theme-song"
    skill_script_path: NonEmptyStr
    skill_script_sha256: Sha256
    composer_id: NonEmptyStr
    seed: Sha256
    bpm: int = Field(ge=1)
    bars: int = Field(ge=1)
    key: NonEmptyStr
    artifacts: list[ThemeSongArtifact] = Field(min_length=2)
    regeneration_check: ThemeSongRegenerationCheck
    canonical_hash: HashOrUnknown = "unknown"

    @field_validator("skill_script_path")
    @classmethod
    def validate_script_path(cls, value: str) -> str:
        return _relative_path(value, "skill script path")

    @model_validator(mode="after")
    def validate_projection(self) -> ThemeSongProjection:
        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("theme song artifact paths must be unique")
        if paths != sorted(paths):
            raise ValueError("theme song artifacts must be sorted by path")
        media_types = {artifact.media_type for artifact in self.artifacts}
        if media_types != {"audio/midi", "text/javascript"}:
            raise ValueError("theme song projection requires one MIDI and one Strudel artifact")
        if self.regeneration_check.status != "reproduced":
            raise ValueError("theme song projection requires a reproduced regeneration check")
        if (
            self.canonical_hash != "unknown"
            and self.canonical_hash != self.computed_canonical_hash()
        ):
            raise ValueError("theme song projection canonical_hash mismatch")
        return self

    def computed_canonical_hash(self) -> Sha256:
        return canonical_json_sha256(self.model_dump(mode="json", exclude={"canonical_hash"}))

    def with_computed_hash(self) -> ThemeSongProjection:
        return self.model_copy(update={"canonical_hash": self.computed_canonical_hash()})
