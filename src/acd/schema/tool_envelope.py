"""External tool execution envelope."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from acd.schema.common import (
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

ConvergenceState = Literal[
    "converged", "not_converged", "not_applicable", "unknown", "timed_out"
]


class ToolEnvelope(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    tool_name: NonEmptyStr
    tool_version: VersionOrUnknown
    format_version: VersionOrUnknown
    config_hash: HashOrUnknown
    input_hash: HashOrUnknown
    output_hash: HashOrUnknown
    execution_env: NonEmptyStr
    execution_context: Literal["container", "host", "unknown"]
    container_image_digest: HashOrUnknown | None = None
    measurement_conditions: NonEmptyStr
    convergence_state: ConvergenceState
    target_revision: Revision
    started_at: Timestamp
    finished_at: Timestamp
    exit_code: int | None = None
    idempotency_key: IdempotencyKey | None = None
    uncertainty: str | None = None

    @model_validator(mode="after")
    def validate_execution_provenance(self) -> ToolEnvelope:
        if self.execution_context == "container" and self.container_image_digest is None:
            raise ValueError("container execution requires container_image_digest")
        if self.execution_context == "host" and self.container_image_digest is not None:
            raise ValueError("host execution cannot have container_image_digest")
        if (
            self.execution_context == "unknown"
            and self.container_image_digest not in {None, "unknown"}
        ):
            raise ValueError("unknown execution context requires unknown or no digest")
        return self

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
            or self.execution_context == "unknown"
            or self.container_image_digest == "unknown"
        )
