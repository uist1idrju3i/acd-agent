"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.library_assets``.
"""

from acd.core.manufacturing.library_assets import (
    LIBRARY_ASSET_ROOT,
    LibraryAsset,
    LibraryAssetError,
    graph_library_assets,
    library_asset_store,
    materialize_library_assets,
    resolve_fixture_library_path,
    resolve_library_asset,
    sha256_of_asset,
    verify_fixture_library_asset,
    verify_fixture_library_assets,
    verify_library_asset,
    verify_materialized_library_assets,
)

__all__ = [
    "LIBRARY_ASSET_ROOT",
    "LibraryAsset",
    "LibraryAssetError",
    "graph_library_assets",
    "library_asset_store",
    "materialize_library_assets",
    "resolve_fixture_library_path",
    "resolve_library_asset",
    "sha256_of_asset",
    "verify_fixture_library_asset",
    "verify_fixture_library_assets",
    "verify_library_asset",
    "verify_materialized_library_assets",
]
