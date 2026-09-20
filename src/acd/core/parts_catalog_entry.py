"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.parts_catalog_entry``.
"""

from acd.core.manufacturing.parts_catalog_entry import (
    PartsCatalogEntryError,
    PartsCatalogEntryResult,
    PinnedLibraryHash,
    register_parts_catalog_entry,
)

__all__ = [
    "PartsCatalogEntryError",
    "PartsCatalogEntryResult",
    "PinnedLibraryHash",
    "register_parts_catalog_entry",
]
