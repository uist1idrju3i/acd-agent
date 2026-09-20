"""Emit the L3 rough-estimate observation for an idea record."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.core.knowledge.idea_dialogue import IdeaDialogueError, load_idea_record
from acd.core.knowledge.idea_estimate import estimate_idea, load_estimate_catalog


def _parser() -> argparse.ArgumentParser:
    """Build the idea-estimate command-line parser."""
    parser = argparse.ArgumentParser(
        description="Estimate cost, power and footprint for an idea record."
    )
    parser.add_argument("--idea", type=Path, required=True, help="idea.json")
    parser.add_argument(
        "--catalog", type=Path, required=True, help="estimate-catalog.json"
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="write JSON here instead of stdout"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Emit the estimate; findings are observations and exit stays 0."""
    args = _parser().parse_args(argv)
    try:
        record = load_idea_record(args.idea)
        catalog = load_estimate_catalog(args.catalog)
        estimate = estimate_idea(record, catalog)
    except (OSError, ValueError, IdeaDialogueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    body = (
        json.dumps(
            estimate.model_dump(mode="json"),
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
    for finding in estimate.findings:
        print(f"finding[{finding.constraint}] {finding.status}: {finding.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
