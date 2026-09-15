"""Contracts for workaround application traceability and retirement."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
    WorkaroundId,
)
from acd.schema.eco import EcoId


class UnitRef(AcdModel):
    lot: NonEmptyStr | None = None
    serial: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_reference(self) -> UnitRef:
        if self.lot is None and self.serial is None:
            raise ValueError("unit reference requires lot or serial")
        return self


class WorkaroundApplication(AcdModel):
    workaround_id: WorkaroundId
    graph_id: NonEmptyStr
    base_revision: Revision
    derived_revision: Revision
    unit: UnitRef
    applied_at: AwareDatetime
    operator: NonEmptyStr
    work_instruction_sha256: Sha256
    post_work_inspection: Literal["pass", "fail", "not_recorded"]
    evidence_ref: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_application(self) -> WorkaroundApplication:
        if "+" in self.base_revision:
            raise ValueError("workaround application base_revision must be canonical")
        expected_revision = f"{self.base_revision}+{self.workaround_id}"
        if self.derived_revision != expected_revision:
            raise ValueError(
                "workaround application derived_revision must match base_revision "
                "and workaround_id"
            )
        if self.post_work_inspection in {"pass", "fail"}:
            if self.evidence_ref is None:
                raise ValueError(
                    "post-work inspection evidence_ref is required for pass or fail"
                )
        elif self.evidence_ref is not None:
            raise ValueError(
                "not_recorded post-work inspection must not have evidence_ref"
            )
        return self


class WorkaroundRetirement(AcdModel):
    workaround_id: WorkaroundId
    eco_id: EcoId
    resolved_revision: Revision
    eco_check_sha256: Sha256

    @model_validator(mode="after")
    def validate_revision(self) -> WorkaroundRetirement:
        if "+" in self.resolved_revision:
            raise ValueError("resolved_revision must be canonical")
        return self


class UnitDisposition(AcdModel):
    unit: UnitRef
    disposition: Literal["scrapped", "upgraded_to_revision"]
    revision: Revision | None = None
    reason: NonEmptyStr

    @model_validator(mode="after")
    def validate_disposition(self) -> UnitDisposition:
        if self.disposition == "upgraded_to_revision" and self.revision is None:
            raise ValueError("upgraded_to_revision requires revision")
        if self.disposition == "scrapped" and self.revision is not None:
            raise ValueError("scrapped disposition must not have revision")
        return self


class WorkaroundLedger(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["workaround_ledger"] = "workaround_ledger"
    pass_evidence: Literal[False] = False
    graph_id: NonEmptyStr
    applications: list[WorkaroundApplication] = Field(
        default_factory=list[WorkaroundApplication]
    )
    retirements: list[WorkaroundRetirement] = Field(
        default_factory=list[WorkaroundRetirement]
    )
    unit_dispositions: list[UnitDisposition] = Field(
        default_factory=list[UnitDisposition]
    )

    @model_validator(mode="after")
    def validate_ledger(self) -> WorkaroundLedger:
        application_keys = [
            (
                application.workaround_id,
                application.unit.lot,
                application.unit.serial,
            )
            for application in self.applications
        ]
        if len(set(application_keys)) != len(application_keys):
            raise ValueError(
                "workaround applications must be unique per workaround and unit"
            )
        retirement_ids = [retirement.workaround_id for retirement in self.retirements]
        if len(set(retirement_ids)) != len(retirement_ids):
            raise ValueError("workaround retirements must be unique per workaround")
        disposition_keys = [
            (item.unit.lot, item.unit.serial) for item in self.unit_dispositions
        ]
        if len(set(disposition_keys)) != len(disposition_keys):
            raise ValueError("unit dispositions must be unique per unit")
        mismatched = sorted(
            {
                application.graph_id
                for application in self.applications
                if application.graph_id != self.graph_id
            }
        )
        if mismatched:
            raise ValueError(
                "workaround application graph_id does not match ledger graph_id: "
                + ", ".join(mismatched)
            )
        return self


class UnitStatus(AcdModel):
    unit: UnitRef
    state: Literal[
        "unmodified",
        "applied_verified",
        "applied_unverified",
        "applied_failed",
    ]
    workaround_ids: list[WorkaroundId] = Field(
        default_factory=list[WorkaroundId]
    )


class WorkaroundRetirementResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["workaround_retirement_check"] = (
        "workaround_retirement_check"
    )
    pass_evidence: Literal[False] = False
    workaround_id: WorkaroundId
    verdict: Literal["retired", "active", "unknown"]
    reasons: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    unit_statuses: list[UnitStatus] = Field(default_factory=list[UnitStatus])
    open_units: list[UnitRef] = Field(default_factory=list[UnitRef])

    @model_validator(mode="after")
    def validate_result(self) -> WorkaroundRetirementResult:
        if self.verdict == "retired" and self.reasons:
            raise ValueError("retired result must not have reasons")
        if self.verdict != "retired" and not self.reasons:
            raise ValueError("non-retired result requires reasons")
        return self


__all__ = [
    "UnitDisposition",
    "UnitRef",
    "UnitStatus",
    "WorkaroundApplication",
    "WorkaroundLedger",
    "WorkaroundRetirement",
    "WorkaroundRetirementResult",
]
