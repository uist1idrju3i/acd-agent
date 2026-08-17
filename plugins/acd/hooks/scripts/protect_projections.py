"""Deny writes that touch generated ACD projections."""

from __future__ import annotations

import shlex
from pathlib import Path

from common import REASON, event, project_dir, result, strings

PROTECTED = ("out", "evidence")
GENERATED = {
    ".kicad_pcb", ".kicad_sch", ".kicad_pro", ".gbr", ".ger", ".drl", ".xln",
    ".step", ".stp", ".3mf", ".zip",
}
READ_COMMANDS = {"cat", "ls", "grep", "rg", "find", "head", "tail", "less", "file", "stat", "pwd"}


def protected(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve(strict=False)
        relative = resolved.relative_to(root)
    except (OSError, ValueError):
        return False
    return bool(
        relative.parts and (relative.parts[0] in PROTECTED or resolved.suffix.lower() in GENERATED)
    )


def path_mentions(value: str, root: Path) -> tuple[bool, bool]:
    tokens = [value]
    try:
        tokens += shlex.split(value)
    except ValueError:
        return True, False
    mentioned = False
    resolvable = True
    for token in tokens:
        candidate = Path(token)
        if not candidate.is_absolute():
            candidate = root / candidate
        if protected(candidate, root) or any(part in PROTECTED for part in Path(token).parts):
            mentioned = True
            try:
                candidate.resolve(strict=False)
            except OSError:
                resolvable = False
    return mentioned, resolvable


def main() -> int:
    payload = event()
    root = project_dir(payload)
    tool = str(payload.get("tool_name", ""))
    values = strings(payload.get("tool_input"))
    command = " ".join(values)
    mentioned = False
    resolvable = True
    for value in values:
        found, can_resolve = path_mentions(value, root)
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
    if not resolvable:
        result(decision="deny", reason=REASON)
    else:
        result(decision="deny", reason=REASON)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
