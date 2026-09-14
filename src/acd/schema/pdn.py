"""Contracts for opt-in power-distribution-network estimates."""

from __future__ import annotations

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

PdnStatus = Literal["pass", "fail", "unknown"]
PdnSourceKind = Literal["kicad_pcb", "gerber"]


class PdnPathRequest(AcdModel):
    path_id: NonEmptyStr
    net: NonEmptyStr
    source_refdes: NonEmptyStr
    sink_refdes: NonEmptyStr
    current_a: float = Field(gt=0)
    max_ir_drop_mv: float = Field(gt=0)
    max_current_density_a_per_mm2: float = Field(gt=0)


class PdnCopper(AcdModel):
    thickness_um: float | None = Field(default=None, gt=0)
    resistivity_ohm_mm: float = Field(default=1.72e-5, gt=0)
    temperature_c: float = 20.0
    temp_coeff_per_c: float = Field(default=0.00393, ge=0)


class PdnSource(AcdModel):
    kind: PdnSourceKind
    path: NonEmptyStr


class PdnAnalysisRequest(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["pdn_analysis_request"] = "pdn_analysis_request"
    graph_id: NonEmptyStr
    revision: Revision
    paths: list[PdnPathRequest] = Field(min_length=1)
    copper: PdnCopper = Field(default_factory=PdnCopper)
    source: PdnSource

    @model_validator(mode="after")
    def validate_paths(self) -> PdnAnalysisRequest:
        path_ids = [path.path_id for path in self.paths]
        if len(path_ids) != len(set(path_ids)):
            raise ValueError("paths must have unique path_id values")
        return self


class PdnSegmentResult(AcdModel):
    layer: NonEmptyStr
    length_mm: float = Field(gt=0)
    width_mm: float = Field(gt=0)
    cross_section_mm2: float = Field(gt=0)
    resistance_mohm: float = Field(ge=0)
    current_density: float = Field(gt=0)


class PdnViaResult(AcdModel):
    drill_mm: float = Field(gt=0)
    plating_um: float = Field(gt=0)
    resistance_mohm: float = Field(ge=0)


class PdnPathResult(AcdModel):
    path_id: NonEmptyStr
    net: NonEmptyStr
    segments: list[PdnSegmentResult] = Field(default_factory=list[PdnSegmentResult])
    vias: list[PdnViaResult] = Field(default_factory=list[PdnViaResult])
    total_resistance_mohm: float | None = Field(default=None, ge=0)
    ir_drop_mv: float | None = Field(default=None, ge=0)
    worst_current_density: float | None = Field(default=None, gt=0)
    status: PdnStatus
    findings: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    zone_on_path: bool = False


class PdnResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["pdn_result"] = "pdn_result"
    graph_id: NonEmptyStr
    revision: Revision
    status: PdnStatus
    authority: Literal["estimate"] = "estimate"
    paths: list[PdnPathResult] = Field(min_length=1)
    input_hashes: dict[str, Sha256]
    tool_versions: dict[str, NonEmptyStr]

    @model_validator(mode="after")
    def validate_paths(self) -> PdnResult:
        path_ids = [path.path_id for path in self.paths]
        if path_ids != sorted(path_ids):
            raise ValueError("paths must be ordered by path_id")
        return self


__all__ = [
    "PdnAnalysisRequest",
    "PdnCopper",
    "PdnPathRequest",
    "PdnPathResult",
    "PdnResult",
    "PdnSegmentResult",
    "PdnSource",
    "PdnStatus",
]
