#!/usr/bin/env python3
"""Update one published image entry in the repository digest lock."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, cast

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ENTRIES = {"acd_tools", "acd_server"}


def _require_digest(value: str) -> str:
    if not _DIGEST.fullmatch(value) or value == "sha256:" + "0" * 64:
        raise ValueError("digest must be a non-placeholder sha256 digest")
    return value


def _load(path: Path) -> dict[str, Any]:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid image lock: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("image lock must be a JSON object")
    return cast(dict[str, Any], payload)


def _validate_current_entry(entry: str, current: dict[str, Any]) -> None:
    for field in ("image", "tag", "digest"):
        if not isinstance(current.get(field), str) or not current[field].strip():
            raise ValueError(f"image lock entry is malformed: {entry}.{field}")
    _require_digest(current["digest"])


def update_lock(
    path: Path,
    *,
    entry: str,
    digest: str,
    tag: str | None = None,
    published_at: str | None = None,
    workflow_run: str | None = None,
    image: str | None = None,
    tools: dict[str, str] | None = None,
) -> bool:
    """Update an entry and return whether the serialized lock changed."""
    if entry not in _ENTRIES:
        raise ValueError(f"unknown image lock entry: {entry}")
    digest = _require_digest(digest)
    payload = _load(path)
    current = payload.get(entry)
    if not isinstance(current, dict):
        raise ValueError(f"image lock entry is missing or malformed: {entry}")
    current = cast(dict[str, Any], current)
    _validate_current_entry(entry, current)
    updates: dict[str, object] = {"digest": digest}
    if tag is not None:
        if not tag.strip():
            raise ValueError("tag must not be empty")
        updates["tag"] = tag.strip()
    if published_at is not None:
        try:
            datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("published_at must be an ISO-8601 timestamp") from exc
        updates["published_at"] = published_at
    if workflow_run is not None:
        if not workflow_run.strip():
            raise ValueError("workflow_run must not be empty")
        updates["workflow_run"] = workflow_run.strip()
    if image is not None:
        if not image.strip() or "@" in image or ":" in image.rsplit("/", 1)[-1]:
            raise ValueError("image must be an untagged repository name")
        updates["image"] = image.strip()
    if tools is not None:
        if not tools or any(not key.strip() or not value.strip() for key, value in tools.items()):
            raise ValueError("tools must contain non-empty versions")
        updates["tools"] = dict(sorted(tools.items()))
    before = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    current.update(updates)
    after = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if before == after:
        return False
    path.write_text(after, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--entry", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--tag")
    parser.add_argument("--published-at")
    parser.add_argument("--workflow-run")
    parser.add_argument("--image")
    parser.add_argument("--tools-json", type=Path)
    args = parser.parse_args(argv)
    try:
        tools = None
        if args.tools_json is not None:
            tools_value: Any = json.loads(args.tools_json.read_text(encoding="utf-8"))
            if not isinstance(tools_value, dict):
                raise ValueError("tools JSON must be an object of string values")
            tools_object = cast(dict[object, object], tools_value)
            if not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in tools_object.items()
            ):
                raise ValueError("tools JSON must be an object of string values")
            tools = {
                cast(str, key): cast(str, value)
                for key, value in tools_object.items()
            }
        changed = update_lock(
            args.lock,
            entry=args.entry,
            digest=args.digest,
            tag=args.tag,
            published_at=args.published_at,
            workflow_run=args.workflow_run,
            image=args.image,
            tools=tools,
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print("UPDATED" if changed else "UNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
