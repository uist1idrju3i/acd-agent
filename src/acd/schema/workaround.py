"""Contracts for deterministic workaround candidate planning and evaluation."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
    WorkaroundId,
)
from acd.schema.rework_diff import ReworkDiff
from acd.schema.salvage import SalvageGateResult

WorkaroundStrategy = Literal["firmware_only", "rework_only", "combined"]
WorkaroundCandidateId = Annotated[
    str, StringConstraints(pattern=r"^WC-[0-9]{3,}$")
]


class SkillProvenance(AcdModel):
    skill_name: Literal["acd-workaround"] = "acd-workaround"
    script_sha256: Sha256
    acd_version: NonEmptyStr
    graph_sha256: Sha256
    defects_sha256: Sha256


class WorkaroundCandidate(AcdModel):
    candidate_id: WorkaroundCandidateId
    strategy: WorkaroundStrategy
    defect_ids: list[NonEmptyStr] = Field(min_length=1)
    anchor_node_ids: list[NodeId] = Field(default_factory=list[NodeId])
    rationale: NonEmptyStr
    rework_template: ReworkDiff | None = None
    status: Literal["proposed", "not_applicable"]
    not_applicable_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_candidate(self) -> WorkaroundCandidate:
        if len(set(self.defect_ids)) != len(self.defect_ids):
            raise ValueError("candidate defect_ids must be unique")
        if len(set(self.anchor_node_ids)) != len(self.anchor_node_ids):
            raise ValueError("candidate anchor_node_ids must be unique")
        if self.status == "not_applicable":
            if self.not_applicable_reason is None:
                raise ValueError(
                    "not_applicable candidate requires not_applicable_reason"
                )
            if self.rework_template is not None:
                raise ValueError("not_applicable candidate must not have a template")
        elif self.not_applicable_reason is not None:
            raise ValueError("proposed candidate must not have not_applicable_reason")
        if self.rework_template is not None:
            if self.rework_template.workaround_id != "WA-000":
                raise ValueError(
                    "candidate rework_template must use placeholder workaround_id WA-000"
                )
            if self.rework_template.defect_ids != self.defect_ids:
                raise ValueError(
                    "candidate template defect_ids must match candidate defect_ids"
                )
            if self.strategy == "firmware_only" and (
                self.rework_template.operations
                or not self.rework_template.firmware_changes
            ):
                raise ValueError(
                    "firmware_only template requires firmware changes and no operations"
                )
            if self.strategy == "rework_only" and (
                not self.rework_template.operations
                or self.rework_template.firmware_changes
            ):
                raise ValueError(
                    "rework_only template requires operations and no firmware changes"
                )
            if self.strategy == "combined" and (
                not self.rework_template.operations
                or not self.rework_template.firmware_changes
            ):
                raise ValueError(
                    "combined template requires operations and firmware changes"
                )
        return self


class WorkaroundProposalSet(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["workaround_candidates"] = "workaround_candidates"
    pass_evidence: Literal[False] = False
    record_class: Literal["L2"] = "L2"
    graph_id: NonEmptyStr
    revision: Revision
    defect_id: NonEmptyStr
    defect_check_status: Literal["workaround_eligible", "blocked"]
    candidates: list[WorkaroundCandidate]
    provenance: SkillProvenance

    @model_validator(mode="after")
    def validate_candidates(self) -> WorkaroundProposalSet:
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("candidate_id entries must be unique")
        if self.defect_check_status == "blocked" and self.candidates:
            raise ValueError("blocked proposal set must not contain candidates")
        if self.defect_check_status == "workaround_eligible" and not self.candidates:
            raise ValueError("eligible proposal set requires candidates")
        if any(self.defect_id not in candidate.defect_ids for candidate in self.candidates):
            raise ValueError("every candidate must include the proposal defect_id")
        return self


class WorkaroundEvaluation(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["workaround_evaluation"] = "workaround_evaluation"
    pass_evidence: Literal[False] = False
    record_class: Literal["L2"] = "L2"
    candidate_id: WorkaroundCandidateId
    workaround_id: WorkaroundId
    graph_id: NonEmptyStr
    base_revision: Revision
    derived_revision: Revision
    defect_check_status: Literal["workaround_eligible", "blocked"]
    salvage: SalvageGateResult | None = None
    rejection_reasons: list[NonEmptyStr] = Field(
        default_factory=list[NonEmptyStr]
    )
    alternatives: list[WorkaroundCandidateId] = Field(
        default_factory=list[WorkaroundCandidateId]
    )
    provenance: SkillProvenance

    @model_validator(mode="after")
    def validate_evaluation(self) -> WorkaroundEvaluation:
        if self.defect_check_status == "blocked" and self.salvage is not None:
            raise ValueError("blocked evaluation must not contain salvage")
        if self.derived_revision != f"{self.base_revision}+{self.workaround_id}":
            raise ValueError("derived_revision must match base_revision and workaround_id")
        if len(set(self.alternatives)) != len(self.alternatives):
            raise ValueError("evaluation alternatives must be unique")
        if self.salvage is None and not self.rejection_reasons:
            raise ValueError("missing salvage requires rejection_reasons")
        if (
            self.salvage is not None
            and self.salvage.verdict != "not_salvageable"
            and self.rejection_reasons
        ):
            raise ValueError(
                "rejection_reasons are only valid without salvage or for not_salvageable"
            )
        if self.salvage is not None and self.salvage.verdict == "not_salvageable":
            missing = set(self.salvage.reasons) - set(self.rejection_reasons)
            if missing:
                raise ValueError(
                    "rejection_reasons must include every salvage reason: "
                    + ", ".join(sorted(missing))
                )
        if len(set(self.rejection_reasons)) != len(self.rejection_reasons):
            raise ValueError("rejection_reasons must be unique")
        return self


__all__ = [
    "SkillProvenance",
    "WorkaroundCandidate",
    "WorkaroundCandidateId",
    "WorkaroundEvaluation",
    "WorkaroundProposalSet",
    "WorkaroundStrategy",
]
