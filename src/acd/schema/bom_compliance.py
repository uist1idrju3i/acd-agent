"""Contracts for non-authoritative BOM compliance declaration summaries."""

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

ComplianceRegime = Literal[
    "rohs",
    "reach_svhc",
    "halogen_free",
    "conflict_minerals",
    "msl",
    "pfas",
]
ComplianceDeclaredStatus = Literal[
    "declared_compliant",
    "declared_non_compliant",
    "exempt",
    "not_declared",
    "unknown",
]
ComplianceSourceKind = Literal[
    "manufacturer_declaration",
    "distributor_attribute",
    "datasheet",
    "manual_declaration",
]
MslLevel = Literal["1", "2", "2a", "3", "4", "5", "5a", "6"]
ComplianceSummaryStatus = Literal["pass", "fail", "unknown"]


class ComplianceDeclarationSource(AcdModel):
    kind: ComplianceSourceKind
    reference: NonEmptyStr
    observed_at: date
    valid_until: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> ComplianceDeclarationSource:
        if self.valid_until is not None and self.valid_until < self.observed_at:
            raise ValueError("valid_until must not precede observed_at")
        return self


class ComplianceDeclaration(AcdModel):
    regime: ComplianceRegime
    declared_status: ComplianceDeclaredStatus
    exemption_reference: NonEmptyStr | None = None
    source: ComplianceDeclarationSource
    msl_level: MslLevel | None = None

    @model_validator(mode="after")
    def validate_declaration(self) -> ComplianceDeclaration:
        if (
            self.declared_status != "exempt"
            and self.exemption_reference is not None
        ):
            raise ValueError(
                "exemption_reference is only valid for exempt declarations"
            )
        if self.msl_level is not None and self.regime != "msl":
            raise ValueError("msl_level is only valid for msl declarations")
        return self


class ComplianceDeclarationEntry(AcdModel):
    mpn: NonEmptyStr
    declarations: list[ComplianceDeclaration] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_regimes(self) -> ComplianceDeclarationEntry:
        regimes = [declaration.regime for declaration in self.declarations]
        if len(regimes) != len(set(regimes)):
            raise ValueError("declarations must have unique regimes per MPN")
        return self


class ComplianceDeclarationPolicy(AcdModel):
    required_regimes: list[ComplianceRegime] = Field(min_length=1)
    max_declaration_age_days: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_regimes(self) -> ComplianceDeclarationPolicy:
        if len(self.required_regimes) != len(set(self.required_regimes)):
            raise ValueError("required_regimes entries must be unique")
        return self


class ComplianceDeclarationRegistry(AcdModel):
    """Declaration metadata only; this contract never asserts compliance."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["compliance_declaration_registry"] = (
        "compliance_declaration_registry"
    )
    registry_id: NonEmptyStr
    graph_id: NonEmptyStr
    revision: Revision
    as_of: date
    regimes: list[ComplianceRegime] = Field(min_length=1)
    entries: list[ComplianceDeclarationEntry] = Field(min_length=1)
    policy: ComplianceDeclarationPolicy

    @model_validator(mode="after")
    def validate_registry(self) -> ComplianceDeclarationRegistry:
        if len(self.regimes) != len(set(self.regimes)):
            raise ValueError("registry regimes must be unique")
        mpns = [entry.mpn for entry in self.entries]
        if len(mpns) != len(set(mpns)):
            raise ValueError("registry entries must have unique mpn values")
        return self


class ComplianceCounts(AcdModel):
    declared_compliant: int = Field(ge=0)
    declared_non_compliant: int = Field(ge=0)
    exempt: int = Field(ge=0)
    not_declared: int = Field(ge=0)
    unknown: int = Field(ge=0)
    missing_entry: int = Field(ge=0)
    stale: int = Field(ge=0)


class BomComplianceRegimeSummary(AcdModel):
    regime: ComplianceRegime
    in_scope: bool
    counts: ComplianceCounts
    unknown_parts: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    non_compliant_parts: list[NonEmptyStr] = Field(
        default_factory=list[NonEmptyStr]
    )
    msl_level_counts: dict[MslLevel, int] = Field(
        default_factory=dict[MslLevel, int]
    )


class BomCompliancePartSummary(AcdModel):
    refdes: list[NonEmptyStr] = Field(min_length=1)
    mpn: NonEmptyStr
    statuses: dict[
        ComplianceRegime,
        ComplianceDeclaredStatus | Literal["missing_entry", "no_mpn", "stale"],
    ]
    msl_levels: list[MslLevel] = Field(default_factory=list[MslLevel])


class BomComplianceSummary(AcdModel):
    """A declaration summary, not a regulatory compliance verdict."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["bom_compliance_summary"] = "bom_compliance_summary"
    registry_id: NonEmptyStr
    graph_id: NonEmptyStr
    revision: Revision
    status: ComplianceSummaryStatus
    per_regime: list[BomComplianceRegimeSummary] = Field(min_length=1)
    per_part: list[BomCompliancePartSummary] = Field(
        default_factory=list[BomCompliancePartSummary]
    )
    input_hashes: dict[str, Sha256]
    authority: Literal["declaration_summary"] = "declaration_summary"
    compliance_verdict: Literal[None] = None


__all__ = [
    "BomCompliancePartSummary",
    "BomComplianceRegimeSummary",
    "BomComplianceSummary",
    "ComplianceCounts",
    "ComplianceDeclaration",
    "ComplianceDeclarationEntry",
    "ComplianceDeclarationPolicy",
    "ComplianceDeclarationRegistry",
    "ComplianceDeclarationSource",
    "ComplianceDeclaredStatus",
    "ComplianceRegime",
    "ComplianceSourceKind",
    "MslLevel",
]
