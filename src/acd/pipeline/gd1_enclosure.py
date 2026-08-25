"""Golden Design #1 mechanical pipeline: graph -> CAD projection -> gates."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TypeGuard

from acd.adapters.cad.mechanical import (
    EnclosureArtifactReport,
    MechanicalGateReport,
    measure_enclosure_artifacts,
    run_mechanical_gates,
)
from acd.adapters.cad.project import CadProjection, project_enclosure
from acd.adapters.cad.visual_projection import generate_mechanical_visual_projections
from acd.core.lane_cli import add_lane_io_arguments
from acd.core.mechanical import MechanicalLane, extract_mechanical_lane
from acd.core.naming import evidence_id, subject_node_id
from acd.core.parallel import DEFAULT_CAD_STAGE_WORKERS, PipelineStageRunner
from acd.core.runtime_records import TimingRecorder, write_timing_record
from acd.openhands.tools.probe import probe_cad_kernel
from acd.pipeline.rationale import validate_and_project_rationale
from acd.pipeline.visual_projection import crosscheck_mechanical_visual_projections
from acd.schema.design_graph import DesignGraph
from acd.schema.evidence import Evidence, EvidenceClaim


def _stage_mechanical_gates(
    projection: CadProjection,
    lane: MechanicalLane,
) -> MechanicalGateReport:
    probe = probe_cad_kernel()
    return run_mechanical_gates(
        step_path=projection.assembly_step_path,
        lane=lane,
        kernel_probe=probe,
    )


def _is_enclosure_artifact_report(
    value: object,
) -> TypeGuard[EnclosureArtifactReport]:
    return isinstance(value, EnclosureArtifactReport)


def run_pipeline(
    fixture_dir: Path,
    out_dir: Path,
    *,
    pipeline_workers: int = DEFAULT_CAD_STAGE_WORKERS,
    timing_recorder: TimingRecorder | None = None,
) -> dict[str, object]:
    with PipelineStageRunner(pipeline_workers) as runner:
        return _run_pipeline(
            fixture_dir,
            out_dir,
            runner=runner,
            timing_recorder=timing_recorder,
        )


def _run_pipeline(
    fixture_dir: Path,
    out_dir: Path,
    *,
    runner: PipelineStageRunner,
    timing_recorder: TimingRecorder | None = None,
) -> dict[str, object]:
    runner.warm_up(("build123d",))
    graph_path = fixture_dir / "graph.json"
    graph = DesignGraph.model_validate(
        json.loads(graph_path.read_text(encoding="utf-8"))
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    stage_number = 0
    if timing_recorder is not None:
        timing_recorder.start("enclosure[0/5]")

    def mark_stage(number: int) -> None:
        nonlocal stage_number
        if timing_recorder is None or number == stage_number:
            return
        timing_recorder.finish(f"enclosure[{stage_number}/5]")
        stage_number = number
        timing_recorder.start(f"enclosure[{stage_number}/5]")

    validate_and_project_rationale(graph, fixture_dir, out_dir)
    print("[0/5] rationale coverage passed")
    mark_stage(1)
    lane = extract_mechanical_lane(graph)
    subject_node = subject_node_id(graph, "mechanical.enclosure")
    print("[1/5] mechanical lane extracted")
    mark_stage(2)

    projection = project_enclosure(
        lane,
        graph_path=graph_path,
        out_dir=out_dir,
        target_revision=graph.revision,
        graph_id=graph.graph_id,
    )
    print(
        "[2/5] enclosure CAD projected: "
        f"shell={projection.shell_step_path}, "
        f"lid={projection.lid_step_path}, "
        f"assembly={projection.assembly_step_path}"
    )
    mark_stage(3)

    runner.wait_for_warm_up()
    gate_future = runner.submit_stage(partial(_stage_mechanical_gates, projection, lane))
    artifact_report: object = measure_enclosure_artifacts(
        shell_step_path=projection.shell_step_path,
        lid_step_path=projection.lid_step_path,
        assembly_step_path=projection.assembly_step_path,
        runner=runner,
    )
    gate_report = gate_future.result()
    if not isinstance(gate_report, MechanicalGateReport):
        raise RuntimeError("mechanical pipeline stage results are unknown (fail-closed)")
    if not _is_enclosure_artifact_report(artifact_report):
        raise RuntimeError("mechanical pipeline stage results are unknown (fail-closed)")
    visual_projections = generate_mechanical_visual_projections(
        projection=projection,
        lane=lane,
        target_revision=graph.revision,
        gate_report=gate_report,
        out_dir=out_dir,
        graph_id=graph.graph_id,
        runner=runner,
    )
    visual_crosscheck = crosscheck_mechanical_visual_projections(
        source_revision=graph.revision,
        visual_projection_set=visual_projections,
        lane=lane,
        projection=projection,
        gate_report=gate_report,
        base_dir=out_dir,
        graph_id=graph.graph_id,
    )
    if visual_crosscheck.status != "match":
        raise RuntimeError("mechanical visual cross-check did not match (fail-closed)")
    print(
        "[3/5] mechanical gates passed: "
        f"volume={gate_report.measured_volume_mm3:.3f} mm3, "
        f"minimum wall={gate_report.measured_min_wall_mm:.3f} mm, "
        f"minimum clearance={gate_report.measured_min_clearance_mm:.3f} mm"
    )
    mark_stage(4)
    print(
        "[4/5] mechanical visual cross-check recorded: "
        f"{out_dir / 'visual-crosscheck-mechanical.json'}"
    )
    mark_stage(5)
    artifact_manifest = json.loads(
        projection.artifact_manifest_path.read_text(encoding="utf-8")
    )
    artifact_hashes = {
        str(item["role"]): str(item["normalized_sha256"])
        for item in artifact_manifest["artifacts"]
    }
    manifest_hash = "sha256:" + hashlib.sha256(
        projection.artifact_manifest_path.read_bytes()
    ).hexdigest()

    evidence = Evidence(
        evidence_id=evidence_id(graph.graph_id, "mechanical"),
        target_revision=graph.revision,
        status="valid",
        envelope=projection.envelope,
        claims=[
            EvidenceClaim(
                subject_node=subject_node,
                property="cad_kernel_valid",
                value=gate_report.kernel_valid,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="interference_free",
                value=gate_report.interference,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="maximum_interference_volume_mm3",
                value=gate_report.measured_max_interference_volume_mm3,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="internal_clearance_passed",
                value=gate_report.clearance,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="measured_min_clearance_mm",
                value=gate_report.measured_min_clearance_mm,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="minimum_wall_thickness_mm",
                value=gate_report.measured_min_wall_mm,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="shell_measured_volume_mm3",
                value=artifact_report.shell_volume_mm3,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="lid_measured_volume_mm3",
                value=artifact_report.lid_volume_mm3,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="assembly_measured_volume_mm3",
                value=artifact_report.assembly_volume_mm3,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="cad_artifact_manifest_hash",
                value=manifest_hash,
                verified=True,
            ),
            *[
                EvidenceClaim(
                    subject_node=subject_node,
                    property=f"{role}_normalized_sha256",
                    value=artifact_hash,
                    verified=True,
                )
                for role, artifact_hash in sorted(artifact_hashes.items())
            ],
        ],
        created_at=datetime.now(UTC),
    )
    evidence_path = out_dir / "evidence-mechanical.json"
    evidence_path.write_text(evidence.model_dump_json(indent=2) + "\n")
    summary: dict[str, object] = {
        "step_path": str(projection.shell_step_path),
        "shell_step_path": str(projection.shell_step_path),
        "lid_step_path": str(projection.lid_step_path),
        "assembly_step_path": str(projection.assembly_step_path),
        "model_path": str(projection.model_path),
        "artifact_manifest_path": str(projection.artifact_manifest_path),
        "artifacts": artifact_manifest["artifacts"],
        "normalized_output_hash": projection.envelope.output_hash,
        "evidence": str(evidence_path),
        "provisional": evidence.is_provisional(),
        "authoritative": evidence.supports_authoritative_pass(graph.revision),
        "measured_volume_mm3": gate_report.measured_volume_mm3,
        "measured_min_wall_mm": gate_report.measured_min_wall_mm,
        "measured_min_clearance_mm": gate_report.measured_min_clearance_mm,
        "measured_max_interference_volume_mm3": (
            gate_report.measured_max_interference_volume_mm3
        ),
        "shell_measured_volume_mm3": artifact_report.shell_volume_mm3,
        "lid_measured_volume_mm3": artifact_report.lid_volume_mm3,
        "assembly_measured_volume_mm3": artifact_report.assembly_volume_mm3,
        "shell_bbox_mm": artifact_report.shell_bbox_mm,
        "lid_bbox_mm": artifact_report.lid_bbox_mm,
        "assembly_bbox_mm": artifact_report.assembly_bbox_mm,
        "visual_projections": "visual-projections-mechanical.json",
        "visual_projection_identity_hash": visual_projections.identity_hash,
        "visual_projection_canonical_hash": visual_projections.canonical_hash,
        "visual_crosscheck": "visual-crosscheck-mechanical.json",
        "visual_crosscheck_identity_hash": visual_crosscheck.identity_hash,
        "visual_crosscheck_canonical_hash": visual_crosscheck.canonical_hash,
    }
    print(f"[5/5] mechanical evidence recorded: {evidence_path}")
    if timing_recorder is not None:
        timing_recorder.finish("enclosure[5/5]")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_lane_io_arguments(parser, out_default=Path("out/gd1-enclosure"))
    parser.add_argument(
        "--pipeline-workers",
        type=int,
        default=DEFAULT_CAD_STAGE_WORKERS,
        help="parallel workers for independent Python pipeline stages",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    timing = TimingRecorder()
    timing.start("gd1-enclosure-pipeline")
    try:
        parameters = inspect.signature(run_pipeline).parameters
        kwargs: dict[str, object] = {"pipeline_workers": args.pipeline_workers}
        if "timing_recorder" in parameters:
            kwargs["timing_recorder"] = timing
        summary = run_pipeline(args.fixture, args.out, **kwargs)  # type: ignore[arg-type]
    except Exception as exc:
        print(f"PIPELINE FAILED (fail-closed): {exc}", file=sys.stderr)
        return 1
    finally:
        timing.finish_open()
        write_timing_record(args.out, timing)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if summary["authoritative"]:
        print("PIPELINE PASSED (authoritative container execution)")
    else:
        print("PIPELINE PASSED (provisional host execution)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
