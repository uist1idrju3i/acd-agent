#!/usr/bin/env python3
"""Print a digest-pinned image reference from the repository lock."""

from __future__ import annotations

from pathlib import Path

from acd.openhands.locked_image_cli import main as _main


def main(argv: list[str] | None = None) -> int:
    return _main(
        argv,
        default_lock=Path(__file__).resolve().parents[1] / "docker" / "image-digests.json",
    )


if __name__ == "__main__":
    raise SystemExit(main())
