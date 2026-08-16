"""Verify the generator's mechanical nodes match the tracked fixture."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "golden-design-1" / "graph.json"
GENERATOR = Path(__file__).resolve().parents[3] / "scripts" / "build_gd1_fixture.py"


def test_generator_mechanical_nodes_match_fixture_without_kicad(
) -> None:
    spec = importlib.util.spec_from_file_location("build_gd1_fixture", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    expected = [
        node
        for node in fixture["nodes"]
        if node["kind"].startswith("mechanical.")
    ]
    actual = [
        node.model_dump(mode="json")
        for node in (
            module.mechanical_nodes()
            + module.silkscreen_nodes("golden-design-1", "r1")
        )
    ]
    assert actual == expected
