"""Contracts for non-authoritative electrical visual cross-check observations."""

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
    Timestamp,
    canonical_json_sha256,
)
from acd.schema.visual_projection import VisualProjectionInput

CrosscheckStatus = Literal["match", "mismatch", "unknown"]
CrosscheckAspect = Literal[
    "readability",
    "design_intent",
    "annotations",
    "units",
    "axis",
    "origin",
    "occlusion",
    "signal_power",
    "section_plane",
    "interference_visibility",
]
ReviewVerification = Literal["deterministic", "observation_required"]


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


class VisualCrosscheckItem(AcdModel):
    check_id: NonEmptyStr
    description: NonEmptyStr
    status: CrosscheckStatus
    expected: NonEmptyStr
    actual: NonEmptyStr
    machine_field: NonEmptyStr


class VisualProjectionCrosscheck(AcdModel):
    projection_id: NodeId
    source_revision: Revision
    image_hash: Sha256
    items: list[VisualCrosscheckItem] = Field(min_length=1)
    status: CrosscheckStatus

    @model_validator(mode="after")
    def validate_status(self) -> VisualProjectionCrosscheck:
        statuses = {item.status for item in self.items}
        if self.status == "match" and statuses != {"match"}:
            raise ValueError("matching crosscheck requires every item to match")
        if self.status == "mismatch" and "mismatch" not in statuses:
            raise ValueError("mismatching crosscheck requires a mismatch item")
        if self.status == "unknown" and "unknown" not in statuses:
            raise ValueError("unknown crosscheck requires an unknown item")
        return self


class VisualReviewObservationReference(AcdModel):
    artifact_kind: Literal["visual_vision_observation"] = "visual_vision_observation"
    pass_evidence: Literal[False] = False
    tool_name: Literal["inspect_image_with_vision"] = "inspect_image_with_vision"
    profile_name: NonEmptyStr
    model: NonEmptyStr
    projection_id: NodeId
    image_hash: Sha256


class VisualReviewChecklistItem(AcdModel):
    item_id: NonEmptyStr
    aspect: CrosscheckAspect
    verification: ReviewVerification
    status: CrosscheckStatus
    basis: NonEmptyStr
    observation: VisualReviewObservationReference | None = None

    @model_validator(mode="after")
    def validate_observation_boundary(self) -> VisualReviewChecklistItem:
        if self.verification == "observation_required" and self.status != "unknown":
            raise ValueError("observation-required review items must remain unknown")
        if self.observation is not None and self.verification != "observation_required":
            raise ValueError("vision observations require observation-required review items")
        if self.observation is not None and self.observation.projection_id == "":
            raise ValueError("vision observation projection id is required")
        if self.observation is not None and self.observation.image_hash == "unknown":
            raise ValueError("vision observation image hash must be concrete")
        return self


class VisualCrosscheckReport(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["visual_crosscheck_report"] = "visual_crosscheck_report"
    pass_evidence: Literal[False] = False
    source_revision: Revision
    visual_projection_set_identity_hash: Sha256
    machine_input_files: list[VisualProjectionInput] = Field(min_length=1)
    set_items: list[VisualCrosscheckItem] = Field(min_length=1)
    crosschecks: list[VisualProjectionCrosscheck] = Field(min_length=1)
    review_items: list[VisualReviewChecklistItem] = Field(min_length=1)
    status: CrosscheckStatus
    canonical_hash: HashOrUnknown = "unknown"
    identity_hash: HashOrUnknown = "unknown"
    generated_at: Timestamp

    @field_validator("machine_input_files")
    @classmethod
    def validate_machine_input_paths(
        cls, value: list[VisualProjectionInput]
    ) -> list[VisualProjectionInput]:
        paths = [item.path for item in value]
        if len(paths) != len(set(paths)):
            raise ValueError("machine input paths must be unique")
        for path in paths:
            _relative_path(path, "machine input path")
        return value

    @model_validator(mode="after")
    def validate_report(self) -> VisualCrosscheckReport:
        identifiers = [record.projection_id for record in self.crosschecks]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("crosscheck projection identifiers must be unique")
        if any(record.source_revision != self.source_revision for record in self.crosschecks):
            raise ValueError("crosscheck revisions must match the report revision")
        statuses = {
            item.status
            for item in self.set_items
        } | {
            item.status
            for record in self.crosschecks
            for item in record.items
        }
        if self.status == "match" and statuses != {"match"}:
            raise ValueError("matching report requires every projection to match")
        if self.status == "mismatch" and "mismatch" not in statuses:
            raise ValueError("mismatching report requires a mismatching projection")
        if self.status == "unknown" and "unknown" not in statuses:
            raise ValueError("unknown report requires an unknown projection")
        if self.identity_hash != "unknown" and self.identity_hash != self.computed_identity_hash():
            raise ValueError("visual crosscheck identity_hash mismatch")
        if (
            self.canonical_hash != "unknown"
            and self.canonical_hash != self.computed_canonical_hash()
        ):
            raise ValueError("visual crosscheck canonical_hash mismatch")
        return self

    def computed_identity_hash(self) -> Sha256:
        return canonical_json_sha256(
            self.model_dump(
                mode="json",
                exclude={"generated_at", "identity_hash", "canonical_hash"},
            )
        )

    def computed_canonical_hash(self) -> Sha256:
        return canonical_json_sha256(self.model_dump(mode="json", exclude={"canonical_hash"}))

    def with_computed_hashes(self) -> VisualCrosscheckReport:
        payload = self.model_dump(mode="json")
        payload["identity_hash"] = self.computed_identity_hash()
        payload["canonical_hash"] = "unknown"
        identity_validated = type(self).model_validate(payload)
        return identity_validated.model_copy(
            update={"canonical_hash": identity_validated.computed_canonical_hash()}
        )
