"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.knowledge_qa``.
"""

from acd.core.knowledge.knowledge_qa import (
    CATEGORY_KEYWORDS,
    CATEGORY_ORDER,
    HistoryEntry,
    KnowledgeBase,
    answer_question,
    classify_question,
)

__all__ = [
    "CATEGORY_KEYWORDS",
    "CATEGORY_ORDER",
    "HistoryEntry",
    "KnowledgeBase",
    "answer_question",
    "classify_question",
]
