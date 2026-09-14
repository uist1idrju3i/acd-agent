"""Promote a fully-confirmed idea record to requirement records."""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.core.idea_dialogue import IdeaDialogueError, load_idea_record
from acd.core.idea_promotion import (
    IdeaPromotionError,
    load_promotion_rationale,
    promote_idea,
)


def _parser() -> argparse.ArgumentParser:
    """Build the idea-promotion command-line parser."""
    parser = argparse.ArgumentParser(
        description="Promote a confirmed idea record into requirements.json."
    )
    parser.add_argument("--idea", type=Path, required=True, help="idea.json")
    parser.add_argument(
        "--rationale",
        type=Path,
        required=True,
        help="promotion-rationale.json",
    )
    parser.add_argument("--graph-id", required=True, help="target graph id")
    parser.add_argument("--revision", required=True, help="target revision")
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="directory receiving requirements.json and the provenance record",
    )
    return parser


def _script_hash() -> str:
    digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return f"sha256:{digest}"


def main(argv: Sequence[str] | None = None) -> int:
    """Promote the idea; promotion errors exit 1 with nothing written."""
    args = _parser().parse_args(argv)
    try:
        record = load_idea_record(args.idea)
        rationale = load_promotion_rationale(args.rationale)
        document, provenance = promote_idea(
            record,
            rationale,
            graph_id=args.graph_id,
            revision=args.revision,
            script_hash=_script_hash(),
        )
    except (OSError, ValueError, IdeaDialogueError, IdeaPromotionError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    requirements_path = args.out_dir / "requirements.json"
    provenance_path = args.out_dir / "idea-promotion-provenance.json"
    requirements_path.write_text(
        document.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    provenance_path.write_text(
        provenance.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {requirements_path}")
    print(f"wrote {provenance_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
