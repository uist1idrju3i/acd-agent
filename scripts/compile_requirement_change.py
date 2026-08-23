"""Compile a requirement update into coupled design input changes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.requirement_compiler import (
    RequirementCompilationError,
    compile_requirement_change,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--requirement", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = compile_requirement_change(
            args.fixture_dir, args.requirement, dry_run=args.dry_run
        )
    except RequirementCompilationError as exc:
        print(
            json.dumps(
                {"status": "error", "error": str(exc), "pass_evidence": False},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result.report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
