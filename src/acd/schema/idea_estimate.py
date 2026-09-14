"""Rough-estimate contracts for idea records (ADR-0049, roadmap 21.4).

Estimates are L3 observations: labelled as estimates, compared only against
confirmed numeric constraints, and never promoted to Evidence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Timestamp,
)


class EstimateRange(AcdModel):
    """A non-negative inclusive range."""

    min: FiniteFloat
    max: FiniteFloat

    @model_validator(mode="after")
    def _ordered(self) -> EstimateRange:
        if self.min > self.max:
            raise ValueError("min must be less than or equal to max")
        if self.min < 0:
            raise ValueError("range values must be non-negative")
        return self


class IdeaEstimateCatalogEntry(AcdModel):
    """One catalog entry describing a typical part for a function class."""

    function_class: NonEmptyStr
    typical_part: NonEmptyStr
    unit_cost_jpy: EstimateRange
    power_mw: EstimateRange
    footprint_mm2: FiniteFloat
    source: NonEmptyStr
    checked_at: Timestamp


class IdeaEstimateCatalog(AcdModel):
    """The estimate catalog; one entry per function class."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    catalog_id: NonEmptyStr
    entries: list[IdeaEstimateCatalogEntry] = Field(
        default_factory=list[IdeaEstimateCatalogEntry]
    )

    @model_validator(mode="after")
    def _unique_classes(self) -> IdeaEstimateCatalog:
        classes = [entry.function_class for entry in self.entries]
        if len(set(classes)) != len(classes):
            raise ValueError("entries function_class entries must be unique")
        return self


class EstimateLine(AcdModel):
    """One estimated function line."""

    function_id: NodeId
    function_class: NonEmptyStr
    typical_part: NonEmptyStr
    unit_cost_jpy: EstimateRange
    power_mw: EstimateRange
    footprint_mm2: FiniteFloat
    source: NonEmptyStr


class UnknownFunction(AcdModel):
    """A function that could not be estimated."""

    function_id: NodeId
    reason: NonEmptyStr


class EstimateTotals(AcdModel):
    """Totals across the known lines only."""

    cost_jpy: EstimateRange
    power_mw: EstimateRange
    footprint_mm2: FiniteFloat
    covers_all_functions: bool


class EstimateFinding(AcdModel):
    """A stop-side comparison finding; never an approval."""

    constraint: NonEmptyStr
    status: Literal["stop", "risk", "not_comparable", "within"]
    detail: NonEmptyStr


class IdeaRoughEstimate(AcdModel):
    """L3 rough-estimate observation for an idea record."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["idea_rough_estimate"] = "idea_rough_estimate"
    record_class: Literal["L3"] = "L3"
    pass_evidence: Literal[False] = False
    estimate: Literal[True] = True
    idea_id: NodeId
    revision: Revision
    catalog_id: NonEmptyStr
    lines: list[EstimateLine] = Field(default_factory=list[EstimateLine])
    unknown_functions: list[UnknownFunction] = Field(
        default_factory=list[UnknownFunction]
    )
    totals: EstimateTotals
    findings: list[EstimateFinding] = Field(default_factory=list[EstimateFinding])


__all__ = [
    "EstimateFinding",
    "EstimateLine",
    "EstimateRange",
    "EstimateTotals",
    "IdeaEstimateCatalog",
    "IdeaEstimateCatalogEntry",
    "IdeaRoughEstimate",
    "UnknownFunction",
]
