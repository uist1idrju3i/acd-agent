"""Canonical L1 verdict for manufacturing-submission quality."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import AcdModel, NonEmptyStr, Revision, SchemaVersion, Sha256

SubmissionStatus = Literal["pass", "fail"]
CheckId = Literal[
    "required_artifacts",
    "independent_reload",
    "normalized_hashes",
    "dfm",
    "geometry",
    "fab_profile_consistency",
    "revision_consistency",
    "evidence_validity",
]
EvidenceClass = Literal["authoritative", "provisional"]


class ManufacturingSubmissionArtifact(AcdModel):
    role: NonEmptyStr
    path: NonEmptyStr
    format: NonEmptyStr
    normalized_sha256: Sha256
    present: bool


class ManufacturingSubmissionCheck(AcdModel):
    check_id: CheckId
    status: SubmissionStatus
    detail: NonEmptyStr


class ManufacturingSubmissionVerdict(AcdModel):
    schema_version: SchemaVersion = "0.1"
    artifact_kind: Literal["manufacturing_submission_verdict"] = (
        "manufacturing_submission_verdict"
    )
    record_class: Literal["L1"] = "L1"
    status: SubmissionStatus
    graph_id: NonEmptyStr
    target_revision: Revision
    artifacts: tuple[ManufacturingSubmissionArtifact, ...] = Field(min_length=1)
    checks: tuple[ManufacturingSubmissionCheck, ...] = Field(min_length=8, max_length=8)
    reasons: tuple[str, ...]
    authoritative: bool
    evidence_class: dict[str, EvidenceClass]
    order_readiness_status: NonEmptyStr
    excluded_scope: tuple[
        Literal["quote_aggregation"], Literal["order_execution"]
    ] = ("quote_aggregation", "order_execution")
    content_sha256: Sha256

    @model_validator(mode="after")
    def validate_checks_and_reasons(self) -> ManufacturingSubmissionVerdict:
        expected = {
            "required_artifacts",
            "independent_reload",
            "normalized_hashes",
            "dfm",
            "geometry",
            "fab_profile_consistency",
            "revision_consistency",
            "evidence_validity",
        }
        observed = [check.check_id for check in self.checks]
        if set(observed) != expected or len(observed) != len(expected):
            raise ValueError("manufacturing submission check set is incomplete")
        failed = tuple(check.detail for check in self.checks if check.status == "fail")
        if self.status == "pass" and self.reasons:
            raise ValueError("passing manufacturing submission must have no reasons")
        if self.status == "fail" and not self.reasons:
            raise ValueError("failed manufacturing submission requires reasons")
        if self.status == "fail" and not set(failed).intersection(self.reasons):
            raise ValueError("manufacturing submission reasons must explain failed checks")
        if self.authoritative != all(
            value == "authoritative" for value in self.evidence_class.values()
        ):
            raise ValueError("authoritative does not match evidence_class")
        return self
