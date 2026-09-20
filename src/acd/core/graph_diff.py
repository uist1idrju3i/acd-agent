"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.graph_diff``.
"""

from acd.core.knowledge.graph_diff import (
    GraphDiffError,
    build_graph_diff,
    unknown_graph_diff,
)

__all__ = [
    "GraphDiffError",
    "build_graph_diff",
    "unknown_graph_diff",
]
