"""Contracts for deterministic order-execution dry-run output."""

from __future__ import annotations

from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
    canonical_json_sha256,
    contains_unknown,
)
from acd.schema.quote import QuoteAmount

DryRunExecutionMode = Literal["dry_run"]


class DryRunOrderPayload(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    execution_mode: DryRunExecutionMode = "dry_run"
    authorization_hash: Sha256
    target_revision: Revision
    package_hash: Sha256
    destination: NonEmptyStr
    total: QuoteAmount

    @field_validator("destination")
    @classmethod
    def validate_destination(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
        except ValueError as exc:
            raise ValueError("dry-run destination is invalid") from exc
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("dry-run destination must not contain credentials")
        if "@" in parsed.netloc:
            raise ValueError("dry-run destination must not contain credentials")
        return value

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        if contains_unknown(self.model_dump(mode="json")):
            raise ValueError("dry-run payload must not contain unknown")
        return self


def dry_run_payload_hash(payload: DryRunOrderPayload) -> Sha256:
    """Return the canonical hash of a dry-run payload."""
    return canonical_json_sha256(payload.model_dump(mode="json"))


__all__ = [
    "DryRunExecutionMode",
    "DryRunOrderPayload",
    "dry_run_payload_hash",
]
