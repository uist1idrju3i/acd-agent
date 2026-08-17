"""Canonical design decision rationale contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd_schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    HashOrUnknown,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
    Timestamp,
)

DecisionKind = Literal[
    "part_selection",
    "placement",
    "routing_width",
    "silkscreen",
    "firmware_pin",
    "mechanical",
    "fab_process",
    "stackup",
    "design_rule",
    "net_class",
    "safety_scope",
    "population",
]
RationaleSource = Literal["human", "openhands_agent", "acd_skill", "deterministic_tool"]


class RejectedAlternative(AcdModel):
    option: NonEmptyStr
    reason: NonEmptyStr


class RationaleProvenance(AcdModel):
    source: RationaleSource
    skill_name: NonEmptyStr | None = None
    script_hash: HashOrUnknown | None = None
    agent_model: NonEmptyStr | None = None
    conversation_event_ref: NonEmptyStr | None = None
    recorded_at: Timestamp

    @model_validator(mode="after")
    def _skill_provenance(self) -> RationaleProvenance:
        if self.source == "acd_skill" and (
            self.skill_name is None or self.script_hash is None
        ):
            raise ValueError("acd_skill provenance requires skill_name and script_hash")
        return self


class RationaleRecord(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    rationale_id: NonEmptyStr
    decision_kind: DecisionKind
    subject_nodes: list[NodeId] = Field(min_length=1)
    subject_attrs: list[NonEmptyStr] = Field(min_length=1)
    subject_hash: Sha256
    decision: NonEmptyStr
    justification: NonEmptyStr
    driving_requirements: list[NodeId] = Field(default_factory=list[NodeId])
    driving_requirement_refs: list[NonEmptyStr] = Field(
        default_factory=list[NonEmptyStr]
    )
    rejected_alternatives: list[RejectedAlternative] = Field(
        default_factory=list[RejectedAlternative]
    )
    no_alternatives_reason: NonEmptyStr | None = None
    assumptions: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    risks: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    provenance: RationaleProvenance
    target_revision: Revision

    @model_validator(mode="after")
    def _validate_alternatives(self) -> RationaleRecord:
        if bool(self.rejected_alternatives) == (self.no_alternatives_reason is not None):
            raise ValueError(
                "exactly one of rejected_alternatives and no_alternatives_reason is required"
            )
        if len(set(self.subject_nodes)) != len(self.subject_nodes):
            raise ValueError("subject_nodes entries must be unique")
        if len(set(self.subject_attrs)) != len(self.subject_attrs):
            raise ValueError("subject_attrs entries must be unique")
        for requirement_ref in self.driving_requirement_refs:
            if (
                "#" not in requirement_ref
                or any(character.isspace() for character in requirement_ref)
                or not requirement_ref.split("#", 1)[0]
                or not requirement_ref.split("#", 1)[1]
            ):
                raise ValueError(
                    "driving_requirement_refs must use a non-empty path#identifier format"
                )
        return self

    def supports_coverage(self, current_revision: str, expected_subject_hash: str) -> bool:
        return (
            self.target_revision == current_revision
            and self.subject_hash == expected_subject_hash
            and self.provenance.script_hash != "unknown"
        )


class RationaleDocument(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    graph_id: NonEmptyStr
    revision: Revision
    records: list[RationaleRecord] = Field(default_factory=list[RationaleRecord])

    @model_validator(mode="after")
    def _unique_rationale_ids(self) -> RationaleDocument:
        ids = [record.rationale_id for record in self.records]
        if len(set(ids)) != len(ids):
            raise ValueError("rationale_id entries must be unique")
        return self


RationaleCoverageStatus = Literal["pass", "fail"]


class RationaleSubject(AcdModel):
    node_id: NodeId
    attr: NonEmptyStr


class RationaleRecordSubject(AcdModel):
    rationale_id: NonEmptyStr
    subject: RationaleSubject


class RationaleUnknownProvenance(AcdModel):
    rationale_id: NonEmptyStr


class RationaleOrphan(AcdModel):
    rationale_id: NonEmptyStr
    subject: RationaleSubject
    reason: NonEmptyStr


class RationaleUntraceable(AcdModel):
    rationale_id: NonEmptyStr
    subject: RationaleSubject


class RationaleUnclassified(AcdModel):
    node_id: NodeId
    node_kind: NonEmptyStr
    attr: NonEmptyStr
    reason: NonEmptyStr


class RationaleCoverageReport(AcdModel):
    status: RationaleCoverageStatus
    graph_id: NonEmptyStr
    revision: Revision
    graph_id_match: bool
    revision_match: bool
    missing: list[RationaleSubject] = Field(default_factory=list[RationaleSubject])
    stale: list[RationaleRecordSubject] = Field(
        default_factory=list[RationaleRecordSubject]
    )
    unknown_provenance: list[RationaleUnknownProvenance] = Field(
        default_factory=list[RationaleUnknownProvenance]
    )
    orphan: list[RationaleOrphan] = Field(default_factory=list[RationaleOrphan])
    untraceable: list[RationaleUntraceable] = Field(
        default_factory=list[RationaleUntraceable]
    )
    conflicting: list[RationaleRecordSubject] = Field(
        default_factory=list[RationaleRecordSubject]
    )
    unclassified: list[RationaleUnclassified] = Field(
        default_factory=list[RationaleUnclassified]
    )
    required_count: int = 0
    covered_count: int = 0
    record_count: int = 0
