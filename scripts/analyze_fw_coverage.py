#!/usr/bin/env python3
"""Evaluate an optional gcovr report against a declared coverage floor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from acd.schema import CoverageFloor

SKILL_SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "plugins/acd/skills/acd-firmware-esp32c3/scripts"
)
sys.path.insert(0, str(SKILL_SCRIPTS))

from fw_coverage import evaluate_coverage, parse_gcovr_json  # noqa: E402


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gcovr-json", type=Path, required=True)
    parser.add_argument("--floor", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        floor = CoverageFloor.model_validate(
            json.loads(args.floor.read_text(encoding="utf-8"))
        )
        report = (
            None
            if not args.gcovr_json.is_file()
            else parse_gcovr_json(args.gcovr_json.read_text(encoding="utf-8"))
        )
        result = evaluate_coverage(report, floor)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2
    _write(args.out, result.model_dump(mode="json"))
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
