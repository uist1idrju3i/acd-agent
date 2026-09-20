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
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import cast

from acd.adapters.freerouting.router import DEFAULT_FREEROUTING_THREADS, DEFAULT_ROUTER_MAX_PASSES
from acd.adapters.kicad.cli import KicadCli
from acd.adapters.kicad.gates import (
    GateError,
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
from acd.core.electrical.electrical import ElectricalLane, extract_electrical_lane
from acd.core.electrical.projection_format_check import ProjectionKind
from acd.core.electrical.silkscreen import extract_silkscreen_lane
from acd.core.knowledge.design_freedom import (
    load_design_freedom_declaration,
    searchable_dimensions,
    validate_change_dimension_alignment,
)
from acd.core.knowledge.design_predicates import (
    OPT_IN_PREDICATES,
    PredicateResult,
    evaluate_design_predicates,
)
from acd.core.knowledge.functional_blocks import (
    declared_functional_blocks,
    load_functional_block_registry,
)
from acd.core.knowledge.naming import output_prefix, subject_node_id
from acd.core.manufacturing.fab import (
    extract_fab_intent,
    load_fab_profile,
    load_fab_profile_registry,
    resolve_fab_profile_path,
)
from acd.core.runtime.evidence_declarations import check_fab_profile_declaration
from acd.core.runtime.fileio import read_json, write_json
from acd.core.runtime.lane_cli import add_lane_io_arguments
from acd.core.runtime.parallel import DEFAULT_PIPELINE_WORKERS, run_ordered_stages
from acd.core.runtime.process import DEFAULT_TOOL_TIMEOUT_S, execution_provenance
from acd.core.runtime.runtime_records import TimingRecorder, write_timing_record
from acd.pipeline.gate_evidence import (
    write_design_predicate_evidence,
    write_gate_evidence_or_unavailable,
)
from acd.pipeline.rationale import validate_and_project_rationale
from acd.pipeline.repository import repository_root
from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import DesignGraph

from .evidence import build_electrical_evidence
from .fabrication import (
    generate_cpl_bom,
    write_dfm_report,
    write_manufacturing_package,
)
from .manifest import write_hash_manifest
from .measurement import GERBER_LAYERS, measure_board
from .routing import (
    refine_stitch_vias,
    route_board,
    write_cache_report,
    write_routing_summary,
)
from .visual_stages import (
    build_electrical_visual_gates,
    run_visual_projection_stages,
)
from .width_control import run_kicad_netclass_positive_control


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
    freerouting_threads: int | None = DEFAULT_FREEROUTING_THREADS,
    cache_dir: Path | None = None,
    timing_recorder: TimingRecorder | None = None,
    router_timeout_s: float = DEFAULT_TOOL_TIMEOUT_S,
) -> dict[str, str]:
    graph = DesignGraph.model_validate(read_json(fixture_dir / "graph.json"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir = out_dir.resolve()
    stage_number = 0
    if timing_recorder is not None:
        timing_recorder.start("board[0/12]")

    def mark_stage(number: int) -> None:
        nonlocal stage_number
        if timing_recorder is None or number == stage_number:
            return
        timing_recorder.finish(f"board[{stage_number}/12]")
        stage_number = number
        timing_recorder.start(f"board[{stage_number}/12]")

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
            for dimension in sorted(design_freedom.dimensions, key=lambda item: item.dimension_id)
        ],
        "searchable_dimensions": list(searchable_dimensions(design_freedom)),
    }
    design_freedom_body["content_sha256"] = canonical_json_sha256(design_freedom_body)
    write_json(out_dir / "design-freedom-declaration.json", design_freedom_body, mkdir=False)
    group0_results = run_ordered_stages(
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
    mark_stage(1)
    revision = graph.revision
    design_predicates = cast(
        tuple[PredicateResult, ...],
        group0_results[1],
    )
    if lane.stackup is None and not any(
        net.differential_pair is not None or net.target_impedance_ohm is not None
        for net in lane.nets
    ):
        design_predicates = tuple(
            predicate for predicate in design_predicates if predicate.name not in OPT_IN_PREDICATES
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
    provenance_reason = check_fab_profile_declaration(
        fab_profile=intent.fab_profile,
        profile_source=intent.profile_source,
        profile_fetched_at=intent.profile_fetched_at,
        sources=cast(list[dict[str, object]], profile.data["sources"]),
    )
    if provenance_reason is not None:
        raise ValueError(
            "fab.order_intent provenance does not resolve to the loaded fab "
            f"profile: {provenance_reason}"
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
    mark_stage(2)

    erc = kicad.erc(project.schematic, out_dir / f"{name}.erc.json", revision)
    assert_rule_check_passed("ERC", erc, require_connected=False)
    print("[2/12] ERC gate passed (0 errors)")
    mark_stage(3)

    routing = route_board(
        project=project,
        lane=lane,
        out_dir=out_dir,
        revision=revision,
        max_passes=max_passes,
        freerouting_threads=freerouting_threads,
        router_timeout_s=router_timeout_s,
        cache_dir=cache_dir,
    )
    routes = routing.routes
    dsn_path = routing.dsn_path
    mark_stage(4)

    routing_summary_path = write_routing_summary(out_dir, revision, routes, lane)
    stitch = refine_stitch_vias(
        project=project,
        lane=lane,
        routes=routes,
        kicad=kicad,
        out_dir=out_dir,
        revision=revision,
    )
    routed_board = stitch.routed_board
    stitch_vias = stitch.stitch_vias
    dru_source = out_dir / f"{name}.kicad_dru"
    # kicad-cli reads DRC constraints from the sibling .kicad_pro, so the
    # routed board lives in its own directory with a copy of the project file.
    routed_dir = out_dir / "routed"
    routed_dir.mkdir(parents=True, exist_ok=True)
    routed_path = routed_dir / f"{name}.kicad_pcb"
    routed_path.write_text(routed_board, encoding="utf-8")
    (routed_dir / f"{name}.kicad_pro").write_text(
        project.project.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
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

    mark_stage(5)
    kicad.refill_zones(routed_path, revision)
    filled_board_hash = normalized_hash(routed_path)
    drc = kicad.drc(routed_path, out_dir / f"{name}.drc.json", revision)
    assert_rule_check_input_matches("DRC", drc, [routed_path])
    assert_rule_check_passed("DRC", drc, require_connected=True)
    print("[5/12] DRC gate passed (0 errors, 0 unconnected)")
    mark_stage(6)
    kicad_positive_control = run_kicad_netclass_positive_control(
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
    gbrjob_path = gerber_dir / f"{routed_path.stem}-job.gbrjob"
    if not gbrjob_path.is_file() or gbrjob_path.stat().st_size == 0:
        raise GateError(f"KiCad gbrjob output is missing: {gbrjob_path}")
    print(f"[6/12] fabrication outputs: {len(gerber_paths)} gerbers, {len(drill_paths)} drill")
    mark_stage(7)

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
        (f"drill-{index}", partial(verify_drill, path)) for index, path in enumerate(drill_paths)
    )
    run_ordered_stages(reload_stages, pipeline_workers)
    print("[7/12] independent reload passed (sexpdata + gerbonara)")
    mark_stage(8)

    measured = measure_board(
        project=project,
        lane=lane,
        silkscreen=silkscreen,
        profile=profile,
        kicad=kicad,
        drc=drc,
        kicad_positive_control=kicad_positive_control,
        routed_path=routed_path,
        dsn_path=dsn_path,
        gerber_paths=gerber_paths,
        drill_paths=drill_paths,
        routes=routes,
        stitch_vias=stitch_vias,
        initial_stitch_report=stitch.initial_stitch_report,
        pipeline_workers=pipeline_workers,
    )
    cpl = generate_cpl_bom(
        kicad=kicad,
        project=project,
        routed_path=routed_path,
        out_dir=out_dir,
        fixture_dir=fixture_dir,
        revision=revision,
        graph=graph,
        lane=lane,
        measurement=measured.measurement,
        profile=profile,
        allowances=allowances,
        intent=intent,
        silk_evidence=measured.silk_evidence,
    )
    mark_stage(9)

    dfm_path, dfm_report, via_profile_evidence = write_dfm_report(
        fab_dir=cpl.fab_dir,
        measurement=measured.measurement,
        profile=profile,
        revision=revision,
        allowances=allowances,
        lane=lane,
        intent=intent,
        edge_overhang_declarations=cpl.edge_overhang_declarations,
        cpl_basis_report=cpl.cpl_basis_report,
        silk_evidence=measured.silk_evidence,
        width_evidence=measured.width_evidence,
        plane_measurement=measured.plane_measurement,
        pruning_evidence=stitch.pruning_evidence,
        routes=routes,
        stitch_vias=stitch_vias,
        drill_count=measured.drill_count,
    )
    mark_stage(10)

    package = write_manufacturing_package(
        project=project,
        out_dir=out_dir,
        fab_dir=cpl.fab_dir,
        gerber_dir=gerber_dir,
        gerber_paths=gerber_paths,
        drill_paths=drill_paths,
        gbrjob_path=gbrjob_path,
        cpl=cpl,
        dfm_path=dfm_path,
        dfm_report=dfm_report,
        kicad=kicad,
        drc=drc,
        revision=revision,
        profile=profile,
        resolved_fab_profile_path=resolved_fab_profile_path,
        intent=intent,
        lane=lane,
        measurement=measured.measurement,
        filled_board_hash=filled_board_hash,
        silk_evidence=measured.silk_evidence,
        width_evidence=measured.width_evidence,
        plane_measurement=measured.plane_measurement,
        pruning_evidence=stitch.pruning_evidence,
        via_profile_evidence=via_profile_evidence,
        stitch_vias=stitch_vias,
        drill_count=measured.drill_count,
    )
    order_readiness = package.order_readiness
    mark_stage(11)
    functional_registry = load_functional_block_registry()
    declared_blocks = declared_functional_blocks(graph, functional_registry)
    evidence = build_electrical_evidence(
        graph_id=graph.graph_id,
        revision=revision,
        subject_node=subject_node_id(graph, "electrical.board"),
        envelope=drc.run.envelope,
        erc_errors=erc.error_count,
        erc_unconnected=len(erc.unconnected_items),
        routing_converged=routing.convergence_state == "converged",
        drc_errors=drc.error_count,
        drc_unconnected=len(drc.unconnected_items),
        silkscreen_status=measured.silk_evidence.get("status"),
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

    theme_song_projection_path, theme_song_projection = run_visual_projection_stages(
        project_name=name,
        out_dir=out_dir,
        fixture_dir=fixture_dir,
        source_revision=revision,
        graph=graph,
        lane=lane,
        schematic=project.schematic,
        routed_path=routed_path,
        board=project.board_projection.model,
        gates=build_electrical_visual_gates(
            erc=erc,
            drc=drc,
            route_convergence_state=routing.convergence_state,
            silkscreen_status=measured.silk_evidence.get("status"),
            dfm_status=dfm_report.get("status"),
            design_predicates=design_predicates,
        ),
        pipeline_workers=pipeline_workers,
    )

    projection_items: list[tuple[Path, ProjectionKind]] = [
        (project.schematic, "kicad_sexpr"),
        (project.board, "kicad_sexpr"),
        (project.bom, "csv" if project.bom.suffix.lower() == ".csv" else "json"),
        (routed_path, "kicad_sexpr"),
        (dsn_path, "dsn"),
        (routing_summary_path, "json"),
        (out_dir / "design-freedom-declaration.json", "json"),
        (stitch.stitch_candidate_report_path, "json"),
        (cpl.pos_path, "csv"),
        (cpl.bom_path, "csv"),
        (cpl.cpl_path, "csv"),
        (dfm_path, "json"),
        (package.order_readiness_path, "json"),
        (package.package_path, "json"),
        (package.zip_path, "zip"),
        *((path, "gerber") for path in gerber_paths),
        *((path, "excellon") for path in drill_paths),
        (gbrjob_path, "gbrjob"),
        (cpl.cpl_basis_path, "json"),
        (theme_song_projection_path, "json"),
        *(
            (
                out_dir / artifact.path,
                "smf" if (out_dir / artifact.path).suffix.lower() == ".mid" else "text",
            )
            for artifact in theme_song_projection.artifacts
        ),
    ]
    hashes = write_hash_manifest(out_dir, revision, projection_items)
    mark_stage(12)
    if timing_recorder is not None:
        timing_recorder.finish("board[12/12]")
    if routing.cache is not None:
        write_cache_report(out_dir, routing.cache_events)
    if order_readiness["status"] != "ready":
        print("製造データは生成済み、発注は不可: order-readiness gate failed")
        raise ValueError(f"Order readiness gate failed: {package.order_readiness_path}")
    return hashes


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_lane_io_arguments(parser, out_default=Path("out/gd1"))
    parser.add_argument(
        "--max-passes",
        type=int,
        default=DEFAULT_ROUTER_MAX_PASSES,
        help="router pass budget",
    )
    parser.add_argument(
        "--router-timeout-s",
        type=float,
        default=DEFAULT_TOOL_TIMEOUT_S,
        help="router execution timeout in seconds",
    )
    parser.add_argument(
        "--freerouting-threads",
        type=positive_int,
        default=DEFAULT_FREEROUTING_THREADS,
        help="FreeRouting router thread count (inherited from FreeRouting's default when omitted)",
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
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="opt-in content-addressed artifact cache directory",
    )
    args = parser.parse_args()
    timing = TimingRecorder()
    timing.start("gd1-board-pipeline")
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
            args.cache_dir,
            timing_recorder=timing,
            router_timeout_s=args.router_timeout_s,
        )
    except Exception as exc:  # fail-closed: any unhandled state stops with nonzero exit
        print(f"PIPELINE FAILED (fail-closed): {exc}", file=sys.stderr)
        return 1
    finally:
        timing.finish_open()
        write_timing_record(args.out, timing)
    context, digest = execution_provenance()
    if context == "container" and digest != "unknown":
        print("PIPELINE PASSED (authoritative container execution)")
    else:
        print("PIPELINE PASSED (provisional host execution)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
