"""Golden Design #1 electrical pipeline: fixture -> Gerber/drill (fail-closed).

Single deterministic command:

    uv run python scripts/run_gd1_pipeline.py --out out/gd1

Stages: graph load/validation -> electrical lane -> KiCad project projection
(schematic, deterministically placed board, BOM) -> kicad-cli ERC gate ->
Specctra DSN export -> freerouting -> SES import -> route injection ->
kicad-cli DRC gate -> Gerber/drill export -> independent reload (sexpdata +
gerbonara) -> normalized output hash manifest. Every external run is wrapped
in a ToolEnvelope; reruns with identical inputs reuse recorded results so
side effects are never duplicated. Any unknown or failing state stops the
pipeline with a nonzero exit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd_adapter_freerouting.dsn import export_dsn
from acd_adapter_freerouting.router import FreeroutingRunner
from acd_adapter_freerouting.ses import parse_ses
from acd_adapter_kicad.cli import KicadCli
from acd_adapter_kicad.gates import assert_converged, assert_rule_check_passed
from acd_adapter_kicad.project import write_project
from acd_adapter_kicad.reload import (
    normalized_hash,
    verify_board,
    verify_drill,
    verify_gerber,
    verify_schematic,
)
from acd_adapter_kicad.routing import inject_routes
from acd_core.electrical import extract_electrical_lane
from acd_schema.design_graph import DesignGraph

GERBER_LAYERS = [
    "F.Cu",
    "B.Cu",
    "F.Mask",
    "B.Mask",
    "F.SilkS",
    "B.SilkS",
    "F.Paste",
    "Edge.Cuts",
]


def run_pipeline(fixture_dir: Path, out_dir: Path, max_passes: int) -> dict[str, str]:
    graph = DesignGraph.model_validate(
        json.loads((fixture_dir / "graph.json").read_text(encoding="utf-8"))
    )
    revision = graph.revision
    lane = extract_electrical_lane(graph)

    project = write_project(lane, fixture_dir, out_dir)
    name = project.name
    kicad = KicadCli()

    print(f"[1/8] project written: {project.root}")

    erc = kicad.erc(project.schematic, out_dir / f"{name}.erc.json", revision)
    assert_rule_check_passed("ERC", erc, require_connected=False)
    print("[2/8] ERC gate passed (0 errors)")

    dsn_path = out_dir / f"{name}.dsn"
    dsn_path.write_text(export_dsn(project.board_projection.model, name))

    router = FreeroutingRunner()
    ses_path = out_dir / f"{name}.ses"
    route_run = router.route(dsn_path, ses_path, revision, max_passes=max_passes)
    assert_converged(route_run.envelope.convergence_state)
    print(f"[3/8] routing converged (skipped={route_run.skipped})")

    routes = parse_ses(
        ses_path.read_text(),
        minimum_width_mm=lane.board.min_track_mm,
    )
    routing_summary_path = out_dir / "routing-summary.json"
    routing_summary_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "target_revision": revision,
                "wire_count": len(routes.wires),
                "via_count": len(routes.vias),
                "observed_min_wire_width_mm": routes.observed_min_width_mm,
                "minimum_width_mm": lane.board.min_track_mm,
                "normalized_wire_count": routes.normalized_wire_count,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    routed_board = inject_routes(
        project.board.read_text(),
        routes,
        project.board_projection.net_numbers,
        lane.board.via_diameter_mm,
        lane.board.via_drill_mm,
    )
    # kicad-cli reads DRC constraints from the sibling .kicad_pro, so the
    # routed board lives in its own directory with a copy of the project file.
    routed_dir = out_dir / "routed"
    routed_dir.mkdir(parents=True, exist_ok=True)
    routed_path = routed_dir / f"{name}.kicad_pcb"
    routed_path.write_text(routed_board)
    (routed_dir / f"{name}.kicad_pro").write_text(project.project.read_text())
    print(
        f"[4/8] SES imported: {len(routes.wires)} wires, {len(routes.vias)} vias; "
        f"observed_min_width={routes.observed_min_width_mm:.4f} mm; "
        f"normalized_wires={routes.normalized_wire_count}"
    )

    drc = kicad.drc(routed_path, out_dir / f"{name}.drc.json", revision)
    assert_rule_check_passed("DRC", drc, require_connected=True)
    print("[5/8] DRC gate passed (0 errors, 0 unconnected)")

    gerber_dir = out_dir / "gerbers"
    _gerber_run, gerber_paths = kicad.export_gerbers(
        routed_path, gerber_dir, GERBER_LAYERS, revision
    )
    _drill_run, drill_paths = kicad.export_drill(routed_path, gerber_dir, revision)
    print(f"[6/8] fabrication outputs: {len(gerber_paths)} gerbers, {len(drill_paths)} drill")

    expected_nets = set(project.board_projection.net_numbers)
    expected_refdes = {c.refdes for c in lane.components}
    verify_schematic(project.schematic, expected_refdes)
    verify_board(routed_path, expected_nets, expected_refdes)
    for layer, path in zip(GERBER_LAYERS, gerber_paths, strict=True):
        # Bottom-side legend may be legitimately empty on a top-assembly board.
        verify_gerber(path, min_objects=0 if layer == "B.SilkS" else 1)
    for path in drill_paths:
        verify_drill(path)
    print("[7/8] independent reload passed (sexpdata + gerbonara)")

    hashes: dict[str, str] = {}
    for path in [
        project.schematic,
        project.board,
        project.bom,
        routed_path,
        dsn_path,
        routing_summary_path,
    ]:
        hashes[path.name] = normalized_hash(path)
    for path in [*gerber_paths, *drill_paths]:
        hashes[f"gerbers/{path.name}"] = normalized_hash(path)
    manifest_path = out_dir / "hashes.json"
    manifest_path.write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n")
    print(f"[8/8] hash manifest: {manifest_path}")
    return hashes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("fixtures/golden-design-1"),
        help="fixture directory containing graph.json",
    )
    parser.add_argument("--out", type=Path, default=Path("out/gd1"), help="output directory")
    parser.add_argument("--max-passes", type=int, default=99999, help="router pass budget")
    args = parser.parse_args()
    try:
        run_pipeline(args.fixture, args.out, args.max_passes)
    except Exception as exc:  # fail-closed: any unhandled state stops with nonzero exit
        print(f"PIPELINE FAILED (fail-closed): {exc}", file=sys.stderr)
        return 1
    print("PIPELINE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
