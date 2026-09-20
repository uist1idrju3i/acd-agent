"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.idea_dialogue``.
"""

from acd.core.knowledge.idea_dialogue import (
    IdeaDialogueError,
    apply_turn,
    load_dialogue_history,
    load_idea_record,
    next_questions,
    progress_summary,
    write_dialogue_history,
    write_idea_record,
)

__all__ = [
    "IdeaDialogueError",
    "apply_turn",
    "load_dialogue_history",
    "load_idea_record",
    "next_questions",
    "progress_summary",
    "write_dialogue_history",
    "write_idea_record",
]
