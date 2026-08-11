"""Review finding (mirrors ``schemas/review-finding.schema.json``)."""

from __future__ import annotations

from typing import Literal

from acd_schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    HashOrUnknown,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Timestamp,
)

ReviewView = Literal["RV1", "RV2"]
FindingSeverity = Literal["high", "medium", "low"]
Disposition = Literal["open", "fixed", "waived", "assumption", "rejected"]
ProjectionKind = Literal["machine_readable", "visual"]


class ProjectionRef(AcdModel):
    projection_kind: ProjectionKind
    content_hash: HashOrUnknown
    generated_at: Timestamp
    source_revision: Revision


class ReviewFinding(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    finding_id: NonEmptyStr
    review_view: ReviewView
    severity: FindingSeverity
    target_revision: Revision
    projection: ProjectionRef
    description: NonEmptyStr
    disposition: Disposition
    disposition_reason: str | None = None
    disposed_at: Timestamp | None = None

    def blocks_pass(self) -> bool:
        """High-severity findings without a closing disposition block pass verdicts."""
        return self.severity == "high" and self.disposition == "open"
