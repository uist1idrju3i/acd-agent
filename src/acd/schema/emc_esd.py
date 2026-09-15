"""Contracts for opt-in EMC/ESD design predicate observations."""

from __future__ import annotations

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

EmcEsdStatus = Literal["pass", "fail", "unknown"]


class EmcEsdPredicateResult(AcdModel):
    predicate_id: NonEmptyStr
    status: EmcEsdStatus
    reason: NonEmptyStr
    subject_node_ids: list[NodeId] = Field(default_factory=list[NodeId])
    details: dict[str, Any] = Field(default_factory=dict[str, Any])

    @model_validator(mode="after")
    def validate_subjects(self) -> EmcEsdPredicateResult:
        if len(set(self.subject_node_ids)) != len(self.subject_node_ids):
            raise ValueError("EMC/ESD subject_node_ids must be unique")
        return self


class EmcEsdResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["emc_esd_predicates"] = "emc_esd_predicates"
    graph_id: NonEmptyStr
    revision: Revision
    status: EmcEsdStatus
    predicates: list[EmcEsdPredicateResult] = Field(min_length=1)
    input_hashes: dict[str, Sha256]
    certification_claim: Literal[False] = False
