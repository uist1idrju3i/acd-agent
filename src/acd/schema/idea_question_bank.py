"""Question-bank contract for idea refinement (ADR-0049, roadmap 21.2)."""

from __future__ import annotations

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    SchemaVersion,
)
from acd.schema.idea import IdeaOption


class IdeaQuestionBankEntry(AcdModel):
    """One banked question for an idea field path."""

    field: NonEmptyStr
    priority: int = Field(ge=1)
    prompt: NonEmptyStr
    options: list[IdeaOption] = Field(min_length=1)


class IdeaQuestionBank(AcdModel):
    """A bank of banked questions; one entry per field path."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    bank_id: NonEmptyStr
    entries: list[IdeaQuestionBankEntry] = Field(
        default_factory=list[IdeaQuestionBankEntry]
    )

    @model_validator(mode="after")
    def _unique_fields(self) -> IdeaQuestionBank:
        fields = [entry.field for entry in self.entries]
        if len(set(fields)) != len(fields):
            raise ValueError("entries field values must be unique")
        return self


__all__ = [
    "IdeaQuestionBank",
    "IdeaQuestionBankEntry",
]
