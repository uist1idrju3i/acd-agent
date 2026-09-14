"""Strict contracts for opt-in SPICE power-network estimates."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictFloat, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
)

SpiceAnalysisKind = Literal["op", "tran"]
SpiceLimitQuantity = Literal["node_voltage", "branch_current", "rise_time"]
SpiceStatus = Literal["pass", "fail", "unknown"]


class SpiceLdoModel(AcdModel):
    refdes: NonEmptyStr
    vout_v: StrictFloat = Field(gt=0)
    dropout_v: StrictFloat = Field(ge=0)
    iq_a: StrictFloat = Field(ge=0)
    model: Literal["behavioral_ldo"] = "behavioral_ldo"


class SpiceLedModel(AcdModel):
    refdes: NonEmptyStr
    vf_v: StrictFloat = Field(gt=0)
    series_resistor_refdes: NonEmptyStr


class SpiceI2cPullup(AcdModel):
    net: NonEmptyStr
    resistor_refdes: NonEmptyStr
    bus_capacitance_pf: StrictFloat = Field(gt=0)
    vdd_net: NonEmptyStr


class SpiceDecoupling(AcdModel):
    refdes: NonEmptyStr


class SpiceModels(AcdModel):
    ldo: SpiceLdoModel
    led: list[SpiceLedModel] = Field(default_factory=list[SpiceLedModel])
    i2c_pullups: list[SpiceI2cPullup] = Field(
        default_factory=list[SpiceI2cPullup]
    )
    decoupling: list[SpiceDecoupling] = Field(
        default_factory=list[SpiceDecoupling]
    )


class SpiceSources(AcdModel):
    vbus_v: StrictFloat = Field(gt=0)
    vbus_ramp_ms: StrictFloat = Field(ge=0)


class SpiceAnalysis(AcdModel):
    kind: SpiceAnalysisKind
    tstep: StrictFloat | None = Field(default=None, gt=0)
    tstop: StrictFloat | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_transient_parameters(self) -> SpiceAnalysis:
        if self.kind == "tran" and (self.tstep is None or self.tstop is None):
            raise ValueError("tran analysis requires tstep and tstop")
        if (
            self.kind == "tran"
            and self.tstop is not None
            and self.tstep is not None
            and self.tstep >= self.tstop
        ):
            raise ValueError("tran tstep must be less than tstop")
        return self


class SpiceLimit(AcdModel):
    quantity: SpiceLimitQuantity
    target: NonEmptyStr
    min: StrictFloat | None = None
    max: StrictFloat | None = None
    tolerance_pct: StrictFloat | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_range(self) -> SpiceLimit:
        if self.min is None and self.max is None:
            raise ValueError("SPICE limit requires min or max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("SPICE limit min must not exceed max")
        return self


class SpiceNgspice(AcdModel):
    version_pin: NonEmptyStr


class SpiceAnalysisRequest(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["spice_analysis_request"] = "spice_analysis_request"
    graph_id: NonEmptyStr
    revision: Revision
    models: SpiceModels
    sources: SpiceSources
    analyses: list[SpiceAnalysis] = Field(min_length=1)
    limits: list[SpiceLimit] = Field(default_factory=list[SpiceLimit])
    ngspice: SpiceNgspice

    @model_validator(mode="after")
    def validate_analyses(self) -> SpiceAnalysisRequest:
        kinds = [analysis.kind for analysis in self.analyses]
        if "op" not in kinds and "tran" not in kinds:
            raise ValueError("analyses must contain op or tran")
        return self


class SpiceCheck(AcdModel):
    quantity: SpiceLimitQuantity
    target: NonEmptyStr
    measured: float | None = None
    status: SpiceStatus
    reason: NonEmptyStr


class SpiceResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["spice_result"] = "spice_result"
    graph_id: NonEmptyStr
    revision: Revision
    status: SpiceStatus
    authority: Literal["estimate"] = "estimate"
    checks: list[SpiceCheck] = Field(min_length=1)
    findings: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    netlist_sha256: Sha256
    raw_output_sha256: Sha256 | Literal["unknown"]
    ngspice_version: NonEmptyStr | Literal["unknown"]
    input_hashes: dict[str, Sha256]


__all__ = [
    "SpiceAnalysis",
    "SpiceAnalysisKind",
    "SpiceAnalysisRequest",
    "SpiceCheck",
    "SpiceDecoupling",
    "SpiceI2cPullup",
    "SpiceLdoModel",
    "SpiceLedModel",
    "SpiceLimit",
    "SpiceLimitQuantity",
    "SpiceModels",
    "SpiceNgspice",
    "SpiceResult",
    "SpiceSources",
    "SpiceStatus",
]
