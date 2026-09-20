"""Fabrication deliverables: CPL/BOM, measured DFM report, and the manufacturing package."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from acd.adapters.kicad.cli import KicadCli, RuleCheckResult
from acd.adapters.kicad.fab import (
    BoardMeasurement,
    CplBasisError,
    apply_cpl_contract,
    cross_validate_bom,
    cross_validate_cpl,
    deterministic_zip,
    jlcpcb_bom_csv,
    jlcpcb_cpl_csv,
    parse_pos_csv,
    run_dfm,
    verify_lcsc_rotation_evidence,
    zip_content_hash,
)
from acd.adapters.kicad.project import ProjectFiles
from acd.adapters.kicad.reload import normalized_hash
from acd.core.electrical.board_model import RoutedDesign
from acd.core.electrical.electrical import ElectricalLane
from acd.core.knowledge.naming import artifact_prefix
from acd.core.manufacturing.fab import FabOrderIntentView, FabProfile, ProcessAllowanceView
from acd.core.runtime.fileio import write_json
from acd.pipeline.repository import repository_root
from acd.schema.design_graph import DesignGraph

from .evidence import check_rotation_offsets
from .measurement import GERBER_LAYERS


@dataclass(frozen=True)
class CplBomOutputs:
    fab_dir: Path
    pos_path: Path
    cpl_path: Path
    bom_path: Path
    cpl_basis_path: Path
    cpl_basis_report: dict[str, object]
    edge_overhang_declarations: dict[str, float]


@dataclass(frozen=True)
class PackageOutputs:
    zip_path: Path
    package_path: Path
    order_readiness_path: Path
    order_readiness: dict[str, object]


def generate_cpl_bom(
    *,
    kicad: KicadCli,
    project: ProjectFiles,
    routed_path: Path,
    out_dir: Path,
    fixture_dir: Path,
    revision: str,
    graph: DesignGraph,
    lane: ElectricalLane,
    measurement: BoardMeasurement,
    profile: FabProfile,
    allowances: tuple[ProcessAllowanceView, ...],
    intent: FabOrderIntentView,
    silk_evidence: dict[str, object],
) -> CplBomOutputs:
    """Emit JLCPCB CPL/BOM and cross-validate them; write a failing package on CPL basis errors."""
    name = project.name
    fab_dir = out_dir / "fab"
    fab_dir.mkdir(parents=True, exist_ok=True)
    pos_path = fab_dir / f"{name}.pos.csv"
    kicad.export_pos(routed_path, pos_path, revision)
    pos_rows = parse_pos_csv(pos_path)
    fitted = {component.refdes for component in lane.components if component.assembly == "fitted"}
    cpl_path = fab_dir / f"{name}-cpl-jlcpcb.csv"
    edge_overhang_declarations = {
        str(node.attrs["component_refdes"]): float(str(node.attrs["overhang_mm"]))
        for node in graph.nodes
        if node.kind == "mechanical.board_edge_overhang"
    }
    cpl_basis_path = fab_dir / "cpl-basis-report.json"
    lcsc_evidence_dir = (
        repository_root() / f"evidence/{artifact_prefix(graph.graph_id)}-cpl-orientation"
    )
    verified_rotation_offsets, rotation_evidence_notes, rotation_unknowns = (
        verify_lcsc_rotation_evidence(lcsc_evidence_dir, fixture_dir, measurement, lane, fitted)
    )
    try:
        resolved_pos_rows, cpl_basis_report = apply_cpl_contract(
            pos_rows, measurement, lane, profile, fitted
        )
    except CplBasisError as exc:
        cpl_basis_report = exc.report
        write_json(cpl_basis_path, cpl_basis_report, mkdir=False)
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
            silkscreen_evidence=silk_evidence,
        )
        dfm_report["status"] = "fail"
        dfm_path = fab_dir / "dfm-report.json"
        write_json(dfm_path, dfm_report, mkdir=False)
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
        write_json(fab_dir / "fab-package.json", failure_package, mkdir=False)
        raise
    cpl_path.write_text(jlcpcb_cpl_csv(resolved_pos_rows, fitted), encoding="utf-8")
    declared_rotation_offsets = cast(dict[str, float], cpl_basis_report["rotation_offsets"])
    check_rotation_offsets(
        lane, declared_rotation_offsets, verified_rotation_offsets, lcsc_evidence_dir
    )
    cpl_basis_report["rotation_evidence"] = rotation_evidence_notes
    cpl_unknowns = cast(dict[str, object], cpl_basis_report["unknowns"])
    existing_rotation_unknowns = cast(list[str], cpl_unknowns["cpl_rotation_basis_fab_lcsc"])
    cpl_unknowns["cpl_rotation_basis_fab_lcsc"] = sorted(
        set(existing_rotation_unknowns).union(rotation_unknowns)
    )
    write_json(cpl_basis_path, cpl_basis_report, mkdir=False)
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
        f"[8/12] CPL/BOM generated and cross-validated "
        f"({len(pos_rows)} position rows, {len(bom_rows)} BOM rows)"
    )
    return CplBomOutputs(
        fab_dir=fab_dir,
        pos_path=pos_path,
        cpl_path=cpl_path,
        bom_path=bom_path,
        cpl_basis_path=cpl_basis_path,
        cpl_basis_report=cpl_basis_report,
        edge_overhang_declarations=edge_overhang_declarations,
    )


def write_dfm_report(
    *,
    fab_dir: Path,
    measurement: BoardMeasurement,
    profile: FabProfile,
    revision: str,
    allowances: tuple[ProcessAllowanceView, ...],
    lane: ElectricalLane,
    intent: FabOrderIntentView,
    edge_overhang_declarations: dict[str, float],
    cpl_basis_report: dict[str, object],
    silk_evidence: dict[str, object],
    width_evidence: dict[str, object],
    plane_measurement: dict[str, object],
    pruning_evidence: dict[str, object],
    routes: RoutedDesign,
    stitch_vias: tuple[tuple[float, float], ...],
    drill_count: int,
) -> tuple[Path, dict[str, object], dict[str, object]]:
    """Write the measured DFM report and return its path, body, and via-cost evidence."""
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
        silkscreen_evidence=silk_evidence,
    )
    profile_preferences = cast(list[dict[str, object]], profile.data["preferences"])
    via_driver_ids = {
        "via-hole-prefer-020",
        "via-hole-015-cost",
        "via-hole-small-diameter-cost",
        "via-diameter-margin-quality",
        "via-hole-capability",
    }
    via_profile_drivers = [
        {
            "rule_id": str(preference["rule_id"]),
            "description": str(preference.get("description", "")),
            "impact": preference.get("impact"),
            "threshold": preference.get("threshold"),
            "matched_dfm_findings": sum(
                str(finding.get("rule_id")) == str(preference["rule_id"])
                for finding in cast(list[dict[str, object]], dfm_report["findings"])
            ),
        }
        for preference in profile_preferences
        if str(preference["rule_id"]) in via_driver_ids
    ]
    via_profile_evidence: dict[str, object] = {
        "route_via_count": len(routes.vias),
        "stitch_via_count": len(stitch_vias),
        "total_routing_via_count": len(routes.vias) + len(stitch_vias),
        "added_via_count_vs_route_only": len(stitch_vias),
        "ground_plane_drill_object_count": drill_count,
        "estimated_drill_object_count_without_stitch": drill_count - len(stitch_vias),
        "added_drill_object_count_vs_route_only": len(stitch_vias),
        "via_diameter_mm": lane.board.via_diameter_mm,
        "via_drill_mm": lane.board.via_drill_mm,
        "profile_driver_basis": via_profile_drivers,
        "count_based_cost_driver_present": False,
        "count_based_cost_driver_note": (
            "The fab profile has geometry/process thresholds but no numeric "
            "per-via quantity surcharge; added via and drill counts are recorded "
            "as process burden."
        ),
    }
    dfm_report["ground_plane"] = {
        **plane_measurement,
        "routed_board_net_name_source": measurement.net_name_source,
        "stitch_via_pruning": pruning_evidence,
        "stitch_via_count": len(stitch_vias),
        "drill_count": drill_count,
        "cost_note": lane.board.stitch_via_cost_note,
        "via_profile_cost_evidence": via_profile_evidence,
    }
    dfm_report["routing_width"] = width_evidence
    dfm_path = fab_dir / "dfm-report.json"
    write_json(dfm_path, dfm_report, mkdir=False)
    print(
        f"[9/12] DFM report written ({dfm_report['status']}; "
        f"{len(cast(list[object], dfm_report['findings']))} findings)"
    )
    return dfm_path, dfm_report, via_profile_evidence


def write_manufacturing_package(
    *,
    project: ProjectFiles,
    out_dir: Path,
    fab_dir: Path,
    gerber_dir: Path,
    gerber_paths: Sequence[Path],
    drill_paths: Sequence[Path],
    gbrjob_path: Path,
    cpl: CplBomOutputs,
    dfm_path: Path,
    dfm_report: dict[str, object],
    kicad: KicadCli,
    drc: RuleCheckResult,
    revision: str,
    profile: FabProfile,
    resolved_fab_profile_path: Path,
    intent: FabOrderIntentView,
    lane: ElectricalLane,
    measurement: BoardMeasurement,
    filled_board_hash: str,
    silk_evidence: dict[str, object],
    width_evidence: dict[str, object],
    plane_measurement: dict[str, object],
    pruning_evidence: dict[str, object],
    via_profile_evidence: dict[str, object],
    stitch_vias: tuple[tuple[float, float], ...],
    drill_count: int,
) -> PackageOutputs:
    """Zip the Gerbers and write fab-package.json plus the order-readiness gate record."""
    name = project.name
    bom_path = cpl.bom_path
    cpl_path = cpl.cpl_path
    pos_path = cpl.pos_path
    cpl_basis_path = cpl.cpl_basis_path
    cpl_basis_report = cpl.cpl_basis_report
    package_members = [*gerber_paths, *drill_paths, gbrjob_path]
    zip_path = fab_dir / f"{name}-gerbers.zip"
    deterministic_zip(zip_path, package_members, gerber_dir)
    profile_hash = normalized_hash(resolved_fab_profile_path)
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
        "required_layers": list(GERBER_LAYERS),
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
                gbrjob_path,
                cpl_basis_path,
            ]
        ],
        "content_hash": zip_content_hash(zip_path),
        "tools": {"kicad-cli": kicad.version(), "measurement_parser": "sexpdata+gerbonara"},
        "filled_board_hash": filled_board_hash,
        "routed_board_net_name_source": measurement.net_name_source,
        "ground_plane": {
            **plane_measurement,
            "stitch_via_pruning": pruning_evidence,
            "stitch_via_count": len(stitch_vias),
            "drill_count": drill_count,
            "cost_note": lane.board.stitch_via_cost_note,
            "via_profile_cost_evidence": via_profile_evidence,
        },
        "routing_width": width_evidence,
        "silkscreen": silk_evidence,
        "gates": {
            "drc": ("pass" if drc.error_count == 0 and not drc.unconnected_items else "fail"),
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
    order_readiness: dict[str, object] = {
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
    write_json(order_readiness_path, order_readiness, mkdir=False)
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
    write_json(package_path, manifest, mkdir=False)
    print("[10/12] manufacturing package written")
    return PackageOutputs(
        zip_path=zip_path,
        package_path=package_path,
        order_readiness_path=order_readiness_path,
        order_readiness=order_readiness,
    )
