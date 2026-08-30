"""CAD projection determinism and independent output artifacts."""

from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path

import pytest

from acd.adapters.cad.mechanical import MechanicalGateError, measure_enclosure_artifacts
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
