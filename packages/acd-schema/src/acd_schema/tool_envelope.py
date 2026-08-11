"""External tool execution envelope (mirrors ``schemas/tool-envelope.schema.json``)."""

from __future__ import annotations

from typing import Literal

from acd_schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    HashOrUnknown,
    IdempotencyKey,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Timestamp,
    VersionOrUnknown,
)

ConvergenceState = Literal["converged", "not_converged", "not_applicable", "unknown"]


class ToolEnvelope(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    tool_name: NonEmptyStr
    tool_version: VersionOrUnknown
    format_version: VersionOrUnknown
    config_hash: HashOrUnknown
    input_hash: HashOrUnknown
    output_hash: HashOrUnknown
    execution_env: NonEmptyStr
    measurement_conditions: NonEmptyStr
    convergence_state: ConvergenceState
    target_revision: Revision
    started_at: Timestamp
    finished_at: Timestamp
    exit_code: int | None = None
    idempotency_key: IdempotencyKey | None = None
    uncertainty: str | None = None

    def has_unknown(self) -> bool:
        """True when any provenance field is unknown; such envelopes never support pass."""
        return (
            "unknown"
            in {
                self.tool_version,
                self.format_version,
                self.config_hash,
                self.input_hash,
                self.output_hash,
            }
            or self.convergence_state == "unknown"
        )
