"""Compatibility re-export.

The implementation lives in ``acd.core.runtime.log_summary``.
"""

from acd.core.runtime.log_summary import (
    DEFAULT_MAX_LINE_CHARS,
    DEFAULT_TAIL_LINES,
    LogSummary,
    summarize_log,
)

__all__ = [
    "DEFAULT_MAX_LINE_CHARS",
    "DEFAULT_TAIL_LINES",
    "LogSummary",
    "summarize_log",
]
