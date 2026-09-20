"""Make each Skill's ``scripts/`` importable from that Skill's ``tests/``.

Skill scripts are standalone PEP 723 entry points, not an installed package, so
their tests import them by bare module name.  The path is added when pytest
collects a module under ``<skill>/tests/``, before the module is imported.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def pytest_pycollect_makemodule(module_path: Path, parent: pytest.Collector) -> None:
    del parent
    if module_path.parent.name != "tests":
        return None
    scripts = module_path.parents[1] / "scripts"
    if not scripts.is_dir():
        return None
    entry = str(scripts)
    if entry not in sys.path:
        sys.path.insert(0, entry)
    return None
