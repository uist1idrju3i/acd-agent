"""Tests for bounded pipeline log summaries."""

from __future__ import annotations

import pytest

from acd.core.log_summary import summarize_log


def test_short_log_is_kept_verbatim() -> None:
    summary = summarize_log("a\nb\nc", tail_lines=5)

    assert summary.text == "a\nb\nc"
    assert summary.total_lines == 3
    assert summary.dropped_lines == 0
    assert summary.truncated is False


def test_long_log_keeps_the_tail_and_reports_the_drop() -> None:
    summary = summarize_log("\n".join(str(index) for index in range(10)), tail_lines=3)

    assert summary.text.splitlines()[1:] == ["7", "8", "9"]
    assert "7 earlier line(s) omitted" in summary.text
    assert summary.dropped_lines == 7
    assert summary.truncated is True


def test_over_long_line_is_clipped() -> None:
    summary = summarize_log("x" * 50, tail_lines=1, max_line_chars=10)

    assert summary.text.startswith("x" * 10)
    assert "40 chars omitted" in summary.text


@pytest.mark.parametrize(("tail", "chars"), [(0, 10), (1, 0)])
def test_non_positive_bounds_are_rejected(tail: int, chars: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        summarize_log("a", tail_lines=tail, max_line_chars=chars)
