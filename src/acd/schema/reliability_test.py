"""Contracts for opt-in reliability-test stress mappings and coverage."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
)
from acd.schema.use_environment import UseEnvironment

ReliabilityStatus = Literal["pass", "fail", "unknown"]
ReliabilityStressCategory = Literal[
    "emc_conducted",
    "emc_radiated",
    "esd",
    "surge",
    "eft_burst",
    "thermal",
    "humidity",
    "thermal_cycle",
    "vibration",
    "shock",
    "drop",
    "dust_ingress",
    "corrosive_gas",
    "transport_storage",
    "user_contact",
    "lifetime",
]
ReliabilitySourceKind = Literal[
    "standard",
    "incident_report",
    "internal_analysis",
    "datasheet",
]
ReliabilityConditionSource = Literal["environment", "declared"]
ReliabilitySeverityRelation = Literal["covers", "under", "over", "unknown"]
ReliabilityLifetimeModelKind = Literal["arrhenius", "coffin_manson", "peck"]


class ReliabilitySourceReference(AcdModel):
    identifier: NonEmptyStr
    edition: NonEmptyStr
    kind: ReliabilitySourceKind


class ReliabilityEnvironmentRef(AcdModel):
    path: NonEmptyStr | None = None
    environment: UseEnvironment | None = None

    @model_validator(mode="after")
    def validate_reference(self) -> ReliabilityEnvironmentRef:
        if (self.path is None) == (self.environment is None):
            raise ValueError("exactly one environment path or inline environment is required")
        return self


class ReliabilityRealUseCondition(AcdModel):
    parameter: NonEmptyStr
    value: Any
    unit: NonEmptyStr
    source: ReliabilityConditionSource


class ReliabilityStress(AcdModel):
    stress_id: NonEmptyStr
    category: ReliabilityStressCategory
    description: NonEmptyStr
    real_use_condition: ReliabilityRealUseCondition
    severity_rank: int = Field(gt=0)


class ReliabilityTestItem(AcdModel):
    test_item_id: NonEmptyStr
    source_reference: ReliabilitySourceReference | None = None
    background: NonEmptyStr | None = None
    simulates_stress_ids: list[NonEmptyStr] = Field(min_length=1)
    severity_relation: ReliabilitySeverityRelation
    rationale: NonEmptyStr


class ReliabilityDesignRequirement(AcdModel):
    requirement_id: NonEmptyStr
    derived_from_test_item_ids: list[NonEmptyStr] = Field(
        default_factory=list[NonEmptyStr]
    )
    derived_from_stress_ids: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    target_predicate: NonEmptyStr
    parameter: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_derivation(self) -> ReliabilityDesignRequirement:
        if not self.derived_from_test_item_ids and not self.derived_from_stress_ids:
            raise ValueError(
                "design requirement must derive from a test item or stress"
            )
        return self


class ReliabilityAcceptedGap(AcdModel):
    stress_id: NonEmptyStr
    acceptance_rationale: NonEmptyStr
    approved_by_role: NonEmptyStr


class ReliabilityLifetimeModel(AcdModel):
    model: ReliabilityLifetimeModelKind
    parameters: dict[str, float] = Field(default_factory=dict[str, float])
    note: Literal["estimate"] = "estimate"


class ReliabilityMeasuredResult(AcdModel):
    test_item_id: NonEmptyStr
    verdict: NonEmptyStr
    conditions: dict[str, Any] | None = None
    equipment: NonEmptyStr | None = None
    date: NonEmptyStr | None = None
    specimen_revision: Revision | None = None


class ReliabilityTestPlan(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["reliability_test_plan"] = "reliability_test_plan"
    plan_id: NonEmptyStr
    graph_id: NonEmptyStr
    revision: Revision
    environment_ref: ReliabilityEnvironmentRef | UseEnvironment | NonEmptyStr
    stresses: list[ReliabilityStress] = Field(min_length=1)
    test_items: list[ReliabilityTestItem] = Field(min_length=1)
    design_requirements: list[ReliabilityDesignRequirement] = Field(
        default_factory=list[ReliabilityDesignRequirement]
    )
    accepted_gaps: list[ReliabilityAcceptedGap] = Field(
        default_factory=list[ReliabilityAcceptedGap]
    )
    lifetime_model: ReliabilityLifetimeModel | None = None
    measured_results: list[ReliabilityMeasuredResult] = Field(
        default_factory=list[ReliabilityMeasuredResult]
    )

    @model_validator(mode="after")
    def validate_unique_ids(self) -> ReliabilityTestPlan:
        for name, values in (
            ("stress_id", [item.stress_id for item in self.stresses]),
            ("test_item_id", [item.test_item_id for item in self.test_items]),
            ("requirement_id", [item.requirement_id for item in self.design_requirements]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} entries must be unique")
        return self


class ReliabilityCheckResult(AcdModel):
    check_id: NonEmptyStr
    status: ReliabilityStatus
    reason: NonEmptyStr
    subject_ids: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    details: dict[str, Any] = Field(default_factory=dict[str, Any])


class ReliabilityTestResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["reliability_test_result"] = "reliability_test_result"
    plan_id: NonEmptyStr
    graph_id: NonEmptyStr
    revision: Revision
    status: ReliabilityStatus
    checks: list[ReliabilityCheckResult] = Field(min_length=1)
    input_hashes: dict[str, Sha256]
    certification_claim: Literal[False] = False
