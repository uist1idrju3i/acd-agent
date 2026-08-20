"""Contracts for machine-readable troubleshooting knowledge.

Troubleshooting knowledge maps a symptom to the check steps and the expected
values a user can compare against. Every expected value is derived from the
design graph or from the generated firmware pin projection: nothing is
estimated. When a value cannot be derived, the entry is recorded as ``unknown``
with a reason so a human decides instead of reading an invented number.
The knowledge is an L3 observation and carries no approval authority.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
)

TroubleshootingStatus = Literal["derived", "unknown"]
UNKNOWN_EXPECTATION = "unknown"


class TroubleshootingExpectation(AcdModel):
    """One expected observation with the source it was derived from."""

    description: NonEmptyStr
    expected: NonEmptyStr
    citation: NonEmptyStr


class TroubleshootingEntry(AcdModel):
    """One symptom with its check steps and expected observations."""

    entry_id: NonEmptyStr
    symptom: NonEmptyStr
    checks: list[NonEmptyStr] = Field(min_length=1)
    expectations: list[TroubleshootingExpectation] = Field(min_length=1)
    status: TroubleshootingStatus
    reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _validate_entry(self) -> TroubleshootingEntry:
        has_unknown = any(
            item.expected == UNKNOWN_EXPECTATION for item in self.expectations
        )
        if self.status == "unknown":
            if self.reason is None:
                raise ValueError("unknown troubleshooting entry requires a reason")
            if not has_unknown:
                raise ValueError(
                    "unknown troubleshooting entry requires an unknown expectation"
                )
            return self
        if self.reason is not None:
            raise ValueError("derived troubleshooting entry cannot carry a reason")
        if has_unknown:
            raise ValueError(
                "derived troubleshooting entry cannot carry an unknown expectation"
            )
        return self


class TroubleshootingKnowledge(AcdModel):
    """The troubleshooting entries derived for one graph revision."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    graph_id: NonEmptyStr
    target_revision: Revision
    entries: list[TroubleshootingEntry] = Field(min_length=1)
    pass_evidence: Literal[False] = False

    @model_validator(mode="after")
    def _validate_entries(self) -> TroubleshootingKnowledge:
        entry_ids = [entry.entry_id for entry in self.entries]
        if len(set(entry_ids)) != len(entry_ids):
            raise ValueError("troubleshooting entry ids must be unique")
        if entry_ids != sorted(entry_ids):
            raise ValueError("troubleshooting entries must be sorted by entry id")
        return self

    def unknown_entries(self) -> tuple[TroubleshootingEntry, ...]:
        return tuple(entry for entry in self.entries if entry.status == "unknown")
