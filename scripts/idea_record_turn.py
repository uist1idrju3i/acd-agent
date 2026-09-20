"""Apply one idea-dialogue turn and print the updated progress."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.core.knowledge.idea_dialogue import (
    apply_turn,
    load_dialogue_history,
    load_idea_record,
    progress_summary,
    write_dialogue_history,
    write_idea_record,
)
from acd.schema.idea import IdeaTurn


def _parser() -> argparse.ArgumentParser:
    """Build the record-turn command-line parser."""
    parser = argparse.ArgumentParser(
        description="Apply one idea dialogue turn to the record and history."
    )
    parser.add_argument("--idea", type=Path, required=True, help="idea.json")
    parser.add_argument(
        "--history", type=Path, required=True, help="idea-dialogue.json"
    )
    parser.add_argument(
        "--turn", type=Path, required=True, help="turn JSON file"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Apply the turn; on failure nothing is rewritten and exit is 1."""
    args = _parser().parse_args(argv)
    try:
        record = load_idea_record(args.idea)
        history = load_dialogue_history(args.history)
        turn = IdeaTurn.model_validate_json(
            args.turn.read_text(encoding="utf-8")
        )
        updated, new_history = apply_turn(record, history, turn)
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    write_idea_record(args.idea, updated)
    write_dialogue_history(args.history, new_history)
    progress = progress_summary(updated, new_history)
    print(
        json.dumps(
            progress.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
