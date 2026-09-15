#!/usr/bin/env python3
"""Create the deterministic synthetic component STEP fixture."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
from typing import Any


def make_fixture(out: Path) -> None:
    build123d: Any = importlib.import_module("build123d")

    board = build123d.Pos(0, 0, 3.8) * build123d.Box(30.0, 25.0, 1.6)
    u1 = build123d.Pos(0.0, 0.5, 5.8) * build123d.Box(10.0, 12.0, 2.4)
    j1 = build123d.Pos(0.0, -7.5, 6.2) * build123d.Box(8.0, 6.0, 3.2)
    out.parent.mkdir(parents=True, exist_ok=True)
    build123d.export_step(
        build123d.Compound([board, u1, j1]),
        out,
        timestamp="2020-01-01T00:00:00",
    )
    out.write_bytes(b"\n".join(line.rstrip() for line in out.read_bytes().split(b"\n")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    make_fixture(args.out)
    print(f"WROTE {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
