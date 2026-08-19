"""Contracts for reproducible visual projection observations."""

from __future__ import annotations

import math
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    HashOrUnknown,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
    Timestamp,
    VersionOrUnknown,
    canonical_json_sha256,
)

VisualProjectionType = Literal["schematic_view", "layered_layout_view"]
VisualProjectionDomain = Literal["electrical", "mechanical", "firmware", "system"]
VisualRegenerationStatus = Literal["reproduced", "not_reproduced", "unknown"]
VisualGateStatus = Literal["pass", "fail"]

_VERSION_UNKNOWN = "unknown"
_DIMENSION_PATTERN = re.compile(
    r"^(?P<value>(?:0|[1-9][0-9]*)(?:\.[0-9]+)?)"
    r"(?P<unit>mm|cm|in|pt|pc)$"
)


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


class VisualProjectionInput(AcdModel):
    path: NonEmptyStr
    content_hash: Sha256

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _relative_path(value, "input path")


class VisualRendererProvenance(AcdModel):
    renderer_type: Literal["kicad-cli"] = "kicad-cli"
    tool_name: Literal["kicad-cli"] = "kicad-cli"
    tool_version: VersionOrUnknown

    @field_validator("tool_version")
    @classmethod
    def reject_unknown_version(cls, value: str) -> str:
        if value == _VERSION_UNKNOWN:
            raise ValueError("renderer tool version must be concrete")
        return value


class VisualResolution(AcdModel):
    width: NonEmptyStr
    height: NonEmptyStr
    view_box: tuple[float, float, float, float]

    @field_validator("width", "height")
    @classmethod
    def validate_dimension(cls, value: str) -> str:
        match = _DIMENSION_PATTERN.fullmatch(value)
        if match is None or not math.isfinite(float(match.group("value"))):
            raise ValueError("resolution dimensions must have a known unit")
        return value

    @field_validator("view_box")
    @classmethod
    def validate_view_box(
        cls, value: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        if not all(math.isfinite(item) for item in value):
            raise ValueError("view_box values must be finite")
        return value


class VisualRegenerationCheck(AcdModel):
    status: VisualRegenerationStatus
    first_image_hash: HashOrUnknown
    second_image_hash: HashOrUnknown
    reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_comparison(self) -> VisualRegenerationCheck:
        if self.status == "reproduced" and (
            self.first_image_hash == "unknown"
            or self.second_image_hash == "unknown"
            or self.first_image_hash != self.second_image_hash
        ):
            raise ValueError("reproduced regeneration requires matching concrete hashes")
        if self.status == "not_reproduced" and self.first_image_hash == self.second_image_hash:
            raise ValueError("not_reproduced regeneration requires different hashes")
        return self


class ElectricalVisualProjectionPredicate(AcdModel):
    name: NonEmptyStr
    status: VisualGateStatus
    detail: NonEmptyStr


class ElectricalVisualProjectionGates(AcdModel):
    """Deterministic electrical gates required before visual projection."""

    erc_errors: StrictInt = Field(ge=0)
    erc_unconnected: StrictInt = Field(ge=0)
    routing_converged: StrictBool
    drc_errors: StrictInt = Field(ge=0)
    drc_unconnected: StrictInt = Field(ge=0)
    independent_reload: StrictBool
    silkscreen_status: Literal["measured_pass", "fail"]
    dfm_status: Literal["pass", "fail"]
    design_predicates: tuple[ElectricalVisualProjectionPredicate, ...] = Field(min_length=1)


class VisualProjectionRecord(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["visual_projection"] = "visual_projection"
    pass_evidence: Literal[False] = False
    projection_id: NodeId
    projection_type: VisualProjectionType
    domain: VisualProjectionDomain
    source_revision: Revision
    input_files: list[VisualProjectionInput] = Field(min_length=1)
    renderer: VisualRendererProvenance
    media_type: Literal["image/svg+xml"] = "image/svg+xml"
    resolution: VisualResolution
    normalization_rule_id: NonEmptyStr
    normalization_rule_description: NonEmptyStr
    image_hash: Sha256
    generated_at: Timestamp
    regeneration_check: VisualRegenerationCheck
    image_path: NonEmptyStr

    @field_validator("image_path")
    @classmethod
    def validate_image_path(cls, value: str) -> str:
        return _relative_path(value, "image path")

    @model_validator(mode="after")
    def validate_inputs(self) -> VisualProjectionRecord:
        paths = [item.path for item in self.input_files]
        if len(paths) != len(set(paths)):
            raise ValueError("visual projection input paths must be unique")
        if self.normalization_rule_id == "unknown":
            raise ValueError("normalization rule must be concrete")
        return self


class VisualProjectionSet(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["visual_projection_set"] = "visual_projection_set"
    pass_evidence: Literal[False] = False
    source_revision: Revision
    projections: list[VisualProjectionRecord] = Field(min_length=1)
    identity_hash: HashOrUnknown = "unknown"
    canonical_hash: HashOrUnknown = "unknown"

    @model_validator(mode="after")
    def validate_set(self) -> VisualProjectionSet:
        identifiers = [projection.projection_id for projection in self.projections]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("visual projection identifiers must be unique")
        if identifiers != sorted(identifiers):
            raise ValueError("visual projections must be sorted by projection_id")
        if any(
            projection.source_revision != self.source_revision for projection in self.projections
        ):
            raise ValueError("visual projection revisions must match")
        if self.identity_hash != "unknown":
            expected_identity = self.computed_identity_hash()
            if self.identity_hash != expected_identity:
                raise ValueError("visual projection set identity_hash mismatch")
        if self.canonical_hash != "unknown":
            expected = canonical_json_sha256(
                self.model_dump(mode="json", exclude={"canonical_hash"})
            )
            if self.canonical_hash != expected:
                raise ValueError("visual projection set canonical_hash mismatch")
        return self

    def computed_identity_hash(self) -> Sha256:
        """Hash projection content while excluding generated timestamps."""
        projections = [
            projection.model_dump(
                mode="json",
                exclude={"generated_at"},
            )
            for projection in self.projections
        ]
        return canonical_json_sha256(
            {
                "source_revision": self.source_revision,
                "projections": projections,
            }
        )

    def computed_canonical_hash(self) -> Sha256:
        return canonical_json_sha256(self.model_dump(mode="json", exclude={"canonical_hash"}))

    def with_computed_hashes(self) -> VisualProjectionSet:
        identity_hash = self.computed_identity_hash()
        payload = self.model_dump(mode="json")
        payload["identity_hash"] = identity_hash
        payload["canonical_hash"] = "unknown"
        identity_validated = type(self).model_validate(payload)
        return identity_validated.model_copy(
            update={"canonical_hash": identity_validated.computed_canonical_hash()}
        )
