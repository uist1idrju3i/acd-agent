"""Validate and register one parts-catalog entry declaration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acd.core.parts_catalog_entry import (
    PartsCatalogEntryError,
    register_parts_catalog_entry,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--entry",
        required=True,
        help="PartCatalogEntry JSON path or inline JSON object.",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("contracts/parts-catalog.json"),
        help="Parts catalog path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without writing the catalog.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = register_parts_catalog_entry(
            args.entry,
            args.catalog,
            dry_run=args.dry_run,
        )
        print(
            json.dumps(
                {"ok": True, **result.model_dump()},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (PartsCatalogEntryError, OSError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "fail_closed": True,
                    "failure_reason": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
