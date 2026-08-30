"""Deny writes that touch generated ACD projections."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any, cast

from common import REASON, STOP_REPORT_PATH, event, project_dir, result

PROTECTED = ("out", "evidence")
GENERATED = {
    ".kicad_pcb", ".kicad_sch", ".kicad_pro", ".gbr", ".ger", ".drl", ".xln",
    ".step", ".stp", ".3mf", ".zip",
}
PATH_FIELDS = {
    "path", "file_path", "paths", "old_path", "new_path", "dest", "destination",
    "target", "source",
}
OUTPUT_OPTIONS = frozenset(
    {"--out", "--out-dir", "--out-root", "--output", "--download", "--cache-dir"}
)
WRITE_COMMANDS = frozenset(
    {
        "rm", "rmdir", "mv", "cp", "dd", "truncate", "install", "tee", "ln",
        "touch", "chmod", "chown", "sed", "patch", "unzip", "tar",
    }
)
SHELL_COMMANDS = frozenset({"bash", "sh", "zsh", "dash"})
INLINE_INTERPRETERS = frozenset({"python", "python3", "perl", "node", "ruby"})
REDIRECTS = frozenset({">", ">>", "2>", "&>", ">|"})
SEPARATORS = frozenset({";", "&&", "||", "|"})
MAX_NESTING_DEPTH = 4
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_INLINE_PATH = re.compile(
    r"(?<![\w-])"
    r"(?:(?:[A-Za-z0-9_.-]+/)*(?:out|evidence)(?:/[A-Za-z0-9_.-]+)+|"
    r"(?:out|evidence)|"
    r"[A-Za-z0-9_.-]+/\.\./(?:out|evidence)/[A-Za-z0-9_.-]+"
    r"(?:/[A-Za-z0-9_.-]+)*|"
    r"[A-Za-z0-9_.-]+\.(?:kicad_pcb|kicad_sch|kicad_pro|gbr|ger|drl|xln|step|stp|3mf|zip))"
    r"(?![\w-])"
)


def protected(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve(strict=False)
        relative = resolved.relative_to(root)
    except (OSError, ValueError):
        return False
    return bool(
        relative.parts
        and (
            relative.parts[0] in PROTECTED
            or resolved.suffix.lower() in GENERATED
        )
    )


def _path_status(value: str, root: Path) -> tuple[bool, bool, Path | None]:
    """Return protected, resolvable, and resolved path status."""
    if "\x00" in value:
        return True, False, None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, ValueError):
        possible = any(part in PROTECTED for part in Path(value).parts)
        possible |= Path(value).suffix.lower() in GENERATED
        return possible, False, None
    return protected(resolved, root), True, resolved


def _allowed_path(value: str, root: Path) -> bool:
    is_protected, resolvable, resolved = _path_status(value, root)
    del is_protected
    if not resolvable or resolved is None:
        return False
    return resolved == (root / STOP_REPORT_PATH).resolve(strict=False)


def _protected_write(value: str, root: Path, *, allow_stop_report: bool = True) -> bool:
    is_protected, resolvable, _ = _path_status(value, root)
    if not resolvable:
        return is_protected
    return is_protected and not (allow_stop_report and _allowed_path(value, root))


def path_mentions(value: str, root: Path, *, command: bool = False) -> tuple[bool, bool]:
    """Retain the legacy helper contract for callers and focused tests."""
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
        found, can_resolve, _ = _path_status(token, root)
        mentioned |= found
        resolvable &= can_resolve
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


def _tokenize(command: str) -> list[str] | None:
    if "\x00" in command:
        return None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return None


def _simple_commands(tokens: list[str]) -> list[list[str]] | None:
    commands: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in SEPARATORS:
            if not current:
                return None
            commands.append(current)
            current = []
        else:
            current.append(token)
    if not current:
        return None
    commands.append(current)
    return commands


def _redirection_targets(tokens: list[str]) -> list[str] | None:
    targets: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in REDIRECTS:
            index += 1
            if index >= len(tokens) or tokens[index] in SEPARATORS or tokens[index] in REDIRECTS:
                return None
            targets.append(tokens[index])
        index += 1
    return targets


def _skip_option(tokens: list[str], index: int, *, value_options: frozenset[str]) -> int:
    token = tokens[index]
    if token in value_options and index + 1 < len(tokens):
        return index + 2
    return index + 1


def _command_index(tokens: list[str]) -> int:
    index = 0
    while index < len(tokens) and _ASSIGNMENT.match(tokens[index]):
        index += 1
    while index < len(tokens):
        name = Path(tokens[index]).name
        if name == "env":
            index += 1
            while index < len(tokens) and (
                _ASSIGNMENT.match(tokens[index]) or tokens[index].startswith("-")
            ):
                index = _skip_option(
                    tokens,
                    index,
                    value_options=frozenset({"-u", "--unset", "-S", "--split-string"}),
                )
            continue
        if name in {"sudo", "nohup"}:
            index += 1
            if name == "sudo":
                while index < len(tokens) and tokens[index].startswith("-"):
                    index = _skip_option(
                        tokens,
                        index,
                        value_options=frozenset(
                            {"-u", "--user", "-C", "--chdir", "-R", "--chroot"}
                        ),
                    )
            continue
        if name == "timeout":
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                index = _skip_option(
                    tokens,
                    index,
                    value_options=frozenset({"-k", "--kill-after", "--signal"}),
                )
            if index < len(tokens):
                index += 1
            continue
        if name == "stdbuf":
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                index = _skip_option(
                    tokens,
                    index,
                    value_options=frozenset({"-o", "-e", "-i"}),
                )
            continue
        if name == "uv" and index + 1 < len(tokens) and tokens[index + 1] == "run":
            index += 2
            while index < len(tokens) and tokens[index].startswith("-"):
                index = _skip_option(
                    tokens,
                    index,
                    value_options=frozenset(
                        {
                            "--project", "--directory", "--python", "--with",
                            "--with-editable", "--script",
                        }
                    ),
                )
            continue
        break
    return index


def _option_targets(tokens: list[str], root: Path) -> bool:
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in OUTPUT_OPTIONS:
            if index + 1 >= len(tokens):
                return True
            value = tokens[index + 1]
            _, resolvable, _ = _path_status(value, root)
            if not resolvable:
                return True
            index += 2
            continue
        if any(token.startswith(option + "=") for option in OUTPUT_OPTIONS):
            value = token.split("=", 1)[1]
            _, resolvable, _ = _path_status(value, root)
            if not value or not resolvable:
                return True
        index += 1
    return False


def _non_option_values(tokens: list[str], *, skip_value_options: frozenset[str]) -> list[str]:
    values: list[str] = []
    index = 0
    options_ended = False
    while index < len(tokens):
        token = tokens[index]
        if not options_ended and token == "--":
            options_ended = True
            index += 1
            continue
        if not options_ended and token.startswith("-"):
            index = _skip_option(tokens, index, value_options=skip_value_options)
            continue
        values.append(token)
        index += 1
    return values


def _write_targets(tokens: list[str], command: str) -> list[str]:
    if command in {"rm", "rmdir", "touch", "chmod", "chown", "truncate", "patch"}:
        return _non_option_values(tokens, skip_value_options=frozenset())
    if command in {"cp", "mv", "ln", "install"}:
        values = _non_option_values(
            tokens,
            skip_value_options=frozenset({"-t", "--target-directory", "-T"}),
        )
        return values[-1:] if values else []
    if command == "dd":
        return [
            value.split("=", 1)[1]
            for value in tokens
            if value.startswith("of=") and value.split("=", 1)[1]
        ]
    if command == "tee":
        return _non_option_values(tokens, skip_value_options=frozenset())
    if command == "sed":
        if not any(value == "-i" or value.startswith("-i") for value in tokens):
            return []
        return _non_option_values(tokens, skip_value_options=frozenset())
    if command == "unzip":
        targets: list[str] = []
        for index, value in enumerate(tokens):
            if value == "-d" and index + 1 < len(tokens):
                targets.append(tokens[index + 1])
            elif value.startswith("-d") and len(value) > 2:
                targets.append(value[2:])
        return targets
    if command == "tar":
        targets = []
        extracting = any(
            value in {"-x", "--extract"} or ("x" in value[1:] and value.startswith("-"))
            for value in tokens
        )
        if not extracting:
            return []
        for index, value in enumerate(tokens):
            if value == "-C" and index + 1 < len(tokens):
                targets.append(tokens[index + 1])
            elif value.startswith("-C") and len(value) > 2:
                targets.append(value[2:])
        return targets
    return []


def _nested_script(tokens: list[str], index: int) -> str | None:
    if index >= len(tokens) or Path(tokens[index]).name not in SHELL_COMMANDS:
        return None
    for position in range(index + 1, len(tokens) - 1):
        if tokens[position] == "-c":
            return tokens[position + 1]
    return None


def _inline_code(tokens: list[str], index: int) -> str | None:
    if index >= len(tokens) or Path(tokens[index]).name not in INLINE_INTERPRETERS:
        return None
    for position in range(index + 1, len(tokens) - 1):
        if tokens[position] in {"-c", "-e"}:
            return tokens[position + 1]
    return None


def _check_inline_code(code: str, root: Path) -> bool:
    for match in _INLINE_PATH.finditer(code):
        if _protected_write(match.group(0), root, allow_stop_report=True):
            return False
    return True


def _check_simple(tokens: list[str], root: Path, depth: int) -> bool:
    redirections = _redirection_targets(tokens)
    if redirections is None:
        return False
    if any(_protected_write(value, root) for value in redirections):
        return False
    if _option_targets(tokens, root):
        return False
    index = _command_index(tokens)
    if index >= len(tokens):
        return False
    nested = _nested_script(tokens, index)
    if nested is not None:
        if depth >= MAX_NESTING_DEPTH:
            return False
        nested_tokens = _tokenize(nested)
        nested_commands = _simple_commands(nested_tokens) if nested_tokens is not None else None
        return nested_commands is not None and all(
            _check_simple(command, root, depth + 1) for command in nested_commands
        )
    code = _inline_code(tokens, index)
    if code is not None and not _check_inline_code(code, root):
        return False
    command = Path(tokens[index]).name
    if command not in WRITE_COMMANDS:
        return True
    return not any(
        _protected_write(value, root)
        for value in _write_targets(tokens[index + 1:], command)
    )


def _terminal_allowed(command: str, root: Path) -> bool:
    tokens = _tokenize(command)
    commands = _simple_commands(tokens) if tokens is not None else None
    return commands is not None and all(_check_simple(item, root, 0) for item in commands)


def _patch_paths(value: str) -> list[str]:
    paths: list[str] = []
    for line in value.splitlines():
        for prefix in ("*** Update File: ", "*** Add File: ", "*** Delete File: "):
            if line.startswith(prefix):
                paths.append(line[len(prefix):].strip())
        if line.startswith("*** Move to: "):
            paths.append(line[len("*** Move to: "):].strip())
    return paths


def _editor_allowed(tool: str, tool_input: Any, root: Path) -> bool:
    if not isinstance(tool_input, dict):
        return False
    mapping = cast(dict[str, Any], tool_input)
    if tool == "file_editor" and mapping.get("command") == "view":
        return True
    if tool in {"apply_patch", "patch"}:
        patch = next(
            (
                mapping[key]
                for key in ("patch", "patch_text", "input")
                if isinstance(mapping.get(key), str)
            ),
            None,
        )
        paths = _patch_paths(patch) if isinstance(patch, str) else []
        return bool(paths) and not any(_protected_write(path, root) for path in paths)
    values = input_paths(tool_input, tool)
    return not any(_protected_write(value, root) for value in values)


def main() -> int:
    payload = event()
    root = project_dir(payload)
    tool = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input")
    if tool == "terminal":
        command = (
            cast(dict[str, Any], tool_input).get("command")
            if isinstance(tool_input, dict)
            else None
        )
        allowed = isinstance(command, str) and _terminal_allowed(command, root)
    elif tool in {"file_editor", "apply_patch", "patch"}:
        allowed = _editor_allowed(tool, tool_input, root)
    else:
        allowed = True
    if allowed:
        return 0
    result(decision="deny", reason=REASON)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
