"""Evidence record for minimal external-tool execution records."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
    Timestamp,
    VersionOrUnknown,
    canonical_sha256,
)
from acd.schema.tool_envelope import ToolEnvelope

EvidenceStatus = Literal["valid", "stale", "invalidated", "unknown"]
MeasurementClass = Literal["measured", "virtual", "unknown"]


class EvidenceClaim(AcdModel):
    subject_node: NodeId
    property: NonEmptyStr
    value: str | float | int | bool
    verified: bool


class Evidence(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    evidence_id: NonEmptyStr
    target_revision: Revision
    status: EvidenceStatus
    envelope: ToolEnvelope
    claims: list[EvidenceClaim] = Field(default_factory=list[EvidenceClaim])
    created_at: Timestamp

    def supports_pass(self, current_revision: str) -> bool:
        """Only valid, revision-matched, fully-known evidence supports a pass verdict."""
        return (
            self.status == "valid"
            and self.target_revision == current_revision
            and self.envelope.target_revision == current_revision
            and not self.envelope.has_unknown()
        )

    def supports_authoritative_pass(self, current_revision: str) -> bool:
        """Return whether this evidence can support an authoritative pass."""
        return (
            self.supports_pass(current_revision)
            and self.envelope.execution_context == "container"
            and self.envelope.container_image_digest not in {None, "unknown"}
        )

    def is_provisional(self) -> bool:
        """Return whether valid evidence lacks authoritative container provenance."""
        return self.supports_pass(self.target_revision) and not self.supports_authoritative_pass(
            self.target_revision
        )


class MeasurementInstrument(AcdModel):
    instrument_name: NonEmptyStr
    instrument_version: VersionOrUnknown
    fixture_id: NonEmptyStr
    operator: NonEmptyStr

    def has_unknown(self) -> bool:
        """Return True when any instrument or execution-condition field is unknown."""
        return any(
            value == "unknown"
            for value in (
                self.instrument_name,
                self.instrument_version,
                self.fixture_id,
                self.operator,
            )
        )


class MeasuredQuantity(AcdModel):
    name: NonEmptyStr
    unit: NonEmptyStr
    value: float
    expected_min: float
    expected_max: float
    tolerance: float

    @field_validator("value", "expected_min", "expected_max", "tolerance")
    @classmethod
    def reject_non_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("measurement values must be finite")
        return value

    @field_validator("name", "unit")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("measurement name and unit must not be blank")
        return value

    @model_validator(mode="after")
    def validate_expected_range(self) -> MeasuredQuantity:
        if self.expected_min > self.expected_max:
            raise ValueError("expected_min must be less than or equal to expected_max")
        if self.tolerance < 0:
            raise ValueError("tolerance must be non-negative")
        return self

    def is_within_expected_range(self) -> bool:
        """Return whether the value is within the expected range and tolerance."""
        return (
            self.expected_min - self.tolerance
            <= self.value
            <= self.expected_max + self.tolerance
        )

    def has_unknown(self) -> bool:
        """Return True when a quantity identifier or unit is explicitly unknown."""
        return self.name == "unknown" or self.unit == "unknown"


class PhysicalEvidence(Evidence):
    measurement_class: MeasurementClass
    instrument: MeasurementInstrument
    acquired_at: Timestamp
    measurements: list[MeasuredQuantity] = Field(
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_physical_evidence(self) -> PhysicalEvidence:
        if self.target_revision != self.envelope.target_revision:
            raise ValueError("target_revision must match envelope.target_revision")
        if not self.envelope.started_at <= self.acquired_at <= self.created_at:
            raise ValueError("acquired_at must be between envelope.started_at and created_at")
        return self

    def supports_pass(self, current_revision: str) -> bool:
        """Return whether complete physical evidence supports a provisional pass input."""
        return (
            super().supports_pass(current_revision)
            and self.measurement_class != "unknown"
            and not self.instrument.has_unknown()
            and all(
                not measurement.has_unknown() and measurement.is_within_expected_range()
                for measurement in self.measurements
            )
        )

    def supports_authoritative_pass(self, current_revision: str) -> bool:
        """Physical evidence never creates an authoritative deterministic gate pass."""
        return False

    def supports_measured_claim(self, current_revision: str) -> bool:
        """Return whether measured-class evidence supports a measured claim."""
        return self.measurement_class == "measured" and self.supports_pass(current_revision)

    def canonical_hash(self) -> Sha256:
        """Return the canonical hash of this physical evidence record."""
        return canonical_sha256(self)
