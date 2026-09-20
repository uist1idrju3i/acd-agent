"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.idea_promotion``.
"""

from acd.core.knowledge.idea_promotion import (
    IdeaPromotionError,
    load_promotion_rationale,
    promote_idea,
)

__all__ = [
    "IdeaPromotionError",
    "load_promotion_rationale",
    "promote_idea",
]
