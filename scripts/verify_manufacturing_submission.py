#!/usr/bin/env python3
"""Verify the independent L1 manufacturing-submission verdict."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.core.manufacturing_submission import (
    ManufacturingSubmissionError,
    evaluate_manufacturing_submission,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-out", required=True, type=Path)
    parser.add_argument("--enclosure-out", required=True, type=Path)
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--require-authoritative", action="store_true")
    args = parser.parse_args(argv)
    try:
        verdict = evaluate_manufacturing_submission(
            board_dir=args.board_out,
            enclosure_dir=args.enclosure_out,
            graph_path=args.graph,
            require_authoritative=args.require_authoritative,
        )
    except ManufacturingSubmissionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(verdict.model_dump_json(indent=2) + "\n", encoding="utf-8")
    for check in verdict.checks:
        print(f"{check.status.upper()}: {check.check_id}: {check.detail}")
    return 0 if verdict.status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
