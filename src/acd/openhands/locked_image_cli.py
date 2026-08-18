"""Print a digest-pinned image reference from the packaged image lock."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from acd.openhands.image_lock import load_image_lock, pinned_reference


def main(
    argv: list[str] | None = None,
    *,
    default_lock: Path | None = None,
) -> int:
    """Print a locked image reference, or return exit code 2 on lock errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry", choices=("acd-tools", "acd-server"), required=True)
    parser.add_argument("--lock", type=Path)
    args = parser.parse_args(argv)

    try:
        lock = load_image_lock(args.lock if args.lock is not None else default_lock)
        entries = {"acd-tools": lock.acd_tools, "acd-server": lock.acd_server}
        entry = entries[args.entry]
        if entry is None:
            raise ValueError(f"image lock entry is unset: {args.entry}")
        print(pinned_reference(entry))
    except (OSError, ValueError, TypeError) as exc:
        print(f"image lock error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
