#!/usr/bin/env python3
"""Verify the import boundary between ACD core and plugin Skills.

AGENTS.md forbids importing Skill Python modules from ACD itself: Skills are
invoked as subprocesses.  Skill scripts may import ``acd.*`` (the package
contract records the symbols), but not another Skill's scripts.  This script
parses every module with ``ast`` and fails closed on:

1. ``src/acd`` or ``scripts`` importing ``plugins`` or a bare module name that
   only exists as a Skill or hook script;
2. ``src/acd`` mutating ``sys.path``;
3. a Skill script importing a bare module that lives in a different Skill's
   ``scripts/`` directory.

Output is an L3 report and grants no pass authority.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Literal

from acd.schema.common import AcdModel, NonEmptyStr

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_ROOTS: tuple[str, ...] = ("src/acd", "scripts")
SKILLS_ROOT = "plugins/acd/skills"
HOOK_SCRIPTS_ROOT = "plugins/acd/hooks/scripts"


class BoundaryViolation(AcdModel):
    path: NonEmptyStr
    line: int
    rule: Literal["core_imports_skill", "core_mutates_sys_path", "skill_imports_other_skill"]
    detail: NonEmptyStr


class BoundaryReport(AcdModel):
    record_class: Literal["L3"] = "L3"
    pass_evidence: Literal[False] = False
    status: Literal["pass", "fail"]
    scanned_files: int
    violations: list[BoundaryViolation]


def _python_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.py")
        if "tests" not in path.relative_to(root).parts and "__pycache__" not in path.parts
    )


def _skill_script_modules(repo: Path) -> dict[str, set[str]]:
    """Map each Skill (or the hooks dir) to the bare module names under scripts/."""
    modules: dict[str, set[str]] = {}
    for scripts_dir in sorted((repo / SKILLS_ROOT).glob("*/scripts")):
        modules[scripts_dir.parent.name] = {
            path.stem for path in scripts_dir.glob("*.py") if path.stem != "__init__"
        }
    hooks = repo / HOOK_SCRIPTS_ROOT
    if hooks.is_dir():
        modules["hooks"] = {path.stem for path in hooks.glob("*.py") if path.stem != "__init__"}
    return modules


def _imports(tree: ast.Module) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.lineno, node.module))
    return found


def _mutates_sys_path(tree: ast.Module) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in {"insert", "append", "extend"}
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "path"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "sys"
        ):
            lines.append(node.lineno)
    return lines


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def build_report(repo: Path) -> BoundaryReport:
    skill_modules = _skill_script_modules(repo)
    all_skill_modules: set[str] = set()
    for modules in skill_modules.values():
        all_skill_modules |= modules
    violations: list[BoundaryViolation] = []
    scanned = 0

    for root_name in CORE_ROOTS:
        for path in _python_files(repo / root_name):
            scanned += 1
            rel = path.relative_to(repo).as_posix()
            tree = _parse(path)
            for line, module in _imports(tree):
                top = module.split(".", 1)[0]
                if top == "plugins" or top in all_skill_modules:
                    violations.append(
                        BoundaryViolation(
                            path=rel,
                            line=line,
                            rule="core_imports_skill",
                            detail=f"imports Skill module {module!r}",
                        )
                    )
            if root_name == "src/acd":
                for line in _mutates_sys_path(tree):
                    violations.append(
                        BoundaryViolation(
                            path=rel,
                            line=line,
                            rule="core_mutates_sys_path",
                            detail="sys.path mutation",
                        )
                    )

    for skill, own_modules in skill_modules.items():
        scripts_dir = (
            repo / HOOK_SCRIPTS_ROOT if skill == "hooks" else repo / SKILLS_ROOT / skill / "scripts"
        )
        for path in _python_files(scripts_dir):
            scanned += 1
            rel = path.relative_to(repo).as_posix()
            for line, module in _imports(_parse(path)):
                top = module.split(".", 1)[0]
                if top in own_modules or top not in all_skill_modules:
                    continue
                owners = sorted(name for name, mods in skill_modules.items() if top in mods)
                violations.append(
                    BoundaryViolation(
                        path=rel,
                        line=line,
                        rule="skill_imports_other_skill",
                        detail=f"imports {module!r} owned by {', '.join(owners)}",
                    )
                )

    violations.sort(key=lambda v: (v.path, v.line, v.rule))
    return BoundaryReport(
        status="fail" if violations else "pass",
        scanned_files=scanned,
        violations=violations,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)
    report = build_report(args.root.resolve())
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False))
    else:
        for violation in report.violations:
            print(
                f"{violation.path}:{violation.line}: {violation.rule}: {violation.detail}",
                file=sys.stderr,
            )
        print(
            f"verify_import_boundaries: {report.status} "
            f"({report.scanned_files} files, {len(report.violations)} violation(s))"
        )
    return 0 if report.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
