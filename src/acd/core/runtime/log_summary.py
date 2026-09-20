"""Summarize pipeline command logs so re-ingestion stays bounded.

The summary is an L3 observation: it never changes a command's verdict. Only the
presentation is reduced, and the dropped-line count is always reported so a
reader knows the log was truncated rather than empty.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

DEFAULT_TAIL_LINES: Final = 40
DEFAULT_MAX_LINE_CHARS: Final = 2000


@dataclass(frozen=True)
class LogSummary:
    """Bounded view of one command log."""

    text: str
    total_lines: int
    dropped_lines: int

    @property
    def truncated(self) -> bool:
        return self.dropped_lines > 0

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "total_lines": self.total_lines,
            "dropped_lines": self.dropped_lines,
            "truncated": self.truncated,
        }


def summarize_log(
    text: str,
    *,
    tail_lines: int = DEFAULT_TAIL_LINES,
    max_line_chars: int = DEFAULT_MAX_LINE_CHARS,
) -> LogSummary:
    """Keep the tail of a log, clipping over-long lines."""
    if tail_lines < 1:
        raise ValueError("tail_lines must be a positive integer")
    if max_line_chars < 1:
        raise ValueError("max_line_chars must be a positive integer")
    lines = text.splitlines()
    dropped = max(len(lines) - tail_lines, 0)
    kept = [_clip(line, max_line_chars) for line in lines[dropped:]]
    if dropped:
        kept.insert(0, f"... {dropped} earlier line(s) omitted; see the full log")
    return LogSummary(
        text="\n".join(kept),
        total_lines=len(lines),
        dropped_lines=dropped,
    )


def _clip(line: str, max_line_chars: int) -> str:
    if len(line) <= max_line_chars:
        return line
    return f"{line[:max_line_chars]}... [{len(line) - max_line_chars} chars omitted]"


__all__ = [
    "DEFAULT_MAX_LINE_CHARS",
    "DEFAULT_TAIL_LINES",
    "LogSummary",
    "summarize_log",
]
