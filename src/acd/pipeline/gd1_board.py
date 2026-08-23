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
import re
import shutil
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Literal, cast

from acd.adapters.freerouting.dsn import export_dsn
from acd.adapters.freerouting.router import (
    DEFAULT_FREEROUTING_THREADS,
    FreeroutingRunner,
)
from acd.adapters.freerouting.ses import parse_ses
from acd.adapters.kicad.cli import KicadCli, RuleCheckResult
from acd.adapters.kicad.fab import (
    BoardMeasurement,
    CplBasisError,
    UncoveredGroundRegionsError,
    UncoveredStitchViasError,
    apply_cpl_contract,
    cross_validate_bom,
    cross_validate_cpl,
    deterministic_zip,
    jlcpcb_bom_csv,
    jlcpcb_cpl_csv,
    measure_net_path_resistance,
    measure_net_track_widths,
    measure_silkscreen,  # pyright: ignore[reportUnknownVariableType]
    parse_pos_csv,
    parse_routed_board,
    read_drill_measurement,
    run_dfm,
    verify_ground_plane_gerbers,
    verify_lcsc_rotation_evidence,
    verify_smd_pad_centers_in_gerber,
    zip_content_hash,
)
from acd.adapters.kicad.gates import (
    GateError,
    assert_converged,
    assert_rule_check_input_matches,
    assert_rule_check_passed,
)
from acd.adapters.kicad.placement import Placement
from acd.adapters.kicad.project import write_project
from acd.adapters.kicad.reload import (
    normalized_hash,
    verify_board,
    verify_drill,
    verify_gerber,
    verify_schematic,
)
from acd.adapters.kicad.routing import inject_routes, inject_stitch_vias
from acd.adapters.svg import (
    generate_firmware_visual_projections,
    generate_layout_visual_projections,
    generate_system_visual_projections,
)
from acd.core.board_model import BoardModel, NetClass
from acd.core.design_freedom import (
    load_design_freedom_declaration,
    searchable_dimensions,
    validate_change_dimension_alignment,
)
from acd.core.design_predicates import (
    PREDICATE_CATALOG,
    PredicateResult,
    evaluate_design_predicates,
)
from acd.core.electrical import ElectricalLane, extract_electrical_lane
from acd.core.fab import (
    extract_fab_intent,
    load_fab_profile,
    load_fab_profile_registry,
    resolve_fab_profile_path,
)
from acd.core.firmware_lane import extract_firmware_lane
from acd.core.functional_blocks import (
    declared_functional_blocks,
    load_functional_block_registry,
)
from acd.core.naming import output_prefix, subject_node_id
from acd.core.parallel import DEFAULT_PIPELINE_WORKERS
from acd.core.parallel import run_ordered_stages as _run_ordered_stages
from acd.core.process import execution_provenance
from acd.core.routing_width import derive_net_widths
from acd.core.silkscreen import extract_silkscreen_lane
from acd.pipeline.gate_evidence import (
    write_design_predicate_evidence,
    write_gate_evidence,
    write_gate_evidence_or_unavailable,
)
from acd.pipeline.rationale import validate_and_project_rationale
from acd.pipeline.repository import repository_root, resolve_repository_file
from acd.pipeline.routing_connectivity import measure_routing_connectivity
from acd.pipeline.stitch_candidate_evidence import (
    summarize_stitch_candidate_report,
    write_stitch_candidate_report,
)
from acd.pipeline.visual_projection import (
    crosscheck_electrical_visual_projections,
    crosscheck_firmware_visual_projections,
    generate_electrical_visual_projections,
)
from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import DesignGraph
from acd.schema.evidence import Evidence, EvidenceClaim
from acd.schema.tool_envelope import ToolEnvelope
from acd.schema.visual_crosscheck import VisualCrosscheckReport
from acd.schema.visual_projection import (
    ElectricalVisualProjectionGates,
    ElectricalVisualProjectionPredicate,
    VisualProjectionSet,
)

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


def _visual_silkscreen_status(
    value: object,
) -> Literal["measured_pass", "fail"]:
    if value == "measured_pass":
        return "measured_pass"
    if value == "fail":
        return "fail"
    raise ValueError("silkscreen status is invalid for visual projection")


def _visual_dfm_status(value: object) -> Literal["pass", "fail"]:
    if value == "pass":
        return "pass"
    if value == "fail":
        return "fail"
    raise ValueError("DFM status is invalid for visual projection")


def _run_ordered_arms(
    run_arm: Callable[[str, bool], dict[str, object]],
    workers: int,
) -> tuple[dict[str, object], dict[str, object]]:
    """Run independent controls concurrently while collecting them in arm order."""
    if workers < 1:
        raise ValueError("width control worker count must be at least 1")
    controls = (
        ("arm-a-class-only", False),
        ("arm-b-class-and-board-minimum", True),
    )
    if workers == 1:
        results = [run_arm(name, board_minimum) for name, board_minimum in controls]
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(run_arm, name, board_minimum) for name, board_minimum in controls
            ]
            results = [future.result() for future in futures]
    return results[0], results[1]


def _stage_electrical_visual_projections(
    *,
    project_name: str,
    out_dir: Path,
    source_revision: str,
    schematic: Path,
    routed_board: Path,
    lane: ElectricalLane,
    board: BoardModel,
    gates: ElectricalVisualProjectionGates,
) -> tuple[VisualProjectionSet, VisualCrosscheckReport]:
    visual_projection_set = generate_electrical_visual_projections(
        project_name=project_name,
        out_dir=out_dir,
        source_revision=source_revision,
        schematic=schematic,
        routed_board=routed_board,
        lane=lane,
        board=board,
        gates=gates,
    )
    visual_crosscheck = crosscheck_electrical_visual_projections(
        project_name=project_name,
        source_revision=source_revision,
        visual_projection_set=visual_projection_set,
        lane=lane,
        board=board,
        base_dir=out_dir,
        machine_inputs=(schematic, routed_board),
    )
    return visual_projection_set, visual_crosscheck


def _stage_firmware_visual_projections(
    *,
    project_name: str,
    out_dir: Path,
    source_revision: str,
    graph: DesignGraph,
    graph_input: Path,
    input_base_dir: Path,
) -> tuple[VisualProjectionSet, VisualCrosscheckReport]:
    firmware_lane = extract_firmware_lane(graph)
    projection_ids = (f"{project_name}-firmware-state", f"{project_name}-firmware-sequence")
    firmware_projection_set = generate_firmware_visual_projections(
        project_name=project_name,
        out_dir=out_dir,
        source_revision=source_revision,
        lane=firmware_lane,
        authoritative_inputs=(graph_input,),
        input_base_dir=input_base_dir,
        projection_ids=projection_ids,
    )
    firmware_crosscheck = crosscheck_firmware_visual_projections(
        source_revision=source_revision,
        visual_projection_set=firmware_projection_set,
        lane=firmware_lane,
        graph_input=graph_input,
        base_dir=out_dir,
        input_base_dir=input_base_dir,
        projection_ids=projection_ids,
    )
    return firmware_projection_set, firmware_crosscheck


def _summarize_width_violations(
    result: RuleCheckResult,
    net_name: str,
    report_path: Path,
) -> dict[str, object]:
    error_count = result.error_count
    unconnected_items = result.unconnected_items
    violations = result.violations
    width_violations = tuple(
        violation
        for violation in violations
        if "width" in json.dumps(violation, sort_keys=True).lower()
    )
    target_width_violations = tuple(
        violation
        for violation in width_violations
        if any(
            f"[{net_name}]" in str(item.get("description", ""))
            for item in cast(list[dict[str, object]], violation.get("items", []))
        )
    )
    return {
        "drc_error_count": error_count,
        "drc_unconnected_count": len(unconnected_items),
        "width_violation_count": len(width_violations),
        "target_net_width_violation_count": len(target_width_violations),
        "width_violation_types": sorted({str(item.get("type", "")) for item in width_violations}),
        "width_violation_messages": sorted(
            {str(item.get("description", "")) for item in width_violations}
        ),
        "width_violation_samples": list(width_violations[:3]),
        "report_path": str(report_path),
    }


def build_electrical_evidence(
    *,
    revision: str,
    subject_node: str,
    envelope: ToolEnvelope,
    erc_errors: object,
    erc_unconnected: object,
    routing_converged: object,
    drc_errors: object,
    drc_unconnected: object,
    silkscreen_status: object,
    dfm_status: object,
    order_readiness_status: object,
    design_predicates: object,
    functional_block_contract: object,
    declared_blocks: object,
) -> Evidence:
    """Build electrical Evidence from completed deterministic gate results."""
    if not subject_node:
        raise ValueError("electrical evidence subject node is unknown (fail-closed)")
    if not isinstance(erc_errors, int) or not isinstance(erc_unconnected, int):
        raise ValueError("electrical ERC results are unknown (fail-closed)")
    if not isinstance(routing_converged, bool):
        raise ValueError("electrical routing result is unknown (fail-closed)")
    if not isinstance(drc_errors, int) or not isinstance(drc_unconnected, int):
        raise ValueError("electrical DRC results are unknown (fail-closed)")
    for name, value in (
        ("silkscreen", silkscreen_status),
        ("DFM", dfm_status),
        ("order readiness", order_readiness_status),
    ):
        if not isinstance(value, str) or not value:
            raise ValueError(f"electrical {name} result is unknown (fail-closed)")
    silkscreen = cast(str, silkscreen_status)
    dfm = cast(str, dfm_status)
    order_readiness = cast(str, order_readiness_status)
    if not isinstance(design_predicates, tuple):
        raise ValueError("electrical design predicates are unknown (fail-closed)")
    candidate_predicates = cast(tuple[object, ...], design_predicates)
    if not all(isinstance(item, PredicateResult) for item in candidate_predicates):
        raise ValueError("electrical design predicates are unknown (fail-closed)")
    typed_predicates = cast(tuple[PredicateResult, ...], design_predicates)
    names = tuple(predicate.name for predicate in typed_predicates)
    if len(names) != len(set(names)) or set(names) != set(PREDICATE_CATALOG):
        raise ValueError("electrical design predicate set is incomplete (fail-closed)")
    for predicate in typed_predicates:
        if predicate.status not in {"pass", "not_applicable"}:
            raise GateError(f"{predicate.name}: status={predicate.status!r} ({predicate.detail})")
    candidate_blocks = cast(tuple[object, ...], declared_blocks)
    if (
        not isinstance(functional_block_contract, str)
        or not functional_block_contract
        or not isinstance(declared_blocks, tuple)
        or not declared_blocks
        or not all(isinstance(item, str) and item for item in candidate_blocks)
    ):
        raise ValueError("functional block evidence claims are unknown (fail-closed)")
    typed_declared_blocks = cast(tuple[str, ...], candidate_blocks)
    if envelope.target_revision != revision:
        raise ValueError("electrical evidence envelope revision mismatch (fail-closed)")
    if (
        erc_errors != 0
        or erc_unconnected != 0
        or not routing_converged
        or drc_errors != 0
        or drc_unconnected != 0
        or silkscreen_status != "measured_pass"
        or dfm_status != "pass"
        or order_readiness_status != "ready"
    ):
        raise ValueError("electrical deterministic gate did not pass (fail-closed)")
    predicate_claims = [
        EvidenceClaim(
            subject_node=subject_node,
            property=predicate.name,
            value=predicate.status,
            verified=predicate.status == "pass",
        )
        for predicate in typed_predicates
        if predicate.status != "not_applicable"
    ]
    return Evidence(
        evidence_id="evidence.gd1.electrical",
        target_revision=revision,
        status="valid",
        envelope=envelope,
        claims=[
            EvidenceClaim(
                subject_node=subject_node,
                property="erc_error_count",
                value=erc_errors,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="functional_block_contract",
                value=functional_block_contract,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="declared_functional_blocks",
                value=",".join(sorted(typed_declared_blocks)),
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="erc_unconnected_count",
                value=erc_unconnected,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="routing_converged",
                value=routing_converged,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="drc_error_count",
                value=drc_errors,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="drc_unconnected_count",
                value=drc_unconnected,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="silkscreen_status",
                value=silkscreen,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="dfm_status",
                value=dfm,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="order_readiness_status",
                value=order_readiness,
                verified=True,
            ),
            *predicate_claims,
        ],
        created_at=datetime.now(UTC),
    )


def _run_kicad_netclass_positive_control(
    kicad: KicadCli,
    routed_path: Path,
    project_path: Path,
    dru_path: Path,
    out_dir: Path,
    revision: str,
    normal_width_mm: float,
    workers: int,
) -> dict[str, object]:
    """Measure class-only and board-level KiCad width controls."""
    control_dir = out_dir / "kicad-netclass-positive-control"
    control_dir.mkdir(parents=True, exist_ok=True)
    project_data = cast(dict[str, object], json.loads(project_path.read_text(encoding="utf-8")))
    net_settings = project_data.get("net_settings")
    net_settings = cast(dict[str, object], net_settings) if isinstance(net_settings, dict) else None
    classes = (
        cast(list[dict[str, object]], net_settings["classes"])
        if net_settings is not None and isinstance(net_settings.get("classes"), list)
        else None
    )
    patterns = (
        cast(list[dict[str, object]], net_settings["netclass_patterns"])
        if net_settings is not None and isinstance(net_settings.get("netclass_patterns"), list)
        else None
    )
    if not isinstance(classes, list) or not isinstance(patterns, list):
        raise ValueError("KiCad netclass positive-control schema is missing")
    custom: dict[str, object] | None = next(
        (item for item in classes if item.get("name") != "Default"),
        None,
    )
    pattern: dict[str, object] | None = next(
        (item for item in patterns if item.get("netclass") == (custom or {}).get("name")),
        None,
    )
    if custom is None or pattern is None:
        raise ValueError("KiCad netclass positive-control mapping is missing")
    class_name = custom.get("name")
    net_name = pattern.get("pattern")
    if not isinstance(class_name, str) or not isinstance(net_name, str):
        raise ValueError("KiCad netclass positive-control names are invalid")
    inflated_width_mm = max(normal_width_mm * 2.0, normal_width_mm + 0.25)
    custom["track_width"] = inflated_width_mm
    board_settings_obj = project_data.get("board")
    board_settings = (
        cast(dict[str, object], board_settings_obj)
        if isinstance(board_settings_obj, dict)
        else None
    )
    design_settings_obj = (
        board_settings.get("design_settings") if board_settings is not None else None
    )
    design_settings = (
        cast(dict[str, object], design_settings_obj)
        if isinstance(design_settings_obj, dict)
        else None
    )
    rules_obj = design_settings.get("rules") if design_settings is not None else None
    rules = cast(dict[str, object], rules_obj) if isinstance(rules_obj, dict) else None
    if not isinstance(rules, dict):
        raise ValueError("KiCad board DRC rules are missing")
    original_min_track_width = rules.get("min_track_width")
    if not isinstance(original_min_track_width, (int, float)):
        raise ValueError("KiCad board minimum track width is invalid")

    def run_arm(name: str, change_board_minimum: bool) -> dict[str, object]:
        arm_dir = control_dir / name
        arm_dir.mkdir(parents=True, exist_ok=True)
        arm_board = arm_dir / routed_path.name
        arm_project = arm_dir / project_path.name
        arm_dru = arm_dir / dru_path.name
        shutil.copy2(routed_path, arm_board)
        shutil.copy2(project_path, arm_project)
        if dru_path.is_file():
            shutil.copy2(dru_path, arm_dru)
        arm_project_data = cast(
            dict[str, object],
            json.loads(arm_project.read_text(encoding="utf-8")),
        )
        arm_net_settings_obj = arm_project_data.get("net_settings")
        arm_net_settings = (
            cast(dict[str, object], arm_net_settings_obj)
            if isinstance(arm_net_settings_obj, dict)
            else None
        )
        if arm_net_settings is None:
            raise ValueError(f"{name}: KiCad net settings are missing")
        arm_classes_obj = arm_net_settings.get("classes")
        arm_classes = (
            cast(list[dict[str, object]], arm_classes_obj)
            if isinstance(arm_classes_obj, list)
            else None
        )
        if arm_classes is None:
            raise ValueError(f"{name}: KiCad netclass list is missing")
        arm_custom = next(
            (item for item in arm_classes if item.get("name") == class_name),
            None,
        )
        if arm_custom is None:
            raise ValueError(f"{name}: selected KiCad netclass is missing")
        arm_custom["track_width"] = inflated_width_mm
        arm_board_settings_obj = arm_project_data.get("board")
        arm_board_settings = (
            cast(dict[str, object], arm_board_settings_obj)
            if isinstance(arm_board_settings_obj, dict)
            else None
        )
        if arm_board_settings is None:
            raise ValueError(f"{name}: KiCad board settings are missing")
        arm_design_settings_obj = arm_board_settings.get("design_settings")
        arm_design_settings = (
            cast(dict[str, object], arm_design_settings_obj)
            if isinstance(arm_design_settings_obj, dict)
            else None
        )
        if arm_design_settings is None:
            raise ValueError(f"{name}: KiCad design settings are missing")
        arm_rules_obj = arm_design_settings.get("rules")
        arm_rules = (
            cast(dict[str, object], arm_rules_obj) if isinstance(arm_rules_obj, dict) else None
        )
        if arm_rules is None:
            raise ValueError(f"{name}: KiCad DRC rules are missing")
        if change_board_minimum:
            arm_rules["min_track_width"] = inflated_width_mm
        else:
            arm_rules["min_track_width"] = original_min_track_width
        arm_project.write_text(
            json.dumps(arm_project_data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_path = arm_dir / "positive-control.drc.json"
        result = kicad.drc(arm_board, report_path, revision)
        assert_rule_check_input_matches(f"DRC {name}", result, [arm_board])
        summary = _summarize_width_violations(
            result,
            net_name,
            report_path.relative_to(out_dir),
        )
        summary.update(
            {
                "class_track_width_mm": inflated_width_mm,
                "board_min_track_width_mm": arm_rules["min_track_width"],
                "board_min_track_width_changed": change_board_minimum,
            }
        )
        return summary

    arm_a, arm_b = _run_ordered_arms(run_arm, workers)
    class_only_detected = bool(arm_a["width_violation_count"])
    board_level_detected = bool(arm_b["width_violation_count"])
    if not class_only_detected and not board_level_detected:
        raise ValueError(
            "KiCad width projection positive controls produced no width violation "
            "in either arm (fail-closed)"
        )
    return {
        "class": class_name,
        "net": net_name,
        "normal_track_width_mm": normal_width_mm,
        "intentionally_inflated_track_width_mm": inflated_width_mm,
        "original_board_min_track_width_mm": original_min_track_width,
        "arm_a_class_only": arm_a,
        "arm_b_class_and_board_minimum": arm_b,
        "class_only_width_violation_detected": class_only_detected,
        "board_level_width_violation_detected": board_level_detected,
        "interpretation": (
            "Arm A measures whether class-only projection affects existing-track "
            "DRC; Arm B measures board-level minimum-width enforcement."
        ),
    }


def _measure_dsn_class_correspondence(
    dsn_path: Path,
    netclasses: tuple[NetClass, ...],
    net_evidence: dict[str, object],
    tolerance_mm: float,
) -> dict[str, object]:
    text = dsn_path.read_text(encoding="utf-8")
    class_matches = list(
        re.finditer(
            r'(?ms)^\s*\(class "([^"]+)" ""(.*?)^\s*\)\s*$',
            text,
        )
    )
    if not class_matches:
        raise ValueError("DSN netclass declarations are missing (fail-closed)")
    expected_names = {item.name for item in netclasses}
    observed: dict[str, dict[str, object]] = {}
    for match in class_matches:
        name = match.group(1)
        body = match.group(2)
        width_match = re.search(r"\(rule \(width ([0-9]+(?:\.[0-9]+)?)\)", body)
        member_names = re.findall(r'"([^"]+)"', body.split("(circuit", 1)[0])
        if width_match is None or name in observed:
            raise ValueError("DSN netclass width declaration is malformed (fail-closed)")
        width_mm = float(width_match.group(1)) / 1000.0
        measured: dict[str, float] = {}
        for net_name in member_names:
            raw_obj = net_evidence.get(net_name)
            raw = cast(dict[str, object], raw_obj) if isinstance(raw_obj, dict) else None
            measured_minimum = raw.get("measured_minimum_mm") if raw is not None else None
            if not isinstance(measured_minimum, (int, float)):
                raise ValueError(f"DSN net {net_name!r} measurement is missing (fail-closed)")
            measured[net_name] = float(measured_minimum)
        observed[name] = {
            "dsn_width_mm": width_mm,
            "members": sorted(member_names),
            "measured_minimum_widths_mm": measured,
            "measured_width_at_least_dsn_width": all(
                value + tolerance_mm >= width_mm for value in measured.values()
            ),
        }
    if set(observed) != expected_names:
        raise ValueError("DSN netclass set differs from projected netclasses (fail-closed)")
    return {
        "measurement_method": (
            "independent parse of generated DSN class rule widths matched to "
            "post-refill Gerber net widths"
        ),
        "tolerance_mm": tolerance_mm,
        "classes": observed,
        "all_classes_correspond": all(
            bool(item["measured_width_at_least_dsn_width"]) for item in observed.values()
        ),
    }


def placements_from_graph(graph: DesignGraph, lane: ElectricalLane) -> tuple[Placement, ...]:
    components = {
        str(node.attrs["refdes"]): node.attrs
        for node in graph.nodes
        if node.kind == "electrical.component" and "refdes" in node.attrs
    }
    expected = {component.refdes for component in lane.components}
    if set(components) != expected:
        raise ValueError("graph component placement set differs from electrical lane")
    placements: list[Placement] = []
    for refdes in sorted(expected):
        attrs = components[refdes]
        x = attrs.get("placement_x_mm")
        y = attrs.get("placement_y_mm")
        rotation = attrs.get("placement_rotation_deg")
        if (
            isinstance(x, bool)
            or not isinstance(x, (int, float))
            or isinstance(y, bool)
            or not isinstance(y, (int, float))
            or isinstance(rotation, bool)
            or not isinstance(rotation, (int, float))
        ):
            raise ValueError(f"{refdes}: graph placement is missing or malformed")
        placements.append(Placement(refdes, float(x), float(y), float(rotation)))
    return tuple(placements)


def run_pipeline(
    fixture_dir: Path,
    out_dir: Path,
    max_passes: int,
    fab_profile_path: Path | None = None,
    width_control_workers: int = 2,
    pipeline_workers: int = DEFAULT_PIPELINE_WORKERS,
    fab_profile_id: str | None = None,
    freerouting_threads: int = DEFAULT_FREEROUTING_THREADS,
) -> dict[str, str]:
    graph = DesignGraph.model_validate(
        json.loads((fixture_dir / "graph.json").read_text(encoding="utf-8"))
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir = out_dir.resolve()
    lane = extract_electrical_lane(graph)
    functional_registry = load_functional_block_registry()
    design_freedom = load_design_freedom_declaration()
    validate_change_dimension_alignment(design_freedom, functional_registry)
    design_freedom_body: dict[str, object] = {
        "schema_version": design_freedom.document.schema_version,
        "target_revision": graph.revision,
        "declaration_id": design_freedom.document.declaration_id,
        "declaration_sha256": design_freedom.declaration_hash,
        "source_path": design_freedom.path.relative_to(repository_root()).as_posix(),
        "dimensions": [
            dimension.model_dump(mode="json")
            for dimension in sorted(
                design_freedom.dimensions, key=lambda item: item.dimension_id
            )
        ],
        "searchable_dimensions": list(searchable_dimensions(design_freedom)),
    }
    design_freedom_body["content_sha256"] = canonical_json_sha256(design_freedom_body)
    (out_dir / "design-freedom-declaration.json").write_text(
        json.dumps(design_freedom_body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    group0_results = _run_ordered_stages(
        (
            (
                "rationale",
                partial(validate_and_project_rationale, graph, fixture_dir, out_dir),
            ),
            (
                "design-predicates",
                partial(
                    evaluate_design_predicates,
                    graph,
                    lane,
                    fixture_dir,
                    functional_registry,
                ),
            ),
        ),
        pipeline_workers,
    )
    print("[0/12] rationale coverage passed")
    revision = graph.revision
    design_predicates = cast(
        tuple[PredicateResult, ...],
        group0_results[1],
    )
    design_evidence_path = write_gate_evidence_or_unavailable(
        out_dir,
        "design-predicates.json",
        target_revision=revision,
        gate="design_predicates",
        message="design predicate diagnostic observations unavailable; not gate authority",
        write_evidence=partial(
            write_design_predicate_evidence,
            out_dir,
            revision,
            design_predicates,
        ),
    )
    evidence_reference = (
        "; evidence: gate-evidence/design-predicates.json"
        if design_evidence_path is not None
        else "; evidence unavailable"
    )
    for predicate in design_predicates:
        if predicate.status not in {"pass", "not_applicable"}:
            remediation = (
                f"; remediation: {predicate.remediation.message}"
                if predicate.remediation is not None
                else ""
            )
            raise GateError(
                f"{predicate.name}: status={predicate.status!r} ({predicate.detail})"
                f"{remediation}{evidence_reference}"
            )
    applicable_count = sum(predicate.status != "not_applicable" for predicate in design_predicates)
    print(
        f"[0/12] design predicates passed "
        f"(applicable={applicable_count}, "
        f"not_applicable={len(design_predicates) - applicable_count})"
    )
    silkscreen = extract_silkscreen_lane(graph)
    intent, allowances = extract_fab_intent(graph)
    if fab_profile_path is not None and fab_profile_id is not None:
        raise ValueError("fab profile path and profile id are mutually exclusive")
    if fab_profile_path is not None:
        profile = load_fab_profile(fab_profile_path)
        resolved_fab_profile_path = fab_profile_path
    else:
        resolved_fab_profile_path = resolve_fab_profile_path(
            fab_profile_id or intent.fab_profile, load_fab_profile_registry()
        )
        profile = load_fab_profile(resolved_fab_profile_path)
    if intent.fab_profile != profile.profile_id:
        raise ValueError(
            f"graph fab profile {intent.fab_profile!r} differs from loaded profile "
            f"{profile.profile_id!r}"
        )

    placements = placements_from_graph(graph, lane)
    project = write_project(
        lane,
        fixture_dir,
        out_dir,
        profile=profile,
        placements=placements,
        name=output_prefix(graph.graph_id),
        silkscreen=silkscreen,
    )
    name = project.name
    kicad = KicadCli()

    print(f"[1/12] project written: {project.root}")

    erc = kicad.erc(project.schematic, out_dir / f"{name}.erc.json", revision)
    assert_rule_check_passed("ERC", erc, require_connected=False)
    print("[2/12] ERC gate passed (0 errors)")

    dsn_path = out_dir / f"{name}.dsn"
    dsn_path.write_text(export_dsn(project.board_projection.model, name))

    router = FreeroutingRunner()
    ses_path = out_dir / f"{name}.ses"
    try:
        route_run = router.route(
            dsn_path,
            ses_path,
            revision,
            max_passes=max_passes,
            freerouting_threads=freerouting_threads,
        )
    except Exception as exc:
        write_gate_evidence_or_unavailable(
            out_dir,
            "routing-connectivity.json",
            target_revision=revision,
            gate="routing_connectivity",
            message="routing connectivity diagnostic unavailable; not gate authority",
            write_evidence=None,
            failure=exc,
        )
        raise
    parsed_routes = None
    try:
        parsed_routes = parse_ses(
            ses_path.read_text(),
            minimum_width_mm=lane.board.min_track_mm,
        )
    except Exception as exc:
        write_gate_evidence_or_unavailable(
            out_dir,
            "routing-connectivity.json",
            target_revision=revision,
            gate="routing_connectivity",
            message="routing connectivity diagnostic unavailable; not gate authority",
            write_evidence=None,
            failure=exc,
        )
    else:
        assert parsed_routes is not None

        def write_connectivity_evidence() -> Path:
            connectivity = measure_routing_connectivity(
                project.board_projection.model,
                parsed_routes,
            )
            connectivity["router_convergence_state"] = route_run.envelope.convergence_state
            connectivity["router_measurement_mismatch"] = (
                route_run.envelope.convergence_state == "converged"
                and connectivity["status"] != "pass"
            )
            return write_gate_evidence(
                out_dir,
                "routing-connectivity.json",
                target_revision=revision,
                gate="routing_connectivity",
                status=str(connectivity["status"]),
                message="routing connectivity diagnostic observation; not gate authority",
                observation=connectivity,
            )

        write_gate_evidence_or_unavailable(
            out_dir,
            "routing-connectivity.json",
            target_revision=revision,
            gate="routing_connectivity",
            message="routing connectivity diagnostic observation; not gate authority",
            write_evidence=write_connectivity_evidence,
        )
    assert_converged(route_run.envelope.convergence_state)
    print("[3/12] routing converged")

    routes = parsed_routes or parse_ses(
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
    base_routed_board = routed_board
    stitch_candidate_reports: list[dict[str, object]] = []
    routed_board, stitch_vias, initial_stitch_report = inject_stitch_vias(
        base_routed_board,
        project.board_projection.model,
        routes,
        project.board_projection.net_numbers,
        project.board_projection.stitch_via_pitch_mm,
        lane.board.via_diameter_mm,
        lane.board.via_drill_mm,
    )
    stitch_candidate_reports.append(
        {"iteration": 0, "phase": "initial", "report": initial_stitch_report}
    )
    max_iterations = project.board_projection.model.stitch_via_refill_max_iterations
    if max_iterations is None or max_iterations <= 0:
        raise RuntimeError("missing stitch-via refill iteration declaration (fail-closed)")
    iteration_dir = out_dir / ".stitch-iterations"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    dru_source = out_dir / f"{name}.kicad_dru"
    initial_candidate_count = len(stitch_vias)
    pruned_vias: list[tuple[float, float]] = []
    attempted_fallback_regions: set[
        tuple[str, tuple[float, float, float, float]]
    ] = set()
    iteration_measurements: list[dict[str, object]] = []
    converged_iteration: int | None = None
    for iteration in range(1, max_iterations + 1):
        iteration_board = iteration_dir / f"{name}-{iteration}.kicad_pcb"
        iteration_board.write_text(routed_board)
        (iteration_dir / f"{name}-{iteration}.kicad_pro").write_text(project.project.read_text())
        if dru_source.is_file():
            (iteration_dir / f"{name}-{iteration}.kicad_dru").write_text(
                dru_source.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        kicad.refill_zones(iteration_board, revision)
        iteration_gerbers = iteration_dir / f"gerbers-{iteration}"
        _, iteration_paths = kicad.export_gerbers(
            iteration_board, iteration_gerbers, ["F.Cu", "B.Cu"], revision
        )
        try:
            verify_ground_plane_gerbers(
                iteration_paths[0],
                iteration_paths[1],
                project.board_projection.model,
                stitch_vias,
                routes,
            )
            iteration_measurements.append(
                {
                    "iteration": iteration,
                    "via_count": len(stitch_vias),
                    "uncovered_count": 0,
                    "uncovered_vias": [],
                }
            )
            print(f"[stitch-prune {iteration}] vias={len(stitch_vias)} uncovered=0")
            converged_iteration = iteration
            break
        except UncoveredStitchViasError as exc:
            uncovered = exc.locations
            write_gate_evidence_or_unavailable(
                out_dir,
                "gnd-stitch-vias.json",
                target_revision=revision,
                gate="gnd_stitch_vias",
                message="GND stitch-via diagnostic observation; not gate authority",
                write_evidence=partial(
                    write_gate_evidence,
                    out_dir,
                    "gnd-stitch-vias.json",
                    target_revision=revision,
                    gate="gnd_stitch_vias",
                    status="fail",
                    message="GND stitch-via diagnostic observation; not gate authority",
                    observation={
                        "uncovered_vias": [
                            [round(point[0], 6), round(point[1], 6)] for point in uncovered
                        ],
                        "candidate_count": len(stitch_vias),
                    },
                ),
                failure=exc,
            )
            pruned_vias.extend(uncovered)
            covered = tuple(point for point in stitch_vias if point not in uncovered)
            if len(covered) == len(stitch_vias):
                raise RuntimeError(
                    f"measured uncovered vias were not in candidate set: {uncovered}"
                ) from None
            iteration_measurements.append(
                {
                    "iteration": iteration,
                    "via_count": len(stitch_vias),
                    "uncovered_count": len(uncovered),
                    "uncovered_vias": uncovered,
                }
            )
            print(
                f"[stitch-prune {iteration}] vias={len(stitch_vias)} "
                f"uncovered={len(uncovered)} at {uncovered}"
            )
        except UncoveredGroundRegionsError as exc:
            fallback_regions = tuple(
                region for region in exc.regions if region not in attempted_fallback_regions
            )
            if fallback_regions:
                attempted_fallback_regions.update(fallback_regions)
                routed_board, stitch_vias, fallback_stitch_report = inject_stitch_vias(
                    base_routed_board,
                    project.board_projection.model,
                    routes,
                    project.board_projection.net_numbers,
                    project.board_projection.stitch_via_pitch_mm,
                    lane.board.via_diameter_mm,
                    lane.board.via_drill_mm,
                    fallback_regions=fallback_regions,
                )
                stitch_candidate_reports.append(
                    {
                        "iteration": iteration,
                        "phase": "region-fallback",
                        "report": fallback_stitch_report,
                    }
                )
                iteration_measurements.append(
                    {
                        "iteration": iteration,
                        "via_count": len(stitch_vias),
                        "uncovered_regions": fallback_regions,
                        "fallback_attempted": True,
                    }
                )
                print(
                    f"[stitch-fallback {iteration}] regions={len(fallback_regions)} "
                    f"vias={len(stitch_vias)}"
                )
                continue
            write_gate_evidence_or_unavailable(
                out_dir,
                "gnd-stitch-vias.json",
                target_revision=revision,
                gate="gnd_stitch_vias",
                message="GND stitch-via diagnostic observation; not gate authority",
                write_evidence=partial(
                    write_gate_evidence,
                    out_dir,
                    "gnd-stitch-vias.json",
                    target_revision=revision,
                    gate="gnd_stitch_vias",
                    status="fail",
                    message="GND stitch-via diagnostic observation; not gate authority",
                    observation={
                        "error": str(exc),
                        "uncovered_regions": [
                            {
                                "layer": layer,
                                "bbox_mm": list(region_bbox),
                            }
                            for layer, region_bbox in exc.regions
                        ],
                    },
                ),
                failure=exc,
            )
            raise
        routed_board, stitch_vias, refill_stitch_report = inject_stitch_vias(
            base_routed_board,
            project.board_projection.model,
            routes,
            project.board_projection.net_numbers,
            project.board_projection.stitch_via_pitch_mm,
            lane.board.via_diameter_mm,
            lane.board.via_drill_mm,
            allowed_points=covered,
        )
        stitch_candidate_reports.append(
            {
                "iteration": iteration,
                "phase": "refill",
                "report": refill_stitch_report,
            }
        )
    shutil.rmtree(iteration_dir)
    if converged_iteration is None:
        raise RuntimeError("stitch-via refill pruning did not converge (fail-closed)")
    stitch_candidate_report_path = write_stitch_candidate_report(
        out_dir,
        {
            "schema_version": "0.1",
            "target_revision": revision,
            "reports": stitch_candidate_reports,
            "coverage_measurements": iteration_measurements,
            "final_selected_points": [
                [round(point[0], 6), round(point[1], 6)] for point in stitch_vias
            ],
        },
    )
    pruning_evidence = {
        "iterations": converged_iteration,
        "initial_candidate_count": initial_candidate_count,
        "pruned_count": len(pruned_vias),
        "pruned_vias": pruned_vias,
        "final_vias": stitch_vias,
        "measurements": iteration_measurements,
    }
    # kicad-cli reads DRC constraints from the sibling .kicad_pro, so the
    # routed board lives in its own directory with a copy of the project file.
    routed_dir = out_dir / "routed"
    routed_dir.mkdir(parents=True, exist_ok=True)
    routed_path = routed_dir / f"{name}.kicad_pcb"
    routed_path.write_text(routed_board)
    (routed_dir / f"{name}.kicad_pro").write_text(project.project.read_text())
    if dru_source.is_file():
        (routed_dir / f"{name}.kicad_dru").write_text(
            dru_source.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    print(
        f"[4/12] SES imported: {len(routes.wires)} wires, {len(routes.vias)} vias; "
        f"observed_min_width={routes.observed_min_width_mm:.4f} mm; "
        f"normalized_wires={routes.normalized_wire_count}"
    )

    kicad.refill_zones(routed_path, revision)
    filled_board_hash = normalized_hash(routed_path)
    drc = kicad.drc(routed_path, out_dir / f"{name}.drc.json", revision)
    assert_rule_check_input_matches("DRC", drc, [routed_path])
    assert_rule_check_passed("DRC", drc, require_connected=True)
    print("[5/12] DRC gate passed (0 errors, 0 unconnected)")
    kicad_positive_control = _run_kicad_netclass_positive_control(
        kicad,
        routed_path,
        routed_dir / f"{name}.kicad_pro",
        dru_source,
        out_dir,
        revision,
        lane.board.min_track_mm,
        width_control_workers,
    )

    gerber_dir = out_dir / "gerbers"
    _gerber_run, gerber_paths = kicad.export_gerbers(
        routed_path, gerber_dir, GERBER_LAYERS, revision
    )
    _drill_run, drill_paths = kicad.export_drill(routed_path, gerber_dir, revision)
    print(f"[6/12] fabrication outputs: {len(gerber_paths)} gerbers, {len(drill_paths)} drill")

    expected_nets = set(project.board_projection.net_numbers)
    expected_refdes = {c.refdes for c in lane.components}
    reload_stages: list[tuple[str, Callable[[], object]]] = [
        ("schematic", partial(verify_schematic, project.schematic, expected_refdes)),
        ("board", partial(verify_board, routed_path, expected_nets, expected_refdes)),
    ]
    for layer, path in zip(GERBER_LAYERS, gerber_paths, strict=True):
        # Bottom-side legend may be legitimately empty on a top-assembly board.
        reload_stages.append(
            (
                f"gerber-{layer}",
                partial(verify_gerber, path, min_objects=0 if layer == "B.SilkS" else 1),
            )
        )
    reload_stages.extend(
        (f"drill-{index}", partial(verify_drill, path))
        for index, path in enumerate(drill_paths)
    )
    _run_ordered_stages(reload_stages, pipeline_workers)
    print("[7/12] independent reload passed (sexpdata + gerbonara)")

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
        measurement.net_name_source,
        measurement.segments,
    )
    profile_minimum = float(profile.data["capabilities"]["min_track_width"]["value"])
    width_requirements = derive_net_widths(lane, profile_minimum)
    if lane.board.width_measurement_tolerance_mm is None:
        raise ValueError("width measurement tolerance is missing (fail-closed)")
    measurement_stages = _run_ordered_stages(
        (
            (
                "silkscreen",
                partial(
                    measure_silkscreen,
                    {
                        "F.SilkS": gerber_paths[GERBER_LAYERS.index("F.SilkS")],
                        "B.SilkS": gerber_paths[GERBER_LAYERS.index("B.SilkS")],
                    },
                    {
                        "F.Mask": gerber_paths[GERBER_LAYERS.index("F.Mask")],
                        "B.Mask": gerber_paths[GERBER_LAYERS.index("B.Mask")],
                    },
                    gerber_paths[GERBER_LAYERS.index("Edge.Cuts")],
                    measurement,
                    silkscreen,
                    profile,
                    {
                        graphic.node_id: resolve_repository_file(graphic.source_path)
                        for graphic in silkscreen.graphics
                        if graphic.source_path is not None
                    },
                ),
            ),
            (
                "net-track-widths",
                partial(
                    measure_net_track_widths,
                    {
                        "F.Cu": gerber_paths[GERBER_LAYERS.index("F.Cu")],
                        "B.Cu": gerber_paths[GERBER_LAYERS.index("B.Cu")],
                    },
                    measurement,
                    width_requirements,
                    lane.board.width_measurement_tolerance_mm,
                ),
            ),
            (
                "net-path-resistance",
                partial(
                    measure_net_path_resistance,
                    measurement,
                    width_requirements,
                    routes.vias,
                    (lane.board.outer_copper_thickness_um or 0.0) / 1000.0,
                ),
            ),
        ),
        pipeline_workers,
    )
    silk_evidence = cast(dict[str, object], measurement_stages[0])
    width_evidence = cast(dict[str, object], measurement_stages[1])
    path_evidence = cast(dict[str, object], measurement_stages[2])
    net_evidence = cast(dict[str, object], width_evidence["nets"])
    for _net_name, raw in net_evidence.items():
        item = cast(dict[str, object], raw)
        item.update(cast(dict[str, object], path_evidence[_net_name]))
        item["copper_thickness_um"] = lane.board.outer_copper_thickness_um
        item["copper_thickness_source"] = lane.board.copper_thickness_source
        item["allowable_temperature_rise_k"] = lane.board.allowable_temperature_rise_k
        item["tolerance_mm"] = width_evidence["tolerance_mm"]
        item["formula_source"] = lane.board.width_basis_source
        item["ipc2221_external"] = {
            "k": lane.board.ipc2221_external_k,
            "b": lane.board.ipc2221_external_b,
            "c": lane.board.ipc2221_external_c,
        }
        if item["current_max_a"] is not None:
            thickness_mm = (lane.board.outer_copper_thickness_um or 0.0) / 1000.0
            width_mm = float(cast(float, item["measured_minimum_mm"]))
            length_mm = float(cast(float, item["total_conductor_length_mm"]))
            resistance = (
                1.724e-5 * length_mm / (width_mm * thickness_mm)
                if width_mm > 0 and thickness_mm > 0
                else None
            )
            item["series_resistance_upper_bound_ohm"] = resistance
            item["ir_drop_upper_bound_v"] = (
                resistance * float(cast(float, item["current_max_a"]))
                if resistance is not None
                else None
            )
            derived_width = float(cast(float, item["derived_width_mm"]))
            item["adopted_to_derived_width_ratio"] = (
                width_mm / derived_width if derived_width > 0 else None
            )
    width_evidence["netclasses"] = [
        {
            "name": netclass.name,
            "track_width_mm": netclass.width_mm,
            "members": list(netclass.nets),
        }
        for netclass in project.board_projection.model.netclasses
    ]
    width_evidence["dsn_class_projection"] = _measure_dsn_class_correspondence(
        dsn_path,
        project.board_projection.model.netclasses,
        net_evidence,
        lane.board.width_measurement_tolerance_mm,
    )
    width_evidence["kicad_projection"] = {
        "schema": "net_settings.classes plus netclass_patterns",
        "kicad_version": kicad.version(),
        "validation": {
            "normal_drc_error_count": drc.error_count,
            "normal_drc_unconnected_count": len(drc.unconnected_items),
            "netclass_patterns_positive_control": kicad_positive_control,
        },
    }
    measurement_gate_results = _run_ordered_stages(
        (
            (
                "smd-pad-centers",
                partial(
                    verify_smd_pad_centers_in_gerber,
                    gerber_paths[GERBER_LAYERS.index("F.Cu")],
                    measurement,
                ),
            ),
            (
                "ground-plane-gerbers",
                partial(
                    verify_ground_plane_gerbers,
                    gerber_paths[GERBER_LAYERS.index("F.Cu")],
                    gerber_paths[GERBER_LAYERS.index("B.Cu")],
                    project.board_projection.model,
                    stitch_vias,
                    routes,
                ),
            ),
        ),
        pipeline_workers,
    )
    plane_measurement = cast(dict[str, object], measurement_gate_results[1])
    plane_measurement["stitch_via_candidates"] = summarize_stitch_candidate_report(
        initial_stitch_report
    )
    edge_overhang_declarations = {
        str(node.attrs["component_refdes"]): float(str(node.attrs["overhang_mm"]))
        for node in graph.nodes
        if node.kind == "mechanical.board_edge_overhang"
    }
    cpl_basis_path = fab_dir / "cpl-basis-report.json"
    lcsc_evidence_dir = repository_root() / "evidence/gd1-cpl-orientation"
    verified_rotation_offsets, rotation_evidence_notes, rotation_unknowns = (
        verify_lcsc_rotation_evidence(lcsc_evidence_dir, fixture_dir, measurement, lane, fitted)
    )
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
            silkscreen_evidence=silk_evidence,
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
    declared_rotation_offsets = cast(dict[str, float], cpl_basis_report["rotation_offsets"])
    for ref, offset in verified_rotation_offsets.items():
        if abs(declared_rotation_offsets.get(ref, 0.0) - offset) > 0.01:
            raise ValueError(f"{ref}: graph CPL rotation offset differs from LCSC Evidence")
    cpl_basis_report["rotation_evidence"] = rotation_evidence_notes
    cpl_unknowns = cast(dict[str, object], cpl_basis_report["unknowns"])
    existing_rotation_unknowns = cast(list[str], cpl_unknowns["cpl_rotation_basis_fab_lcsc"])
    cpl_unknowns["cpl_rotation_basis_fab_lcsc"] = sorted(
        set(existing_rotation_unknowns).union(rotation_unknowns)
    )
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
        f"[8/12] CPL/BOM generated and cross-validated "
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
    via_profile_evidence = {
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
    dfm_path.write_text(json.dumps(dfm_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(
        f"[9/12] DFM report written ({dfm_report['status']}; "
        f"{len(cast(list[object], dfm_report['findings']))} findings)"
    )

    package_members = [*gerber_paths, *drill_paths]
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
    print("[10/12] manufacturing package written")
    functional_registry = load_functional_block_registry()
    declared_blocks = declared_functional_blocks(graph, functional_registry)
    evidence = build_electrical_evidence(
        revision=revision,
        subject_node=subject_node_id(graph, "electrical.board"),
        envelope=drc.run.envelope,
        erc_errors=erc.error_count,
        erc_unconnected=len(erc.unconnected_items),
        routing_converged=route_run.envelope.convergence_state == "converged",
        drc_errors=drc.error_count,
        drc_unconnected=len(drc.unconnected_items),
        silkscreen_status=silk_evidence.get("status"),
        dfm_status=dfm_report.get("status"),
        order_readiness_status=order_readiness.get("status"),
        design_predicates=design_predicates,
        functional_block_contract=(
            f"{functional_registry.registry_id}:{functional_registry.registry_hash}"
        ),
        declared_blocks=declared_blocks,
    )
    evidence_path = out_dir / "evidence-electrical.json"
    evidence_path.write_text(evidence.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"[10/12] electrical evidence recorded: {evidence_path}")

    electrical_gates = ElectricalVisualProjectionGates(
        erc_errors=erc.error_count,
        erc_unconnected=len(erc.unconnected_items),
        routing_converged=route_run.envelope.convergence_state == "converged",
        drc_errors=drc.error_count,
        drc_unconnected=len(drc.unconnected_items),
        independent_reload=True,
        silkscreen_status=_visual_silkscreen_status(silk_evidence.get("status")),
        dfm_status=_visual_dfm_status(dfm_report.get("status")),
        design_predicates=tuple(
            ElectricalVisualProjectionPredicate.model_validate(
                predicate.model_dump(
                    mode="json",
                    include={"name", "status", "detail"},
                )
            )
            for predicate in design_predicates
            if predicate.status != "not_applicable"
        ),
    )
    visual_stage_results = _run_ordered_stages(
        (
            (
                "electrical-visual-projections",
                partial(
                    _stage_electrical_visual_projections,
                    project_name=name,
                    out_dir=out_dir,
                    source_revision=revision,
                    schematic=project.schematic,
                    routed_board=routed_path,
                    lane=lane,
                    board=project.board_projection.model,
                    gates=electrical_gates,
                ),
            ),
            (
                "layout-visual-projections",
                partial(
                    generate_layout_visual_projections,
                    project_name=name,
                    out_dir=out_dir,
                    source_revision=revision,
                    board=project.board_projection.model,
                    board_view=lane.board,
                    authoritative_inputs=(fixture_dir / "graph.json",),
                    input_base_dir=repository_root(),
                ),
            ),
            (
                "system-visual-projections",
                partial(
                    generate_system_visual_projections,
                    project_name=name,
                    out_dir=out_dir,
                    source_revision=revision,
                    graph=graph,
                    lane=lane,
                    authoritative_inputs=(fixture_dir / "graph.json",),
                    input_base_dir=repository_root(),
                ),
            ),
            (
                "firmware-visual-projections",
                partial(
                    _stage_firmware_visual_projections,
                    project_name=name,
                    out_dir=out_dir,
                    source_revision=revision,
                    graph=graph,
                    graph_input=fixture_dir / "graph.json",
                    input_base_dir=repository_root(),
                ),
            ),
        ),
        pipeline_workers,
    )
    _visual_projection_set, visual_crosscheck = cast(
        tuple[VisualProjectionSet, VisualCrosscheckReport],
        visual_stage_results[0],
    )
    layout_projection_set = cast(VisualProjectionSet, visual_stage_results[1])
    system_projection_set = cast(VisualProjectionSet, visual_stage_results[2])
    firmware_projection_set, firmware_crosscheck = cast(
        tuple[VisualProjectionSet, VisualCrosscheckReport],
        visual_stage_results[3],
    )
    print(
        "[10/12] electrical visual projections recorded: "
        f"{out_dir / 'visual-projections-electrical.json'}"
    )
    if visual_crosscheck.status != "match":
        raise RuntimeError("electrical visual cross-check did not match (fail-closed)")
    print(
        "[10/12] electrical visual cross-check recorded: "
        f"{out_dir / 'visual-crosscheck-electrical.json'}"
    )
    print(
        "[10/12] layout visual projections recorded: "
        f"{out_dir / 'visual-projections-layout.json'} "
        f"(identity_hash={layout_projection_set.identity_hash}; "
        f"canonical_hash={layout_projection_set.canonical_hash})"
    )
    print(
        "[10/12] system visual projections recorded: "
        f"{out_dir / 'visual-projections-system.json'} "
        f"(identity_hash={system_projection_set.identity_hash}; "
        f"canonical_hash={system_projection_set.canonical_hash})"
    )
    print(
        "[11/12] firmware visual projections recorded: "
        f"{out_dir / 'visual-projections-firmware.json'} "
        f"(identity_hash={firmware_projection_set.identity_hash}; "
        f"canonical_hash={firmware_projection_set.canonical_hash})"
    )
    if firmware_crosscheck.status != "match":
        raise RuntimeError("firmware visual cross-check did not match (fail-closed)")
    print(
        "[11/12] firmware visual cross-check recorded: "
        f"{out_dir / 'visual-crosscheck-firmware.json'} "
        f"(identity_hash={firmware_crosscheck.identity_hash}; "
        f"canonical_hash={firmware_crosscheck.canonical_hash})"
    )

    hashes: dict[str, str] = {}
    hash_paths = [
        project.schematic,
        project.board,
        project.bom,
        routed_path,
        dsn_path,
        routing_summary_path,
        out_dir / "design-freedom-declaration.json",
        stitch_candidate_report_path,
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
            zip_content_hash(path)
            if path.suffix == ".zip"
            else normalized_hash(path)
        )
    manifest_path = out_dir / "hashes.json"
    manifest_path.write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n")
    print(f"[12/12] hash manifest: {manifest_path}")
    if order_readiness["status"] != "ready":
        print("製造データは生成済み、発注は不可: order-readiness gate failed")
        raise ValueError(f"Order readiness gate failed: {order_readiness_path}")
    return hashes


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


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
        "--freerouting-threads",
        type=_positive_int,
        default=DEFAULT_FREEROUTING_THREADS,
        help="explicit FreeRouting router thread count",
    )
    parser.add_argument(
        "--width-control-workers",
        type=int,
        default=2,
        help="parallel workers for independent width positive-control arms",
    )
    parser.add_argument(
        "--pipeline-workers",
        type=int,
        default=DEFAULT_PIPELINE_WORKERS,
        help="parallel workers for independent Python pipeline stages",
    )
    parser.add_argument("--fab-profile", type=Path, default=None, help="versioned fab profile")
    parser.add_argument("--fab-profile-id", default=None, help="registered fab profile id")
    args = parser.parse_args()
    try:
        run_pipeline(
            args.fixture,
            args.out,
            args.max_passes,
            args.fab_profile,
            args.width_control_workers,
            args.pipeline_workers,
            args.fab_profile_id,
            args.freerouting_threads,
        )
    except Exception as exc:  # fail-closed: any unhandled state stops with nonzero exit
        print(f"PIPELINE FAILED (fail-closed): {exc}", file=sys.stderr)
        return 1
    context, digest = execution_provenance()
    if context == "container" and digest != "unknown":
        print("PIPELINE PASSED (authoritative container execution)")
    else:
        print("PIPELINE PASSED (provisional host execution)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
