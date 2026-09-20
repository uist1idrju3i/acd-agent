"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.part_selection``.
"""

from acd.core.manufacturing.part_selection import (
    PartSelectionError,
    PartSelectionResult,
    default_parts_catalog_path,
    load_parts_catalog,
    select_cern_part,
    select_part,
)

__all__ = [
    "PartSelectionError",
    "PartSelectionResult",
    "default_parts_catalog_path",
    "load_parts_catalog",
    "select_cern_part",
    "select_part",
]
