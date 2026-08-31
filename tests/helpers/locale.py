"""Helpers for subprocess regressions under a forced non-UTF-8 locale."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def run_under_c_locale(code: str, *arguments: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "LC_ALL": "C",
            "LANG": "C",
            "PYTHONUTF8": "0",
            "PYTHONCOERCECLOCALE": "0",
        }
    )
    environment.pop("PYTHONIOENCODING", None)
    completed = subprocess.run(
        [sys.executable, "-c", code, *(str(path) for path in arguments)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )
    if completed.returncode == 3:
        pytest.skip("locale cannot be forced to non-UTF-8")
    return completed
