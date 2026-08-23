#!/usr/bin/env python3
"""Apply a feedback proposal under a declared, bounded policy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.feedback import FeedbackError, apply_input_feedback
from acd.schema import FeedbackApplyPolicy, FeedbackProposal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        proposal = FeedbackProposal.model_validate_json(
            args.proposal.read_text(encoding="utf-8")
        )
        policy = FeedbackApplyPolicy.model_validate_json(
            args.policy.read_text(encoding="utf-8")
        )
        record = apply_input_feedback(
            proposal,
            policy,
            repository=args.repo_root.resolve(),
            dry_run=args.dry_run,
            record_path=args.record,
        )
    except (OSError, TypeError, ValueError, FeedbackError) as exc:
        print(f"feedback application refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
