"""Check canonical evidence, with ``--valid-only`` reserved for the Stop guard.

``--valid-only`` checks only status and the absence of unknown envelope fields
for the Stop guard's mtime freshness escape hatch. It is not pass evidence:
pass evidence still requires ``supports_pass()`` for a committed revision.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acd_schema import Evidence


def _paths(values: Path | list[Path]) -> list[Path]:
    paths: list[Path] = []
    candidates = [values] if isinstance(values, Path) else values
    for value in candidates:
        if value.is_file():
            paths.append(value)
        elif value.is_dir():
            paths.extend(value.rglob("*.json"))
    return sorted(set(paths))


def check(
    revision: str | None,
    evidence: Path | list[Path],
    required_ids: set[str] | None = None,
    *,
    valid_only: bool = False,
) -> bool:
    matched: set[str] = set()
    invalid: set[str] = set()
    for path in _paths(evidence):
        try:
            record = Evidence.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if valid_only:
            if record.status == "valid" and not record.envelope.has_unknown():
                return True
            continue
        if revision is None:
            return False
        if record.supports_pass(revision):
            if required_ids is None:
                return True
            if record.evidence_id in required_ids:
                matched.add(record.evidence_id)
        elif required_ids is not None and record.evidence_id in required_ids:
            invalid.add(record.evidence_id)
    return required_ids is not None and not invalid and matched == required_ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision")
    parser.add_argument("--evidence", type=Path, action="append", required=True)
    parser.add_argument("--require-id", action="append", default=[])
    parser.add_argument("--valid-only", action="store_true")
    args = parser.parse_args()
    if args.valid_only and (args.revision is not None or args.require_id):
        parser.error("--valid-only cannot be combined with --revision or --require-id")
    if not args.valid_only and args.revision is None:
        parser.error("--revision is required unless --valid-only is used")
    required_ids = set(args.require_id) or None
    return (
        0
        if check(args.revision, args.evidence, required_ids, valid_only=args.valid_only)
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
