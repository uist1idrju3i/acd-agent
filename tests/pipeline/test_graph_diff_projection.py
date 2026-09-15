"""Tests for the graph-diff projection pipeline stage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.pipeline.graph_diff_projection import (
    GraphDiffProjectionError,
    run_graph_diff_projection,
)
from acd.schema.design_graph import DesignGraph, GraphNode


def _write_graph(path: Path, revision: str, *, graph_id: str = "demo") -> None:
    graph = DesignGraph(
        graph_id=graph_id,
        revision=revision,
        nodes=[GraphNode(id="node.a", kind="requirement")],
    )
    path.write_text(
        json.dumps(graph.model_dump(mode="json"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_run_graph_diff_projection_writes_projection_set(tmp_path: Path) -> None:
    current = tmp_path / "current.json"
    previous = tmp_path / "previous.json"
    _write_graph(current, "r2")
    _write_graph(previous, "r1")

    output = run_graph_diff_projection(
        graph_path=current,
        previous_graph_path=previous,
        out_dir=tmp_path / "out",
        project_name="demo",
    )

    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["source_revision"] == "r2"
    assert payload["projections"][0]["projection_type"] == "graph_diff_view"


def test_run_graph_diff_projection_uses_common_input_base_dir(
    tmp_path: Path,
) -> None:
    current = tmp_path / "fixture" / "graph.json"
    previous = tmp_path / "prev" / "graph.json"
    current.parent.mkdir()
    previous.parent.mkdir()
    _write_graph(current, "r2")
    _write_graph(previous, "r1")

    output = run_graph_diff_projection(
        graph_path=current,
        previous_graph_path=previous,
        out_dir=tmp_path / "out",
        project_name="demo",
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [item["path"] for item in payload["projections"][0]["input_files"]] == [
        "prev/graph.json",
        "fixture/graph.json",
    ]


def test_run_graph_diff_projection_fails_on_mismatched_graph_id(
    tmp_path: Path,
) -> None:
    current = tmp_path / "current.json"
    previous = tmp_path / "previous.json"
    _write_graph(current, "r2")
    _write_graph(previous, "r1", graph_id="other")

    with pytest.raises(GraphDiffProjectionError):
        run_graph_diff_projection(
            graph_path=current,
            previous_graph_path=previous,
            out_dir=tmp_path / "out",
            project_name="demo",
        )
