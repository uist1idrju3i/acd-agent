"""Every scripts/*.py entrypoint is classified exactly once in scripts/README.md."""

from __future__ import annotations

import re
from pathlib import Path

SCRIPTS = Path(__file__).parents[1]
_ROW = re.compile(r"^\| `([a-z0-9_]+\.py)` \|", re.MULTILINE)


def test_every_script_is_classified_once() -> None:
    listed = _ROW.findall((SCRIPTS / "README.md").read_text(encoding="utf-8"))
    present = sorted(p.name for p in SCRIPTS.glob("*.py") if p.name != "__init__.py")
    duplicates = sorted({name for name in listed if listed.count(name) > 1})
    assert duplicates == []
    assert sorted(set(listed) - set(present)) == []
    assert sorted(set(present) - set(listed)) == []
