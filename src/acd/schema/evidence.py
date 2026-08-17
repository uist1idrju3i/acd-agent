"""Evidence record for minimal external-tool execution records."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Timestamp,
)
from acd.schema.tool_envelope import ToolEnvelope

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

    def supports_authoritative_pass(self, current_revision: str) -> bool:
        """Return whether this evidence can support an authoritative pass."""
        return (
            self.supports_pass(current_revision)
            and self.envelope.execution_context == "container"
            and self.envelope.container_image_digest not in {None, "unknown"}
        )

    def is_provisional(self) -> bool:
        """Return whether valid evidence lacks authoritative container provenance."""
        return self.supports_pass(self.target_revision) and not self.supports_authoritative_pass(
            self.target_revision
        )
