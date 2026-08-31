#!/usr/bin/env python3
"""Verify explicit UTF-8 handling for production text I/O."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# ASCII is stricter than UTF-8 and intentionally fails closed on non-ASCII Gerber data.
ALLOWED_ENCODINGS = {"ascii", "utf-8", "utf-8-sig"}
EXEMPTION_PREFIX = "# encoding-exempt:"
# Gerbonara parser classmethods are constructors, not filesystem text I/O.
NON_FILE_OPEN_OWNERS = {"GerberFile", "ExcellonFile"}


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    column: int
    rule: str
    detail: str

    def format(self) -> str:
        return (
            f"{self.path.relative_to(REPO_ROOT)}:{self.line}:{self.column}: "
            f"{self.rule}: {self.detail}"
        )


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _encoding_status(call: ast.Call) -> tuple[bool, str]:
    keyword = next((item for item in call.keywords if item.arg == "encoding"), None)
    if keyword is None:
        return False, "encoding= is required"
    value = _literal_string(keyword.value)
    if value not in ALLOWED_ENCODINGS:
        return False, 'encoding= must be the literal "utf-8" or "utf-8-sig"'
    return True, ""


def _attribute_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _contains_name(node: ast.AST, names: set[str]) -> bool:
    return any(
        isinstance(child, ast.Name) and child.id in names
        for child in ast.walk(node)
    )


def _call_name(call: ast.Call) -> tuple[str | None, str | None]:
    function = call.func
    if isinstance(function, ast.Name):
        return function.id, None
    if isinstance(function, ast.Attribute):
        return function.attr, _attribute_name(function.value)
    return None, None


def _is_true_literal(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _exemption_state(source_lines: list[str], line: int) -> bool | None:
    if not 1 <= line <= len(source_lines):
        return None
    comment = source_lines[line - 1].split(EXEMPTION_PREFIX, 1)
    if len(comment) != 2:
        return None
    return bool(comment[1].strip())


class _EncodingVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, source_lines: list[str]) -> None:
        self.path = path
        self.source_lines = source_lines
        self.violations: list[Violation] = []

    def _report(self, call: ast.Call, rule: str, detail: str) -> None:
        exemption = _exemption_state(self.source_lines, call.lineno)
        if exemption is True:
            return
        if exemption is False:
            detail = "encoding-exempt requires a non-empty English reason"
        self.violations.append(
            Violation(
                self.path,
                call.lineno,
                call.col_offset + 1,
                rule,
                detail,
            )
        )

    def visit_Call(self, node: ast.Call) -> None:
        call = node
        name, owner = _call_name(call)
        if name == "open":
            if _contains_name(call.func, NON_FILE_OPEN_OWNERS):
                self.generic_visit(call)
                return
            if isinstance(call.func, ast.Name):
                positional_mode = call.args[1] if len(call.args) > 1 else None
            else:
                positional_mode = call.args[0] if call.args else None
            mode = _literal_string(
                next(
                    (item.value for item in call.keywords if item.arg == "mode"),
                    positional_mode,
                )
            )
            if mode is None or "b" not in mode:
                valid, detail = _encoding_status(call)
                if not valid:
                    self._report(call, "open-encoding", detail)
        elif name in {"read_text", "write_text"}:
            valid, detail = _encoding_status(call)
            if not valid:
                self._report(call, "text-method-encoding", detail)
        elif owner == "subprocess" and name in {
            "run",
            "Popen",
            "check_output",
            "check_call",
        }:
            text_mode = any(
                item.arg in {"text", "universal_newlines"}
                and _is_true_literal(item.value)
                for item in call.keywords
            )
            if text_mode:
                valid, detail = _encoding_status(call)
                if not valid:
                    self._report(call, "subprocess-encoding", detail)
        elif owner == "io" and name == "TextIOWrapper":
            valid, detail = _encoding_status(call)
            if not valid:
                self._report(call, "textiowrapper-encoding", detail)
        self.generic_visit(call)


def check_file(path: Path) -> list[Violation]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [
            Violation(
                path,
                1,
                1,
                "file-read",
                f"cannot read source as UTF-8: {exc}",
            )
        ]
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            Violation(
                path,
                exc.lineno or 1,
                exc.offset or 1,
                "syntax-error",
                str(exc),
            )
        ]
    visitor = _EncodingVisitor(path, source.splitlines())
    visitor.visit(tree)
    return visitor.violations


def source_files() -> list[Path]:
    files = set((REPO_ROOT / "src" / "acd").rglob("*.py"))
    files.update(
        path
        for path in (REPO_ROOT / "scripts").rglob("*.py")
        if "tests" not in path.relative_to(REPO_ROOT / "scripts").parts
    )
    files.update((REPO_ROOT / "plugins").glob("**/scripts/**/*.py"))
    return sorted(files)


def main(argv: list[str] | None = None) -> int:
    del argv
    violations = [
        violation
        for path in source_files()
        for violation in check_file(path)
    ]
    for violation in violations:
        print(violation.format())
    print(f"verify_text_encoding: {len(violations)} violation(s)")
    return 2 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
