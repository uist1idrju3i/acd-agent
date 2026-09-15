"""Contracts for deterministic worst-case analysis."""

from __future__ import annotations

import math
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

WcaQuantityKind = Literal[
    "divider_ratio",
    "series_current",
    "rc_time_constant",
    "i2c_rise_time",
    "ldo_output",
    "power_budget_peak",
]
WcaNominalSource = Literal["spice_result", "declared"]
WcaSourceKind = Literal["datasheet", "manual_declaration"]
WcaComponentKind = Literal[
    "initial_tolerance",
    "initial_center_shift",
    "temperature",
    "aging",
]
WcaResultStatus = Literal["pass", "fail", "unknown"]


class WcaToleranceSource(AcdModel):
    kind: WcaSourceKind
    reference: NonEmptyStr


class WcaAging(AcdModel):
    value: float = Field(ge=0)
    horizon_years: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_value(self) -> WcaAging:
        if not math.isfinite(self.value) or not math.isfinite(self.horizon_years):
            raise ValueError("aging values must be finite")
        return self


class WcaToleranceEntry(AcdModel):
    part_class_or_refdes: NonEmptyStr
    initial_tolerance_pct: float = Field(ge=0)
    temp_coeff_ppm_per_c: float | None = Field(default=None, ge=0)
    aging_pct: WcaAging | None = None
    bias_pct: float | None = None
    source: WcaToleranceSource

    @model_validator(mode="after")
    def validate_values(self) -> WcaToleranceEntry:
        values = (
            self.initial_tolerance_pct,
            self.temp_coeff_ppm_per_c,
            self.bias_pct,
        )
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("tolerance values must be finite")
        return self


class ToleranceTable(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["tolerance_table"] = "tolerance_table"
    table_id: NonEmptyStr
    entries: list[WcaToleranceEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_entries(self) -> ToleranceTable:
        keys = [entry.part_class_or_refdes for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("tolerance table entries must be unique")
        return self


class WcaQuantity(AcdModel):
    quantity_id: NonEmptyStr
    kind: WcaQuantityKind
    inputs: dict[str, object] = Field(default_factory=dict[str, object])
    nominal_source: WcaNominalSource
    nominal_value: float | None = None
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def validate_values(self) -> WcaQuantity:
        values = (self.nominal_value, self.min, self.max)
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("WCA quantity values must be finite")
        if self.nominal_source == "declared" and self.nominal_value is None:
            raise ValueError("declared WCA quantities require nominal_value")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("WCA quantity min must not exceed max")
        return self


class WcaPowerLoad(AcdModel):
    refdes_or_block: NonEmptyStr
    current_a: dict[str, float]
    duty: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_current(self) -> WcaPowerLoad:
        if set(self.current_a) != {"typical", "peak"}:
            raise ValueError("power loads require typical and peak currents")
        if any(
            not math.isfinite(value) or value < 0
            for value in self.current_a.values()
        ):
            raise ValueError("power currents must be finite and non-negative")
        if self.current_a["peak"] < self.current_a["typical"]:
            raise ValueError("peak current must not be below typical current")
        return self


class WcaPowerBudget(AcdModel):
    supply_capacity_a: float = Field(gt=0)
    loads: list[WcaPowerLoad] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_capacity(self) -> WcaPowerBudget:
        if not math.isfinite(self.supply_capacity_a):
            raise ValueError("supply capacity must be finite")
        return self


class WcaRequest(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["wca_request"] = "wca_request"
    graph_id: NonEmptyStr
    revision: Revision
    tolerance_table_ref: NonEmptyStr | ToleranceTable
    environment_ref: NonEmptyStr
    service_life_years: float = Field(ge=0)
    quantities: list[WcaQuantity] = Field(min_length=1)
    power_budget: WcaPowerBudget | None = None

    @model_validator(mode="after")
    def validate_values(self) -> WcaRequest:
        if not math.isfinite(self.service_life_years):
            raise ValueError("service_life_years must be finite")
        ids = [quantity.quantity_id for quantity in self.quantities]
        if len(ids) != len(set(ids)):
            raise ValueError("WCA quantity_id values must be unique")
        return self


class WcaComponent(AcdModel):
    source_refdes: NonEmptyStr
    kind: WcaComponentKind
    value_pct: float
    signed: bool = True


class WcaQuantityResult(AcdModel):
    quantity_id: NonEmptyStr
    nominal: float | None
    bias_components: list[WcaComponent] = Field(
        default_factory=list[WcaComponent]
    )
    random_components: list[WcaComponent] = Field(
        default_factory=list[WcaComponent]
    )
    bias_total_pct: float | None
    random_rss_pct: float | None
    worst_low: float | None
    worst_high: float | None
    status: WcaResultStatus
    findings: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


class WcaResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["wca_result"] = "wca_result"
    graph_id: NonEmptyStr
    revision: Revision
    status: WcaResultStatus
    authority: Literal["estimate"] = "estimate"
    quantities: list[WcaQuantityResult] = Field(min_length=1)
    composition_method: Literal["bias_sum_plus_rss"] = "bias_sum_plus_rss"
    tolerance_table_sha256: Sha256 | Literal["unknown"]
    environment_sha256: Sha256 | Literal["unknown"]
    spice_result_sha256: Sha256 | Literal["unknown"]
    input_hashes: dict[str, Sha256 | Literal["unknown"]]
    findings: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


__all__ = [
    "ToleranceTable",
    "WcaAging",
    "WcaComponent",
    "WcaComponentKind",
    "WcaNominalSource",
    "WcaPowerBudget",
    "WcaPowerLoad",
    "WcaQuantity",
    "WcaQuantityKind",
    "WcaQuantityResult",
    "WcaRequest",
    "WcaResult",
    "WcaResultStatus",
    "WcaSourceKind",
    "WcaToleranceEntry",
    "WcaToleranceSource",
]
