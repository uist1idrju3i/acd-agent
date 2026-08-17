"""Tests for the rationale validation CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_check_rationale_missing_file_returns_hook_blocking_exit_code(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_rationale.py",
            "--graph",
            "fixtures/golden-design-1/graph.json",
            "--rationale",
            str(tmp_path / "missing.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_check_rationale_if_present_is_not_applicable(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_rationale.py",
            "--rationale",
            str(tmp_path / "missing.json"),
            "--if-present",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
