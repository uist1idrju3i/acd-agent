"""Structured error (mirrors ``schemas/error-taxonomy.schema.json``)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import StringConstraints

from acd_schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
)

ErrorCode = Annotated[str, StringConstraints(pattern=r"^ACD-E[0-9]{3}$")]

ErrorCategory = Literal[
    "input_unknown",
    "version_unknown",
    "hash_mismatch",
    "revision_mismatch",
    "stale",
    "not_converged",
    "invalid_output",
    "tool_missing",
    "external_service",
    "safety_boundary",
    "budget",
    "license",
    "irreversible_operation",
    "internal",
]

ErrorSeverity = Literal["fatal", "error", "warning", "info"]


class AcdError(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    code: ErrorCode
    category: ErrorCategory
    severity: ErrorSeverity
    message: NonEmptyStr
    retriable: bool
    source_tool: str | None = None
    target_revision: Revision | None = None
