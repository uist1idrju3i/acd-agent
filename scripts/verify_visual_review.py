#!/usr/bin/env python3
"""Verify that every manifest requirement has a matching vision observation.

The verdict is an L3 observation: a ``complete`` status never grants pass
authority and never changes gates or Evidence.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from acd.pipeline.visual_review import verify_visual_review


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-root",
        type=Path,
        required=True,
        help="run output root containing the visual review manifest",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    verdict = verify_visual_review(args.out_root)
    for item in verdict.items:
        print(f"{item.projection_id}: {item.status.upper()}")
    for problem in verdict.problems:
        print(f"problem: {problem}")
    print(
        f"visual review: {verdict.status} "
        f"({verdict.observed}/{verdict.required} observed)"
    )
    return 0 if verdict.status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
