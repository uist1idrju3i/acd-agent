#!/usr/bin/env python3
"""Record one inspect_image_with_vision response as an L3 observation.

The observation is bound to the visual review manifest by projection_id and
image_hash; a response that does not match the manifest is refused
fail-closed. Observations never become Evidence or pass authority.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.pipeline.visual_review import VisualReviewError, record_observation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-root",
        type=Path,
        required=True,
        help="run output root containing the visual review manifest",
    )
    parser.add_argument("--projection-id", required=True)
    parser.add_argument("--image-hash", required=True)
    parser.add_argument(
        "--profile-name",
        required=True,
        help="name of the LLM profile that produced the vision response",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="model identifier that produced the vision response",
    )
    parser.add_argument(
        "--response-file",
        type=Path,
        required=True,
        help="file containing the full vision response text",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        response = args.response_file.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"FAIL: response file is unreadable: {exc}", file=sys.stderr)
        return 1
    try:
        path = record_observation(
            args.out_root,
            projection_id=args.projection_id,
            image_hash=args.image_hash,
            profile_name=args.profile_name,
            model=args.model,
            response=response,
        )
    except (OSError, ValueError, VisualReviewError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"observation: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
