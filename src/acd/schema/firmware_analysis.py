"""Strict contracts for opt-in firmware analysis observations."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
)
from acd.schema.fw_coverage import CoverageResult

AnalysisStatus = Literal["pass", "fail", "unknown"]


class StaticAnalysisFinding(AcdModel):
    file: NonEmptyStr
    line: int = Field(ge=1)
    col: int = Field(ge=1)
    severity: Literal["warning", "error"]
    check: NonEmptyStr
    message: NonEmptyStr


class StaticAnalysisCounts(AcdModel):
    warning: int = Field(ge=0)
    error: int = Field(ge=0)


class StaticAnalysisResult(AcdModel):
    status: AnalysisStatus
    authority: Literal["estimate"] = "estimate"
    tool_version: NonEmptyStr | Literal["unknown"]
    checks_sha256: Sha256 | Literal["unknown"]
    findings: list[StaticAnalysisFinding] = Field(
        default_factory=list[StaticAnalysisFinding]
    )
    counts: StaticAnalysisCounts
    findings_detail: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


class StackFunctionUsage(AcdModel):
    file: NonEmptyStr
    line: int = Field(ge=1)
    col: int = Field(ge=1)
    function: NonEmptyStr
    bytes: int = Field(ge=0)
    kind: Literal["static", "dynamic", "dynamic,bounded"]


class StackTaskUsage(AcdModel):
    task: NonEmptyStr
    stack_bytes: int = Field(ge=1)
    margin_pct: float = Field(ge=0, le=100)
    worst_static_bytes: int = Field(ge=0)
    budget_bytes: float = Field(ge=0)
    status: AnalysisStatus


class FirmwareSizeUsage(AcdModel):
    flash_bytes: int | None = Field(default=None, ge=0)
    dram_bytes: int | None = Field(default=None, ge=0)
    flash_budget_bytes: int | None = Field(default=None, ge=0)
    dram_budget_bytes: int | None = Field(default=None, ge=0)
    status: AnalysisStatus


class StackUsageResult(AcdModel):
    status: AnalysisStatus
    authority: Literal["estimate"] = "estimate"
    functions: list[StackFunctionUsage] = Field(
        default_factory=list[StackFunctionUsage]
    )
    tasks: list[StackTaskUsage] = Field(default_factory=list[StackTaskUsage])
    size: FirmwareSizeUsage
    findings: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


class PeripheralSimulationResult(AcdModel):
    status: AnalysisStatus
    authority: Literal["observation"] = "observation"
    scenario_sha256: Sha256 | Literal["unknown"]
    samples: list[dict[str, float | int]] = Field(
        default_factory=list[dict[str, float | int]]
    )
    findings: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


class FirmwareAnalysisResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["firmware_analysis_result"] = "firmware_analysis_result"
    graph_id: NonEmptyStr
    revision: Revision
    status: AnalysisStatus
    authority: Literal["estimate"] = "estimate"
    static_analysis: StaticAnalysisResult | None = None
    stack_usage: StackUsageResult | None = None
    peripheral_sim: PeripheralSimulationResult | None = None
    coverage: CoverageResult | None = None
    tool_versions: dict[str, NonEmptyStr | Literal["unknown"]] = Field(
        default_factory=dict[str, NonEmptyStr | Literal["unknown"]]
    )
    input_hashes: dict[str, Sha256 | Literal["unknown"]]
    findings: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


__all__ = [
    "AnalysisStatus",
    "FirmwareAnalysisResult",
    "FirmwareSizeUsage",
    "PeripheralSimulationResult",
    "StackFunctionUsage",
    "StackTaskUsage",
    "StackUsageResult",
    "StaticAnalysisCounts",
    "StaticAnalysisFinding",
    "StaticAnalysisResult",
]
