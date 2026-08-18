"""Contracts for non-authoritative ACD context memory and event views."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    HashOrUnknown,
    NonEmptyStr,
    SchemaVersion,
    Sha256,
)

ContextSource = Literal["event_log", "memory_index"]
EventViewStatus = Literal["pass", "unknown"]


class EventViewEntry(AcdModel):
    """One displayed event, identified by the original EventLog entry."""

    index: int = Field(ge=0)
    event_id: NonEmptyStr
    event_kind: NonEmptyStr
    content_hash: Sha256


class EventViewProjection(AcdModel):
    """Display-only projection of an EventLog, reconciled with its source.

    The projection carries no verdict: it exists so that a session view can be
    reproduced from the original EventLog and compared against it.
    """

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["event_view_projection"] = "event_view_projection"
    pass_evidence: Literal[False] = False
    source: Literal["event_log"] = "event_log"
    source_event_count: int = Field(ge=0)
    entries: list[EventViewEntry] = Field(default_factory=list[EventViewEntry])
    canonical_hash: HashOrUnknown = "unknown"

    @model_validator(mode="after")
    def validate_entries(self) -> EventViewProjection:
        if [entry.index for entry in self.entries] != list(range(len(self.entries))):
            raise ValueError("event view indices must be contiguous from zero")
        if len(self.entries) > self.source_event_count:
            raise ValueError("event view must not exceed its source EventLog")
        identifiers = [entry.event_id for entry in self.entries]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("event view entries must be unique")
        return self


class EventViewCheckReport(AcdModel):
    """Result of replaying a tracked event view from its source EventLog."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    pass_evidence: Literal[False] = False
    status: EventViewStatus
    canonical_hash: HashOrUnknown
    reason: NonEmptyStr | None = None


class MemoryContextObservation(AcdModel):
    """Observation of loaded persistent memory, without its text.

    Memory assists the working context only. The observation records where the
    memory came from and its hash so that memory content never becomes an
    input to contract or pass decisions.
    """

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["memory_context_observation"] = "memory_context_observation"
    pass_evidence: Literal[False] = False
    source: Literal["memory_index"] = "memory_index"
    index_paths: list[NonEmptyStr] = Field(default_factory=list[str])
    char_count: int = Field(ge=0)
    context_hash: HashOrUnknown = "unknown"

    @model_validator(mode="after")
    def validate_paths(self) -> MemoryContextObservation:
        if len(self.index_paths) != len(set(self.index_paths)):
            raise ValueError("memory index paths must be unique")
        if (self.char_count == 0) != (self.index_paths == []):
            raise ValueError("memory char count must accompany an index path")
        return self
