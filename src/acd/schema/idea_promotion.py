"""Idea-to-requirement promotion contracts (ADR-0049, roadmap 21.5)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
)
from acd.schema.idea import IdeaSource
from acd.schema.rationale import RejectedAlternative


class IdeaPromotionRationaleRecord(AcdModel):
    """Rationale for one promoted requirement; mirrors RationaleRecord rules."""

    requirement_id: NonEmptyStr
    justification: NonEmptyStr
    sources: list[IdeaSource] = Field(min_length=1)
    rejected_alternatives: list[RejectedAlternative] = Field(
        default_factory=list[RejectedAlternative]
    )
    no_alternatives_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _validate(self) -> IdeaPromotionRationaleRecord:
        if not any(
            source.kind == "user_statement" for source in self.sources
        ):
            raise ValueError("promotion rationale requires a user_statement source")
        if bool(self.rejected_alternatives) == (
            self.no_alternatives_reason is not None
        ):
            raise ValueError(
                "exactly one of rejected_alternatives and "
                "no_alternatives_reason is required"
            )
        return self


class IdeaPromotionRationale(AcdModel):
    """Rationale document for promoting one idea record."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    idea_id: NodeId
    revision: Revision
    records: list[IdeaPromotionRationaleRecord] = Field(
        default_factory=list[IdeaPromotionRationaleRecord]
    )

    @model_validator(mode="after")
    def _unique_requirement_ids(self) -> IdeaPromotionRationale:
        ids = [record.requirement_id for record in self.records]
        if len(set(ids)) != len(ids):
            raise ValueError("records requirement_id entries must be unique")
        return self


class IdeaPromotionProvenance(AcdModel):
    """Provenance of a promotion run; L3, never approval evidence."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["idea_promotion"] = "idea_promotion"
    record_class: Literal["L3"] = "L3"
    pass_evidence: Literal[False] = False
    idea_id: NodeId
    idea_revision: Revision
    graph_id: NonEmptyStr
    target_revision: Revision
    idea_hash: Sha256
    rationale_hash: Sha256
    script_hash: Sha256
    requirement_ids: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


__all__ = [
    "IdeaPromotionProvenance",
    "IdeaPromotionRationale",
    "IdeaPromotionRationaleRecord",
]
