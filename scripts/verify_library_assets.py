"""Verify declared library assets against the canonical asset store.

The parts catalog and every committed fixture declare symbol and footprint files
with a content hash. This check resolves each declaration through the single
library-asset contract and fails closed on a missing, escaping, or mismatched
asset, so a generated fixture can never inherit an unresolvable declaration.

A container-absolute declaration is pinned by an installed package and can only
be hash-verified where that package exists. Such a declaration is verified when
present and reported as ``container_pending`` otherwise; ``--require-present``
turns an absent one into a failure for the container gate path. Reporting is an
L3 observation and never grants pass authority.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from acd.core.library_assets import (
    LibraryAsset,
    LibraryAssetError,
    graph_library_assets,
    verify_fixture_library_asset,
    verify_library_asset,
)
from acd.core.part_selection import default_parts_catalog_path, load_parts_catalog
from acd.schema.design_graph import DesignGraph

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURES: tuple[Path, ...] = (REPO_ROOT / "fixtures" / "golden-design-1",)
PINNED_ABSOLUTE_ROOTS: tuple[str, ...] = ("/usr/share/kicad/",)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify catalog and fixture library asset declarations",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="parts catalog path (default: declared repository catalog)",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        action="append",
        default=None,
        help="fixture directory to verify (repeatable)",
    )
    parser.add_argument(
        "--require-present",
        action="store_true",
        help="fail when a container-absolute declaration is absent",
    )
    return parser


def _verify_asset(asset: LibraryAsset, *, require_present: bool) -> str:
    """Verify one declaration and return its verification class."""
    if asset.relative:
        verify_library_asset(asset)
        return "store_verified"
    path = Path(asset.declared_path)
    if not any(asset.declared_path.startswith(root) for root in PINNED_ABSOLUTE_ROOTS):
        raise LibraryAssetError(
            "absolute library asset is outside the pinned package roots: "
            + asset.declared_path
        )
    if not path.is_file():
        if require_present:
            raise LibraryAssetError(
                f"pinned library asset is absent: {asset.declared_path}"
            )
        return "container_pending"
    verify_library_asset(asset)
    return "package_verified"


def _verify_catalog(path: Path, *, require_present: bool) -> dict[str, int]:
    document, _ = load_parts_catalog(path)
    counts: Counter[str] = Counter()
    for entry in document.entries:
        library = entry.library_ref
        for declared, digest in (
            (library.symbol_file, library.symbol_sha256),
            (library.footprint_file, library.footprint_sha256),
        ):
            asset = LibraryAsset(declared_path=declared, sha256=digest)
            counts[_verify_asset(asset, require_present=require_present)] += 1
    return dict(counts)


def _verify_fixture(fixture_dir: Path, *, require_present: bool) -> dict[str, int]:
    graph_path = fixture_dir / "graph.json"
    graph = DesignGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    counts: Counter[str] = Counter()
    for asset in graph_library_assets(graph):
        if asset.relative:
            local = fixture_dir / asset.declared_path
            verify_fixture_library_asset(asset, fixture_dir)
            counts["fixture_verified" if local.is_file() else "store_verified"] += 1
            continue
        counts[_verify_asset(asset, require_present=require_present)] += 1
    return dict(counts)


def main(argv: list[str] | None = None) -> int:
    """Verify every declared library asset without emitting a traceback."""
    args = _parser().parse_args(argv)
    catalog_path = args.catalog or default_parts_catalog_path()
    fixtures = tuple(args.fixture) if args.fixture else DEFAULT_FIXTURES
    try:
        catalog_assets = _verify_catalog(
            catalog_path, require_present=args.require_present
        )
        fixture_assets = {
            str(fixture): _verify_fixture(
                fixture, require_present=args.require_present
            )
            for fixture in fixtures
        }
    except (LibraryAssetError, OSError, ValueError) as exc:
        print(f"library asset verification failed: {exc}")
        return 1
    print(
        json.dumps(
            {
                "catalog": str(catalog_path),
                "catalog_assets": catalog_assets,
                "fixture_assets": fixture_assets,
                "record_class": "L3",
                "pass_evidence": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
