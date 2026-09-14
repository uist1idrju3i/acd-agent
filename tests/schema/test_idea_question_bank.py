"""Contract tests for the idea question bank (ADR-0049)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from acd.schema.idea import IdeaOption, IdeaSource
from acd.schema.idea_question_bank import (
    IdeaQuestionBank,
    IdeaQuestionBankEntry,
)

REPOSITORY = Path(__file__).resolve().parents[2]
BANK_PATH = (
    REPOSITORY
    / "plugins"
    / "acd"
    / "skills"
    / "acd-ideate"
    / "question-bank.json"
)

OPTION = IdeaOption(
    label="a",
    tradeoff="t",
    sources=[IdeaSource(kind="design_example", ref="fixtures")],
)


def test_bank_requires_unique_fields_and_options() -> None:
    entry = IdeaQuestionBankEntry(
        field="purpose", priority=1, prompt="p", options=[OPTION]
    )
    with pytest.raises(ValidationError):
        IdeaQuestionBank(bank_id="b", entries=[entry, entry])
    with pytest.raises(ValidationError):
        IdeaQuestionBankEntry(field="purpose", priority=1, prompt="p", options=[])
    with pytest.raises(ValidationError):
        IdeaQuestionBankEntry(
            field="purpose", priority=0, prompt="p", options=[OPTION]
        )


def test_shipped_bank_covers_every_scalar_and_list_path() -> None:
    bank = IdeaQuestionBank.model_validate_json(
        BANK_PATH.read_text(encoding="utf-8")
    )
    fields = {entry.field for entry in bank.entries}
    expected = {
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
    }
    assert expected <= fields
