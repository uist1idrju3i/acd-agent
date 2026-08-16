"""Make the skill's scripts importable from its tests."""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[5]

sys.path.insert(0, str(SKILL_ROOT / "scripts"))
