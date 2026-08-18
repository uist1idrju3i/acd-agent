"""Run a deterministic ACD command in an OpenHands Docker workspace."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.openhands.workspace import (
    DEFAULT_COMMAND,
    DEFAULT_DOWNLOAD_FILES,
    run_command_in_workspace,
)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        default=os.getenv("ACD_CONTAINER_IMAGE"),
        help="Docker image reference (or set ACD_CONTAINER_IMAGE).",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--download",
        dest="download_files",
        action="append",
        metavar="PATH",
        help="Evidence-relative file to download after a successful run.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.image:
        parser.error("--image or ACD_CONTAINER_IMAGE is required")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    command = " ".join(args.command).strip() or DEFAULT_COMMAND
    download_files = tuple(args.download_files or DEFAULT_DOWNLOAD_FILES)
    try:
        result = run_command_in_workspace(
            image=args.image,
            command=command,
            repository=args.repo,
            download_files=download_files,
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
    for path in result.downloaded_files:
        print(f"downloaded: {path}")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
