"""Contracts for opt-in simplified thermal estimates."""

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

ThermalStatus = Literal["pass", "fail", "unknown"]


class ThermalMaterial(AcdModel):
    k_w_per_mk: float = Field(gt=0)
    source: NonEmptyStr


class ThermalSource(AcdModel):
    refdes: NonEmptyStr
    power_w: float | None = Field(default=None, ge=0)
    package_theta_jc_c_per_w: float | None = Field(default=None, gt=0)
    package_theta_ja_c_per_w: float | None = Field(default=None, gt=0)
    pcb_copper_area_mm2: float | None = Field(default=None, gt=0)
    tj_max_c: float = Field(gt=-273.15)

    @model_validator(mode="after")
    def validate_values(self) -> ThermalSource:
        if self.power_w is not None and not math.isfinite(self.power_w):
            raise ValueError("power_w must be finite")
        return self


class ThermalEnclosure(AcdModel):
    wall_thickness_mm: float = Field(gt=0)
    material: ThermalMaterial
    vent_area_mm2: float | None = Field(default=None, ge=0)
    internal_free_volume_mm3: float | None = Field(default=None, gt=0)


class ThermalRequest(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["thermal_request"] = "thermal_request"
    graph_id: NonEmptyStr
    revision: Revision
    ambient_c: float | None = None
    environment_ref: NonEmptyStr | None = None
    sources: list[ThermalSource] = Field(min_length=1)
    enclosure: ThermalEnclosure

    @model_validator(mode="after")
    def validate_ambient(self) -> ThermalRequest:
        if self.ambient_c is None and self.environment_ref is None:
            raise ValueError("ambient_c or environment_ref is required")
        if self.ambient_c is not None and not math.isfinite(self.ambient_c):
            raise ValueError("ambient_c must be finite")
        refdes = [source.refdes for source in self.sources]
        if len(refdes) != len(set(refdes)):
            raise ValueError("thermal source refdes values must be unique")
        return self


class ThermalSourceResult(AcdModel):
    refdes: NonEmptyStr
    power_w: float | None = Field(default=None, ge=0)
    theta_jc_c_per_w: float | None = Field(default=None, ge=0)
    theta_ja_c_per_w: float | None = Field(default=None, ge=0)
    theta_cb_c_per_w: float | None = Field(default=None, ge=0)
    theta_ba_c_per_w: float | None = Field(default=None, ge=0)
    theta_total_c_per_w: float | None = Field(default=None, ge=0)
    tj_c: float | None = None
    status: ThermalStatus
    findings: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


class ThermalResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["thermal_result"] = "thermal_result"
    graph_id: NonEmptyStr
    revision: Revision
    status: ThermalStatus
    authority: Literal["estimate"] = "estimate"
    ambient_c: float | None = None
    sources: list[ThermalSourceResult] = Field(min_length=1)
    input_hashes: dict[str, Sha256 | Literal["unknown"]]
    findings: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


__all__ = [
    "ThermalEnclosure",
    "ThermalMaterial",
    "ThermalRequest",
    "ThermalResult",
    "ThermalSource",
    "ThermalSourceResult",
    "ThermalStatus",
]
