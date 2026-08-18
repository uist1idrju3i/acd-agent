"""Contracts for structured, secret-free ACD observation log records."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    SchemaVersion,
    Sha256,
)
from acd.schema.observation import ObservationArtifactKind

ObservationLogEvent = Literal["acd.observation.write"]


class ObservationLogRecord(AcdModel):
    """One structured log record describing a stored L3 observation.

    The record names the observation and its canonical hash only. Payload
    values are withheld by construction so that neither secret material nor
    evidence content can reach the log stream.
    """

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["observation_log_record"] = "observation_log_record"
    pass_evidence: Literal[False] = False
    event: ObservationLogEvent = "acd.observation.write"
    logger_name: NonEmptyStr
    observation_kind: ObservationArtifactKind
    store_path: NonEmptyStr
    payload_hash: Sha256
    payload_bytes: int = Field(ge=1)
    payload_fields: list[NonEmptyStr] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_record(self) -> ObservationLogRecord:
        if len(self.payload_fields) != len(set(self.payload_fields)):
            raise ValueError("observation log payload fields must be unique")
        if self.payload_fields != sorted(self.payload_fields):
            raise ValueError("observation log payload fields must be sorted")
        if "unknown" in self.payload_fields:
            raise ValueError("observation log payload fields must not be unknown")
        parts = self.store_path.split("/")
        if self.store_path.startswith("/") or ".." in parts:
            raise ValueError("observation log store path must be relative")
        return self
