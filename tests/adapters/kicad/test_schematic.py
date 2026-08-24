"""Deterministic KiCad schematic projection tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from acd.adapters.kicad.library import SymbolLibrary
from acd.adapters.kicad.schematic import (
    CONNECTION_CONVENTION_NOTE,
    PWR_FLAG_LIB_ID,
    generate_schematic,
)
from acd.core.electrical import extract_electrical_lane
from acd.schema import DesignGraph

ROOT = Path(__file__).parents[3]
FIXTURE_DIR = ROOT / "fixtures/golden-design-1"
POWER_LIBRARY = Path("/usr/share/kicad/symbols/power.kicad_sym")


def _schematic() -> str:
    if not POWER_LIBRARY.is_file():
        pytest.skip("host KiCad power symbol library is unavailable")
    graph = DesignGraph.model_validate(
        json.loads((FIXTURE_DIR / "graph.json").read_text(encoding="utf-8"))
    )
    library = SymbolLibrary()
    digest = "sha256:" + hashlib.sha256(POWER_LIBRARY.read_bytes()).hexdigest()
    pwr_flag = library.load(PWR_FLAG_LIB_ID, POWER_LIBRARY, digest)
    return generate_schematic(
        extract_electrical_lane(graph),
        library,
        FIXTURE_DIR,
        pwr_flag,
        project_name="gd1",
    )


def test_schematic_states_the_label_connection_convention() -> None:
    content = _schematic()
    assert f'(text "{CONNECTION_CONVENTION_NOTE}"' in content
    assert "global net labels" in CONNECTION_CONVENTION_NOTE


def test_schematic_generation_is_deterministic() -> None:
    assert _schematic() == _schematic()
