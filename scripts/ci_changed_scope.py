#!/usr/bin/env python3
"""Classify a change as documentation-only for the CI fast path."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

_Run = Callable[[list[str]], str]


def _git_diff(command: list[str]) -> str:
    result = subprocess.run(
        command,
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout


def _has_code_changes(base_sha: str | None, head_sha: str | None, *, run: _Run) -> bool:
    if not base_sha or not head_sha:
        return True
    try:
        changed_files = [
            line
            for line in run(["git", "diff", "--name-only", base_sha, head_sha]).splitlines()
            if line
        ]
    except (OSError, RuntimeError, subprocess.CalledProcessError):
        return True
    if not changed_files:
        return True
    return any(not path.endswith(".md") for path in changed_files)


def _write_result(code_changes: bool, output_path: str | None) -> None:
    result = f"code={'true' if code_changes else 'false'}\n"
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output:
            output.write(result)
    else:
        sys.stdout.write(result)


def main(*, run: _Run = _git_diff) -> int:
    code_changes = _has_code_changes(
        os.environ.get("BASE_SHA"),
        os.environ.get("HEAD_SHA"),
        run=run,
    )
    _write_result(code_changes, os.environ.get("GITHUB_OUTPUT"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
