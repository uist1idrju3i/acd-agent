"""Strict contracts for opt-in firmware coverage observations."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from acd.schema.common import AcdModel, NonEmptyStr

CoverageStatus = Literal["pass", "fail", "unknown"]


class CoverageFile(AcdModel):
    path: NonEmptyStr
    lines_total: int = Field(ge=0)
    lines_covered: int = Field(ge=0)
    branches_total: int = Field(ge=0)
    branches_covered: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> CoverageFile:
        if self.lines_covered > self.lines_total:
            raise ValueError("covered lines cannot exceed total lines")
        if self.branches_covered > self.branches_total:
            raise ValueError("covered branches cannot exceed total branches")
        return self


class CoverageReport(AcdModel):
    files: list[CoverageFile] = Field(default_factory=list[CoverageFile])
    line_pct: float = Field(ge=0, le=100)
    branch_pct: float = Field(ge=0, le=100)

    @field_validator("line_pct", "branch_pct")
    @classmethod
    def validate_finite_percentage(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("coverage percentages must be finite")
        return value

    @model_validator(mode="after")
    def validate_totals(self) -> CoverageReport:
        paths = [item.path for item in self.files]
        if paths != sorted(paths):
            raise ValueError("coverage files must be sorted by path")
        if len(paths) != len(set(paths)):
            raise ValueError("coverage file paths must be unique")
        line_total = sum(item.lines_total for item in self.files)
        line_covered = sum(item.lines_covered for item in self.files)
        branch_total = sum(item.branches_total for item in self.files)
        branch_covered = sum(item.branches_covered for item in self.files)
        expected_line = 100.0 * line_covered / line_total if line_total else 100.0
        expected_branch = (
            100.0 * branch_covered / branch_total if branch_total else 100.0
        )
        if abs(self.line_pct - expected_line) > 0.001:
            raise ValueError("line_pct does not match coverage file totals")
        if abs(self.branch_pct - expected_branch) > 0.001:
            raise ValueError("branch_pct does not match coverage file totals")
        return self


class CoverageFloor(AcdModel):
    line_pct_min: float = Field(ge=0, le=100)
    branch_pct_min: float | None = Field(default=None, ge=0, le=100)

    @field_validator("line_pct_min", "branch_pct_min")
    @classmethod
    def validate_finite_floor(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("coverage floors must be finite")
        return value


class CoverageResult(AcdModel):
    status: CoverageStatus
    authority: Literal["observation"] = "observation"
    report: CoverageReport | None = None
    floor: CoverageFloor
    findings: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


__all__ = [
    "CoverageFile",
    "CoverageFloor",
    "CoverageReport",
    "CoverageResult",
    "CoverageStatus",
]
