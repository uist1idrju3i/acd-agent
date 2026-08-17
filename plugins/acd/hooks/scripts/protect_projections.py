"""Deny writes that touch generated ACD projections."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, cast

from common import REASON, event, project_dir, result

PROTECTED = ("out", "evidence")
GENERATED = {
    ".kicad_pcb", ".kicad_sch", ".kicad_pro", ".gbr", ".ger", ".drl", ".xln",
    ".step", ".stp", ".3mf", ".zip",
}
READ_COMMANDS = {"cat", "ls", "grep", "rg", "find", "head", "tail", "less", "file", "stat", "pwd"}
PATH_FIELDS = {
    "path", "file_path", "paths", "old_path", "new_path", "dest", "destination",
    "target", "source",
}


def protected(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve(strict=False)
        relative = resolved.relative_to(root)
    except (OSError, ValueError):
        return False
    return bool(
        relative.parts and (relative.parts[0] in PROTECTED or resolved.suffix.lower() in GENERATED)
    )


def path_mentions(value: str, root: Path, *, command: bool = False) -> tuple[bool, bool]:
    if "\x00" in value:
        return True, False
    tokens = [value]
    if command:
        try:
            tokens = shlex.split(value)
        except ValueError:
            return True, False
    mentioned = False
    resolvable = True
    for token in tokens:
        candidate = Path(token)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, ValueError):
            mentioned |= any(part in PROTECTED for part in Path(token).parts)
            resolvable = False
            continue
        if protected(resolved, root):
            mentioned = True
    return mentioned, resolvable


def input_paths(tool_input: Any, tool: str) -> list[str]:
    if tool == "terminal":
        if not isinstance(tool_input, dict):
            return []
        command = cast(dict[str, Any], tool_input).get("command")
        return [command] if isinstance(command, str) else []
    if not isinstance(tool_input, dict):
        return []
    mapping = cast(dict[str, Any], tool_input)
    values: list[str] = []
    for key, value in mapping.items():
        if key not in PATH_FIELDS:
            continue
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in cast(list[Any], value) if isinstance(item, str))
    return values


def main() -> int:
    payload = event()
    root = project_dir(payload)
    tool = str(payload.get("tool_name", ""))
    values = input_paths(payload.get("tool_input"), tool)
    command = values[0] if tool == "terminal" and values else ""
    mentioned = False
    resolvable = True
    for value in values:
        found, can_resolve = path_mentions(value, root, command=tool == "terminal")
        mentioned |= found
        resolvable &= can_resolve
    if not mentioned:
        return 0
    if tool == "terminal":
        try:
            first = shlex.split(command)[0]
        except (IndexError, ValueError):
            first = ""
        if first in READ_COMMANDS and resolvable:
            return 0
    result(decision="deny", reason=REASON)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
