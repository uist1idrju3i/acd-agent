"""Defect records and horizontal-scope declaration contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
)

DefectSeverity = Literal["safety", "functional", "cosmetic"]
HorizontalCriterion = Literal[
    "same_component_mpn",
    "same_node_kind",
    "same_rule",
    "same_fixture",
    "same_profile",
]


class AffectedUnits(AcdModel):
    lots: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    serials: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    scope_status: Literal["declared", "unknown"]

    @model_validator(mode="after")
    def validate_scope(self) -> AffectedUnits:
        if len(set(self.lots)) != len(self.lots):
            raise ValueError("affected lots must be unique")
        if len(set(self.serials)) != len(self.serials):
            raise ValueError("affected serials must be unique")
        if self.scope_status == "declared" and not (self.lots or self.serials):
            raise ValueError("declared affected units require lots or serials")
        if self.scope_status == "unknown" and (self.lots or self.serials):
            raise ValueError("unknown affected units must not list lots or serials")
        return self


class ReproductionCondition(AcdModel):
    description: NonEmptyStr
    environment: dict[str, str | float | int | bool] = Field(
        default_factory=dict[str, str | float | int | bool]
    )
    occurrence_rate: float | Literal["unknown"]
    sample_size: int | Literal["unknown"]

    @model_validator(mode="after")
    def validate_measurements(self) -> ReproductionCondition:
        if isinstance(self.occurrence_rate, float) and not (
            0.0 < self.occurrence_rate <= 1.0
        ):
            raise ValueError("occurrence_rate must be greater than 0 and at most 1")
        if isinstance(self.sample_size, int) and self.sample_size < 1:
            raise ValueError("sample_size must be at least 1")
        return self


class RootCauseCandidate(AcdModel):
    candidate_id: NonEmptyStr
    status: Literal["identified", "unknown"]
    description: NonEmptyStr
    node_ids: list[NodeId] = Field(default_factory=list[NodeId])
    rule_ids: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    confidence: Literal["confirmed", "suspected"] | None = None

    @model_validator(mode="after")
    def validate_status(self) -> RootCauseCandidate:
        if self.status == "identified":
            if not self.node_ids:
                raise ValueError("identified root cause requires node_ids")
            if self.confidence is None:
                raise ValueError("identified root cause requires confidence")
        elif self.node_ids or self.confidence is not None:
            raise ValueError("unknown root cause must not have node_ids or confidence")
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("root cause node_ids must be unique")
        if len(set(self.rule_ids)) != len(self.rule_ids):
            raise ValueError("root cause rule_ids must be unique")
        return self


class HorizontalExclusion(AcdModel):
    node_id: NodeId
    reason: NonEmptyStr


class HorizontalScope(AcdModel):
    criterion: HorizontalCriterion
    search_status: Literal["searched", "unsearched"]
    matched_node_ids: list[NodeId] = Field(default_factory=list[NodeId])
    excluded: list[HorizontalExclusion] = Field(
        default_factory=list[HorizontalExclusion]
    )

    @model_validator(mode="after")
    def validate_search_status(self) -> HorizontalScope:
        if len(set(self.matched_node_ids)) != len(self.matched_node_ids):
            raise ValueError("matched_node_ids must be unique")
        excluded_ids = [item.node_id for item in self.excluded]
        if len(set(excluded_ids)) != len(excluded_ids):
            raise ValueError("excluded node_ids must be unique")
        if self.search_status == "unsearched" and (
            self.matched_node_ids or self.excluded
        ):
            raise ValueError("unsearched horizontal scope must be empty")
        return self


class DefectRecord(AcdModel):
    defect_id: NonEmptyStr
    severity: DefectSeverity
    symptom: NonEmptyStr
    affected_functions: list[NonEmptyStr]
    affected_units: AffectedUnits
    reproduction: ReproductionCondition
    root_cause_candidates: list[RootCauseCandidate]
    horizontal_scopes: list[HorizontalScope]
    fixture_refs: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    profile_refs: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])

    @model_validator(mode="after")
    def validate_record(self) -> DefectRecord:
        if not self.affected_functions:
            raise ValueError("affected_functions must not be empty")
        if len(set(self.affected_functions)) != len(self.affected_functions):
            raise ValueError("affected_functions must be unique")
        if not self.root_cause_candidates:
            raise ValueError("root_cause_candidates must not be empty")
        candidate_ids = [item.candidate_id for item in self.root_cause_candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("root cause candidate_id entries must be unique")
        if not self.horizontal_scopes:
            raise ValueError("horizontal_scopes must not be empty")
        criteria = [item.criterion for item in self.horizontal_scopes]
        if len(set(criteria)) != len(criteria):
            raise ValueError("horizontal scope criteria must be unique")
        expected = {
            "same_component_mpn",
            "same_node_kind",
            "same_rule",
            "same_fixture",
            "same_profile",
        }
        actual = set(criteria)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            detail: list[str] = []
            if missing:
                detail.append("missing " + ", ".join(missing))
            if extra:
                detail.append("extra " + ", ".join(extra))
            raise ValueError("horizontal scope criteria must cover all five: " + "; ".join(detail))
        if len(set(self.fixture_refs)) != len(self.fixture_refs):
            raise ValueError("fixture_refs must be unique")
        if len(set(self.profile_refs)) != len(self.profile_refs):
            raise ValueError("profile_refs must be unique")
        return self


class DefectDocument(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["defect_record"] = "defect_record"
    graph_id: NonEmptyStr
    revision: Revision
    records: list[DefectRecord]

    @model_validator(mode="after")
    def validate_records(self) -> DefectDocument:
        defect_ids = [record.defect_id for record in self.records]
        if len(set(defect_ids)) != len(defect_ids):
            raise ValueError("defect_id entries must be unique")
        return self


__all__ = [
    "AffectedUnits",
    "DefectDocument",
    "DefectRecord",
    "DefectSeverity",
    "HorizontalCriterion",
    "HorizontalExclusion",
    "HorizontalScope",
    "ReproductionCondition",
    "RootCauseCandidate",
]
