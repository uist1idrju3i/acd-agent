"""Strict contracts for opt-in BOM cost estimation."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, StrictInt, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
    Timestamp,
)
from acd.schema.part_lifecycle import AlternateEquivalence

PriceSourceKind = Literal["distributor", "manufacturer", "manual_declaration"]
PriceBasis = Literal["primary", "inference"]
BomCostStatus = Literal["pass", "fail", "unknown"]
BomCostLineStatus = Literal["pass", "unknown", "not_applicable"]


class PartPriceSource(AcdModel):
    kind: PriceSourceKind
    reference: NonEmptyStr
    fetched_at: Timestamp
    valid_until: Timestamp | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> PartPriceSource:
        if self.valid_until is not None and self.valid_until <= self.fetched_at:
            raise ValueError("valid_until must be later than fetched_at")
        return self


class PartPriceBreak(AcdModel):
    min_qty: StrictInt = Field(ge=1)
    unit_price_minor: StrictInt = Field(ge=0)


class PartPriceEntry(AcdModel):
    mpn: NonEmptyStr
    supplier: NonEmptyStr
    source: PartPriceSource
    price_breaks: list[PartPriceBreak] = Field(min_length=1)
    stock_quantity: int | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0)
    basis: PriceBasis

    @model_validator(mode="after")
    def validate_price_breaks(self) -> PartPriceEntry:
        quantities = [price_break.min_qty for price_break in self.price_breaks]
        if quantities != sorted(quantities):
            raise ValueError("price_breaks must be sorted by min_qty")
        if len(quantities) != len(set(quantities)):
            raise ValueError("price_breaks min_qty values must be unique")
        return self


class PartPricePolicy(AcdModel):
    target_total_minor: StrictInt | None = Field(default=None, ge=0)
    max_unit_share_pct: StrictInt | None = Field(default=None, ge=1, le=100)
    require_primary_basis: bool = True


class PartPriceBook(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["part_price_book"] = "part_price_book"
    price_book_id: NonEmptyStr
    graph_id: NonEmptyStr
    revision: Revision
    as_of: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    minor_unit_digits: StrictInt = Field(ge=0, le=9)
    build_quantity: StrictInt = Field(ge=1)
    entries: list[PartPriceEntry] = Field(min_length=1)
    policy: PartPricePolicy

    @model_validator(mode="after")
    def validate_entries(self) -> PartPriceBook:
        mpns = [entry.mpn for entry in self.entries]
        if len(mpns) != len(set(mpns)):
            raise ValueError("part price entries must have unique mpn values")
        return self


class BomCostCheckResult(AcdModel):
    check_id: NonEmptyStr
    status: BomCostStatus
    reason: NonEmptyStr
    subject_ids: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    details: dict[str, object] = Field(default_factory=dict[str, object])


class BomCostLine(AcdModel):
    mpn: NonEmptyStr
    refdes: list[NonEmptyStr] = Field(min_length=1)
    qty_per_board: StrictInt = Field(ge=1)
    extended_qty: StrictInt = Field(ge=1)
    unit_price_minor: StrictInt | None = Field(default=None, ge=0)
    extended_minor: StrictInt | None = Field(default=None, ge=0)
    price_break_used: StrictInt | None = Field(default=None, ge=1)
    share_pct: float | None = Field(default=None, ge=0, le=100)
    status: BomCostLineStatus


class BomCostDriver(AcdModel):
    mpn: NonEmptyStr
    extended_minor: StrictInt = Field(ge=0)
    share_pct: float = Field(ge=0, le=100)


class BomCostSubstitutionCandidate(AcdModel):
    mpn: NonEmptyStr
    alternate_mpn: NonEmptyStr
    equivalence: AlternateEquivalence
    alternate_unit_price_minor: StrictInt | None = Field(default=None, ge=0)
    delta_minor: int | None = None
    note: NonEmptyStr


class BomCostWarning(AcdModel):
    check_id: NonEmptyStr
    mpn: NonEmptyStr
    reason: NonEmptyStr
    share_pct: float = Field(ge=0, le=100)


class BomCostEstimate(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["bom_cost_estimate"] = "bom_cost_estimate"
    price_book_id: NonEmptyStr
    graph_id: NonEmptyStr
    revision: Revision
    status: BomCostStatus
    authority: Literal["estimate"] = "estimate"
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    minor_unit_digits: StrictInt = Field(ge=0, le=9)
    build_quantity: StrictInt = Field(ge=1)
    checks: list[BomCostCheckResult] = Field(min_length=1)
    lines: list[BomCostLine] = Field(default_factory=list[BomCostLine])
    total_minor: StrictInt | None = Field(default=None, ge=0)
    partial_total_minor: StrictInt | None = Field(default=None, ge=0)
    coverage_pct: float = Field(ge=0, le=100)
    over_target: bool | None = None
    cost_drivers: list[BomCostDriver] = Field(
        default_factory=list[BomCostDriver]
    )
    substitution_candidates: list[BomCostSubstitutionCandidate] = Field(
        default_factory=list[BomCostSubstitutionCandidate]
    )
    warnings: list[BomCostWarning] = Field(
        default_factory=list[BomCostWarning]
    )
    input_hashes: dict[str, Sha256]


__all__ = [
    "AlternateEquivalence",
    "BomCostCheckResult",
    "BomCostDriver",
    "BomCostEstimate",
    "BomCostLine",
    "BomCostLineStatus",
    "BomCostStatus",
    "BomCostSubstitutionCandidate",
    "BomCostWarning",
    "PartPriceBook",
    "PartPriceBreak",
    "PartPriceEntry",
    "PartPricePolicy",
    "PartPriceSource",
    "PriceBasis",
    "PriceSourceKind",
]
