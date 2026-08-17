"""Verify the generator's mechanical nodes match the tracked fixture."""

from __future__ import annotations

import json
from pathlib import Path

from acd_pipeline.gd1_fixture import mechanical_nodes, silkscreen_nodes

# pyright: reportMissingTypeStubs=false

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "golden-design-1" / "graph.json"


def test_generator_mechanical_nodes_match_fixture_without_kicad() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    expected = [node for node in fixture["nodes"] if node["kind"].startswith("mechanical.")]
    actual = [
        node.model_dump(mode="json")
        for node in (mechanical_nodes() + silkscreen_nodes("golden-design-1", "r1"))
    ]
    assert actual == expected
