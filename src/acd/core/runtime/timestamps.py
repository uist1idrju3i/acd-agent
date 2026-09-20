"""Timestamp parsing helpers used by deterministic gates."""

from __future__ import annotations

from datetime import datetime


def parse_evaluated_at(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and require an explicit timezone."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("evaluated-at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("evaluated-at must include a timezone")
    return parsed
