"""Run a deterministic ACD command in an OpenHands Docker workspace."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.openhands.workspace import DEFAULT_COMMAND, run_command_in_workspace


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        default=os.getenv("ACD_CONTAINER_IMAGE"),
        help="Docker image reference (or set ACD_CONTAINER_IMAGE).",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.image:
        parser.error("--image or ACD_CONTAINER_IMAGE is required")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    command = " ".join(args.command).strip() or DEFAULT_COMMAND
    try:
        result = run_command_in_workspace(
            image=args.image,
            command=command,
            repository=args.repo,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"image digest: {result.digest} ({result.source})")
    print(f"exit code: {result.exit_code}")
    print("stdout:")
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    print("stderr:")
    print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    for relative in ("out", "evidence"):
        path = args.repo / relative
        if path.exists():
            print(f"generated {relative}: {path}")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
