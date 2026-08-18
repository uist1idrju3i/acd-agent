"""Resolve and validate the revision declared by a Design Graph."""

from __future__ import annotations

import argparse
from pathlib import Path

from acd.schema.design_graph import DesignGraph


def resolve(paths: list[Path]) -> str | None:
    """Return the sole graph revision, or None for an invalid request."""
    if len(paths) != 1:
        return None
    try:
        return DesignGraph.model_validate_json(
            paths[0].read_text(encoding="utf-8")
        ).revision
    except (OSError, ValueError, TypeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("graph", type=Path, nargs="+")
    args = parser.parse_args()
    revision = resolve(args.graph)
    if revision is None:
        return 2
    print(revision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
