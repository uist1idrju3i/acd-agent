"""Golden Design #1 mechanical pipeline: graph -> CAD projection -> gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from acd.adapters.cad.mechanical import (
    measure_enclosure_artifacts,
    run_mechanical_gates,
)
from acd.adapters.cad.project import project_enclosure
from acd.core.mechanical import extract_mechanical_lane
from acd.openhands.tools.probe import probe_cad_kernel
from acd.pipeline.rationale import validate_and_project_rationale
from acd.schema.design_graph import DesignGraph
from acd.schema.evidence import Evidence, EvidenceClaim


def run_pipeline(fixture_dir: Path, out_dir: Path) -> dict[str, object]:
    graph_path = fixture_dir / "graph.json"
    graph = DesignGraph.model_validate(
        json.loads(graph_path.read_text(encoding="utf-8"))
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    validate_and_project_rationale(graph, fixture_dir, out_dir)
    print("[0/4] rationale coverage passed")
    lane = extract_mechanical_lane(graph)
    print("[1/4] mechanical lane extracted")

    projection = project_enclosure(
        lane,
        graph_path=graph_path,
        out_dir=out_dir,
        target_revision=graph.revision,
    )
    print(
        "[2/4] enclosure CAD projected: "
        f"shell={projection.shell_step_path}, "
        f"lid={projection.lid_step_path}, "
        f"assembly={projection.assembly_step_path}"
    )

    probe = probe_cad_kernel()
    gate_report = run_mechanical_gates(
        step_path=projection.shell_step_path,
        lane=lane,
        kernel_probe=probe,
    )
    artifact_report = measure_enclosure_artifacts(
        shell_step_path=projection.shell_step_path,
        lid_step_path=projection.lid_step_path,
        assembly_step_path=projection.assembly_step_path,
    )
    print(
        "[3/4] mechanical gates passed: "
        f"volume={gate_report.measured_volume_mm3:.3f} mm3, "
        f"minimum wall={gate_report.measured_min_wall_mm:.3f} mm, "
        f"minimum clearance={gate_report.measured_min_clearance_mm:.3f} mm"
    )
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
        evidence_id="evidence.gd1.mechanical",
        target_revision=graph.revision,
        status="valid",
        envelope=projection.envelope,
        claims=[
            EvidenceClaim(
                subject_node="mechanical.enclosure.gd1",
                property="cad_kernel_valid",
                value=gate_report.kernel_valid,
                verified=True,
            ),
            EvidenceClaim(
                subject_node="mechanical.enclosure.gd1",
                property="interference_free",
                value=gate_report.interference,
                verified=True,
            ),
            EvidenceClaim(
                subject_node="mechanical.enclosure.gd1",
                property="maximum_interference_volume_mm3",
                value=gate_report.measured_max_interference_volume_mm3,
                verified=True,
            ),
            EvidenceClaim(
                subject_node="mechanical.enclosure.gd1",
                property="internal_clearance_passed",
                value=gate_report.clearance,
                verified=True,
            ),
            EvidenceClaim(
                subject_node="mechanical.enclosure.gd1",
                property="measured_min_clearance_mm",
                value=gate_report.measured_min_clearance_mm,
                verified=True,
            ),
            EvidenceClaim(
                subject_node="mechanical.enclosure.gd1",
                property="minimum_wall_thickness_mm",
                value=gate_report.measured_min_wall_mm,
                verified=True,
            ),
            EvidenceClaim(
                subject_node="mechanical.enclosure.gd1",
                property="shell_measured_volume_mm3",
                value=artifact_report.shell_volume_mm3,
                verified=True,
            ),
            EvidenceClaim(
                subject_node="mechanical.enclosure.gd1",
                property="lid_measured_volume_mm3",
                value=artifact_report.lid_volume_mm3,
                verified=True,
            ),
            EvidenceClaim(
                subject_node="mechanical.enclosure.gd1",
                property="assembly_measured_volume_mm3",
                value=artifact_report.assembly_volume_mm3,
                verified=True,
            ),
            EvidenceClaim(
                subject_node="mechanical.enclosure.gd1",
                property="cad_artifact_manifest_hash",
                value=manifest_hash,
                verified=True,
            ),
            *[
                EvidenceClaim(
                    subject_node="mechanical.enclosure.gd1",
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
    }
    print(f"[4/4] mechanical evidence recorded: {evidence_path}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path("fixtures/golden-design-1"))
    parser.add_argument("--out", type=Path, default=Path("out/gd1-enclosure"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        summary = run_pipeline(args.fixture, args.out)
    except Exception as exc:
        print(f"PIPELINE FAILED (fail-closed): {exc}", file=sys.stderr)
        return 1
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if summary["provisional"]:
        print("PIPELINE PASSED (provisional host execution)")
    else:
        print("PIPELINE PASSED (authoritative container execution)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
