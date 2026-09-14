"""Regression tests for graph-derived KiCad library table declarations."""

from __future__ import annotations

import json
from pathlib import Path

from acd.adapters.kicad.project import _lib_table  # pyright: ignore[reportPrivateUsage]
from acd.schema.design_graph import DesignGraph

ROOT = Path(__file__).parents[3]
GRAPH = ROOT / "examples/sensor-node-20260820/fixture/graph.json"
TABLE = ROOT / "examples/sensor-node-20260820/board/fp-lib-table"


def _table_names(path: Path) -> set[str]:
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if '(lib (name "' not in line:
            continue
        names.add(line.split('(lib (name "', 1)[1].split('"', 1)[0])
    return names


def test_gd1_project_table_declares_every_graph_footprint_library() -> None:
    graph = DesignGraph.model_validate(json.loads(GRAPH.read_text(encoding="utf-8")))
    referenced = {
        node.attrs["footprint"].split(":", 1)[0]
        for node in graph.nodes
        if node.kind == "electrical.component"
    }
    assert referenced <= _table_names(TABLE)


def test_lib_table_projection_contains_every_graph_nickname() -> None:
    graph = DesignGraph.model_validate(json.loads(GRAPH.read_text(encoding="utf-8")))
    referenced = {
        node.attrs["footprint"].split(":", 1)[0]
        for node in graph.nodes
        if node.kind == "electrical.component"
    }
    projected = _lib_table(
        "fp",
        {
            name: Path(f"/usr/share/kicad/footprints/{name}.pretty")
            for name in referenced
        },
    )
    assert referenced <= _table_names_from_text(projected)


def _table_names_from_text(content: str) -> set[str]:
    return {
        line.split('(lib (name "', 1)[1].split('"', 1)[0]
        for line in content.splitlines()
        if '(lib (name "' in line
    }
