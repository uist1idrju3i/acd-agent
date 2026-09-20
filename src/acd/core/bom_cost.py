"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.bom_cost``.
"""

from acd.core.manufacturing.bom_cost import (
    bom_cost_markdown,
    estimate_bom_cost,
)

__all__ = [
    "bom_cost_markdown",
    "estimate_bom_cost",
]
