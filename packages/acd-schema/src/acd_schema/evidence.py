"""Evidence record (mirrors ``schemas/evidence.schema.json``)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from acd_schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Timestamp,
)
from acd_schema.tool_envelope import ToolEnvelope

EvidenceStatus = Literal["valid", "stale", "invalidated", "unknown"]


class EvidenceClaim(AcdModel):
    subject_node: NodeId
    property: NonEmptyStr
    value: str | float | int | bool
    verified: bool


class Evidence(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    evidence_id: NonEmptyStr
    target_revision: Revision
    status: EvidenceStatus
    envelope: ToolEnvelope
    claims: list[EvidenceClaim] = Field(default_factory=list[EvidenceClaim])
    created_at: Timestamp

    def supports_pass(self, current_revision: str) -> bool:
        """Only valid, revision-matched, fully-known evidence supports a pass verdict."""
        return (
            self.status == "valid"
            and self.target_revision == current_revision
            and self.envelope.target_revision == current_revision
            and not self.envelope.has_unknown()
        )
