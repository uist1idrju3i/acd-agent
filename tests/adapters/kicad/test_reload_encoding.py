"""Regression tests for locale-independent KiCad artifact loading."""
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

from pathlib import Path

from acd.adapters.kicad.reload import normalized_hash
from tests.helpers.locale import run_under_c_locale


def test_reload_and_hash_work_under_non_utf8_locale(tmp_path: Path) -> None:
    artifact = tmp_path / "minimal.kicad_pcb"
    artifact.write_text(
        '(kicad_pcb (comment "Bluetooth®Low Energy"))\n',
        encoding="utf-8",
    )
    completed = run_under_c_locale(
        (
            "import locale\n"
            "import sys\n"
            "from pathlib import Path\n"
            "from acd.adapters.kicad.reload import _load_sexpr, normalized_hash\n"
            "if locale.getpreferredencoding(False).upper() in {'UTF-8', 'UTF8'}:\n"
            "    raise SystemExit(3)\n"
            "path = Path(sys.argv[1])\n"
            "_load_sexpr(path)\n"
            "print(normalized_hash(path))\n"
        ),
        artifact,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == normalized_hash(artifact)
