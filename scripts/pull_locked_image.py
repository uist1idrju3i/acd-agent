#!/usr/bin/env python3
"""Pull a digest-pinned image from the repository lock with bounded retries."""

from __future__ import annotations

from pathlib import Path

from acd.openhands.pull_image_cli import main as _main


def main(argv: list[str] | None = None) -> int:
    return _main(
        argv,
        default_lock=Path(__file__).resolve().parents[1] / "docker" / "image-digests.json",
    )


if __name__ == "__main__":
    raise SystemExit(main())
