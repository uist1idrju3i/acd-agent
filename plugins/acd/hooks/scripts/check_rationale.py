"""Run the workspace rationale coverage check when its inputs are present.

``scripts/check_rationale.py`` belongs to the ACD repository checkout and is not part
of the copied plugin tree, so the installed-plugin path has no such script in the
conversation workspace. Invoking it unconditionally makes the hook exit with a missing
file and block every stop event. This wrapper keeps the check fail-closed where it can
apply: the rationale inputs decide whether the check is applicable, and a missing
validator with present inputs is a denial rather than a silent pass.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from common import event, project_dir, result

VALIDATOR_PATH = "scripts/check_rationale.py"


def _not_applicable(reason: str) -> int:
    print(json.dumps({"status": "not_applicable", "reason": reason}))
    return 0


def _deny(reason: str, *, warn_only: bool) -> int:
    if warn_only:
        print(reason)
        return 0
    result(decision="deny", reason=reason)
    return 2


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _target_from_environment(root: Path) -> tuple[Path | None, str | None]:
    raw = os.environ.get("ACD_TARGET_DESIGN")
    if raw is None:
        return None, None
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None, (
            f"declared target: ACD_TARGET_DESIGN is not a "
            f"repository-relative fixture: {raw!r}"
        )
    target = root / candidate
    try:
        if not target.resolve().is_relative_to(root.resolve()):
            return None, f"declared target: ACD_TARGET_DESIGN escapes the repository: {raw!r}"
    except OSError as exc:
        return None, f"declared target: ACD_TARGET_DESIGN could not be resolved: {exc}"
    if not (target / "graph.json").is_file():
        return None, f"declared target: ACD_TARGET_DESIGN has no graph.json: {raw!r}"
    return target, None


def _changed_fixture_dirs(root: Path) -> tuple[set[Path] | None, str | None]:
    try:
        changed = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return None, f"git status could not be obtained: {exc}"
    candidates: set[Path] = set()
    for line in changed.splitlines():
        if len(line) <= 3:
            continue
        path = line[3:]
        relative = Path(path)
        if not relative.as_posix().startswith("fixtures/"):
            continue
        if relative.name not in {"graph.json", "rationale.json"}:
            continue
        candidates.add(root / relative.parent)
    return candidates, None


def _resolve_target(root: Path) -> tuple[Path | None, str | None]:
    target, error = _target_from_environment(root)
    if target is not None or error is not None:
        return target, error

    changed, error = _changed_fixture_dirs(root)
    if error is not None:
        return None, error
    assert changed is not None
    if len(changed) == 1:
        return next(iter(changed)), None
    if len(changed) > 1:
        listed = ", ".join(sorted(_relative_path(root, path) for path in changed))
        return None, f"not applicable: target design is ambiguous; candidates: {listed}"

    graphs = sorted(root.glob("fixtures/**/graph.json"))
    if len(graphs) == 1:
        return graphs[0].parent, None
    listed = ", ".join(
        _relative_path(root, graph.parent) for graph in graphs
    )
    return None, (
        f"not applicable: target design could not be resolved; "
        f"candidates: {listed or '(none)'}"
    )


def main(argv: list[str]) -> int:
    warn_only = "--warn-only" in argv
    root = project_dir(event())
    target, target_error = _resolve_target(root)
    if target_error is not None:
        if "git status could not be obtained" in target_error:
            return _not_applicable(target_error)
        if target_error.startswith("not applicable:"):
            return _not_applicable(target_error)
        return _deny(target_error, warn_only=warn_only)
    assert target is not None
    graph_path = target / "graph.json"
    rationale_path = target / "rationale.json"
    if not graph_path.is_file():
        return _deny(
            f"resolved target design is missing graph.json: "
            f"{_relative_path(root, target)}",
            warn_only=warn_only,
        )
    if not rationale_path.is_file():
        return _deny(
            f"resolved target design is missing rationale.json: "
            f"{_relative_path(root, target)}",
            warn_only=warn_only,
        )
    validator = root / VALIDATOR_PATH
    if not validator.is_file():
        reason = (
            f"Rationale inputs are present but {VALIDATOR_PATH} cannot be resolved "
            f"under {root} for {_relative_path(root, graph_path)}."
        )
        return _deny(reason, warn_only=warn_only)
    command = [
        "uv",
        "run",
        "--project",
        str(root),
        "python",
        str(validator),
        "--graph",
        str(graph_path),
        "--rationale",
        str(rationale_path),
    ]
    if warn_only:
        command.append("--warn-only")
    try:
        completed = subprocess.run(command, cwd=root, check=False)
    except OSError as exc:
        reason = f"Rationale validation could not be executed: {exc}."
        return _deny(reason, warn_only=warn_only)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
