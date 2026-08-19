"""Tests for the authoritative mechanical visual renderer."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from acd.adapters.cad.mechanical import (
    MechanicalGateError,
    MechanicalGateReport,
    run_mechanical_gates,
)
from acd.adapters.cad.project import project_enclosure
from acd.adapters.cad.visual_projection import (
    MechanicalVisualProjectionError,
    MechanicalVisualRenderer,
    generate_mechanical_visual_projections,
)
from acd.core.mechanical import extract_mechanical_lane
from acd.openhands.tools.probe import probe_cad_kernel
from acd.schema.design_graph import DesignGraph


def _fixture() -> tuple[DesignGraph, Path]:
    fixture_dir = Path("fixtures/golden-design-1")
    graph = DesignGraph.model_validate(
        json.loads((fixture_dir / "graph.json").read_text(encoding="utf-8"))
    )
    return graph, fixture_dir / "graph.json"


def _authoritative(out_dir: Path):
    graph, graph_path = _fixture()
    lane = extract_mechanical_lane(graph)
    projection = project_enclosure(
        lane,
        graph_path=graph_path,
        out_dir=out_dir,
        target_revision=graph.revision,
    )
    gates = run_mechanical_gates(
        step_path=projection.assembly_step_path,
        lane=lane,
        kernel_probe=probe_cad_kernel(),
    )
    return graph, lane, projection, gates


def _generate(out_dir: Path):
    graph, lane, projection, gates = _authoritative(out_dir)
    return generate_mechanical_visual_projections(
        projection=projection,
        lane=lane,
        target_revision=graph.revision,
        gate_report=gates,
        out_dir=out_dir,
    )


def test_mechanical_visual_renderer_uses_authoritative_step_and_reproduces(
    tmp_path: Path,
) -> None:
    first = _generate(tmp_path / "first")
    second = _generate(tmp_path / "second")

    assert [item.projection_type for item in first.projections] == [
        "mechanical_interference_view",
        "mechanical_section_view",
    ]
    assert all(item.renderer.tool_name == "build123d" for item in first.projections)
    assert first.identity_hash == second.identity_hash
    assert first.canonical_hash != second.canonical_hash
    assert (tmp_path / "first/visual/gd1-mechanical-section.svg").is_file()
    assert (tmp_path / "first/visual/gd1-mechanical-interference.svg").is_file()
    assert (tmp_path / "first/visual-projections-mechanical.json").is_file()
    assert not list((tmp_path / "first/visual").glob("*.png"))
    assert 'id="interference"' in (
        tmp_path / "first/visual/gd1-mechanical-interference.svg"
    ).read_text(encoding="utf-8")


def test_mechanical_renderer_rejects_unsupported_or_non_intersecting_sections(
    tmp_path: Path,
) -> None:
    graph, lane, projection, _gates = _authoritative(tmp_path / "authoritative")
    renderer = MechanicalVisualRenderer(base_dir=tmp_path / "authoritative")

    with pytest.raises(MechanicalVisualProjectionError, match="declared XY"):
        renderer.render_section(
            projection=projection,
            lane=lane,
            target_revision=graph.revision,
            output_path=tmp_path / "unsupported.svg",
            section_plane_id="xz",
            section_offset_mm=2.0,
        )
    with pytest.raises(MechanicalVisualProjectionError, match="does not intersect"):
        renderer.render_section(
            projection=projection,
            lane=lane,
            target_revision=graph.revision,
            output_path=tmp_path / "empty.svg",
            section_plane_id="xy",
            section_offset_mm=100.0,
        )


def test_mechanical_renderer_rejects_step_hash_and_gate_volume_mismatch(
    tmp_path: Path,
) -> None:
    graph, lane, projection, gates = _authoritative(tmp_path / "authoritative")
    renderer = MechanicalVisualRenderer(base_dir=tmp_path / "authoritative")
    projection.assembly_step_path.write_text(
        projection.assembly_step_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    with pytest.raises(MechanicalVisualProjectionError, match="input hash mismatch"):
        renderer.render_interference(
            projection=projection,
            lane=lane,
            target_revision=graph.revision,
            gate_report=gates,
            output_path=tmp_path / "hash-mismatch.svg",
        )

    graph, lane, projection, gates = _authoritative(tmp_path / "volume")
    renderer = MechanicalVisualRenderer(base_dir=tmp_path / "volume")
    with pytest.raises(MechanicalVisualProjectionError, match="gate measurement"):
        renderer.render_interference(
            projection=projection,
            lane=lane,
            target_revision=graph.revision,
            gate_report=replace(
                gates,
                measured_max_interference_volume_mm3=1.0,
            ),
            output_path=tmp_path / "volume-mismatch.svg",
        )


def test_mechanical_visual_generation_requires_passing_gate(tmp_path: Path) -> None:
    graph, lane, projection, gates = _authoritative(tmp_path / "authoritative")
    failing = MechanicalGateReport(
        kernel_valid=False,
        interference=gates.interference,
        clearance=gates.clearance,
        wall_thickness=gates.wall_thickness,
        measured_volume_mm3=gates.measured_volume_mm3,
        measured_min_wall_mm=gates.measured_min_wall_mm,
        measured_min_clearance_mm=gates.measured_min_clearance_mm,
        measured_max_interference_volume_mm3=gates.measured_max_interference_volume_mm3,
    )
    with pytest.raises(MechanicalGateError, match="require passing gates"):
        generate_mechanical_visual_projections(
            projection=projection,
            lane=lane,
            target_revision=graph.revision,
            gate_report=failing,
            out_dir=tmp_path / "blocked",
        )
