"""Tests for the authoritative mechanical visual renderer."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from acd.adapters.cad.mechanical import (
    MechanicalGateError,
    MechanicalGateReport,
    build_component_body_shape,
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
    graph, _ = _fixture()
    lane = extract_mechanical_lane(graph)

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
    assert 'id="interference"' not in (
        tmp_path / "first/visual/gd1-mechanical-interference.svg"
    ).read_text(encoding="utf-8")
    section_svg = (
        tmp_path / "first/visual/gd1-mechanical-section.svg"
    ).read_text(encoding="utf-8")
    assert section_svg.count("<line") == 12
    assert section_svg.count("<circle") == 4
    assert 'x1="-16.0" y1="13.5" x2="16.0" y2="13.5"' in section_svg
    assert 'x1="-4.5" y1="-13.5" x2="-4.5" y2="-15.5"' in section_svg
    assert first.projections[1].section_offset_mm == (
        lane.enclosure.wall_thickness_mm + lane.enclosure.standoff_height_mm / 2
    )


def test_mechanical_renderer_rejects_unsupported_section_plane(
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


def test_mechanical_renderer_records_positive_interference_section(
    tmp_path: Path,
) -> None:
    graph, lane, projection, _gates = _authoritative(tmp_path / "authoritative")
    body = replace(
        lane.component_bodies[0],
        width_mm=30.0,
        depth_mm=25.0,
        height_mm=10.0,
        x_mm=15.0,
        y_mm=12.5,
    )
    overlapping_lane = replace(
        lane,
        component_bodies=(body, *lane.component_bodies[1:]),
    )
    renderer = MechanicalVisualRenderer(base_dir=tmp_path / "authoritative")
    assembly = renderer.build123d.import_step(projection.assembly_step_path)
    body_shape = build_component_body_shape(
        body,
        overlapping_lane.enclosure.wall_thickness_mm
        + overlapping_lane.enclosure.internal_clearance_mm,
        overlapping_lane.outline.width_mm,
        overlapping_lane.outline.depth_mm,
    )
    intersections = [solid & body_shape for solid in assembly.solids()]
    interference = max(intersections, key=lambda shape: float(shape.volume))
    measured_volume = float(interference.volume)
    expected_offset = (
        float(interference.bounding_box().min.Z)
        + float(interference.bounding_box().max.Z)
    ) / 2
    assert measured_volume > 0
    gate_report = MechanicalGateReport(
        kernel_valid=True,
        interference=True,
        clearance=True,
        wall_thickness=True,
        measured_volume_mm3=0.0,
        measured_min_wall_mm=2.0,
        measured_min_clearance_mm=1.0,
        measured_max_interference_volume_mm3=measured_volume,
    )
    record = renderer.render_interference(
        projection=projection,
        lane=overlapping_lane,
        target_revision=graph.revision,
        gate_report=gate_report,
        output_path=tmp_path / "authoritative/positive-interference.svg",
    )

    assert record.section_plane_id == "xy"
    assert record.section_offset_mm == expected_offset
    assert record.interference_region_present is True
    assert record.interference_volume_mm3 == measured_volume
    assert record.regeneration_check.first_image_hash == record.regeneration_check.second_image_hash
    svg = (tmp_path / "authoritative/positive-interference.svg").read_text(
        encoding="utf-8"
    )
    assert 'id="interference"' in svg
    assert "<line" in svg


def test_mechanical_renderer_rejects_section_without_declared_features(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph, lane, projection, _gates = _authoritative(tmp_path / "authoritative")
    renderer = MechanicalVisualRenderer(base_dir=tmp_path / "authoritative")
    shape = renderer.build123d.Box(
        36.0,
        31.0,
        10.0,
    )

    def fake_import_step(_path: Path) -> object:
        return shape

    monkeypatch.setattr(renderer.build123d, "import_step", fake_import_step)

    with pytest.raises(
        MechanicalVisualProjectionError,
        match="missing declared standoff features",
    ):
        renderer.render_section(
            projection=projection,
            lane=lane,
            target_revision=graph.revision,
            output_path=tmp_path / "authoritative/missing-features.svg",
            section_plane_id="xy",
        )


def test_mechanical_renderer_rejects_invalid_declared_section_offset(
    tmp_path: Path,
) -> None:
    graph, lane, projection, _gates = _authoritative(tmp_path / "authoritative")
    invalid_lane = replace(
        lane,
        enclosure=replace(lane.enclosure, standoff_height_mm=0.0),
    )
    renderer = MechanicalVisualRenderer(base_dir=tmp_path / "authoritative")

    with pytest.raises(
        MechanicalVisualProjectionError,
        match="section offset declarations are invalid",
    ):
        renderer.render_section(
            projection=projection,
            lane=invalid_lane,
            target_revision=graph.revision,
            output_path=tmp_path / "authoritative/invalid-offset.svg",
            section_plane_id="xy",
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
