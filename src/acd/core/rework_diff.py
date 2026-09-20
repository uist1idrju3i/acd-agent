"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.rework_diff``.
"""

from acd.core.manufacturing.rework_diff import (
    DerivedGraph,
    LoadedReworkDiff,
    ReworkDiffError,
    apply_rework_diff,
    load_rework_diff,
    safety_related_node_ids,
    write_derived_graph,
)

__all__ = [
    "DerivedGraph",
    "LoadedReworkDiff",
    "ReworkDiffError",
    "apply_rework_diff",
    "load_rework_diff",
    "safety_related_node_ids",
    "write_derived_graph",
]
