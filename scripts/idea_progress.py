"""Print or write the L3 idea-progress observation for an idea record."""

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
    progress_summary,
)


def _parser() -> argparse.ArgumentParser:
    """Build the idea-progress command-line parser."""
    parser = argparse.ArgumentParser(
        description="Summarize idea confirmation progress (L3 observation)."
    )
    parser.add_argument(
        "--idea",
        type=Path,
        required=True,
        help="path to idea.json",
    )
    parser.add_argument(
        "--history",
        type=Path,
        required=True,
        help="path to idea-dialogue.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the progress JSON here instead of printing",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Emit the idea-progress JSON; open items still exit 0."""
    args = _parser().parse_args(argv)
    try:
        record = load_idea_record(args.idea)
        history = load_dialogue_history(args.history)
        progress = progress_summary(record, history)
    except IdeaDialogueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    body = (
        json.dumps(
            progress.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if args.out is None:
        print(body, end="")
    else:
        args.out.write_text(body, encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
