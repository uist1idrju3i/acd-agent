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
import csv
import json
import sys
from pathlib import Path
from typing import cast

from acd_adapter_freerouting.dsn import export_dsn
from acd_adapter_freerouting.router import FreeroutingRunner
from acd_adapter_freerouting.ses import parse_ses
from acd_adapter_kicad.cli import KicadCli
from acd_adapter_kicad.fab import (
    BoardMeasurement,
    CplBasisError,
    apply_cpl_contract,
    cross_validate_bom,
    cross_validate_cpl,
    deterministic_zip,
    jlcpcb_bom_csv,
    jlcpcb_cpl_csv,
    parse_pos_csv,
    parse_routed_board,
    read_drill_measurement,
    run_dfm,
    verify_smd_pad_centers_in_gerber,
    zip_content_hash,
)
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
from acd_core.fab import extract_fab_intent, load_fab_profile
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


def run_pipeline(
    fixture_dir: Path,
    out_dir: Path,
    max_passes: int,
    fab_profile_path: Path,
) -> dict[str, str]:
    graph = DesignGraph.model_validate(
        json.loads((fixture_dir / "graph.json").read_text(encoding="utf-8"))
    )
    revision = graph.revision
    lane = extract_electrical_lane(graph)
    intent, allowances = extract_fab_intent(graph)
    profile = load_fab_profile(fab_profile_path)
    if intent.fab_profile != profile.profile_id:
        raise ValueError(
            f"graph fab profile {intent.fab_profile!r} differs from loaded profile "
            f"{profile.profile_id!r}"
        )

    project = write_project(lane, fixture_dir, out_dir, profile=profile)
    name = project.name
    kicad = KicadCli()

    print(f"[1/10] project written: {project.root}")

    erc = kicad.erc(project.schematic, out_dir / f"{name}.erc.json", revision)
    assert_rule_check_passed("ERC", erc, require_connected=False)
    print("[2/10] ERC gate passed (0 errors)")

    dsn_path = out_dir / f"{name}.dsn"
    dsn_path.write_text(export_dsn(project.board_projection.model, name))

    router = FreeroutingRunner()
    ses_path = out_dir / f"{name}.ses"
    route_run = router.route(dsn_path, ses_path, revision, max_passes=max_passes)
    assert_converged(route_run.envelope.convergence_state)
    print(f"[3/10] routing converged (skipped={route_run.skipped})")

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
    dru_path = out_dir / f"{name}.kicad_dru"
    if dru_path.is_file():
        (routed_dir / f"{name}.kicad_dru").write_text(
            dru_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    print(
        f"[4/10] SES imported: {len(routes.wires)} wires, {len(routes.vias)} vias; "
        f"observed_min_width={routes.observed_min_width_mm:.4f} mm; "
        f"normalized_wires={routes.normalized_wire_count}"
    )

    drc = kicad.drc(routed_path, out_dir / f"{name}.drc.json", revision)
    assert_rule_check_passed("DRC", drc, require_connected=True)
    print("[5/10] DRC gate passed (0 errors, 0 unconnected)")

    gerber_dir = out_dir / "gerbers"
    _gerber_run, gerber_paths = kicad.export_gerbers(
        routed_path, gerber_dir, GERBER_LAYERS, revision
    )
    _drill_run, drill_paths = kicad.export_drill(routed_path, gerber_dir, revision)
    print(f"[6/10] fabrication outputs: {len(gerber_paths)} gerbers, {len(drill_paths)} drill")

    expected_nets = set(project.board_projection.net_numbers)
    expected_refdes = {c.refdes for c in lane.components}
    verify_schematic(project.schematic, expected_refdes)
    verify_board(routed_path, expected_nets, expected_refdes)
    for layer, path in zip(GERBER_LAYERS, gerber_paths, strict=True):
        # Bottom-side legend may be legitimately empty on a top-assembly board.
        verify_gerber(path, min_objects=0 if layer == "B.SilkS" else 1)
    for path in drill_paths:
        verify_drill(path)
    print("[7/10] independent reload passed (sexpdata + gerbonara)")

    fab_dir = out_dir / "fab"
    fab_dir.mkdir(parents=True, exist_ok=True)
    pos_path = fab_dir / f"{name}.pos.csv"
    kicad.export_pos(routed_path, pos_path, revision)
    pos_rows = parse_pos_csv(pos_path)
    fitted = {component.refdes for component in lane.components if component.assembly == "fitted"}
    cpl_path = fab_dir / f"{name}-cpl-jlcpcb.csv"
    measurement = parse_routed_board(routed_path)
    drill_tools, drill_count = read_drill_measurement(drill_paths[0])
    measurement = BoardMeasurement(
        measurement.footprints,
        measurement.vias,
        measurement.min_track_width_mm,
        measurement.silk_min_height_mm,
        measurement.silk_min_width_mm,
        measurement.outline_bbox_mm,
        drill_tools,
        drill_count,
    )
    verify_smd_pad_centers_in_gerber(
        gerber_paths[GERBER_LAYERS.index("F.Cu")], measurement
    )
    edge_overhang_declarations = {
        str(node.attrs["component_refdes"]): float(str(node.attrs["overhang_mm"]))
        for node in graph.nodes
        if node.kind == "mechanical.board_edge_overhang"
    }
    cpl_basis_path = fab_dir / "cpl-basis-report.json"
    try:
        resolved_pos_rows, cpl_basis_report = apply_cpl_contract(
            pos_rows, measurement, lane, profile, fitted
        )
    except CplBasisError as exc:
        cpl_basis_report = exc.report
        cpl_basis_path.write_text(
            json.dumps(cpl_basis_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        unknowns = cast(dict[str, object], cpl_basis_report["unknowns"])
        dfm_report = run_dfm(
            measurement,
            profile,
            revision,
            allowances,
            lane,
            intent,
            edge_clearance_mm=lane.board.edge_copper_clearance_mm,
            edge_overhang_declarations=edge_overhang_declarations,
            cpl_unknowns={
                key: tuple(cast(list[str], value))
                for key, value in unknowns.items()
                if isinstance(value, list)
            },
        )
        dfm_report["status"] = "fail"
        dfm_path = fab_dir / "dfm-report.json"
        dfm_path.write_text(
            json.dumps(dfm_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        failure_package: dict[str, object] = {
            "schema_version": "0.1",
            "status": "fail",
            "target_revision": revision,
            "fab_profile": {
                "profile_id": profile.profile_id,
                "source_url": profile.data["sources"][0]["url"],
                "fetched_at": profile.data["sources"][0]["fetched_at"],
            },
            "files": [],
            "gates": {"cpl_basis": "fail", "dfm": str(dfm_report["status"])},
            "unknowns": unknowns,
        }
        (fab_dir / "fab-package.json").write_text(
            json.dumps(failure_package, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        raise
    cpl_path.write_text(jlcpcb_cpl_csv(resolved_pos_rows, fitted), encoding="utf-8")
    cpl_basis_path.write_text(
        json.dumps(cpl_basis_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    cross_validate_cpl(
        cpl_path,
        pos_rows,
        measurement,
        fitted,
        cast(dict[str, str], cpl_basis_report["position_bases"]),
        cast(dict[str, float], cpl_basis_report["rotation_offsets"]),
    )
    bom_path = fab_dir / f"{name}-bom-jlcpcb.csv"
    bom_path.write_text(jlcpcb_bom_csv(lane), encoding="utf-8")
    cross_validate_bom(bom_path, lane, fitted)
    with bom_path.open(newline="", encoding="utf-8") as stream:
        bom_rows = tuple(csv.DictReader(stream))
    print(
        f"[8/10] CPL/BOM generated and cross-validated "
        f"({len(pos_rows)} position rows, {len(bom_rows)} BOM rows)"
    )

    dfm_report = run_dfm(
        measurement,
        profile,
        revision,
        allowances,
        lane,
        intent,
        edge_clearance_mm=lane.board.edge_copper_clearance_mm,
        edge_overhang_declarations=edge_overhang_declarations,
        cpl_unknowns={
            key: tuple(cast(list[str], value))
            for key, value in cast(dict[str, object], cpl_basis_report["unknowns"]).items()
            if isinstance(value, list)
        },
    )
    dfm_path = fab_dir / "dfm-report.json"
    dfm_path.write_text(json.dumps(dfm_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(
        f"[9/10] DFM report written ({dfm_report['status']}; "
        f"{len(cast(list[object], dfm_report['findings']))} findings)"
    )

    package_members = [*gerber_paths, *drill_paths]
    zip_path = fab_dir / f"{name}-gerbers.zip"
    deterministic_zip(zip_path, package_members, gerber_dir)
    profile_hash = normalized_hash(fab_profile_path)
    manifest: dict[str, object] = {
        "schema_version": "0.1",
        "status": "not_order_ready",
        "target_revision": revision,
        "fab_profile": {
            "profile_id": profile.profile_id,
            "source_url": profile.data["sources"][0]["url"],
            "fetched_at": profile.data["sources"][0]["fetched_at"],
            "hash": profile_hash,
        },
        "overlays": list(project.board_projection.overlays),
        "files": [
            {
                "path": str(path.relative_to(out_dir)),
                "content_hash": (
                    zip_content_hash(path) if path.suffix == ".zip" else normalized_hash(path)
                ),
            }
            for path in [
                *gerber_paths,
                *drill_paths,
                zip_path,
                bom_path,
                cpl_path,
                pos_path,
                dfm_path,
            ]
        ],
        "content_hash": zip_content_hash(zip_path),
        "tools": {"kicad-cli": kicad.version(), "measurement_parser": "sexpdata+gerbonara"},
        "gates": {
            "drc": (
                "pass"
                if drc.error_count == 0 and not drc.unconnected_items
                else "fail"
            ),
            "dfm": str(dfm_report["status"]),
        },
        "pcb_class": "standard",
        "pcb_class_basis": "profile:combinations; standard PCB process without advanced options",
        "pcba_class": intent.pcba_class_target,
        "unknowns": {
            "price": "unknown",
            "inventory": "unknown",
            "lead_time": "unknown",
            "total_order_amount": "unknown",
            "fab_dfm_review": "unknown",
            "cpl_rotation_basis_fab_lcsc": (
                "unknown: KiCad rotation was emitted without independent fab/LCSC "
                "component-orientation preview comparison"
            ),
        },
    }
    cpl_unknowns = cast(dict[str, object], cpl_basis_report["unknowns"])
    position_unknown = cast(list[str], cpl_unknowns["cpl_position_basis"])
    rotation_unknown = cast(list[str], cpl_unknowns["cpl_rotation_basis_fab_lcsc"])
    readiness_reasons: list[str] = []
    if position_unknown:
        readiness_reasons.append("CPL位置基準に未確認またはestimatedの部品がある")
    if rotation_unknown:
        readiness_reasons.append("CPL回転基準に未確認の部品がある")
    if dfm_report["status"] != "pass":
        readiness_reasons.append("実測DFM指摘が未解決である")
    order_readiness = {
        "schema_version": "0.1",
        "status": "not_order_ready" if readiness_reasons else "ready",
        "target_revision": revision,
        "reasons": readiness_reasons,
        "unknowns": {
            "cpl_position_basis": position_unknown,
            "cpl_rotation_basis_fab_lcsc": rotation_unknown,
        },
    }
    order_readiness_path = fab_dir / "order-readiness.json"
    order_readiness_path.write_text(
        json.dumps(order_readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    manifest["status"] = order_readiness["status"]
    cast(dict[str, object], manifest["gates"])["order_readiness"] = order_readiness["status"]
    cast(list[dict[str, str]], manifest["files"]).append(
        {
            "path": str(order_readiness_path.relative_to(out_dir)),
            "content_hash": normalized_hash(order_readiness_path),
        }
    )
    cast(dict[str, object], manifest["unknowns"]).update(
        cast(dict[str, object], dfm_report["unknowns"])
    )
    package_path = fab_dir / "fab-package.json"
    package_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print("[10/10] manufacturing package written")

    hashes: dict[str, str] = {}
    hash_paths = [
        project.schematic,
        project.board,
        project.bom,
        routed_path,
        dsn_path,
        routing_summary_path,
        pos_path,
        bom_path,
        cpl_path,
        dfm_path,
        order_readiness_path,
        package_path,
        zip_path,
        *gerber_paths,
        *drill_paths,
    ]
    for path in hash_paths:
        hashes[str(path.relative_to(out_dir))] = (
            zip_content_hash(path) if path.suffix == ".zip" else normalized_hash(path)
        )
    manifest_path = out_dir / "hashes.json"
    manifest_path.write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n")
    print(f"[10/10] hash manifest: {manifest_path}")
    if order_readiness["status"] != "ready":
        print("製造データは生成済み、発注は不可: order-readiness gate failed")
        raise ValueError(f"Order readiness gate failed: {order_readiness_path}")
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
    parser.add_argument(
        "--fab-profile",
        type=Path,
        default=Path("profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json"),
        help="versioned fab profile",
    )
    args = parser.parse_args()
    try:
        run_pipeline(args.fixture, args.out, args.max_passes, args.fab_profile)
    except Exception as exc:  # fail-closed: any unhandled state stops with nonzero exit
        print(f"PIPELINE FAILED (fail-closed): {exc}", file=sys.stderr)
        return 1
    print("PIPELINE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
