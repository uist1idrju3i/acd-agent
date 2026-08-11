"""Golden Design #1 mechanical pipeline: graph -> CAD projection -> gates."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from acd_adapter_cad.project import project_enclosure
from acd_core.mechanical import extract_mechanical_lane
from acd_runtime.mechanical import run_mechanical_gates
from acd_schema.design_graph import DesignGraph
from acd_schema.evidence import Evidence, EvidenceClaim
from acd_tools.probe import probe_cad_kernel


def run_pipeline(fixture_dir: Path, out_dir: Path) -> dict[str, object]:
    graph_path = fixture_dir / "graph.json"
    graph = DesignGraph.model_validate(
        json.loads(graph_path.read_text(encoding="utf-8"))
    )
    lane = extract_mechanical_lane(graph)
    print("[1/4] mechanical lane extracted")

    projection = project_enclosure(
        lane,
        graph_path=graph_path,
        out_dir=out_dir,
        target_revision=graph.revision,
    )
    state = "skipped" if projection.skipped else "projected"
    print(f"[2/4] enclosure CAD {state}: {projection.step_path}")

    probe = probe_cad_kernel()
    gate_report = run_mechanical_gates(
        step_path=projection.step_path,
        lane=lane,
        kernel_probe=probe,
    )
    print(
        "[3/4] mechanical gates passed: "
        f"volume={gate_report.measured_volume_mm3:.3f} mm3, "
        f"minimum wall={gate_report.measured_min_wall_mm:.3f} mm, "
        f"minimum clearance={gate_report.measured_min_clearance_mm:.3f} mm"
    )

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
        ],
        created_at=datetime.now(UTC),
    )
    evidence_path = out_dir / "evidence-mechanical.json"
    evidence_path.write_text(evidence.model_dump_json(indent=2) + "\n")
    summary: dict[str, object] = {
        "step_path": str(projection.step_path),
        "model_path": str(projection.model_path),
        "normalized_output_hash": projection.envelope.output_hash,
        "skipped": projection.skipped,
        "evidence": str(evidence_path),
        "measured_volume_mm3": gate_report.measured_volume_mm3,
        "measured_min_wall_mm": gate_report.measured_min_wall_mm,
        "measured_min_clearance_mm": gate_report.measured_min_clearance_mm,
        "measured_max_interference_volume_mm3": (
            gate_report.measured_max_interference_volume_mm3
        ),
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
    print("PIPELINE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
