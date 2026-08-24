"""Run the graph-driven VibeBB design loop."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from acd.core.timestamps import parse_evaluated_at
from acd.pipeline.design_loop import run_design_loop


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path("fixtures/golden-design-1"))
    parser.add_argument("--out-root", type=Path, default=Path("out"))
    parser.add_argument("--order-total", type=Path, required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("plugins/acd/hooks/order-policy.json"),
    )
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--fab-profile", type=Path, default=None)
    parser.add_argument("--fab-profile-id", default=None)
    parser.add_argument("--max-passes", type=int, default=3)
    parser.add_argument("--max-silkscreen-iterations", type=int, default=5)
    parser.add_argument("--run-seconds", type=int, default=15)
    parser.add_argument("--evaluated-at", default=None)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="opt-in content-addressed cache directory for deterministic artifacts",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse only valid matching artifact-cache entries; never restore verdicts",
    )
    parser.add_argument(
        "--jobs",
        type=_positive_int,
        default=min(os.cpu_count() or 1, 3),
        help="maximum parallel board, enclosure, and firmware lanes",
    )
    parser.add_argument(
        "--explore-board",
        "--explore-board-candidates",
        dest="explore_board",
        action="store_true",
        help="explore board candidates after a fail-closed board rejection",
    )
    parser.add_argument(
        "--max-exploration-candidates",
        type=_positive_int,
        default=3,
        help="maximum candidates evaluated in each board exploration round",
    )
    parser.add_argument(
        "--max-exploration-rounds",
        type=_positive_int,
        default=1,
        help="maximum board exploration and loop rerun rounds",
    )
    parser.add_argument(
        "--requirement",
        type=Path,
        default=None,
        help="optional updated requirement record to compile before the loop",
    )
    parser.add_argument(
        "--fixture-spec",
        type=Path,
        default=None,
        help="optional design fixture specification to generate before the loop",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        evaluated_at = (
            parse_evaluated_at(args.evaluated_at) if args.evaluated_at else None
        )
        result: dict[str, Any] = run_design_loop(
            args.fixture,
            args.out_root,
            order_total=args.order_total,
            policy=args.policy,
            repository=args.repository,
            fab_profile=args.fab_profile,
            fab_profile_id=args.fab_profile_id,
            max_passes=args.max_passes,
            max_silkscreen_iterations=args.max_silkscreen_iterations,
            run_seconds=args.run_seconds,
            evaluated_at=evaluated_at,
            cache_dir=args.cache_dir,
            resume=args.resume,
            jobs=args.jobs,
            explore_board=args.explore_board,
            max_exploration_candidates=args.max_exploration_candidates,
            max_exploration_rounds=args.max_exploration_rounds,
            requirement=args.requirement,
            fixture_spec=args.fixture_spec,
        )
    except Exception as exc:
        result = {
            "ok": False,
            "fail_closed": True,
            "pass_evidence": False,
            "failed_stage": "input",
            "failure_reason": f"{type(exc).__name__}: {exc}",
            "results": [],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
