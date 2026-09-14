"""Contract tests for the idea record schema (ADR-0049)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from acd.schema.idea import (
    IdeaAnswer,
    IdeaDialogueHistory,
    IdeaField,
    IdeaFunction,
    IdeaOption,
    IdeaQuestion,
    IdeaRecord,
    IdeaSource,
    IdeaSuccessCriterion,
    IdeaTurn,
)

USER_SOURCE = IdeaSource(kind="user_statement", ref="conversation:evt-0001")
CONFIRMED_AT = datetime(2026, 9, 13, 10, 0, 0, tzinfo=UTC)


def _record() -> IdeaRecord:
    return IdeaRecord(
        idea_id="idea.sample",
        revision="r1",
        title="sample",
    )


def test_confirmed_field_requires_user_statement_source() -> None:
    with pytest.raises(ValidationError):
        IdeaField(
            status="confirmed",
            value="x",
            confirmed_at=CONFIRMED_AT,
            sources=[IdeaSource(kind="design_graph", ref="graph.json")],
        )


def test_confirmed_field_requires_value_and_timestamp() -> None:
    with pytest.raises(ValidationError):
        IdeaField(
            status="confirmed",
            confirmed_at=CONFIRMED_AT,
            sources=[USER_SOURCE],
        )
    with pytest.raises(ValidationError):
        IdeaField(status="confirmed", value="x", sources=[USER_SOURCE])


def test_open_field_rejects_value_and_timestamp() -> None:
    with pytest.raises(ValidationError):
        IdeaField(status="open", value="x")
    with pytest.raises(ValidationError):
        IdeaField(status="open", confirmed_at=CONFIRMED_AT)


def test_open_field_may_carry_steering_sources() -> None:
    field = IdeaField(
        status="open",
        sources=[IdeaSource(kind="fab_profile", ref="profiles#jlcpcb")],
    )
    assert field.status == "open"


def test_duplicate_criterion_ids_fail() -> None:
    with pytest.raises(ValidationError):
        IdeaRecord(
            idea_id="idea.sample",
            revision="r1",
            title="t",
            success_criteria=[
                IdeaSuccessCriterion(criterion_id="sc-001"),
                IdeaSuccessCriterion(criterion_id="sc-001"),
            ],
        )


def test_duplicate_function_ids_fail() -> None:
    with pytest.raises(ValidationError):
        IdeaRecord(
            idea_id="idea.sample",
            revision="r1",
            title="t",
            functions=[
                IdeaFunction(function_id="fn-001"),
                IdeaFunction(function_id="fn-001"),
            ],
        )


def test_question_rejects_two_recommended_options() -> None:
    option = IdeaOption(
        label="a",
        tradeoff="t",
        recommended=True,
        sources=[USER_SOURCE],
    )
    other = option.model_copy(update={"label": "b"})
    with pytest.raises(ValidationError):
        IdeaQuestion(field="purpose", prompt="p", priority=1, options=[option, other])


def test_answer_requires_user_statement_source() -> None:
    with pytest.raises(ValidationError):
        IdeaAnswer(
            field="purpose",
            value="x",
            sources=[IdeaSource(kind="evidence", ref="evidence.json")],
        )


def test_history_requires_contiguous_turn_numbers() -> None:
    turn = IdeaTurn(turn_no=2, recorded_at=CONFIRMED_AT)
    with pytest.raises(ValidationError):
        IdeaDialogueHistory(idea_id="idea.sample", turns=[turn])


def test_open_items_ordering_and_list_sentinels() -> None:
    record = _record()
    assert record.open_items() == [
        "purpose",
        "target_users",
        "experience",
        "environment",
        "constraints.cost",
        "constraints.dimensions",
        "constraints.power",
        "constraints.communication",
        "constraints.regulatory",
        "success_criteria",
        "functions",
    ]
    confirmed = IdeaField(
        status="confirmed",
        value="v",
        sources=[USER_SOURCE],
        confirmed_at=CONFIRMED_AT,
    )
    filled = record.model_copy(
        update={
            "purpose": confirmed,
            "success_criteria": [
                IdeaSuccessCriterion(criterion_id="sc-001", statement=confirmed)
            ],
        }
    )
    assert filled.open_items() == [
        "target_users",
        "experience",
        "environment",
        "constraints.cost",
        "constraints.dimensions",
        "constraints.power",
        "constraints.communication",
        "constraints.regulatory",
        "functions",
    ]
    assert filled.confirmed_items() == ["purpose", "success_criteria.sc-001"]
    assert not filled.ready_for_promotion()
