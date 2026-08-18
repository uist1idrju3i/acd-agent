"""Contracts for deterministic physical-measurement feedback proposals."""

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
)
from acd.schema.design_graph import AttrValue, NodeId
from acd.schema.rationale import DecisionKind

FeedbackRuleKind = Literal["set_value", "reconfirm"]
FeedbackItemStatus = Literal["no_change", "proposed"]
FeedbackProposalStatus = Literal["pass", "unknown"]
FeedbackValidationStatus = Literal["pass", "fail", "unknown"]


class FeedbackRule(AcdModel):
    rule_id: NonEmptyStr
    measurement_name: NonEmptyStr
    node_id: NodeId
    attr: NonEmptyStr
    rule_kind: FeedbackRuleKind
    tolerance: float = Field(ge=0)
    decision_kind: DecisionKind

    @field_validator("tolerance")
    @classmethod
    def reject_non_finite_tolerance(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("feedback tolerance must be finite")
        return value


class FeedbackPolicy(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    graph_id: NonEmptyStr
    revision: Revision
    rules: list[FeedbackRule] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_rules(self) -> FeedbackPolicy:
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("feedback rule_id entries must be unique")
        targets = [(rule.node_id, rule.attr) for rule in self.rules]
        if len(set(targets)) != len(targets):
            raise ValueError("feedback rule targets must be unique")
        return self


class FeedbackProposalItem(AcdModel):
    rule_id: NonEmptyStr
    status: FeedbackItemStatus
    node_id: NodeId
    attr: NonEmptyStr
    current_value: AttrValue
    measured_value: float
    proposed_value: AttrValue
    difference: float
    evidence_id: NonEmptyStr
    measurement_name: NonEmptyStr
    decision_kind: DecisionKind
    rationale_required: bool

    @field_validator("measured_value", "difference")
    @classmethod
    def reject_non_finite_values(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("feedback values must be finite")
        return value


class FeedbackProposal(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    status: FeedbackProposalStatus
    graph_id: NonEmptyStr | Literal["unknown"]
    revision: Revision | Literal["unknown"]
    input_hash: Sha256 | Literal["unknown"]
    output_hash: Sha256 | Literal["unknown"]
    applicable: bool = False
    items: list[FeedbackProposalItem] = Field(default_factory=list[FeedbackProposalItem])
    error: NonEmptyStr | None = None


class AppliedFeedbackValidationReport(AcdModel):
    status: FeedbackValidationStatus
    reason: NonEmptyStr | None = None
