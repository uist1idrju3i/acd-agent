"""Tests for opt-in real component STEP integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from acd.adapters.cad.component_3d import import_component_step
from acd.core.electrical import extract_electrical_lane
from acd.core.mechanical import extract_mechanical_lane
from acd.schema.design_graph import DesignGraph


def _gd1_lanes() -> tuple[Any, dict[str, str]]:
    root = Path(__file__).resolve().parents[3]
    graph = DesignGraph.model_validate(
        json.loads(
            (root / "fixtures/golden-design-1/graph.json").read_text(
                encoding="utf-8"
            )
        )
    )
    lane = extract_mechanical_lane(graph)
    electrical = extract_electrical_lane(graph)
    return lane, {item.node_id: item.refdes for item in electrical.components}


def test_synthetic_step_matches_gd1_u1_and_j1() -> None:
    lane, refdes = _gd1_lanes()
    root = Path(__file__).resolve().parents[3]
    result = import_component_step(
        root / "fixtures/component-3d/gd1-components.step",
        lane,
        refdes_by_component_id=refdes,
    )
    assert len(result.component_solids) == 2
    assert {item.refdes for item in result.component_solids} == {"U1", "J1"}
    assert result.status == "unknown"
    assert any(item.rule_id == "model_missing" for item in result.findings)


def test_corrupt_step_is_unknown(tmp_path: Path) -> None:
    lane, refdes = _gd1_lanes()
    corrupt = tmp_path / "corrupt.step"
    corrupt.write_text("not a STEP file\n", encoding="utf-8")
    result = import_component_step(corrupt, lane, refdes_by_component_id=refdes)
    assert result.status == "unknown"
    assert result.findings[0].rule_id == "component_step_import"
