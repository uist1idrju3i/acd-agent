"""Contracts for deterministic firmware programming and functional measurements."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
    Timestamp,
)
from acd.schema.evidence import MeasurementClass, MeasurementInstrument

FunctionalCheckStatus = Literal["pass", "fail", "unknown"]
FunctionalArtifactType = Literal["elf", "bin"]
FunctionalLogType = Literal["build", "flash", "led", "serial"]


class FunctionalArtifact(AcdModel):
    path: NonEmptyStr
    content_hash: Sha256
    artifact_type: FunctionalArtifactType

    @model_validator(mode="after")
    def validate_artifact_path(self) -> FunctionalArtifact:
        expected_suffix = f".{self.artifact_type}"
        if not self.path.endswith(expected_suffix):
            raise ValueError("artifact path suffix does not match artifact_type")
        return self


class FunctionalLogReference(AcdModel):
    log_type: FunctionalLogType
    path: NonEmptyStr
    content_hash: Sha256


class LedExpectation(AcdModel):
    frequency_hz: float
    tolerance_hz: float = Field(ge=0)
    minimum_cycles: int = Field(ge=2)
    duty_min: float = Field(ge=0, le=1)
    duty_max: float = Field(ge=0, le=1)

    @field_validator("frequency_hz", "tolerance_hz", "duty_min", "duty_max")
    @classmethod
    def reject_non_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("expectation values must be finite")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> LedExpectation:
        if self.duty_min > self.duty_max:
            raise ValueError("duty_min must be less than or equal to duty_max")
        return self


class SerialExpectation(AcdModel):
    temperature_min_deg_c: float
    temperature_max_deg_c: float
    humidity_min_rh: float
    humidity_max_rh: float
    period_s: float = Field(gt=0)
    period_tolerance_s: float = Field(ge=0)
    minimum_samples: int = Field(ge=2)

    @field_validator(
        "temperature_min_deg_c",
        "temperature_max_deg_c",
        "humidity_min_rh",
        "humidity_max_rh",
        "period_s",
        "period_tolerance_s",
    )
    @classmethod
    def reject_non_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("expectation values must be finite")
        return value

    @model_validator(mode="after")
    def validate_ranges(self) -> SerialExpectation:
        if self.temperature_min_deg_c > self.temperature_max_deg_c:
            raise ValueError("temperature range is reversed")
        if self.humidity_min_rh > self.humidity_max_rh:
            raise ValueError("humidity range is reversed")
        return self


class FunctionalExpectations(AcdModel):
    led: LedExpectation
    serial: SerialExpectation


class FunctionalRunRecord(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    run_id: NonEmptyStr
    target_revision: Revision
    measurement_class: MeasurementClass
    esp_idf_version: NonEmptyStr
    toolchain_version: NonEmptyStr
    project_git_commit: NonEmptyStr
    build_artifacts: list[FunctionalArtifact] = Field(min_length=2, max_length=2)
    logs: list[FunctionalLogReference] = Field(min_length=4, max_length=4)
    instrument: MeasurementInstrument
    serial_capture_route: NonEmptyStr
    serial_log_tag: NonEmptyStr = "gd1"
    app_flash_offset: int = Field(ge=0)
    expectations: FunctionalExpectations
    build_at: Timestamp
    flash_at: Timestamp
    acquired_at: Timestamp
    recorded_at: Timestamp

    @field_validator(
        "esp_idf_version",
        "toolchain_version",
        "project_git_commit",
        "serial_capture_route",
    )
    @classmethod
    def reject_unknown_text(cls, value: str) -> str:
        if value == "unknown":
            raise ValueError("functional run declarations must be concrete")
        return value

    @field_validator("build_artifacts")
    @classmethod
    def validate_artifact_types(
        cls, value: list[FunctionalArtifact]
    ) -> list[FunctionalArtifact]:
        if {item.artifact_type for item in value} != {"elf", "bin"}:
            raise ValueError("functional run must declare one elf and one bin artifact")
        return value

    @field_validator("logs")
    @classmethod
    def validate_log_types(
        cls, value: list[FunctionalLogReference]
    ) -> list[FunctionalLogReference]:
        if {item.log_type for item in value} != {"build", "flash", "led", "serial"}:
            raise ValueError("functional run must declare one log of each type")
        return value

    @model_validator(mode="after")
    def validate_run(self) -> FunctionalRunRecord:
        if self.measurement_class == "unknown":
            raise ValueError("measurement_class must be measured or virtual")
        if not (
            self.build_at <= self.flash_at <= self.acquired_at <= self.recorded_at
        ):
            raise ValueError("functional run timestamps must be monotonic")
        if self.instrument.has_unknown():
            raise ValueError("functional run instrument must be concrete")
        paths = [item.path for item in self.build_artifacts] + [
            item.path for item in self.logs
        ]
        if len(paths) != len(set(paths)):
            raise ValueError("functional run paths must be unique")
        if any(
            path.startswith("/") or path == ".." or path.startswith("../")
            for path in paths
        ):
            raise ValueError("functional run paths must be relative")
        return self


class FunctionalCheckReport(AcdModel):
    status: FunctionalCheckStatus
    measured_values: dict[NonEmptyStr, float] = Field(default_factory=dict)
    reason: NonEmptyStr | None = None


class FunctionalRunReport(AcdModel):
    status: FunctionalCheckStatus
    run_id: NonEmptyStr | Literal["unknown"]
    target_revision: Revision | Literal["unknown"]
    input_hash: Sha256 | Literal["unknown"]
    build: FunctionalCheckReport
    flash: FunctionalCheckReport
    led: FunctionalCheckReport
    serial: FunctionalCheckReport
    error: NonEmptyStr | None = None
