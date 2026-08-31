"""Contracts for the non-authoritative run progress digest."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    SchemaVersion,
)

ProgressRecordKind = Literal[
    "timing_record",
    "board_exploration_report",
    "enclosure_exploration_report",
    "firmware_exploration_report",
    "design_loop_summary",
    "unknown",
]
ProgressRecordStatus = Literal["read", "unknown"]
ProgressDigestStatus = Literal["pass", "unknown"]


class ProgressRecord(AcdModel):
    """One L3 record surfaced to the conversation."""

    kind: ProgressRecordKind
    path: NonEmptyStr
    status: ProgressRecordStatus
    record_ok: bool | None = None
    # Status reported by the record itself, such as an exploration termination.
    record_status: NonEmptyStr | None = None
    termination_reason: NonEmptyStr | None = None
    failed_stage: NonEmptyStr | None = None
    failure_reason: NonEmptyStr | None = None
    next_step_action: NonEmptyStr | None = None
    exploration_rounds: int | None = Field(default=None, ge=0)
    target_revision: NonEmptyStr | None = None
    evaluated_candidates: int | None = Field(default=None, ge=0)
    remaining_budget: int | None = Field(default=None, ge=0)
    winner_candidate_id: NonEmptyStr | None = None
    winner_written: bool | None = None
    stage_count: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0.0)
    reason: NonEmptyStr | None = None
    pass_evidence: Literal[False] = False

    @model_validator(mode="after")
    def validate_reason(self) -> ProgressRecord:
        if self.status == "unknown" and self.reason is None:
            raise ValueError("an unreadable progress record requires a reason")
        return self


class ProgressDigestReport(AcdModel):
    """Conversation-visible digest of the L3 records written by one run."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    status: ProgressDigestStatus
    out_dir: NonEmptyStr
    records: list[ProgressRecord] = Field(default_factory=list[ProgressRecord])
    unreadable_records: int = Field(default=0, ge=0)
    reason: NonEmptyStr | None = None
    record_class: Literal["L3"] = "L3"
    pass_evidence: Literal[False] = False

    @model_validator(mode="after")
    def validate_status(self) -> ProgressDigestReport:
        unreadable = sum(1 for record in self.records if record.status == "unknown")
        if unreadable != self.unreadable_records:
            raise ValueError("unreadable record count must match the records")
        if unreadable and self.status != "unknown":
            raise ValueError("a digest with unreadable records must be unknown")
        if self.status == "unknown" and self.reason is None:
            raise ValueError("an unknown digest requires a reason")
        paths = [record.path for record in self.records]
        if paths != sorted(paths):
            raise ValueError("progress records must be sorted by path")
        return self


__all__ = [
    "ProgressDigestReport",
    "ProgressDigestStatus",
    "ProgressRecord",
    "ProgressRecordKind",
    "ProgressRecordStatus",
]
