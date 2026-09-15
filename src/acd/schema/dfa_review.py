"""Contracts for deterministic design-for-assembly review observations."""

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
    Sha256,
)

DfaAspect = Literal[
    "orientation_uniformity",
    "single_side_assembly",
    "hand_solder_access",
    "connector_cable_order",
    "enclosure_assembly_effort",
    "fixture_required",
]
DfaSeverity = Literal["info", "advisory", "stop_recommendation"]
DfaStatus = Literal["observed", "unknown"]


class DfaFinding(AcdModel):
    finding_id: NonEmptyStr
    aspect: DfaAspect
    severity: DfaSeverity
    status: DfaStatus
    subject_node_ids: list[NodeId] = Field(default_factory=list)
    basis: NonEmptyStr
    unknown_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_unknown_state(self) -> DfaFinding:
        if self.status == "unknown" and self.unknown_reason is None:
            raise ValueError("unknown DFA findings require unknown_reason")
        if self.status == "observed" and self.unknown_reason is not None:
            raise ValueError("observed DFA findings must not have unknown_reason")
        if len(set(self.subject_node_ids)) != len(self.subject_node_ids):
            raise ValueError("DFA subject_node_ids must be unique")
        return self


class DfaReviewReport(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["dfa_review"] = "dfa_review"
    record_class: Literal["L2"] = "L2"
    pass_evidence: Literal[False] = False
    graph_id: NonEmptyStr
    revision: Revision
    findings: list[DfaFinding] = Field(min_length=1)
    input_hash: Sha256
    tool_version: NonEmptyStr

    @model_validator(mode="after")
    def validate_findings(self) -> DfaReviewReport:
        finding_ids = [finding.finding_id for finding in self.findings]
        if len(set(finding_ids)) != len(finding_ids):
            raise ValueError("DFA finding_id entries must be unique")
        return self
