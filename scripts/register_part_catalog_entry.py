"""Validate and register one parts-catalog entry declaration.

Entry JSON may omit ``*_sha256`` when ``--pin-hashes`` is used. Container-absolute
library paths require running via ``scripts/run_in_workspace.py`` with the
repository mounted so catalog writes land in the checkout. Commit the resulting
``contracts/parts-catalog.json`` change and send it through a pull request;
``--allow-dirty`` never covers ``contracts/`` (AA-5).
"""

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
    parser.add_argument(
        "--pin-hashes",
        action="store_true",
        help="Compute missing or placeholder library digests from the files.",
    )
    parser.add_argument(
        "--pinned-entry-out",
        type=Path,
        default=None,
        help="Write the validated entry with computed digests to this path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = register_parts_catalog_entry(
            args.entry,
            args.catalog,
            dry_run=args.dry_run,
            pin_hashes=args.pin_hashes,
        )
        if args.pinned_entry_out is not None:
            args.pinned_entry_out.write_text(
                json.dumps(
                    result.entry.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
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
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
