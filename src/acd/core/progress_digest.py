"""Compatibility re-export.

The implementation lives in ``acd.core.runtime.progress_digest``.
"""

from acd.core.runtime.progress_digest import (
    EVIDENCE_UNVERIFIED_LINE,
    collect_progress_digest,
    render_progress_digest,
)

__all__ = [
    "EVIDENCE_UNVERIFIED_LINE",
    "collect_progress_digest",
    "render_progress_digest",
]
