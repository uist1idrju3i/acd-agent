"""CAD projection determinism and independent output artifacts."""

from __future__ import annotations

import importlib
import json
import re
import shutil
from pathlib import Path

import pytest

from acd.adapters.cad.mechanical import (
    MechanicalGateError,
    measure_enclosure_artifacts,
    measure_enclosure_mesh_artifacts,
)
from acd.adapters.cad.project import project_enclosure
from acd.core.mechanical import extract_mechanical_lane
from acd.core.parallel import PipelineStageRunner
from acd.schema.design_graph import DesignGraph

FIXTURE = (
    Path(__file__).resolve().parents[3] / "fixtures" / "golden-design-1" / "graph.json"
)


def test_projection_rerun_matches_normalized_hash(tmp_path: Path) -> None:
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    lane = extract_mechanical_lane(graph)
    first = project_enclosure(
        lane,
        graph_path=FIXTURE,
        out_dir=tmp_path,
        target_revision=graph.revision,
    )
    second = project_enclosure(
        lane,
        graph_path=FIXTURE,
        out_dir=tmp_path,
        target_revision=graph.revision,
    )
    assert first.envelope.output_hash == second.envelope.output_hash
    assert first.shell_step_path.is_file()
    assert first.lid_step_path.is_file()
    assert first.assembly_step_path.is_file()
    assert first.model_path.is_file()
    assert first.mesh_stl_path.is_file()
    assert first.artifact_manifest_path.is_file()


def test_projection_exports_separated_solids_and_assembly(tmp_path: Path) -> None:
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    lane = extract_mechanical_lane(graph)
    projection = project_enclosure(
        lane,
        graph_path=FIXTURE,
        out_dir=tmp_path,
        target_revision=graph.revision,
    )
    with PipelineStageRunner(4) as runner:
        report = measure_enclosure_artifacts(
            shell_step_path=projection.shell_step_path,
            lid_step_path=projection.lid_step_path,
            assembly_step_path=projection.assembly_step_path,
            runner=runner,
        )
    build123d = importlib.import_module("build123d")
    assert report.shell_volume_mm3 == pytest.approx(4493.532021, abs=1e-3)
    assert report.lid_volume_mm3 == pytest.approx(2201.589383, abs=1e-3)
    assert report.assembly_volume_mm3 == pytest.approx(
        report.shell_volume_mm3 + report.lid_volume_mm3, abs=1e-3
    )
    assert report.shell_bbox_mm == pytest.approx((-18.0, -15.5, 0.0, 18.0, 15.5, 10.9))
    assert report.lid_bbox_mm == pytest.approx((-18.0, -15.5, 11.1, 18.0, 15.5, 13.1))
    assert len(build123d.import_step(projection.shell_step_path).solids()) == 1
    assert len(build123d.import_step(projection.lid_step_path).solids()) == 1
    assert len(build123d.import_step(projection.assembly_step_path).solids()) == 2
    mesh_report = measure_enclosure_mesh_artifacts(
        model_3mf_path=projection.model_path,
        mesh_stl_path=projection.mesh_stl_path,
        assembly_report=report,
    )
    assert mesh_report.model_part_count == 2
    assert mesh_report.stl_triangle_count == 6156
    assert mesh_report.stl_volume_mm3 == pytest.approx(6695.063990, abs=1e-3)
    manifest = json.loads(projection.artifact_manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifacts"][-1]["role"] == "enclosure_mesh_stl"
    assert report.shell_bbox_mm != report.assembly_bbox_mm
    assert report.lid_bbox_mm != report.assembly_bbox_mm


def test_artifact_measurement_is_stable_across_worker_counts(tmp_path: Path) -> None:
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    lane = extract_mechanical_lane(graph)
    serial_projection = project_enclosure(
        lane,
        graph_path=FIXTURE,
        out_dir=tmp_path / "serial",
        target_revision=graph.revision,
    )
    parallel_projection = project_enclosure(
        lane,
        graph_path=FIXTURE,
        out_dir=tmp_path / "parallel",
        target_revision=graph.revision,
    )
    serial = measure_enclosure_artifacts(
        shell_step_path=serial_projection.shell_step_path,
        lid_step_path=serial_projection.lid_step_path,
        assembly_step_path=serial_projection.assembly_step_path,
    )
    with PipelineStageRunner(4) as runner:
        parallel = measure_enclosure_artifacts(
            shell_step_path=parallel_projection.shell_step_path,
            lid_step_path=parallel_projection.lid_step_path,
            assembly_step_path=parallel_projection.assembly_step_path,
            runner=runner,
        )
    assert parallel == serial


def test_projection_rejects_fused_part_artifact(tmp_path: Path) -> None:
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    lane = extract_mechanical_lane(graph)
    projection = project_enclosure(
        lane,
        graph_path=FIXTURE,
        out_dir=tmp_path,
        target_revision=graph.revision,
    )
    shutil.copyfile(projection.assembly_step_path, projection.shell_step_path)
    with (
        PipelineStageRunner(4) as runner,
        pytest.raises(MechanicalGateError, match="shell STEP must contain exactly one solid"),
    ):
        measure_enclosure_artifacts(
            shell_step_path=projection.shell_step_path,
            lid_step_path=projection.lid_step_path,
            assembly_step_path=projection.assembly_step_path,
            runner=runner,
        )


def test_mesh_measurement_rejects_missing_stl(tmp_path: Path) -> None:
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    lane = extract_mechanical_lane(graph)
    projection = project_enclosure(
        lane, graph_path=FIXTURE, out_dir=tmp_path, target_revision=graph.revision
    )
    report = measure_enclosure_artifacts(
        shell_step_path=projection.shell_step_path,
        lid_step_path=projection.lid_step_path,
        assembly_step_path=projection.assembly_step_path,
    )
    projection.mesh_stl_path.unlink()
    with pytest.raises(MechanicalGateError, match="STL is missing"):
        measure_enclosure_mesh_artifacts(
            model_3mf_path=projection.model_path,
            mesh_stl_path=projection.mesh_stl_path,
            assembly_report=report,
        )


def test_mesh_measurement_rejects_truncated_stl(tmp_path: Path) -> None:
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    lane = extract_mechanical_lane(graph)
    projection = project_enclosure(
        lane, graph_path=FIXTURE, out_dir=tmp_path, target_revision=graph.revision
    )
    report = measure_enclosure_artifacts(
        shell_step_path=projection.shell_step_path,
        lid_step_path=projection.lid_step_path,
        assembly_step_path=projection.assembly_step_path,
    )
    projection.mesh_stl_path.write_bytes(projection.mesh_stl_path.read_bytes()[:100])
    with pytest.raises(MechanicalGateError, match="STL cannot be reloaded"):
        measure_enclosure_mesh_artifacts(
            model_3mf_path=projection.model_path,
            mesh_stl_path=projection.mesh_stl_path,
            assembly_report=report,
        )


def test_mesh_measurement_rejects_shifted_stl_bbox(tmp_path: Path) -> None:
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    lane = extract_mechanical_lane(graph)
    projection = project_enclosure(
        lane, graph_path=FIXTURE, out_dir=tmp_path, target_revision=graph.revision
    )
    report = measure_enclosure_artifacts(
        shell_step_path=projection.shell_step_path,
        lid_step_path=projection.lid_step_path,
        assembly_step_path=projection.assembly_step_path,
    )
    shifted = re.sub(
        rb"(?m)^(\s*vertex )([-+0-9.eE]+)(\s+[-+0-9.eE]+\s+[-+0-9.eE]+)",
        lambda match: (
            match.group(1)
            + f"{float(match.group(2)) + 1.0:g}".encode()
            + match.group(3)
        ),
        projection.mesh_stl_path.read_bytes(),
    )
    projection.mesh_stl_path.write_bytes(shifted)
    with pytest.raises(MechanicalGateError, match="STL bbox"):
        measure_enclosure_mesh_artifacts(
            model_3mf_path=projection.model_path,
            mesh_stl_path=projection.mesh_stl_path,
            assembly_report=report,
        )


def test_mesh_measurement_rejects_wrong_3mf_part_count(tmp_path: Path) -> None:
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    lane = extract_mechanical_lane(graph)
    projection = project_enclosure(
        lane, graph_path=FIXTURE, out_dir=tmp_path, target_revision=graph.revision
    )
    report = measure_enclosure_artifacts(
        shell_step_path=projection.shell_step_path,
        lid_step_path=projection.lid_step_path,
        assembly_step_path=projection.assembly_step_path,
    )
    build123d = importlib.import_module("build123d")
    mesher = build123d.Mesher()
    mesher.add_shape(build123d.Box(1, 1, 1), part_number="wrong-count")
    mesher.write(projection.model_path)
    with pytest.raises(MechanicalGateError, match="exactly two parts"):
        measure_enclosure_mesh_artifacts(
            model_3mf_path=projection.model_path,
            mesh_stl_path=projection.mesh_stl_path,
            assembly_report=report,
        )
