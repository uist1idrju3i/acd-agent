#!/usr/bin/env python3
"""Aggregate declared quote records into an order-total document."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from acd.core.order_total import aggregate_order_total, order_total_result_to_document
from acd.core.timestamps import parse_evaluated_at
from acd.schema import FabProfileDocument, OrderScope, QuoteRecord


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quote-record",
        "--quote",
        dest="quote_records",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--order-scope", "--scope", type=Path, required=True)
    parser.add_argument("--fab-profile", "--profile", type=Path, required=True)
    parser.add_argument("--target-revision", required=True)
    parser.add_argument("--evaluated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        records = [
            QuoteRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in args.quote_records
        ]
        scope = OrderScope.model_validate_json(
            args.order_scope.read_text(encoding="utf-8")
        )
        fab_profile = FabProfileDocument.model_validate_json(
            args.fab_profile.read_text(encoding="utf-8")
        )
        evaluated_at = parse_evaluated_at(args.evaluated_at)
        result = aggregate_order_total(
            records,
            scope,
            fab_profile=fab_profile,
            evaluated_at=evaluated_at,
            target_revision=args.target_revision,
        )
        document = order_total_result_to_document(result)
        _write_atomic(
            args.output,
            document.model_dump_json(indent=2) + "\n",
        )
    except Exception as exc:
        print(f"order total aggregation refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output": str(args.output),
                "quote_count": len(records),
                "target_revision": result.target_revision,
                "breakdown_hash": result.breakdown_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
