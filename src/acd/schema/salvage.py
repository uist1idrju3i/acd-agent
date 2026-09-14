"""Contracts for deterministic workaround salvageability decisions."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    WorkaroundId,
)


class ReworkDfaAssessment(AcdModel):
    operation_index: int = Field(ge=0)
    tool_access: Literal["yes", "no", "unknown"]
    hand_solderable: Literal["yes", "no", "not_applicable", "unknown"]
    enclosure_disassembly: Literal[
        "not_required", "reversible", "destructive", "unknown"
    ]
    basis: NonEmptyStr


class ReworkDfaDeclaration(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["rework_dfa"] = "rework_dfa"
    pass_evidence: Literal[False] = False
    workaround_id: WorkaroundId
    graph_id: NonEmptyStr
    base_revision: Revision
    assessments: list[ReworkDfaAssessment] = Field(
        default_factory=list[ReworkDfaAssessment]
    )

    @model_validator(mode="after")
    def validate_assessments(self) -> ReworkDfaDeclaration:
        indexes = [item.operation_index for item in self.assessments]
        if len(set(indexes)) != len(indexes):
            raise ValueError("DFA operation_index entries must be unique")
        return self


class SafetyApproval(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["safety_approval"] = "safety_approval"
    workaround_id: WorkaroundId
    graph_id: NonEmptyStr
    derived_revision: Revision
    approver: NonEmptyStr
    approved_at: AwareDatetime
    scope: NonEmptyStr

    @field_validator("derived_revision")
    @classmethod
    def validate_derived_revision(cls, value: Revision) -> Revision:
        if "+" not in value:
            raise ValueError("safety approval requires a derived revision")
        return value


class GateRun(AcdModel):
    gate: NonEmptyStr
    status: Literal["pass", "fail", "unknown", "not_applicable"]
    source: Literal["computed", "evidence_file", "missing"]
    detail: NonEmptyStr
    evidence_path: str | None = None


SalvageVerdict = Literal["salvageable", "constrained_salvage", "not_salvageable"]


class SalvageGateResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["salvage_gate"] = "salvage_gate"
    pass_evidence: Literal[False] = False
    workaround_id: WorkaroundId
    graph_id: NonEmptyStr
    base_revision: Revision
    derived_revision: Revision
    verdict: SalvageVerdict
    gate_runs: list[GateRun]
    dfa_blockers: list[NonEmptyStr]
    safety_boundary_touched: bool
    approval_status: Literal["not_required", "approved", "missing", "invalid"]
    degraded_functions: list[NonEmptyStr]
    reasons: list[NonEmptyStr]

    @model_validator(mode="after")
    def validate_verdict(self) -> SalvageGateResult:
        if not self.gate_runs:
            raise ValueError("gate_runs must not be empty")
        if [run.gate for run in self.gate_runs] != sorted(
            run.gate for run in self.gate_runs
        ):
            raise ValueError("gate_runs must be sorted by gate")
        if self.verdict != "not_salvageable":
            if any(run.status not in {"pass", "not_applicable"} for run in self.gate_runs):
                raise ValueError("salvageable verdict requires passing gate runs")
            if self.dfa_blockers:
                raise ValueError("salvageable verdict must not have DFA blockers")
            if self.approval_status not in {"not_required", "approved"}:
                raise ValueError("salvageable verdict requires valid safety approval")
            if self.verdict == "constrained_salvage" and not self.degraded_functions:
                raise ValueError("constrained salvage requires degraded functions")
            if self.verdict == "salvageable" and self.degraded_functions:
                raise ValueError("salvageable verdict must not degrade functions")
        if self.verdict == "not_salvageable" and not self.reasons:
            raise ValueError("not salvageable verdict requires reasons")
        return self


__all__ = [
    "GateRun",
    "ReworkDfaAssessment",
    "ReworkDfaDeclaration",
    "SafetyApproval",
    "SalvageGateResult",
    "SalvageVerdict",
]
