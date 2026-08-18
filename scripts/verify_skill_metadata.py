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
REF_PATH = SKILLS_ROOT / "acd-package-ref.txt"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

IMPORT_RE = re.compile(r"^(?:from acd|import acd)\b", re.MULTILINE)
SCRIPT_BLOCK_RE = re.compile(
    r"(?ms)^# /// script[ \t]*\n(?P<body>(?:#.*\n)*)^# ///[ \t]*$"
)
REF_RE = re.compile(r"^(?:[0-9a-f]{40}|v\d+\.\d+\.\d+)$")
REQUIRES_RE = re.compile(r'(?m)^requires-python\s*=\s*"([^"]*)"\s*$')
DEPENDENCIES_RE = re.compile(r"(?ms)^dependencies\s*=\s*\[\s*(.*?)\s*\]")
DEPENDENCY_ENTRY_RE = re.compile(r'(?m)^\s*"([^"]*)"\s*,?\s*$')


def _relative(path: Path, repository: Path) -> str:
    return path.relative_to(repository).as_posix()


def _metadata_body(source: str) -> tuple[str | None, list[str], str | None]:
    match = SCRIPT_BLOCK_RE.match(source)
    if match is None:
        return None, [], "missing PEP 723 script block at the top of the file"

    body_lines: list[str] = []
    for line in match.group("body").splitlines():
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


def _read_ref(repository: Path, errors: list[str]) -> str | None:
    path = repository / "plugins" / "acd" / "skills" / "acd-package-ref.txt"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"{_relative(path, repository)}: cannot read ref: {error}")
        return None
    lines = raw.splitlines()
    ref = raw.strip()
    if len(lines) != 1 or not ref or lines[0].strip() != ref:
        errors.append(
            f"{_relative(path, repository)}: ref must contain exactly one non-empty line"
        )
        return None
    if REF_RE.fullmatch(ref) is None:
        errors.append(
            f"{_relative(path, repository)}: invalid pinned ref {ref!r}; "
            "expected a 40-character lowercase SHA or v<semver> tag"
        )
        return None
    return ref


def _read_requires_python(repository: Path, errors: list[str]) -> str | None:
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
    ref = _read_ref(repository, errors)
    requires_python = _read_requires_python(repository, errors)
    scripts_root = repository / "plugins" / "acd" / "skills"
    scripts = sorted(scripts_root.glob("*/scripts/*.py"))
    acd_scripts: list[Path] = []
    for script in scripts:
        try:
            source = script.read_text(encoding="utf-8")
        except OSError as error:
            errors.append(f"{_relative(script, repository)}: cannot read script: {error}")
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
        relative_script = _relative(script, repository)
        try:
            source = script.read_text(encoding="utf-8")
        except OSError:
            continue
        script_requires, dependencies, metadata_error = _metadata_body(source)
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
        relative_skill = _relative(skill, repository)
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
