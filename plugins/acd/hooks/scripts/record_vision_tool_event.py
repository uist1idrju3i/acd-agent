"""Record successful inspect_image_with_vision tool observations without blocking."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from common import event, project_dir

EVENTS_ENV = "ACD_VISION_TOOL_EVENTS"
EVENTS_RELATIVE_PATH = Path(".openhands/acd/vision-tool-events.jsonl")
VISION_TOOL_NAME = "inspect_image_with_vision"


def _response_sha256(response: str) -> str:
    return f"sha256:{hashlib.sha256(response.encode('utf-8')).hexdigest()}"


def _event_id(record: dict[str, Any]) -> str:
    payload = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _events_path(payload: dict[str, Any]) -> Path:
    override = os.environ.get(EVENTS_ENV)
    if override:
        path = Path(override).expanduser()
        return path if path.is_absolute() else project_dir(payload) / path
    return project_dir(payload) / EVENTS_RELATIVE_PATH


def _record(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("tool_name") != VISION_TOOL_NAME:
        return None
    response = payload.get("tool_response")
    if not isinstance(response, dict) or "error" in response:
        return None
    response = cast(dict[str, Any], response)
    answer = response.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None
    tool_input = payload.get("tool_input")
    tool_input = (
        {} if not isinstance(tool_input, dict) else cast(dict[str, Any], tool_input)
    )
    response_hash = _response_sha256(answer)
    profile_name = response.get("profile_name")
    model = response.get("model")
    identity = {
        "sequence": 0,
        "tool_name": VISION_TOOL_NAME,
        "tool_input": tool_input,
        "profile_name": profile_name,
        "model": model,
        "response_sha256": response_hash,
    }
    return {
        "tool_name": VISION_TOOL_NAME,
        "profile_name": profile_name,
        "model": model,
        "image_index": tool_input.get("image_index"),
        "question": tool_input.get("question"),
        "response_sha256": response_hash,
        "_identity": identity,
        "session_id": payload.get("session_id"),
    }


def main() -> int:
    payload = event()
    candidate = _record(payload)
    if candidate is None:
        return 0
    path = _events_path(payload)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        sequence = 1
        if path.exists():
            sequence += len(path.read_text(encoding="utf-8").splitlines())
        identity = cast(dict[str, Any], candidate.pop("_identity"))
        identity["sequence"] = sequence
        record = {
            "sequence": sequence,
            "event_id": _event_id(identity),
            "tool_name": candidate["tool_name"],
            "profile_name": candidate["profile_name"],
            "model": candidate["model"],
            "image_index": candidate["image_index"],
            "question": candidate["question"],
            "response_sha256": candidate["response_sha256"],
            "recorded_at": datetime.now(UTC).isoformat(),
            "session_id": candidate["session_id"],
        }
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"vision tool event log unavailable: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
