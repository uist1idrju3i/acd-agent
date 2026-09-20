"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.rationale``.
"""

from acd.core.knowledge.rationale import (
    BULK_RECORD_MIN,
    KNOWN_DETERMINISTIC_GENERATORS,
    MAX_IDENTICAL_TEXT_RECORDS,
    MIN_TEXT_DIVERSITY_RATIO,
    RATIONALE_EXEMPT_ATTRS,
    REQUIRED_RATIONALE_ATTRS,
    RationaleRefreshError,
    check_rationale_coverage,
    refresh_rationale_document,
    subject_hash_for,
    summarize_rationale_coverage,
)

__all__ = [
    "BULK_RECORD_MIN",
    "KNOWN_DETERMINISTIC_GENERATORS",
    "MAX_IDENTICAL_TEXT_RECORDS",
    "MIN_TEXT_DIVERSITY_RATIO",
    "RATIONALE_EXEMPT_ATTRS",
    "REQUIRED_RATIONALE_ATTRS",
    "RationaleRefreshError",
    "check_rationale_coverage",
    "refresh_rationale_document",
    "subject_hash_for",
    "summarize_rationale_coverage",
]
