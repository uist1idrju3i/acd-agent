"""Tests for idea dialogue turn application and progress observation."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from acd.core.idea_dialogue import (
    IdeaDialogueError,
    apply_turn,
    load_dialogue_history,
    load_idea_record,
    progress_summary,
    write_idea_record,
)
from acd.schema.idea import (
    IdeaAnswer,
    IdeaField,
    IdeaFunction,
    IdeaSource,
    IdeaSuccessCriterion,
    IdeaTurn,
)

REPOSITORY = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPOSITORY / "fixtures" / "idea" / "sample-usb-thermometer"
RECORDED_AT = datetime(2026, 9, 13, 11, 0, 0, tzinfo=UTC)


def _source(ref: str = "conversation:evt-0003") -> IdeaSource:
    return IdeaSource(kind="user_statement", ref=ref)


def _answer(field: str, value: str | float, unit: str | None = None) -> IdeaAnswer:
    return IdeaAnswer(field=field, value=value, unit=unit, sources=[_source()])


def _turn(answers: list[IdeaAnswer], turn_no: int = 2) -> IdeaTurn:
    return IdeaTurn(turn_no=turn_no, answers=answers, recorded_at=RECORDED_AT)


def test_fixture_loads() -> None:
    record = load_idea_record(FIXTURE_DIR / "idea.json")
    history = load_dialogue_history(FIXTURE_DIR / "idea-dialogue.json")
    assert record.idea_id == "idea.sample-usb-thermometer"
    assert len(history.turns) == 1
    assert "constraints.cost" in record.open_items()
    assert "purpose" in record.confirmed_items()
    assert "functions.fn-measure-temp" in record.confirmed_items()
    assert "functions.fn-stream-usb" in record.open_items()


def test_apply_turn_confirms_scalar_and_appends_history() -> None:
    record = load_idea_record(FIXTURE_DIR / "idea.json")
    history = load_dialogue_history(FIXTURE_DIR / "idea-dialogue.json")
    updated, new_history = apply_turn(
        record,
        history,
        _turn([_answer("constraints.cost", 3000, unit="JPY")]),
    )
    assert updated.constraints.cost.status == "confirmed"
    assert updated.constraints.cost.value == 3000
    assert updated.constraints.cost.unit == "JPY"
    assert "constraints.cost" not in updated.open_items()
    assert len(new_history.turns) == 2
    assert new_history.turns[1].turn_no == 2
    # inputs are never mutated
    assert record.constraints.cost.status == "open"
    assert len(history.turns) == 1


def test_apply_turn_rejects_unknown_path() -> None:
    record = load_idea_record(FIXTURE_DIR / "idea.json")
    history = load_dialogue_history(FIXTURE_DIR / "idea-dialogue.json")
    with pytest.raises(IdeaDialogueError, match="not an idea field path"):
        apply_turn(record, history, _turn([_answer("constraints.weight", 1)]))


def test_apply_turn_rejects_reanswer_of_confirmed_field() -> None:
    record = load_idea_record(FIXTURE_DIR / "idea.json")
    history = load_dialogue_history(FIXTURE_DIR / "idea-dialogue.json")
    with pytest.raises(IdeaDialogueError, match="already confirmed"):
        apply_turn(record, history, _turn([_answer("purpose", "other")]))


def test_apply_turn_rejects_wrong_turn_number() -> None:
    record = load_idea_record(FIXTURE_DIR / "idea.json")
    history = load_dialogue_history(FIXTURE_DIR / "idea-dialogue.json")
    with pytest.raises(IdeaDialogueError, match="turn_no"):
        apply_turn(
            record, history, _turn([_answer("constraints.cost", 1)], turn_no=5)
        )


def test_apply_turn_rejects_idea_id_mismatch() -> None:
    record = load_idea_record(FIXTURE_DIR / "idea.json")
    history = load_dialogue_history(
        FIXTURE_DIR / "idea-dialogue.json"
    ).model_copy(update={"idea_id": "idea.other"})
    with pytest.raises(IdeaDialogueError, match="idea_id"):
        apply_turn(record, history, _turn([_answer("constraints.cost", 1)]))


def test_apply_turn_rejects_duplicate_field_in_one_turn() -> None:
    record = load_idea_record(FIXTURE_DIR / "idea.json")
    history = load_dialogue_history(FIXTURE_DIR / "idea-dialogue.json")
    turn = _turn(
        [
            _answer("constraints.cost", 1),
            _answer("constraints.cost", 2),
        ]
    )
    with pytest.raises(IdeaDialogueError, match="twice"):
        apply_turn(record, history, turn)


def test_bare_list_path_appends_sc_001() -> None:
    record = load_idea_record(FIXTURE_DIR / "idea.json")
    history = load_dialogue_history(FIXTURE_DIR / "idea-dialogue.json")
    updated, _ = apply_turn(
        record,
        history,
        _turn([_answer("success_criteria", "連続1時間の記録が壊れない")]),
    )
    assert [item.criterion_id for item in updated.success_criteria] == ["sc-001"]
    assert updated.success_criteria[0].statement.status == "confirmed"


def test_progress_summary_counts_and_ready_flag() -> None:
    record = load_idea_record(FIXTURE_DIR / "idea.json")
    history = load_dialogue_history(FIXTURE_DIR / "idea-dialogue.json")
    progress = progress_summary(record, history)
    assert progress.turn_count == 1
    assert progress.record_class == "L3"
    assert progress.pass_evidence is False
    assert progress.ready_for_promotion is False
    assert progress.blocking_unknowns == progress.open_items
    assert progress.confirmed_count + progress.open_count == len(
        record.confirmed_items()
    ) + len(record.open_items())

    confirmed = IdeaField(
        status="confirmed",
        value="v",
        sources=[_source()],
        confirmed_at=RECORDED_AT,
    )
    full = record.model_copy(
        update={
            "purpose": confirmed,
            "target_users": confirmed,
            "experience": confirmed,
            "environment": confirmed,
            "constraints": record.constraints.model_copy(
                update={
                    "cost": confirmed,
                    "dimensions": confirmed,
                    "power": confirmed,
                    "communication": confirmed,
                    "regulatory": confirmed,
                }
            ),
            "success_criteria": [
                IdeaSuccessCriterion(criterion_id="sc-001", statement=confirmed)
            ],
            "functions": [
                IdeaFunction(function_id="fn-001", description=confirmed)
            ],
        }
    )
    full_progress = progress_summary(full, history)
    assert full_progress.open_count == 0
    assert full_progress.ready_for_promotion is True


def test_roundtrip_write_is_deterministic(tmp_path: Path) -> None:
    record = load_idea_record(FIXTURE_DIR / "idea.json")
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    write_idea_record(first, record)
    write_idea_record(second, record)
    assert first.read_bytes() == second.read_bytes()


def test_cli_writes_progress_json_and_exits_zero(tmp_path: Path) -> None:
    out = tmp_path / "progress.json"
    result = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY / "scripts" / "idea_progress.py"),
            "--idea",
            str(FIXTURE_DIR / "idea.json"),
            "--history",
            str(FIXTURE_DIR / "idea-dialogue.json"),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    progress = json.loads(out.read_text(encoding="utf-8"))
    assert progress["artifact_kind"] == "idea_progress"
    assert progress["pass_evidence"] is False
    assert progress["ready_for_promotion"] is False


def test_cli_fails_on_missing_input(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY / "scripts" / "idea_progress.py"),
            "--idea",
            str(tmp_path / "missing.json"),
            "--history",
            str(FIXTURE_DIR / "idea-dialogue.json"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 1
    assert "FAIL" in result.stderr
