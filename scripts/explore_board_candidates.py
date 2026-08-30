"""Run a bounded placement and GPIO candidate exploration loop."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.adapters.freerouting.router import DEFAULT_ROUTER_MAX_PASSES
from acd.core.exploration import (
    ExplorationError,
    explore_board_candidates,
)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--graph",
        type=Path,
        default=Path("fixtures/golden-design-1/graph.json"),
        help="source design graph JSON",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=Path("fixtures/golden-design-1"),
        help="source fixture directory",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out/exploration"),
        help="exploration report and candidate output directory",
    )
    parser.add_argument(
        "--max-candidates",
        type=_positive_int,
        default=8,
        help="bounded number of candidates to evaluate",
    )
    parser.add_argument(
        "--max-passes",
        type=_positive_int,
        default=DEFAULT_ROUTER_MAX_PASSES,
        help="bounded router pass budget per candidate",
    )
    parser.add_argument("--dry-run", action="store_true", help="do not write a confirmed winner")
    args = parser.parse_args(argv)
    try:
        result = explore_board_candidates(
            args.graph,
            args.fixture_dir,
            args.out,
            args.max_candidates,
            max_passes=args.max_passes,
            dry_run=args.dry_run,
        )
    except (ExplorationError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "fail_closed": True,
                    "failure_reason": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "fail_closed": False,
                "report_path": str(result.report_path),
                "status": result.report["status"],
                "pass_evidence": result.report["pass_evidence"],
                "winner_candidate_id": result.report["winner_candidate_id"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
