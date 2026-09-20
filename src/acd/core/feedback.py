"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.feedback``.
"""

from acd.core.manufacturing.feedback import (
    FeedbackError,
    apply_input_feedback,
    propose_input_feedback,
    validate_applied_feedback,
)

__all__ = [
    "FeedbackError",
    "apply_input_feedback",
    "propose_input_feedback",
    "validate_applied_feedback",
]
