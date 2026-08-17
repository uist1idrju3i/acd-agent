"""Check whether canonical evidence supports a pass verdict."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acd_schema import Evidence


def _paths(value: Path) -> list[Path]:
    if value.is_file():
        return [value]
    if value.is_dir():
        return sorted(value.rglob("*.json"))
    return []


def check(revision: str, evidence: Path) -> bool:
    for path in _paths(evidence):
        try:
            record = Evidence.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if record.supports_pass(revision):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    return 0 if check(args.revision, args.evidence) else 2


if __name__ == "__main__":
    raise SystemExit(main())
