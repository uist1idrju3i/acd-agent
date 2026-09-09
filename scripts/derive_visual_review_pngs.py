#!/usr/bin/env python3
"""Derive review PNGs for every visual projection set and write the manifest.

The manifest records which ``inspect_image_with_vision`` observations the agent
must produce before the loop may be reported as done. It is an L3 observation
and carries no pass authority.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.pipeline.visual_review import (
    VISUAL_REVIEW_MANIFEST_NAME,
    VisualReviewError,
    derive_visual_review,
)


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
    parser.add_argument(
        "--out-root",
        type=Path,
        required=True,
        help="run output root containing the visual projection sets",
    )
    parser.add_argument(
        "--jobs",
        type=_positive_int,
        default=min(os.cpu_count() or 1, 4),
        help="maximum parallel projection-set derivations",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = derive_visual_review(args.out_root, jobs=args.jobs)
    except VisualReviewError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    manifest_path = args.out_root / VISUAL_REVIEW_MANIFEST_NAME
    print(f"manifest: {manifest_path}")
    print(f"required: {len(manifest.required)} projection(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
