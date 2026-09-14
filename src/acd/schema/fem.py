"""Contracts for opt-in CalculiX finite-element estimates."""

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

FemStatus = Literal["pass", "fail", "unknown"]
FemAnalysisKind = Literal["drop", "static_stress", "thermal"]


class FemMesh(AcdModel):
    source: NonEmptyStr
    element_size_mm: float = Field(gt=0)


class FemMaterial(AcdModel):
    e_pa: float = Field(gt=0)
    nu: float = Field(gt=-1, lt=0.5)
    rho_kg_m3: float = Field(gt=0)
    k_w_per_mk: float | None = Field(default=None, gt=0)
    source: NonEmptyStr


class FemDropLoad(AcdModel):
    height_m: float = Field(gt=0)
    mass_kg: float = Field(gt=0)
    contact_face: NonEmptyStr
    crush_distance_mm: float = Field(gt=0)


class FemStaticLoad(AcdModel):
    force_n: float = Field(gt=0)
    face: NonEmptyStr


class FemThermalLoad(AcdModel):
    heat_w: float = Field(gt=0)
    ambient_c: float


class FemLoads(AcdModel):
    drop: FemDropLoad | None = None
    static: FemStaticLoad | None = None
    thermal: FemThermalLoad | None = None


class FemLimits(AcdModel):
    max_von_mises_pa: float | None = Field(default=None, gt=0)
    max_deflection_mm: float | None = Field(default=None, gt=0)
    max_temp_c: float | None = None

    @model_validator(mode="after")
    def validate_limit(self) -> FemLimits:
        if self.max_temp_c is not None and not math.isfinite(self.max_temp_c):
            raise ValueError("max_temp_c must be finite")
        if (
            self.max_von_mises_pa is None
            and self.max_deflection_mm is None
            and self.max_temp_c is None
        ):
            raise ValueError("at least one FEM limit is required")
        return self


class FemCalculix(AcdModel):
    version_pin: NonEmptyStr = "2.21"


class FemRequest(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["fem_request"] = "fem_request"
    graph_id: NonEmptyStr
    revision: Revision
    analysis: FemAnalysisKind
    mesh: FemMesh
    material: FemMaterial
    loads: FemLoads
    limits: FemLimits
    ccx: FemCalculix = Field(default_factory=FemCalculix)

    @model_validator(mode="after")
    def validate_analysis_load(self) -> FemRequest:
        selected = {
            "drop": self.loads.drop,
            "static_stress": self.loads.static,
            "thermal": self.loads.thermal,
        }
        if selected[self.analysis] is None:
            raise ValueError(f"loads.{self.analysis} is required")
        if sum(value is not None for value in selected.values()) != 1:
            raise ValueError("exactly one analysis load must be declared")
        return self


class FemResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["fem_result"] = "fem_result"
    graph_id: NonEmptyStr
    revision: Revision
    analysis: FemAnalysisKind
    status: FemStatus
    authority: Literal["estimate"] = "estimate"
    max_von_mises_pa: float | None = Field(default=None, ge=0)
    max_deflection_mm: float | None = Field(default=None, ge=0)
    max_temp_c: float | None = None
    input_hashes: dict[str, Sha256 | Literal["unknown"]]
    tool_versions: dict[str, NonEmptyStr | Literal["unknown"]]
    findings: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


__all__ = [
    "FemAnalysisKind",
    "FemCalculix",
    "FemDropLoad",
    "FemLimits",
    "FemLoads",
    "FemMaterial",
    "FemMesh",
    "FemRequest",
    "FemResult",
    "FemStaticLoad",
    "FemStatus",
    "FemThermalLoad",
]
