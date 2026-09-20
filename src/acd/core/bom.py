"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.bom``.
"""

from acd.core.manufacturing.bom import (
    BomRow,
    bom_csv,
    build_bom,
    group_bom_rows_by_mpn,
    refdes_key,
)

__all__ = [
    "BomRow",
    "bom_csv",
    "build_bom",
    "group_bom_rows_by_mpn",
    "refdes_key",
]
