"""Emit the next prioritized idea questions as an L3 observation."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.core.idea_dialogue import (
    IdeaDialogueError,
    load_dialogue_history,
    load_idea_record,
    next_questions,
)
from acd.schema.idea_question_bank import IdeaQuestionBank


def _parser() -> argparse.ArgumentParser:
    """Build the next-questions command-line parser."""
    parser = argparse.ArgumentParser(
        description="List the next idea questions from the question bank."
    )
    parser.add_argument("--idea", type=Path, required=True, help="idea.json")
    parser.add_argument(
        "--history", type=Path, required=True, help="idea-dialogue.json"
    )
    parser.add_argument(
        "--bank", type=Path, required=True, help="question-bank.json"
    )
    parser.add_argument("--max", type=int, default=3, dest="max_questions")
    parser.add_argument(
        "--out", type=Path, default=None, help="write JSON here instead of stdout"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Emit the next questions; open items are an observation, exit 0."""
    args = _parser().parse_args(argv)
    try:
        record = load_idea_record(args.idea)
        history = load_dialogue_history(args.history)
        if history.idea_id != record.idea_id:
            raise IdeaDialogueError("history idea_id does not match record")
        bank = IdeaQuestionBank.model_validate_json(
            args.bank.read_text(encoding="utf-8")
        )
        questions, uncovered = next_questions(
            record, bank, max_questions=args.max_questions
        )
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    body = {
        "artifact_kind": "idea_questions",
        "record_class": "L3",
        "pass_evidence": False,
        "idea_id": record.idea_id,
        "turn_no": len(history.turns) + 1,
        "questions": [
            question.model_dump(mode="json") for question in questions
        ],
        "uncovered_open_items": uncovered,
    }
    text = (
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    if args.out is None:
        print(text, end="")
    else:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
