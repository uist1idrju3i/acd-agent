"""Contracts for non-authoritative design knowledge answers.

An answer restates values that already exist in the indexed knowledge sources
and cites where each statement came from. Answers are L2 steering or L3
observations: they cannot approve a design, they never become design inputs, and
a question that cannot be answered from the indexed sources is answered with
``unknown`` and a reason instead of an estimate.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
)
from acd.schema.knowledge_index import KnowledgeAudience, KnowledgeSourceKind

KnowledgeCategory = Literal[
    "product_spec",
    "usage",
    "troubleshooting",
    "design_rationale",
    "history",
    "unknown",
]
KnowledgeAnswerStatus = Literal["answered", "unknown"]


class KnowledgeCitation(AcdModel):
    """The source a single answer statement was taken from."""

    kind: KnowledgeSourceKind
    reference: NonEmptyStr
    locator: NonEmptyStr | None = None


class KnowledgeAnswer(AcdModel):
    """One answered or explicitly unknown question."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    question: NonEmptyStr
    category: KnowledgeCategory
    audience: KnowledgeAudience
    graph_id: NonEmptyStr
    target_revision: Revision
    status: KnowledgeAnswerStatus
    statements: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    citations: list[KnowledgeCitation] = Field(default_factory=list[KnowledgeCitation])
    reason: NonEmptyStr | None = None
    pass_evidence: Literal[False] = False

    @model_validator(mode="after")
    def _validate_answer(self) -> KnowledgeAnswer:
        if self.status == "unknown":
            if self.reason is None:
                raise ValueError("unknown answer requires a reason")
            if self.statements:
                raise ValueError("unknown answer cannot carry statements")
            return self
        if self.reason is not None:
            raise ValueError("answered question cannot carry a reason")
        if self.category == "unknown":
            raise ValueError("answered question requires a known category")
        if not self.statements:
            raise ValueError("answered question requires at least one statement")
        if not self.citations:
            raise ValueError("answered question requires at least one citation")
        return self
