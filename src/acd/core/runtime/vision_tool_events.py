"""Canonical helpers for hook-written vision tool event records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

VISION_TOOL_EVENTS_RELATIVE_PATH = Path(".openhands/acd/vision-tool-events.jsonl")
VISION_TOOL_NAME = "inspect_image_with_vision"


def vision_tool_events_path(project_dir: Path, override: str | Path | None = None) -> Path:
    """Resolve the event log path from an explicit override or project directory."""
    if override is not None:
        path = Path(override).expanduser()
        return path if path.is_absolute() else project_dir / path
    return project_dir / VISION_TOOL_EVENTS_RELATIVE_PATH


def response_sha256(response: str) -> str:
    """Return a prefixed SHA-256 digest for the exact response text."""
    return f"sha256:{hashlib.sha256(response.encode('utf-8')).hexdigest()}"


def event_id(record: dict[str, Any]) -> str:
    """Return the bare SHA-256 ID for a canonical event identity payload."""
    payload = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
