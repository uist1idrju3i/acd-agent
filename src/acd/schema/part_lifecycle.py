"""Contracts for opt-in part lifecycle and second-source governance."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
)

PartLifecycleStatus = Literal[
    "active",
    "nrnd",
    "last_time_buy",
    "eol",
    "obsolete",
    "unknown",
]
PartLifecycleSourceKind = Literal[
    "manufacturer_pcn",
    "distributor",
    "datasheet",
    "manual_declaration",
]
AlternateEquivalence = Literal[
    "drop_in",
    "footprint_compatible_value_check",
    "requires_redesign",
]
AlternateVerificationKind = Literal["datasheet_comparison", "manual_declaration"]
SecondSourcePolicy = Literal["all", "single_source_risk_classes", "none"]
PartLifecycleStatusValue = Literal["eol", "obsolete"]
PartLifecycleWarningStatus = Literal["nrnd", "last_time_buy"]
PartLifecycleResultStatus = Literal["pass", "fail", "unknown"]


class PartLifecycleStatusSource(AcdModel):
    kind: PartLifecycleSourceKind
    reference: NonEmptyStr
    observed_at: date
    valid_until: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> PartLifecycleStatusSource:
        if self.valid_until is not None and self.valid_until < self.observed_at:
            raise ValueError("valid_until must not precede observed_at")
        return self


class PartLifecycleAlternateVerification(AcdModel):
    kind: AlternateVerificationKind
    reference: NonEmptyStr


class PartLifecycleAlternate(AcdModel):
    mpn: NonEmptyStr
    manufacturer: NonEmptyStr | None = None
    equivalence: AlternateEquivalence
    footprint: NonEmptyStr
    verified_by: PartLifecycleAlternateVerification
    notes: NonEmptyStr | None = None


class PartLifecycleEntry(AcdModel):
    mpn: NonEmptyStr
    manufacturer: NonEmptyStr | None = None
    lifecycle_status: PartLifecycleStatus
    status_source: PartLifecycleStatusSource
    last_time_buy_date: date | None = None
    alternates: list[PartLifecycleAlternate] = Field(
        default_factory=list[PartLifecycleAlternate]
    )


class PartLifecyclePolicy(AcdModel):
    require_second_source_for: SecondSourcePolicy = "none"
    risk_classes: list[NonEmptyStr] | None = None
    max_status_age_days: int = Field(ge=0)
    reject_statuses: list[PartLifecycleStatusValue] = Field(
        default_factory=lambda: ["eol", "obsolete"]
    )
    warn_statuses: list[PartLifecycleWarningStatus] = Field(
        default_factory=lambda: ["nrnd", "last_time_buy"]
    )

    @model_validator(mode="after")
    def validate_policy(self) -> PartLifecyclePolicy:
        if self.require_second_source_for == "single_source_risk_classes" and not self.risk_classes:
            raise ValueError(
                "risk_classes are required for single_source_risk_classes policy"
            )
        if len(set(self.reject_statuses)) != len(self.reject_statuses):
            raise ValueError("reject_statuses entries must be unique")
        if len(set(self.warn_statuses)) != len(self.warn_statuses):
            raise ValueError("warn_statuses entries must be unique")
        if set(self.reject_statuses) & set(self.warn_statuses):
            raise ValueError("reject_statuses and warn_statuses must be disjoint")
        return self


class PartLifecycleRegistry(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["part_lifecycle_registry"] = "part_lifecycle_registry"
    registry_id: NonEmptyStr
    graph_id: NonEmptyStr
    revision: Revision
    as_of: date
    entries: list[PartLifecycleEntry] = Field(min_length=1)
    policy: PartLifecyclePolicy

    @model_validator(mode="after")
    def validate_entries(self) -> PartLifecycleRegistry:
        mpns = [entry.mpn for entry in self.entries]
        if len(mpns) != len(set(mpns)):
            raise ValueError("part lifecycle entries must have unique mpn values")
        return self


class PartLifecycleCheckResult(AcdModel):
    check_id: NonEmptyStr
    status: PartLifecycleResultStatus
    reason: NonEmptyStr
    subject_ids: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    details: dict[str, object] = Field(default_factory=dict[str, object])


class PartLifecyclePartResult(AcdModel):
    refdes: list[NonEmptyStr] = Field(min_length=1)
    mpn: NonEmptyStr
    lifecycle_status: PartLifecycleStatus | Literal["no_mpn"]
    alternates_count: int = Field(ge=0)
    status: PartLifecycleResultStatus


class PartLifecycleResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["part_lifecycle_result"] = "part_lifecycle_result"
    registry_id: NonEmptyStr
    graph_id: NonEmptyStr
    revision: Revision
    status: PartLifecycleResultStatus
    checks: list[PartLifecycleCheckResult] = Field(min_length=1)
    per_part: list[PartLifecyclePartResult] = Field(default_factory=list[PartLifecyclePartResult])
    input_hashes: dict[str, Sha256]


__all__ = [
    "AlternateEquivalence",
    "PartLifecycleAlternate",
    "PartLifecycleAlternateVerification",
    "PartLifecycleCheckResult",
    "PartLifecycleEntry",
    "PartLifecyclePartResult",
    "PartLifecyclePolicy",
    "PartLifecycleRegistry",
    "PartLifecycleResult",
    "PartLifecycleResultStatus",
    "PartLifecycleSourceKind",
    "PartLifecycleStatus",
    "PartLifecycleStatusSource",
]
