"""Load optional skill scripts from ``plugins/acd/skills`` by module name.

The reference pipelines use the skills that ship with this repository the same
way OpenHands would: the skill is an optional asset resolved at run time, not a
package dependency of the ACD core. A missing skill stops the pipeline instead of
silently falling back.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SKILLS_DIR = Path(__file__).resolve().parents[1] / "plugins" / "acd" / "skills"


def load_skill_module(skill: str, module: str) -> ModuleType:
    path = SKILLS_DIR / skill / "scripts" / f"{module}.py"
    if not path.is_file():
        raise FileNotFoundError(f"skill script not found: {path} (fail-closed)")
    name = f"acd_skill_{skill.replace('-', '_')}_{module}"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load skill script {path}")
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded
