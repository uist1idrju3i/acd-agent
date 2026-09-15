"""Routing stage: DSN export, FreeRouting, SES import, and GND stitch-via refinement."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path

from acd.adapters.freerouting.dsn import export_dsn
from acd.adapters.freerouting.router import FreeroutingRunner, router_pass_progression
from acd.adapters.freerouting.ses import parse_ses
from acd.adapters.kicad.cli import KicadCli
from acd.adapters.kicad.fab import (
    UncoveredGroundRegionsError,
    UncoveredStitchViasError,
    verify_ground_plane_gerbers,
)
from acd.adapters.kicad.gates import assert_converged
from acd.adapters.kicad.project import ProjectFiles
from acd.adapters.kicad.routing import inject_routes, inject_stitch_vias
from acd.core.board_model import RoutedDesign
from acd.core.electrical import ElectricalLane
from acd.core.process import ToolTimeoutError
from acd.core.runtime_records import StageArtifactCache
from acd.pipeline.gate_evidence import write_gate_evidence, write_gate_evidence_or_unavailable
from acd.pipeline.routing_connectivity import measure_routing_connectivity
from acd.pipeline.stitch_candidate_evidence import write_stitch_candidate_report
from acd.schema.common import canonical_json_sha256


@dataclass(frozen=True)
class RoutingStageResult:
    dsn_path: Path
    ses_path: Path
    convergence_state: str
    routes: RoutedDesign
    cache: StageArtifactCache | None
    cache_events: list[dict[str, object]]


@dataclass(frozen=True)
class StitchRefinement:
    routed_board: str
    stitch_vias: tuple[tuple[float, float], ...]
    initial_stitch_report: dict[str, object]
    pruning_evidence: dict[str, object]
    stitch_candidate_report_path: Path


def write_router_pass_progression(
    out_dir: Path,
    target_revision: str,
    convergence_state: str,
    progression: tuple[int, ...],
) -> None:
    path = out_dir / "l3" / "router-pass-progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "tool_name": "freerouting",
                "target_revision": target_revision,
                "unrouted": list(progression),
                "convergence_state": convergence_state,
                "authority": "L3 observation; not gate authority",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def parse_cached_router_record(cached_ses: bytes) -> tuple[bytes, str] | None:
    try:
        cached_record = json.loads(cached_ses.decode("utf-8"))
        ses_bytes = str(cached_record["ses"]).encode("utf-8")
        convergence_state = str(cached_record["convergence_state"])
        if convergence_state not in {"converged", "not_converged", "unknown"}:
            raise ValueError("cached router convergence state is invalid")
    except (UnicodeDecodeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return ses_bytes, convergence_state


def route_board(
    *,
    project: ProjectFiles,
    lane: ElectricalLane,
    out_dir: Path,
    revision: str,
    max_passes: int,
    freerouting_threads: int | None,
    router_timeout_s: float,
    cache_dir: Path | None,
) -> RoutingStageResult:
    """Export DSN, route with FreeRouting (or reuse the cache), and import the SES."""
    name = project.name
    router = FreeroutingRunner()
    cache_events: list[dict[str, object]] = []
    cache = StageArtifactCache(cache_dir, cache_events) if cache_dir is not None else None
    router_version = router.version() if cache is not None else None
    routing_inputs = {
        "graph_revision": revision,
        "board_projection": asdict(project.board_projection.model),
        "routing_config": {
            "max_passes": max_passes,
            "freerouting_threads": freerouting_threads,
        },
        "freerouting_version": router_version or "uncached",
    }
    dsn_path = out_dir / f"{name}.dsn"
    dsn_key = StageArtifactCache.key("dsn-export", routing_inputs)
    dsn_bytes = cache.get("dsn-export", dsn_key, ".dsn") if cache is not None else None
    if dsn_bytes is None:
        dsn_bytes = export_dsn(project.board_projection.model, name).encode("utf-8")
        if cache is not None:
            cache.put("dsn-export", dsn_key, ".dsn", dsn_bytes)
    dsn_path.write_bytes(dsn_bytes)

    ses_path = out_dir / f"{name}.ses"
    ses_key = StageArtifactCache.key("freerouting-ses", routing_inputs)
    cached_ses = cache.get("freerouting-ses", ses_key, ".ses-record") if cache is not None else None
    route_convergence_state = "unknown"
    ses_bytes = b""
    router_log = ""
    if cached_ses is not None:
        cached_record = parse_cached_router_record(cached_ses)
        if cached_record is None:
            cache_events.append(
                {
                    "stage": "freerouting-ses",
                    "key": ses_key,
                    "status": "ignored",
                    "reason": "cached router record is malformed",
                }
            )
            cached_ses = None
        else:
            ses_bytes, route_convergence_state = cached_record
    if cached_ses is not None:
        ses_path.write_bytes(ses_bytes)
    else:
        route_run = None
        try:
            route_run = router.route(
                dsn_path,
                ses_path,
                revision,
                max_passes=max_passes,
                freerouting_threads=freerouting_threads,
                timeout_s=router_timeout_s,
            )
            route_convergence_state = route_run.envelope.convergence_state
            router_log = route_run.stdout + route_run.stderr
            if cache is not None:
                cache.put(
                    "freerouting-ses",
                    ses_key,
                    ".ses-record",
                    json.dumps(
                        {
                            "ses": ses_path.read_text(encoding="utf-8"),
                            "convergence_state": route_convergence_state,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                )
        except ToolTimeoutError as exc:
            route_convergence_state = "timed_out"
            router_log = exc.stdout + exc.stderr
            write_gate_evidence_or_unavailable(
                out_dir,
                "routing-connectivity.json",
                target_revision=revision,
                gate="routing_connectivity",
                message="routing connectivity diagnostic unavailable; not gate authority",
                write_evidence=None,
                failure=exc,
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
    write_router_pass_progression(
        out_dir,
        revision,
        route_convergence_state,
        router_pass_progression(router_log),
    )
    parsed_routes = None
    if route_convergence_state != "timed_out":
        try:
            parsed_routes = parse_ses(
                ses_path.read_text(encoding="utf-8"),
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
                connectivity["router_convergence_state"] = route_convergence_state
                connectivity["router_measurement_mismatch"] = (
                    route_convergence_state == "converged" and connectivity["status"] != "pass"
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
    assert_converged(route_convergence_state)
    print("[3/12] routing converged")
    routes = parsed_routes or parse_ses(
        ses_path.read_text(encoding="utf-8"),
        minimum_width_mm=lane.board.min_track_mm,
    )
    return RoutingStageResult(
        dsn_path=dsn_path,
        ses_path=ses_path,
        convergence_state=route_convergence_state,
        routes=routes,
        cache=cache,
        cache_events=cache_events,
    )


def write_routing_summary(
    out_dir: Path, revision: str, routes: RoutedDesign, lane: ElectricalLane
) -> Path:
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
        + "\n",
        encoding="utf-8",
    )
    return routing_summary_path


def refine_stitch_vias(
    *,
    project: ProjectFiles,
    lane: ElectricalLane,
    routes: RoutedDesign,
    kicad: KicadCli,
    out_dir: Path,
    revision: str,
) -> StitchRefinement:
    """Inject routes and prune GND stitch vias until refilled planes cover every via."""
    name = project.name
    routed_board = inject_routes(
        project.board.read_text(encoding="utf-8"),
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
    attempted_fallback_regions: set[tuple[str, tuple[float, float, float, float]]] = set()
    iteration_measurements: list[dict[str, object]] = []
    converged_iteration: int | None = None
    for iteration in range(1, max_iterations + 1):
        iteration_board = iteration_dir / f"{name}-{iteration}.kicad_pcb"
        iteration_board.write_text(routed_board, encoding="utf-8")
        (iteration_dir / f"{name}-{iteration}.kicad_pro").write_text(
            project.project.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
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
                        "uncovered_regions": (
                            [detail.as_dict() for detail in exc.details]
                            if exc.details
                            else [
                                {
                                    "layer": layer,
                                    "bbox_mm": list(region_bbox),
                                }
                                for layer, region_bbox in exc.regions
                            ]
                        ),
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
    pruning_evidence: dict[str, object] = {
        "iterations": converged_iteration,
        "initial_candidate_count": initial_candidate_count,
        "pruned_count": len(pruned_vias),
        "pruned_vias": pruned_vias,
        "final_vias": stitch_vias,
        "measurements": iteration_measurements,
    }
    return StitchRefinement(
        routed_board=routed_board,
        stitch_vias=stitch_vias,
        initial_stitch_report=initial_stitch_report,
        pruning_evidence=pruning_evidence,
        stitch_candidate_report_path=stitch_candidate_report_path,
    )


def write_cache_report(out_dir: Path, cache_events: list[dict[str, object]]) -> None:
    cache_report: dict[str, object] = {
        "schema_version": "0.1",
        "record_class": "L3",
        "pass_evidence": False,
        "events": cache_events,
    }
    cache_report["content_sha256"] = canonical_json_sha256(cache_report)
    (out_dir / "cache-report.json").write_text(
        json.dumps(cache_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
