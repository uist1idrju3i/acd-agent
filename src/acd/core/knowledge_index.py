"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.knowledge_index``.
"""

from acd.core.knowledge.knowledge_index import (
    INDEXED_SUFFIXES,
    KnowledgeIndexError,
    KnowledgeSourceLocation,
    build_knowledge_index,
    git_history_source,
    load_indexed_graph,
)

__all__ = [
    "INDEXED_SUFFIXES",
    "KnowledgeIndexError",
    "KnowledgeSourceLocation",
    "build_knowledge_index",
    "git_history_source",
    "load_indexed_graph",
]
