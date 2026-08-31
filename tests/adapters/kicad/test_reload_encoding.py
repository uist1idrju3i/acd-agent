"""Regression tests for locale-independent KiCad artifact loading."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from acd.adapters.kicad.reload import normalized_hash

ROOT = Path(__file__).parents[3]


def test_reload_and_hash_work_under_non_utf8_locale(tmp_path: Path) -> None:
    artifact = tmp_path / "minimal.kicad_pcb"
    artifact.write_text(
        '(kicad_pcb (comment "Bluetooth®Low Energy"))\n',
        encoding="utf-8",
    )
    child_code = (
        "import locale\n"
        "import sys\n"
        "from pathlib import Path\n"
        "from acd.adapters.kicad.reload import _load_sexpr, normalized_hash\n"
        "if locale.getpreferredencoding(False).upper() in {'UTF-8', 'UTF8'}:\n"
        "    raise SystemExit(3)\n"
        "path = Path(sys.argv[1])\n"
        "_load_sexpr(path)\n"
        "print(normalized_hash(path))\n"
    )
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
        [sys.executable, "-c", child_code, str(artifact)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 3:
        pytest.skip("locale cannot be forced to non-UTF-8")
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == normalized_hash(artifact)
