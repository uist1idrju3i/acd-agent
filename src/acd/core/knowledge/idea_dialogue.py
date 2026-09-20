"""Idea dialogue operations: load, append turns, and summarize progress."""

from __future__ import annotations

from pathlib import Path

from acd.schema.idea import (
    IdeaAnswer,
    IdeaDialogueHistory,
    IdeaField,
    IdeaFunction,
    IdeaProgress,
    IdeaQuestion,
    IdeaRecord,
    IdeaSuccessCriterion,
    IdeaTurn,
)
from acd.schema.idea_question_bank import IdeaQuestionBank


class IdeaDialogueError(ValueError):
    """Raised when an idea record, history, or turn violates the contract."""


_SCALAR_PATHS = (
    "purpose",
    "target_users",
    "experience",
    "environment",
    "constraints.cost",
    "constraints.dimensions",
    "constraints.power",
    "constraints.communication",
    "constraints.regulatory",
)
_LIST_PATHS = ("success_criteria", "functions")


def load_idea_record(path: Path) -> IdeaRecord:
    """Load an idea record; any parse or validation failure is an error."""
    try:
        return IdeaRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IdeaDialogueError(f"idea record {path} is not valid: {exc}") from exc


def load_dialogue_history(path: Path) -> IdeaDialogueHistory:
    """Load a dialogue history; any parse or validation failure is an error."""
    try:
        return IdeaDialogueHistory.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IdeaDialogueError(f"dialogue history {path} is not valid: {exc}") from exc


def write_idea_record(path: Path, record: IdeaRecord) -> None:
    """Write an idea record as UTF-8 JSON."""
    path.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")


def write_dialogue_history(path: Path, history: IdeaDialogueHistory) -> None:
    """Write a dialogue history as UTF-8 JSON."""
    path.write_text(history.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _scalar_field_map(record: IdeaRecord) -> dict[str, IdeaField]:
    return {
        "purpose": record.purpose,
        "target_users": record.target_users,
        "experience": record.experience,
        "environment": record.environment,
        "constraints.cost": record.constraints.cost,
        "constraints.dimensions": record.constraints.dimensions,
        "constraints.power": record.constraints.power,
        "constraints.communication": record.constraints.communication,
        "constraints.regulatory": record.constraints.regulatory,
    }


def _resolve_field(record: IdeaRecord, path: str) -> IdeaField | None:
    """Return the IdeaField addressed by a dotted path, or None."""
    if path in _SCALAR_PATHS:
        return _scalar_field_map(record)[path]
    if "." in path:
        head, _, item_id = path.partition(".")
        if head == "success_criteria":
            for item in record.success_criteria:
                if item.criterion_id == item_id:
                    return item.statement
            return None
        if head == "functions":
            for item in record.functions:
                if item.function_id == item_id:
                    return item.description
            return None
    return None


def _valid_path(path: str) -> bool:
    if path in _SCALAR_PATHS or path in _LIST_PATHS:
        return True
    head, _, _ = path.partition(".")
    return "." in path and head in _LIST_PATHS


def _confirmed_field(answer: IdeaAnswer, turn: IdeaTurn) -> IdeaField:
    return IdeaField(
        status="confirmed",
        value=answer.value,
        unit=answer.unit,
        sources=list(answer.sources),
        confirmed_at=turn.recorded_at,
    )


def _set_field(record: IdeaRecord, path: str, field: IdeaField) -> IdeaRecord:
    """Return a copy of the record with the addressed field replaced."""
    if "." not in path:
        return record.model_copy(update={path: field})
    head, _, tail = path.partition(".")
    if head == "constraints":
        constraints = record.constraints.model_copy(update={tail: field})
        return record.model_copy(update={"constraints": constraints})
    if head == "success_criteria":
        updated = [
            item.model_copy(update={"statement": field}) if item.criterion_id == tail else item
            for item in record.success_criteria
        ]
        return record.model_copy(update={"success_criteria": updated})
    updated = [
        item.model_copy(update={"description": field}) if item.function_id == tail else item
        for item in record.functions
    ]
    return record.model_copy(update={"functions": updated})


def apply_turn(
    record: IdeaRecord,
    history: IdeaDialogueHistory,
    turn: IdeaTurn,
) -> tuple[IdeaRecord, IdeaDialogueHistory]:
    """Apply one dialogue turn; returns new record and history copies.

    Never mutates the inputs. Unknown paths, re-answering a confirmed field,
    duplicate fields within a turn, a non-append turn number, or an
    idea_id mismatch all fail closed.
    """
    if history.idea_id != record.idea_id:
        raise IdeaDialogueError(
            f"history idea_id {history.idea_id!r} does not match record idea_id {record.idea_id!r}"
        )
    expected_turn = len(history.turns) + 1
    if turn.turn_no != expected_turn:
        raise IdeaDialogueError(f"turn_no {turn.turn_no} is not the next turn {expected_turn}")
    seen: set[str] = set()
    updated = record
    for question in turn.asked:
        if not _valid_path(question.field):
            raise IdeaDialogueError(f"question field {question.field!r} is not an idea field path")
    for answer in turn.answers:
        path = answer.field
        if path in seen:
            raise IdeaDialogueError(f"field {path!r} answered twice in one turn")
        seen.add(path)
        confirmed = _confirmed_field(answer, turn)
        if path == "success_criteria":
            item_id = f"sc-{len(updated.success_criteria) + 1:03d}"
            if any(item.criterion_id == item_id for item in updated.success_criteria):
                raise IdeaDialogueError(f"generated criterion id {item_id!r} already exists")
            updated = updated.model_copy(
                update={
                    "success_criteria": [
                        *updated.success_criteria,
                        IdeaSuccessCriterion(criterion_id=item_id, statement=confirmed),
                    ]
                }
            )
            continue
        if path == "functions":
            item_id = f"fn-{len(updated.functions) + 1:03d}"
            if any(item.function_id == item_id for item in updated.functions):
                raise IdeaDialogueError(f"generated function id {item_id!r} already exists")
            updated = updated.model_copy(
                update={
                    "functions": [
                        *updated.functions,
                        IdeaFunction(function_id=item_id, description=confirmed),
                    ]
                }
            )
            continue
        field = _resolve_field(updated, path)
        if field is None:
            raise IdeaDialogueError(f"answer field {path!r} is not an idea field path")
        if field.status == "confirmed":
            raise IdeaDialogueError(
                f"field {path!r} is already confirmed; re-deciding requires a new idea revision"
            )
        updated = _set_field(updated, path, confirmed)
    new_history = history.model_copy(update={"turns": [*history.turns, turn]})
    return updated, new_history


def progress_summary(record: IdeaRecord, history: IdeaDialogueHistory) -> IdeaProgress:
    """Summarize confirmation progress as an L3 observation."""
    if history.idea_id != record.idea_id:
        raise IdeaDialogueError(
            f"history idea_id {history.idea_id!r} does not match record idea_id {record.idea_id!r}"
        )
    open_items = record.open_items()
    confirmed = record.confirmed_items()
    return IdeaProgress(
        idea_id=record.idea_id,
        revision=record.revision,
        turn_count=len(history.turns),
        confirmed_count=len(confirmed),
        open_count=len(open_items),
        open_items=open_items,
        blocking_unknowns=open_items,
        ready_for_promotion=record.ready_for_promotion(),
    )


def next_questions(
    record: IdeaRecord,
    bank: IdeaQuestionBank,
    *,
    max_questions: int = 3,
) -> tuple[list[IdeaQuestion], list[str]]:
    """Return banked questions for open items plus uncovered open paths.

    Ordering is priority then field path; the result is truncated to
    ``max_questions``. Open items without a bank entry are returned in
    ``uncovered`` so the Skill can report them as human-decision items.
    """
    if max_questions < 1:
        raise IdeaDialogueError("max_questions must be >= 1")
    open_paths = record.open_items()
    open_set = set(open_paths)
    bank_fields = {entry.field for entry in bank.entries}

    def covered(path: str) -> bool:
        if path in bank_fields:
            return True
        head, _, _ = path.partition(".")
        return head in bank_fields and head in _LIST_PATHS

    # Bare list paths match item paths too: a bank entry for
    # "success_criteria" covers "success_criteria.<id>" items as well.
    questions: list[IdeaQuestion] = []
    for entry in sorted(bank.entries, key=lambda e: (e.priority, e.field)):
        matched = any(
            entry.field == path or path.startswith(f"{entry.field}.") for path in open_set
        )
        if matched:
            questions.append(
                IdeaQuestion(
                    field=entry.field,
                    prompt=entry.prompt,
                    priority=entry.priority,
                    options=list(entry.options),
                )
            )
    uncovered = [path for path in open_paths if not covered(path)]
    return questions[:max_questions], uncovered
