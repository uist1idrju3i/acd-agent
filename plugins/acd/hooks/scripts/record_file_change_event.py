"""Record file-changing tool actions without blocking the conversation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from common import event, project_dir

EVENTS_ENV = "ACD_FILE_CHANGE_EVENTS"
EVENTS_RELATIVE_PATH = Path(".openhands/acd/file-change-events.jsonl")
PATCH_PATH = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$")


def _events_path(payload: dict[str, Any]) -> Path:
    override = os.environ.get(EVENTS_ENV)
    if override:
        path = Path(override).expanduser()
        return path if path.is_absolute() else project_dir(payload) / path
    return project_dir(payload) / EVENTS_RELATIVE_PATH


def _relative_path(value: str, root: Path) -> str:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return candidate.resolve(strict=False).relative_to(root).as_posix()
    except (OSError, ValueError):
        return str(candidate.resolve(strict=False))


def _patch_paths(patch: str, root: Path) -> list[str]:
    paths: list[str] = []
    for line in patch.splitlines():
        match = PATCH_PATH.match(line)
        if match:
            paths.append(_relative_path(match.group(1).strip(), root))
    return paths


def _record(payload: dict[str, Any]) -> dict[str, Any] | None:
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    tool_input = cast(dict[str, Any], tool_input)
    root = project_dir(payload)
    if tool_name == "file_editor":
        command = tool_input.get("command")
        path = tool_input.get("path")
        if command == "view" or not isinstance(command, str) or not command:
            return None
        if not isinstance(path, str) or not path:
            return None
        return {
            "tool_name": tool_name,
            "action": command,
            "paths": [_relative_path(path, root)],
            "command_sha256": None,
        }
    if tool_name == "apply_patch":
        patch = tool_input.get("patch")
        if not isinstance(patch, str):
            return None
        paths = _patch_paths(patch, root)
        if not paths:
            return None
        return {
            "tool_name": tool_name,
            "action": "apply_patch",
            "paths": paths,
            "command_sha256": None,
        }
    if tool_name != "terminal":
        return None
    response = payload.get("tool_response")
    if isinstance(response, dict) and cast(dict[str, Any], response).get("is_error"):
        return None
    command = tool_input.get("command")
    if not isinstance(command, str) or not command:
        return None
    return {
        "tool_name": tool_name,
        "action": "terminal",
        "paths": [],
        "command_sha256": f"sha256:{hashlib.sha256(command.encode('utf-8')).hexdigest()}",
        "command_excerpt": command[:200],
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
        record = {
            "sequence": sequence,
            "recorded_at": datetime.now(UTC).isoformat(),
            "tool_name": candidate["tool_name"],
            "action": candidate["action"],
            "paths": candidate["paths"],
            "command_sha256": candidate["command_sha256"],
            "session_id": payload.get("session_id"),
        }
        if "command_excerpt" in candidate:
            record["command_excerpt"] = candidate["command_excerpt"]
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"file change event log unavailable: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
