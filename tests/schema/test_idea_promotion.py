"""Contract tests for idea-promotion schema (ADR-0049)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema.idea import IdeaSource
from acd.schema.idea_promotion import (
    IdeaPromotionRationale,
    IdeaPromotionRationaleRecord,
)
from acd.schema.rationale import RejectedAlternative

USER = IdeaSource(kind="user_statement", ref="conversation:evt-0001")


def test_promotion_rationale_requires_user_statement() -> None:
    with pytest.raises(ValidationError):
        IdeaPromotionRationaleRecord(
            requirement_id="r-1",
            justification="j",
            sources=[IdeaSource(kind="design_graph", ref="graph.json")],
            no_alternatives_reason="none",
        )


def test_promotion_rationale_requires_exactly_one_alternatives_form() -> None:
    with pytest.raises(ValidationError):
        IdeaPromotionRationaleRecord(
            requirement_id="r-1",
            justification="j",
            sources=[USER],
        )
    with pytest.raises(ValidationError):
        IdeaPromotionRationaleRecord(
            requirement_id="r-1",
            justification="j",
            sources=[USER],
            rejected_alternatives=[
                RejectedAlternative(option="a", reason="r")
            ],
            no_alternatives_reason="none",
        )


def test_promotion_rationale_rejects_duplicate_requirement_ids() -> None:
    record = IdeaPromotionRationaleRecord(
        requirement_id="r-1",
        justification="j",
        sources=[USER],
        no_alternatives_reason="none",
    )
    with pytest.raises(ValidationError):
        IdeaPromotionRationale(
            idea_id="idea.x", revision="r1", records=[record, record]
        )
