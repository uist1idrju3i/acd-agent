"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.design_history``.
"""

from acd.core.knowledge.design_history import (
    DEFAULT_HISTORY_LIMIT,
    design_input_history,
    graph_revision_at,
    resolve_head_commit,
)

__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "design_input_history",
    "graph_revision_at",
    "resolve_head_commit",
]
