"""Reconstruct one order from a validated side-effect journal."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.core.side_effect_journal import (
    SideEffectJournalError,
    reconstruct_order,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--idempotency-key", required=True)
    args = parser.parse_args(argv)

    try:
        reconstruction = reconstruct_order(
            args.journal,
            idempotency_key=args.idempotency_key,
        )
    except (OSError, SideEffectJournalError, ValueError) as exc:
        print(f"side-effect journal validation failed: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "planned": reconstruction.planned.model_dump(mode="json"),
                "result": reconstruction.result.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
