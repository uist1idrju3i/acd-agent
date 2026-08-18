"""Contracts for deterministic role-based model routing."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    HashOrUnknown,
    NonEmptyStr,
    SchemaVersion,
)

RoutingRole = Literal["agent", "judge", "condenser"]
ModelRoutingStatus = Literal["pass", "unknown"]


class ModelRoutingBinding(AcdModel):
    role: RoutingRole
    model: NonEmptyStr
    usage_id: NonEmptyStr
    profile: NonEmptyStr

    @model_validator(mode="after")
    def reject_unknown_values(self) -> ModelRoutingBinding:
        if "unknown" in (self.model, self.usage_id, self.profile):
            raise ValueError("model routing values must not be unknown")
        return self


class ModelRoutingPolicy(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    bindings: list[ModelRoutingBinding] = Field(min_length=1)
    canonical_hash: HashOrUnknown = "unknown"

    @model_validator(mode="after")
    def validate_bindings(self) -> ModelRoutingPolicy:
        roles = [binding.role for binding in self.bindings]
        if len(roles) != len(set(roles)):
            raise ValueError("model routing roles must be unique")
        required = {"agent", "judge"}
        if not required.issubset(roles):
            raise ValueError("model routing policy must declare agent and judge")
        models = {binding.role: binding.model for binding in self.bindings}
        if models["agent"] == models["judge"]:
            raise ValueError("agent and judge models must be different")
        if roles != sorted(roles):
            raise ValueError("model routing bindings must be sorted by role")
        return self


class ModelRoutingObservation(AcdModel):
    role: RoutingRole
    model: NonEmptyStr
    usage_id: NonEmptyStr
    profile: NonEmptyStr


class ModelRoutingReport(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["model_routing_observation"] = (
        "model_routing_observation"
    )
    pass_evidence: Literal[False] = False
    status: ModelRoutingStatus
    policy_hash: HashOrUnknown
    bindings: list[ModelRoutingObservation] = Field(
        default_factory=list[ModelRoutingObservation]
    )
    reason: NonEmptyStr | None = None
