"""Deny writes that touch generated ACD projections."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from common import (
    REASON,
    RUNNER_GUIDANCE,
    STOP_REPORT_PATH,
    event,
    project_dir,
    result,
)

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
READ_ONLY_COMMANDS = frozenset(
    {
        "cat", "grep", "egrep", "fgrep", "rg", "head", "tail", "less",
        "more", "wc", "ls", "stat", "file", "diff", "cmp", "md5sum",
        "sha1sum", "sha256sum", "jq", "sort", "uniq", "cut", "tr", "echo",
        "printf", "test", "[", "true", "false", "du", "tree", "realpath",
        "readlink", "basename", "dirname", "strings", "hexdump", "xxd",
        "od", "nl", "tac", "column",
    }
)
REDIRECTS = frozenset({">", ">>", "2>", "&>", ">|"})
SEPARATORS = frozenset({";", "&&", "||", "|", "&"})
MAX_NESTING_DEPTH = 4
WRAPPER_COMMANDS = frozenset({"ssh", "docker", "podman", "kubectl", "chroot", "nsenter"})
_SSH_VALUE_OPTIONS = frozenset(
    {
        "-p", "-l", "-i", "-F", "-o", "-J", "-L", "-R", "-D", "-W",
        "-b", "-c", "-m", "-O", "-Q", "-S", "-E", "-e", "-B", "-w",
    }
)
_DOCKER_GLOBAL_VALUE_OPTIONS = frozenset(
    {"-H", "--host", "--config", "--context", "-D", "--log-level", "-l"}
)
_DOCKER_WRAPPER_SUBCOMMANDS = frozenset({"exec", "run", "create"})
_DOCKER_EXEC_VALUE_OPTIONS = frozenset(
    {"-e", "--env", "-u", "--user", "-w", "--workdir", "--env-file", "--detach-keys"}
)
_DOCKER_RUN_VALUE_OPTIONS = frozenset(
    {
        "-e", "--env", "-v", "--volume", "--mount", "-w", "--workdir",
        "-u", "--user", "--name", "--entrypoint", "-p", "--publish",
        "--network", "--platform", "-m", "--memory", "--memory-swap",
        "--cpus", "--label", "-l", "--env-file", "--add-host", "--device",
        "--gpus", "--shm-size", "--pull", "--restart", "--log-driver",
        "--log-opt", "--ulimit", "--security-opt", "--cap-add", "--cap-drop",
        "--tmpfs", "--hostname", "-h", "--pid", "--ipc", "--uts",
        "--cgroupns", "--stop-timeout", "--health-cmd", "--sysctl", "--dns",
        "--group-add",
    }
)
_KUBECTL_VALUE_OPTIONS = frozenset({"-n", "--namespace", "-c", "--container"})
_NSENTER_VALUE_OPTIONS = frozenset({"-t", "--target", "-S", "-G", "-w", "-r"})
_DYNAMIC_EXEC = re.compile(
    r"\b(?:exec|eval|compile|__import__)\s*\(|\bbase64\."
    r"(?:b64decode|b32decode|b16decode|a85decode|b85decode)\s*\(|"
    r"\bcodecs\.decode\s*\(|\bmarshal\.loads?\s*\(|"
    r"\bimportlib\.import_module\s*\(|\bzlib\.decompress\s*\(|"
    r"\bbytes\.fromhex\s*\("
)
_PIPELINE_ENTRY = re.compile(
    r"(?:^|/)scripts/(?:run|resolve)_[a-z0-9_]+\.py$"
    r"|(?:^|/)scripts/build_design_fixture\.py$"
    r"|(?:^|/)run_design_(?:loop|lanes)$"
    r"|(?:^|/)acd-[a-z0-9_-]+$"
)
_CONTAINER_IMAGE_PREFIXES = ("acd-server", "acd-tools")


@dataclass(frozen=True)
class Denial:
    """A projection-protection denial with its judgment kind and token."""

    kind: str
    token: str


@dataclass(frozen=True)
class WrapperInfo:
    """Split details of a recognised wrapper command.

    ``inner_index`` is the token index where the inner command begins (equal
    to ``len(tokens)`` when the wrapper carries none). ``image`` is the
    image token of a container ``run``/``create``. ``pipeline_check`` marks
    wrappers whose inner command may invoke pipeline entry points
    (container ``exec``/``run``).
    """

    inner_index: int
    image: str | None
    pipeline_check: bool
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_UNSUPPORTED_SYNTAX = re.compile(r"\$\(|`|<\(|>\(|[(){}]")
_COMMAND_SUBSTITUTION = re.compile(r"\$\(|`|<\(|>\(")
_HEREDOC = re.compile(
    r"(?<!<)<<-?(?!<)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1"
)
_INLINE_WRITE_INDICATOR = re.compile(
    r"\b(?:write_text|write_bytes|unlink|rmtree|rename|replace|remove|"
    r"removedirs|rmdir|mkdir|makedirs|touch|chmod|chown|copy|copy2|copyfile|"
    r"copytree|move|system|subprocess|popen|Popen|exec|eval|__import__|"
    r"importlib|truncate|symlink|link|dump|dumps|to_csv|to_json|save|savefig|"
    r"writeFile|writeFileSync|unlinkSync|renameSync|rmSync|child_process|"
    r"execSync|spawn)\b"
    r"|open\([^)]*['\"][rb]*[wax+][rbt+]*['\"]"
    r"|open\([^)]*\bmode\s*="
)
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


def _split_heredocs(command: str) -> tuple[str, dict[str, str]] | None:
    """Extract heredoc bodies so they are not parsed as commands.

    Returns the command with each `<<[-]WORD` operator replaced by a
    `__acd_heredoc_N__` placeholder token and a mapping of placeholder to
    body text. Returns None on an unterminated heredoc.
    """
    if "<<" not in command:
        return command, {}
    lines = command.splitlines()
    output: list[str] = []
    bodies: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        pending = list(_HEREDOC.finditer(line))
        if not pending:
            output.append(line)
            continue
        # Rebuild the line with operators replaced by placeholder tokens.
        rebuilt: list[str] = []
        cursor = 0
        operators: list[tuple[str, bool, str]] = []
        for match in pending:
            rebuilt.append(line[cursor:match.start()])
            delimiter = match.group(2)
            strip_tabs = match.group(0).startswith("<<-")
            placeholder = f"__acd_heredoc_{len(bodies)}__"
            rebuilt.append(placeholder)
            operators.append((delimiter, strip_tabs, placeholder))
            cursor = match.end()
        rebuilt.append(line[cursor:])
        output.append("".join(rebuilt))
        for delimiter, strip_tabs, placeholder in operators:
            body: list[str] = []
            closed = False
            while index < len(lines):
                candidate = lines[index]
                index += 1
                normalized = candidate.lstrip("\t") if strip_tabs else candidate
                if normalized == delimiter:
                    closed = True
                    break
                body.append(candidate)
            if not closed:
                return None
            bodies[placeholder] = "\n".join(body)
    return "\n".join(output), bodies


def _tokenize(command: str) -> list[str] | None:
    if "\x00" in command:
        return None
    normalized: list[str] = []
    quote: str | None = None
    escaped = False
    for character in command:
        if escaped:
            normalized.append(character)
            escaped = False
            continue
        if character == "\\":
            normalized.append(character)
            escaped = True
            continue
        if quote is None and character in {"'", '"'}:
            quote = character
        elif quote == character:
            quote = None
        if character == "\n" and quote is None:
            normalized.append(";")
        else:
            normalized.append(character)
    try:
        lexer = shlex.shlex("".join(normalized), posix=True, punctuation_chars=";&|<>")
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
        # An escaped `;` (e.g. find -exec terminator) loses its escape and
        # becomes a separator; a trailing separator runs nothing further.
        return commands if commands else None
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


def _option_targets(tokens: list[str], root: Path) -> str | None:
    """Return the offending output-option token, or ``None`` when allowed."""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in OUTPUT_OPTIONS:
            if index + 1 >= len(tokens):
                return token
            value = tokens[index + 1]
            _, resolvable, _ = _path_status(value, root)
            if not resolvable:
                return value
            index += 2
            continue
        if any(token.startswith(option + "=") for option in OUTPUT_OPTIONS):
            value = token.split("=", 1)[1]
            _, resolvable, _ = _path_status(value, root)
            if not value or not resolvable:
                return token
        index += 1
    return None


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
        targets: list[str] = []
        for position, token in enumerate(tokens):
            if token in {"-t", "--target-directory"} and position + 1 < len(tokens):
                targets.append(tokens[position + 1])
            elif token.startswith("--target-directory="):
                targets.append(token.split("=", 1)[1])
        values = _non_option_values(
            tokens,
            skip_value_options=frozenset({"-t", "--target-directory", "-T"}),
        )
        if command == "mv":
            targets.extend(values)
        else:
            targets.extend(values[-1:] if values else [])
        return targets
    if command == "dd":
        return [
            value.split("=", 1)[1]
            for value in tokens
            if value.startswith("of=") and value.split("=", 1)[1]
        ]
    if command == "tee":
        return _non_option_values(tokens, skip_value_options=frozenset())
    if command == "sed":
        options_ended = False
        in_place = False
        for value in tokens:
            if value == "--":
                options_ended = True
                continue
            if options_ended:
                continue
            in_place |= value == "--in-place" or value.startswith("--in-place=")
            in_place |= value.startswith("-") and not value.startswith("--") and "i" in value[1:]
        if not in_place:
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


def _first_protected_reference(value: str, root: Path) -> str | None:
    for match in _INLINE_PATH.finditer(value):
        if _protected_write(match.group(0), root):
            return match.group(0)
    return None


def _xargs_command(tokens: list[str]) -> list[str]:
    value_options = frozenset(
        {
            "-a", "-d", "-E", "-I", "-J", "-L", "-n", "-P", "-s",
            "--arg-file", "--delimiter", "--eof", "--max-args",
            "--max-lines", "--max-procs", "--replace",
        }
    )
    index = 0
    while index < len(tokens) and tokens[index].startswith("-"):
        index = _skip_option(tokens, index, value_options=value_options)
    return tokens[index:]


def _find_write_targets(tokens: list[str]) -> tuple[list[str], list[list[str]]]:
    roots: list[str] = []
    inner_commands: list[list[str]] = []
    index = 0
    while index < len(tokens) and not tokens[index].startswith("-"):
        roots.append(tokens[index])
        index += 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-delete", "-fprint", "-fprint0", "-fls", "-fprintf"}:
            if token != "-delete" and index + 1 < len(tokens):
                roots.append(tokens[index + 1])
                index += 2
            else:
                index += 1
            continue
        if token in {"-exec", "-execdir", "-ok", "-okdir"}:
            index += 1
            inner: list[str] = []
            while index < len(tokens) and tokens[index] not in {";", "+"}:
                inner.append(tokens[index])
                index += 1
            if inner:
                inner_commands.append(inner)
            if index < len(tokens):
                index += 1
            continue
        index += 1
    return roots, inner_commands


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


def _check_inline_code(code: str, root: Path) -> Denial | None:
    # Dynamic execution and decode primitives cannot be inspected, so they are
    # denied even without a visible protected reference (they are not
    # read-only inline code).
    dynamic = _DYNAMIC_EXEC.search(code)
    if dynamic is not None:
        protected = _first_protected_reference(code, root)
        token = dynamic.group(0)
        if protected is not None:
            token = f"{token} {protected}"
        return Denial("dynamic_exec", token)
    indicator = _INLINE_WRITE_INDICATOR.search(code)
    if indicator is not None:
        protected = _first_protected_reference(code, root)
        if protected is not None:
            return Denial("inline_write", f"{indicator.group(0)} {protected}")
    return None


def _unsupported_syntax_denial(tokens: list[str], root: Path) -> Denial | None:
    joined = " ".join(tokens)
    # `<` and `>` are tokenized as separate punctuation, so `<(`/`>(` appear as
    # a redirect-looking token followed by a `(`-led token rather than one word.
    has_substitution = _COMMAND_SUBSTITUTION.search(joined) is not None or any(
        token.endswith(("<", ">"))
        and position + 1 < len(tokens)
        and tokens[position + 1].startswith("(")
        for position, token in enumerate(tokens)
    )
    if has_substitution or _UNSUPPORTED_SYNTAX.search(joined):
        protected = _first_protected_reference(joined, root)
        if protected is not None:
            return Denial("unsupported_syntax", protected)
    return None


def _skip_flag_sequence(
    tokens: list[str], index: int, *, value_options: frozenset[str]
) -> int:
    while index < len(tokens) and tokens[index].startswith("-"):
        if tokens[index] == "--":
            return index + 1
        index = _skip_option(tokens, index, value_options=value_options)
    return index


def _wrapper_inner(
    tokens: list[str], index: int
) -> tuple[list[str] | None, WrapperInfo | None]:
    """Split a recognised wrapper command into its inner command tokens.

    Returns ``(inner, info)`` for a recognised wrapper (``inner`` is ``None``
    when the wrapper carries no inner command) and ``(None, None)`` when the
    command is not a recognised wrapper.
    """
    if index >= len(tokens):
        return None, None
    name = Path(tokens[index]).name
    if name not in WRAPPER_COMMANDS:
        return None, None
    if name == "ssh":
        cursor = _skip_flag_sequence(
            tokens, index + 1, value_options=_SSH_VALUE_OPTIONS
        )
        if cursor >= len(tokens):
            return None, WrapperInfo(len(tokens), None, False)
        inner_index = cursor + 1  # skip the host token
        inner = tokens[inner_index:]
        return inner or None, WrapperInfo(inner_index, None, False)
    if name in {"docker", "podman"}:
        cursor = _skip_flag_sequence(
            tokens, index + 1, value_options=_DOCKER_GLOBAL_VALUE_OPTIONS
        )
        if cursor >= len(tokens):
            return None, None
        subcommand = tokens[cursor]
        cursor += 1
        if subcommand == "container" and cursor < len(tokens):
            subcommand = tokens[cursor]
            cursor += 1
        if subcommand not in _DOCKER_WRAPPER_SUBCOMMANDS:
            return None, None
        value_options = (
            _DOCKER_EXEC_VALUE_OPTIONS
            if subcommand == "exec"
            else _DOCKER_RUN_VALUE_OPTIONS
        )
        cursor = _skip_flag_sequence(tokens, cursor, value_options=value_options)
        image: str | None = None
        if subcommand == "exec":
            inner_index = min(cursor + 1, len(tokens))  # skip the container token
        else:
            if cursor < len(tokens):
                image = tokens[cursor]
            inner_index = min(cursor + 1, len(tokens))
        inner = tokens[inner_index:]
        info = WrapperInfo(
            inner_index,
            image if subcommand in {"run", "create"} else None,
            subcommand in {"exec", "run"},
        )
        return inner or None, info
    if name == "kubectl":
        cursor = index + 1
        if cursor >= len(tokens) or tokens[cursor] != "exec":
            return None, None
        cursor = _skip_flag_sequence(
            tokens, cursor + 1, value_options=_KUBECTL_VALUE_OPTIONS
        )
        if cursor >= len(tokens):
            return None, WrapperInfo(len(tokens), None, False)
        inner_index = cursor + 1  # skip the pod token
        if inner_index < len(tokens) and tokens[inner_index] == "--":
            inner_index += 1
        inner = tokens[inner_index:]
        return inner or None, WrapperInfo(inner_index, None, False)
    if name == "chroot":
        cursor = _skip_flag_sequence(
            tokens, index + 1, value_options=frozenset()
        )
        if cursor >= len(tokens):
            return None, WrapperInfo(len(tokens), None, False)
        inner_index = cursor + 1  # skip the newroot token
        inner = tokens[inner_index:]
        return inner or None, WrapperInfo(inner_index, None, False)
    # nsenter
    inner_index = _skip_flag_sequence(
        tokens, index + 1, value_options=_NSENTER_VALUE_OPTIONS
    )
    inner = tokens[inner_index:]
    return inner or None, WrapperInfo(inner_index, None, False)


def _check_wrapper(
    tokens: list[str],
    index: int,
    inner: list[str] | None,
    info: WrapperInfo,
    root: Path,
    depth: int,
    heredocs: dict[str, str],
) -> Denial | None:
    if info.image is not None:
        base = info.image.rsplit("/", 1)[-1].split("@", 1)[0].split(":", 1)[0]
        if base.startswith(_CONTAINER_IMAGE_PREFIXES):
            return Denial("raw_container_image", info.image)
    if inner and info.pipeline_check:
        for token in inner:
            if _PIPELINE_ENTRY.search(token):
                return Denial("raw_container_pipeline", token)
    # The wrapper's own tokens keep the generic shell checks; the inner
    # command is evaluated recursively below. Wrapper commands are neither
    # read-only nor write commands, so the substitution and unsupported-syntax
    # checks both apply to them.
    denial = _unsupported_syntax_denial(tokens[index : info.inner_index], root)
    if denial is not None:
        return denial
    if not inner:
        return None
    if depth >= MAX_NESTING_DEPTH:
        return Denial("nesting_depth", inner[0])
    if len(inner) == 1:
        # A wrapper such as ssh joins its arguments into one remote shell
        # string, so a single token is re-tokenized as that string.
        inner_tokens = _tokenize(inner[0])
        if inner_tokens is None:
            return Denial("unparseable_command", inner[0])
    else:
        inner_tokens = inner
    inner_commands = _simple_commands(inner_tokens)
    if inner_commands is None:
        return Denial("unparseable_command", " ".join(inner)[:120])
    for item in inner_commands:
        denial = _check_simple(item, root, depth + 1, heredocs)
        if denial is not None:
            return denial
    return None


def _check_simple(
    tokens: list[str],
    root: Path,
    depth: int,
    heredocs: dict[str, str],
) -> Denial | None:
    redirections = _redirection_targets(tokens)
    if redirections is None:
        return Denial("unparseable_command", " ".join(tokens)[:120])
    for value in redirections:
        if _protected_write(value, root):
            return Denial("redirect_target", value)
    option = _option_targets(tokens, root)
    if option is not None:
        return Denial("output_option", option)
    index = _command_index(tokens)
    if index >= len(tokens):
        return Denial("unparseable_command", " ".join(tokens)[:120])
    nested = _nested_script(tokens, index)
    if nested is not None:
        if depth >= MAX_NESTING_DEPTH:
            return Denial("nesting_depth", nested[:120])
        nested_tokens = _tokenize(nested)
        nested_commands = _simple_commands(nested_tokens) if nested_tokens is not None else None
        if nested_commands is None:
            return Denial("unparseable_command", nested[:120])
        for command in nested_commands:
            denial = _check_simple(command, root, depth + 1, heredocs)
            if denial is not None:
                return denial
        return None
    code = _inline_code(tokens, index)
    if code is not None:
        return _check_inline_code(code, root)
    command = Path(tokens[index]).name
    inner, wrapper = _wrapper_inner(tokens, index)
    if wrapper is not None:
        return _check_wrapper(tokens, index, inner, wrapper, root, depth, heredocs)
    if command == "xargs":
        protected = _first_protected_reference(" ".join(tokens), root)
        if protected is not None:
            return Denial("protected_path_token", protected)
        inner_command = _xargs_command(tokens[index + 1:])
        if not inner_command:
            return None
        return _check_simple(inner_command, root, depth, heredocs)
    if command == "find":
        roots, inner_commands = _find_write_targets(tokens[index + 1:])
        has_write_primary = any(
            value in {"-delete", "-fprint", "-fprint0", "-fls", "-fprintf", "-exec",
                      "-execdir", "-ok", "-okdir"}
            for value in tokens[index + 1:]
        )
        if not has_write_primary:
            return None
        for value in roots:
            if _protected_write(value, root):
                return Denial("write_target", value)
        for inner_command in inner_commands:
            denial = _check_simple(inner_command, root, depth, heredocs)
            if denial is not None:
                return denial
        return None
    if command == "eval":
        protected = _first_protected_reference(" ".join(tokens[index + 1:]), root)
        if protected is not None:
            return Denial("protected_path_token", protected)
    for position, token in enumerate(tokens):
        body = heredocs.get(token)
        if body is None:
            continue
        if command in SHELL_COMMANDS:
            if depth >= MAX_NESTING_DEPTH:
                return Denial("nesting_depth", body[:120])
            body_tokens = _tokenize(body)
            body_commands = (
                _simple_commands(body_tokens) if body_tokens is not None else None
            )
            if body_commands is None:
                return Denial("unparseable_command", body[:120])
            for item in body_commands:
                denial = _check_simple(item, root, depth + 1, heredocs)
                if denial is not None:
                    return denial
        elif command in INLINE_INTERPRETERS or command in {"eval", "xargs"}:
            denial = _check_inline_code(body, root)
            if denial is not None:
                return denial
        tokens[position] = "-"
    joined = " ".join(tokens)
    # `<` and `>` are tokenized as separate punctuation, so `<(`/`>(` appear as
    # a redirect-looking token followed by a `(`-led token rather than one word.
    has_substitution = _COMMAND_SUBSTITUTION.search(joined) is not None or any(
        token.endswith(("<", ">"))
        and position + 1 < len(tokens)
        and tokens[position + 1].startswith("(")
        for position, token in enumerate(tokens)
    )
    if has_substitution:
        protected = _first_protected_reference(joined, root)
        if protected is not None:
            return Denial("unsupported_syntax", protected)
    if command in READ_ONLY_COMMANDS:
        return None
    if _UNSUPPORTED_SYNTAX.search(joined):
        protected = _first_protected_reference(joined, root)
        if protected is not None:
            return Denial("unsupported_syntax", protected)
    if command not in WRITE_COMMANDS:
        return None
    arguments = tokens[index + 1:]
    mv_sources: tuple[str, ...] = ()
    if command == "mv":
        values = _non_option_values(
            arguments,
            skip_value_options=frozenset({"-t", "--target-directory", "-T"}),
        )
        mv_sources = tuple(values[:-1]) if values else ()
    for value in _write_targets(arguments, command):
        if _protected_write(value, root):
            kind = "mv_source" if value in mv_sources else "write_target"
            return Denial(kind, value)
    return None


def _terminal_denial(command: str, root: Path) -> Denial | None:
    if command.strip() == "":
        return None
    split = _split_heredocs(command)
    if split is None:
        return Denial("unterminated_heredoc", command.strip()[:120])
    text, heredocs = split
    tokens = _tokenize(text)
    commands = _simple_commands(tokens) if tokens is not None else None
    if commands is None:
        return Denial("unparseable_command", command.strip()[:120])
    if any(
        _command_index(item) < len(item)
        and Path(item[_command_index(item)]).name == "xargs"
        for item in commands
    ):
        protected = _first_protected_reference(command, root)
        if protected is not None:
            return Denial("protected_path_token", protected)
    for item in commands:
        denial = _check_simple(item, root, 0, heredocs)
        if denial is not None:
            return denial
    return None


def _terminal_allowed(  # pyright: ignore[reportUnusedFunction]
    command: str, root: Path
) -> bool:
    """Bool compatibility wrapper over :func:`_terminal_denial`."""
    return _terminal_denial(command, root) is None


def _patch_paths(value: str) -> list[str]:
    paths: list[str] = []
    for line in value.splitlines():
        for prefix in ("*** Update File: ", "*** Add File: ", "*** Delete File: "):
            if line.startswith(prefix):
                paths.append(line[len(prefix):].strip())
        if line.startswith("*** Move to: "):
            paths.append(line[len("*** Move to: "):].strip())
    return paths


def _editor_denial(tool: str, tool_input: Any, root: Path) -> Denial | None:
    if not isinstance(tool_input, dict):
        return Denial("editor_path", tool)
    mapping = cast(dict[str, Any], tool_input)
    if tool == "file_editor" and mapping.get("command") == "view":
        return None
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
        if not paths:
            return Denial("patch_path", "")
        for path in paths:
            if _protected_write(path, root):
                return Denial("patch_path", path)
        return None
    for value in input_paths(tool_input, tool):
        if _protected_write(value, root):
            return Denial("editor_path", value)
    return None


def _editor_allowed(  # pyright: ignore[reportUnusedFunction]
    tool: str, tool_input: Any, root: Path
) -> bool:
    """Bool compatibility wrapper over :func:`_editor_denial`."""
    return _editor_denial(tool, tool_input, root) is None


def main() -> int:
    payload = event()
    root = project_dir(payload)
    tool = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input")
    denial: Denial | None
    if tool == "terminal":
        command = (
            cast(dict[str, Any], tool_input).get("command")
            if isinstance(tool_input, dict)
            else None
        )
        denial = (
            _terminal_denial(command, root)
            if isinstance(command, str)
            else Denial("unparseable_command", tool)
        )
    elif tool in {"file_editor", "apply_patch", "patch"}:
        denial = _editor_denial(tool, tool_input, root)
    else:
        denial = None
    if denial is None:
        return 0
    reason = f"{REASON} [denied: {denial.kind}: {denial.token}]"
    if denial.kind in {"raw_container_image", "raw_container_pipeline"}:
        reason = f"{reason} {RUNNER_GUIDANCE}"
    result(decision="deny", reason=reason)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
