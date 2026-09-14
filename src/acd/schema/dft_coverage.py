"""Contracts for opt-in design-for-test coverage results."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
)

DftCoverageStatus = Literal["pass", "fail", "unknown"]


class DftCoverageSet(AcdModel):
    required_nets: list[NodeId] = Field(default_factory=list[NodeId])
    covered_nets: list[NodeId] = Field(default_factory=list[NodeId])
    uncovered_nets: list[NodeId] = Field(default_factory=list[NodeId])
    ratio: float

    @model_validator(mode="after")
    def validate_sets(self) -> DftCoverageSet:
        for name, values in (
            ("required_nets", self.required_nets),
            ("covered_nets", self.covered_nets),
            ("uncovered_nets", self.uncovered_nets),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{name} entries must be unique")
        if set(self.covered_nets) & set(self.uncovered_nets):
            raise ValueError("covered and uncovered nets must be disjoint")
        if set(self.covered_nets) | set(self.uncovered_nets) != set(self.required_nets):
            raise ValueError("coverage sets must partition required_nets")
        if not math.isfinite(self.ratio) or not 0.0 <= self.ratio <= 1.0:
            raise ValueError("coverage ratio must be between zero and one")
        return self


class DftCheckResult(AcdModel):
    check_id: NonEmptyStr
    status: DftCoverageStatus
    reason: NonEmptyStr
    subject_node_ids: list[NodeId] = Field(default_factory=list[NodeId])
    details: dict[str, Any] = Field(default_factory=dict[str, Any])

    @model_validator(mode="after")
    def validate_subjects(self) -> DftCheckResult:
        if len(set(self.subject_node_ids)) != len(self.subject_node_ids):
            raise ValueError("DFT subject_node_ids must be unique")
        return self


class DftCoverageResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["dft_coverage"] = "dft_coverage"
    graph_id: NonEmptyStr
    revision: Revision
    status: DftCoverageStatus
    checks: list[DftCheckResult] = Field(min_length=1)
    coverage: DftCoverageSet
    input_hashes: dict[str, Sha256]
