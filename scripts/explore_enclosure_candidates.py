"""Run bounded enclosure interference candidate exploration."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from acd.core.enclosure_exploration import (
    DEFAULT_JOBS,
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_SAMPLING_POINTS,
    EnclosureExplorationError,
    explore_enclosure_candidates,
)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _sampling_points(value: str) -> int:
    parsed = _positive_int(value)
    if parsed < 2:
        raise argparse.ArgumentTypeError("sampling-points must be at least 2")
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
        default=Path("out/enclosure-exploration"),
        help="exploration report and candidate output directory",
    )
    parser.add_argument(
        "--max-candidates",
        type=_positive_int,
        default=DEFAULT_MAX_CANDIDATES,
        help="bounded number of candidates to evaluate",
    )
    parser.add_argument(
        "--dimensions",
        nargs="+",
        default=None,
        help="optional searchable mechanical dimension IDs",
    )
    parser.add_argument(
        "--jobs",
        type=_positive_int,
        default=DEFAULT_JOBS,
        help="number of independent candidate evaluations",
    )
    parser.add_argument(
        "--sampling-points",
        type=_sampling_points,
        default=DEFAULT_SAMPLING_POINTS,
        help="number of equally spaced values including both boundaries",
    )
    args = parser.parse_args(argv)
    try:
        result = explore_enclosure_candidates(
            args.graph,
            args.fixture_dir,
            args.out,
            args.max_candidates,
            dimensions=args.dimensions,
            jobs=args.jobs,
            sampling_points=args.sampling_points,
        )
    except (EnclosureExplorationError, OSError, ValueError) as exc:
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
    raise SystemExit(main())
