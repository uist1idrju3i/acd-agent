#!/usr/bin/env python3
"""Run one bounded ACD goal loop whose pass side stays with L1 gates."""

from __future__ import annotations

from acd.openhands.goal_cli import main as _main


def main(argv: list[str] | None = None) -> int:
    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
