#!/usr/bin/env python3
"""Classify a change as documentation-only for the CI fast path."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

_Run = Callable[[list[str]], str]
_CORE_PREFIXES = (
    "src/",
    "tests/",
    "scripts/",
    ".github/workflows/",
)


def _git_diff(command: list[str]) -> str:
    result = subprocess.run(
        command,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def _changed_files(
    base_sha: str | None, head_sha: str | None, *, run: _Run
) -> list[str] | None:
    if not base_sha or not head_sha:
        return None
    try:
        changed_files = [
            line
            for line in run(["git", "diff", "--name-only", base_sha, head_sha]).splitlines()
            if line
        ]
    except (OSError, RuntimeError, subprocess.CalledProcessError):
        return None
    if not changed_files:
        return None
    return changed_files


def _classify_changes(
    base_sha: str | None, head_sha: str | None, *, run: _Run
) -> tuple[bool, bool, bool]:
    changed_files = _changed_files(base_sha, head_sha, run=run)
    if changed_files is None:
        return True, True, True
    code_changes = any(not path.endswith(".md") for path in changed_files)
    core_changes = any(
        path.startswith(_CORE_PREFIXES)
        or path in {"pyproject.toml", "uv.lock"}
        for path in changed_files
    )
    plugin_changes = any(path.startswith("plugins/") for path in changed_files)
    return code_changes, core_changes, plugin_changes


def _write_result(
    code_changes: bool,
    core_changes: bool,
    plugin_changes: bool,
    output_path: str | None,
) -> None:
    result = "".join(
        (
            f"code={'true' if code_changes else 'false'}\n",
            f"core={'true' if core_changes else 'false'}\n",
            f"plugins={'true' if plugin_changes else 'false'}\n",
        )
    )
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output:
            output.write(result)
    else:
        sys.stdout.write(result)


def main(*, run: _Run = _git_diff) -> int:
    code_changes, core_changes, plugin_changes = _classify_changes(
        os.environ.get("BASE_SHA"),
        os.environ.get("HEAD_SHA"),
        run=run,
    )
    _write_result(
        code_changes,
        core_changes,
        plugin_changes,
        os.environ.get("GITHUB_OUTPUT"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
