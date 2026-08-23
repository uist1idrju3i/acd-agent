#!/usr/bin/env python3
"""Verify PEP 723 metadata for ACD Skill scripts."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_ROOT = REPO_ROOT / "plugins" / "acd" / "skills"

IMPORT_RE = re.compile(r"^(?:from acd|import acd)\b", re.MULTILINE)
SCRIPT_START_RE = re.compile(r"\A# /// script[ \t]*\r?\n")
SCRIPT_END_RE = re.compile(r"(?m)^# ///[ \t]*$")
REF_RE = re.compile(r"^(?:[0-9a-f]{40}|v\d+\.\d+\.\d+)$")
REQUIRES_RE = re.compile(r'(?m)^requires-python\s*=\s*"([^"]*)"\s*$')
DEPENDENCIES_RE = re.compile(r"(?ms)^dependencies\s*=\s*\[\s*(.*?)\s*\]")
DEPENDENCY_ENTRY_RE = re.compile(r'(?m)^\s*"([^"]*)"\s*,?\s*$')


def relative(path: Path, repository: Path) -> str:
    return path.relative_to(repository).as_posix()


def metadata_block(source: str) -> str | None:
    start = SCRIPT_START_RE.match(source)
    if start is None:
        return None
    end = SCRIPT_END_RE.search(source, start.end())
    if end is None:
        return None
    return source[start.start() : end.end()]


def metadata_body(source: str) -> tuple[str | None, list[str], str | None]:
    start = SCRIPT_START_RE.match(source)
    if start is None:
        return None, [], "missing PEP 723 script block at the top of the file"
    end = SCRIPT_END_RE.search(source, start.end())
    if end is None:
        return None, [], "PEP 723 script block is missing its closing marker"

    body_lines: list[str] = []
    for line in source[start.end() : end.start()].splitlines():
        if line == "#":
            body_lines.append("")
        elif line.startswith("# "):
            body_lines.append(line[2:])
        else:
            return None, [], "invalid non-comment line in PEP 723 script block"
    body = "\n".join(body_lines)

    requires = REQUIRES_RE.findall(body)
    if len(requires) != 1:
        return None, [], "PEP 723 block must contain exactly one requires-python"

    dependencies = DEPENDENCIES_RE.findall(body)
    if len(dependencies) != 1:
        return None, [], "PEP 723 block must contain exactly one dependencies array"
    entries = DEPENDENCY_ENTRY_RE.findall(dependencies[0])
    if len(entries) != 1:
        return None, [], "PEP 723 dependencies must contain exactly one string entry"
    return requires[0], entries, None


def read_ref(repository: Path, errors: list[str]) -> str | None:
    path = repository / "plugins" / "acd" / "skills" / "acd-package-ref.txt"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"{relative(path, repository)}: cannot read ref: {error}")
        return None
    lines = raw.splitlines()
    ref = raw.strip()
    if len(lines) != 1 or not ref or lines[0].strip() != ref:
        errors.append(
            f"{relative(path, repository)}: ref must contain exactly one non-empty line"
        )
        return None
    if REF_RE.fullmatch(ref) is None:
        errors.append(
            f"{relative(path, repository)}: invalid pinned ref {ref!r}; "
            "expected a 40-character lowercase SHA or v<semver> tag"
        )
        return None
    return ref


def read_requires_python(repository: Path, errors: list[str]) -> str | None:
    try:
        document = tomllib.loads(
            (repository / "pyproject.toml").read_text(encoding="utf-8")
        )
    except (OSError, tomllib.TOMLDecodeError) as error:
        errors.append(f"pyproject.toml: cannot parse project metadata: {error}")
        return None
    project = cast(dict[str, object], document.get("project", {}))
    requires = project.get("requires-python")
    if not isinstance(requires, str) or not requires:
        errors.append("pyproject.toml: project.requires-python is missing or invalid")
        return None
    return requires


def verify_repository(repository: Path = REPO_ROOT) -> list[str]:
    """Return all metadata drift errors found in a repository tree."""
    errors: list[str] = []
    ref = read_ref(repository, errors)
    requires_python = read_requires_python(repository, errors)
    scripts_root = repository / "plugins" / "acd" / "skills"
    scripts = sorted(scripts_root.glob("*/scripts/*.py"))
    acd_scripts: list[Path] = []
    for script in scripts:
        try:
            source = script.read_text(encoding="utf-8")
        except OSError as error:
            errors.append(f"{relative(script, repository)}: cannot read script: {error}")
            continue
        if IMPORT_RE.search(source) is not None:
            acd_scripts.append(script)

    if not acd_scripts:
        errors.append("fail-closed: no ACD-importing Skill scripts discovered")
        return errors

    expected_dependency = (
        f"acd @ git+https://github.com/uist1idrju3i/acd-agent@{ref}"
        if ref is not None
        else None
    )
    for script in acd_scripts:
        relative_script = relative(script, repository)
        try:
            source = script.read_text(encoding="utf-8")
        except OSError:
            continue
        script_requires, dependencies, metadata_error = metadata_body(source)
        if metadata_error is not None:
            errors.append(f"{relative_script}: {metadata_error}")
        elif requires_python is not None and script_requires != requires_python:
            errors.append(
                f"{relative_script}: requires-python {script_requires!r} does not match "
                f"pyproject.toml {requires_python!r}"
            )
        if expected_dependency is not None and dependencies != [expected_dependency]:
            errors.append(
                f"{relative_script}: dependencies must be exactly "
                f"[{expected_dependency!r}], found {dependencies!r}"
            )

        skill = script.parent.parent / "SKILL.md"
        relative_skill = relative(skill, repository)
        try:
            skill_text = skill.read_text(encoding="utf-8")
        except OSError as error:
            errors.append(f"{relative_skill}: cannot read owning SKILL.md: {error}")
            continue
        expected_command = f"uv run --script {relative_script}"
        if expected_command not in skill_text:
            errors.append(f"{relative_skill}: missing {expected_command!r}")
        old_command = f"uv run python {relative_script}"
        if old_command in skill_text:
            errors.append(f"{relative_skill}: contains forbidden {old_command!r}")
    return errors


def main() -> int:
    """Run metadata verification and print fail-closed diagnostics."""
    try:
        errors = verify_repository()
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        print(f"fail-closed: {error}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Skill metadata verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
