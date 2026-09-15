"""Tests for deterministic graph-diff SVG projections."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

from pathlib import Path

import pytest

from acd.adapters.svg.graph_diff import (
    SvgGraphDiffRenderer,
    SvgVisualProjectionError,
    generate_graph_diff_visual_projection,
)
from acd.schema.design_graph import DesignGraph, GraphNode


def _graphs() -> tuple[DesignGraph, DesignGraph]:
    previous = DesignGraph(
        graph_id="demo",
        revision="r1",
        nodes=[
            GraphNode(id="node.a", kind="requirement", attrs={"text": "old"}),
            GraphNode(id="node.b", kind="electrical.net", depends_on=["node.a"]),
            GraphNode(id="node.removed", kind="requirement"),
        ],
    )
    current = DesignGraph(
        graph_id="demo",
        revision="r2",
        nodes=[
            GraphNode(id="node.a", kind="requirement", attrs={"text": "new"}),
            GraphNode(id="node.b", kind="electrical.net", depends_on=["node.a"]),
            GraphNode(id="node.added", kind="requirement"),
        ],
    )
    return previous, current


def _render(tmp_path: Path, name: str):
    previous, current = _graphs()
    source = tmp_path / "graph.json"
    source.write_text("graph\n", encoding="utf-8")
    return generate_graph_diff_visual_projection(
        project_name="demo",
        out_dir=tmp_path / name,
        previous_graph=previous,
        current_graph=current,
        authoritative_inputs=(source,),
        input_base_dir=tmp_path,
    )


def test_graph_diff_projection_is_deterministic_and_colored(tmp_path: Path) -> None:
    first = _render(tmp_path, "first")
    second = _render(tmp_path, "second")
    assert first.identity_hash == second.identity_hash
    assert first.projections[0].projection_type == "graph_diff_view"
    assert first.projections[0].domain == "system"
    first_svg = (tmp_path / "first" / first.projections[0].image_path).read_bytes()
    second_svg = (tmp_path / "second" / second.projections[0].image_path).read_bytes()
    assert first_svg == second_svg
    assert b'fill="#2e7d32"' in first_svg
    assert b'fill="#c62828"' in first_svg
    assert b'fill="#c2410c"' in first_svg
    assert b'id="graph-diff-legend"' in first_svg
    assert b"Graph diff r1 -&gt; r2" in first_svg
    assert b'marker-end="url(#arrow)"' in first_svg


def test_graph_diff_projection_rejects_graph_id_mismatch(tmp_path: Path) -> None:
    previous, current = _graphs()
    current = current.model_copy(update={"graph_id": "other"})
    source = tmp_path / "graph.json"
    source.write_text("graph\n", encoding="utf-8")
    with pytest.raises(SvgVisualProjectionError, match="graph IDs"):
        generate_graph_diff_visual_projection(
            project_name="demo",
            out_dir=tmp_path / "out",
            previous_graph=previous,
            current_graph=current,
            authoritative_inputs=(source,),
            input_base_dir=tmp_path,
        )


def test_renderer_rejects_unknown_tool_version() -> None:
    with pytest.raises(SvgVisualProjectionError, match="renderer version"):
        SvgGraphDiffRenderer(tool_version="unknown")
