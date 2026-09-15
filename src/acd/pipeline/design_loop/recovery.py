"""Lane recovery and exploration helpers for the design loop."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from acd.core.enclosure_exploration import (
    EnclosureExplorationResult,
    explore_enclosure_candidates,
)
from acd.core.exploration import (
    ExplorationResult,
    RemediationRequest,
    explore_board_candidates,
    load_remediation_requests,
)
from acd.core.firmware_coverage import FirmwareCoverageFinding
from acd.core.firmware_exploration import (
    explore_firmware_candidates,
    load_firmware_coverage_findings,
)
from acd.core.lane_recovery import (
    LaneRecoveryDeclarationError,
    LaneRecoveryPlan,
    load_lane_recovery_declarations,
    resolve_lane_recovery,
)
from acd.core.runtime_records import (
    RuntimeObservationError,
    TimingRecorder,
    write_timing_record,
)
from acd.pipeline.enclosure import run_pipeline as run_enclosure_pipeline
from acd.pipeline.gd1_board import run_pipeline as run_board_pipeline
from acd.pipeline.lane_plan import (
    RECOVERY_EXPLORATION_STAGE_IDS,
)
from acd.schema import (
    DesignGraph,
)

from .config import DesignLoopConfig, stage_failure, stage_success


def write_candidate_timing_record(
    recorder: TimingRecorder, candidate_out: Path, *, lane_id: str
) -> None:
    try:
        recorder.finish_open()
        write_timing_record(
            candidate_out,
            recorder,
            owner=f"candidate/{lane_id}/{candidate_out.name}",
        )
    except RuntimeObservationError:
        raise
    except Exception as exc:
        raise RuntimeObservationError(
            f"candidate timing record could not be written: {exc}"
        ) from exc


def recovery_fields(plan: LaneRecoveryPlan) -> dict[str, Any]:
    """Return the L3 recovery diagnostic as stage-record fields."""
    fields = plan.as_diagnostic()
    fields.pop("pass_evidence", None)
    fields.pop("record_class", None)
    fields["recovery_lane_id"] = fields.pop("lane_id")
    return fields


def recovery_rerun_arguments(
    failed: dict[str, Any], max_candidates: int, max_rounds: int
) -> dict[str, Any] | None:
    """Return machine-readable rerun arguments for a recoverable rejection.

    A rejection that a declared recovery path could explore reports how to rerun
    with recovery enabled, so a conversation does not have to guess the bounded
    budget arguments. A declared lane without an explorer reports its next-step
    action instead. The rejection itself stays fail-closed.
    """
    lane_id = failed.get("stage_id")
    if not isinstance(lane_id, str):
        return None
    try:
        declarations = load_lane_recovery_declarations()
        if declarations.lane(lane_id) is None:
            return None
        plan = resolve_lane_recovery(lane_id, declarations=declarations)
    except LaneRecoveryDeclarationError:
        return None
    if not plan.supported or lane_id not in RECOVERY_EXPLORATION_STAGE_IDS:
        return {
            "record_class": "L3",
            "pass_evidence": False,
            "lane_id": lane_id,
            "recovery_supported": False,
            "next_step_action": plan.next_step_action,
            "recovery_unsupported_reason": plan.reason,
        }
    return {
        "record_class": "L3",
        "pass_evidence": False,
        "lane_id": lane_id,
        "recovery_supported": True,
        "recovery_explorer": plan.explorer,
        "recovery_dimensions": list(plan.dimensions),
        "next_step_action": plan.next_step_action,
        "arguments": {
            "--recover-lanes": True,
            "--max-exploration-candidates": max_candidates,
            "--max-exploration-rounds": max_rounds,
        },
    }


def lane_remediation(
    config: DesignLoopConfig, lane_id: str, target_revision: str
) -> tuple[RemediationRequest, ...]:
    """Load declared remediation requests from one lane's gate evidence."""
    lane_output = config.lane_plan.stage(lane_id).output_path
    if lane_output is None:
        raise ValueError(f"{lane_id} has no declared output path (fail-closed)")
    evidence = lane_output / "gate-evidence" / "design-predicates.json"
    if not evidence.is_file():
        raise ValueError(
            f"{lane_id} rejection has no predicate evidence at {evidence}; "
            "recovery has no declared remediation to explore (fail-closed)"
        )
    return load_remediation_requests(evidence, target_revision)


def run_lane_exploration(
    config: DesignLoopConfig,
    plan: LaneRecoveryPlan,
    round_out: Path,
    *,
    board_pipeline_runner: Callable[[Path, Path], object],
    enclosure_pipeline_runner: Callable[[Path, Path], object],
    remediation_driven: bool,
) -> ExplorationResult | EnclosureExplorationResult:
    """Run the declared explorer of one rejected lane.

    Declaration-driven lane recovery only explores candidates that a declared
    remediation subject supports, so a rejection without remediation stops
    fail-closed instead of consuming the candidate budget. The explicit
    board-only exploration path keeps its existing bounded broad search.
    """
    graph_path = config.fixture_dir / "graph.json"
    if not remediation_driven:
        if plan.explorer != "board":
            raise ValueError(
                "explicit board exploration cannot run the "
                f"{plan.explorer} explorer of {plan.lane_id}"
            )
        return explore_board_candidates(
            graph_path,
            config.fixture_dir,
            round_out,
            config.max_exploration_candidates,
            max_passes=config.max_passes,
            dry_run=False,
            pipeline_runner=board_pipeline_runner,
        )
    if plan.explorer == "enclosure":
        return explore_enclosure_candidates(
            graph_path,
            config.fixture_dir,
            round_out,
            config.max_exploration_candidates,
            dimensions=plan.dimensions,
            jobs=config.jobs,
            pipeline_runner=enclosure_pipeline_runner,
            commit=True,
        )
    if plan.explorer == "firmware":
        return run_firmware_exploration(
            config,
            plan,
            graph_path,
            round_out,
            board_pipeline_runner,
        )
    graph = DesignGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    remediation = lane_remediation(config, plan.lane_id, graph.revision)
    if not remediation:
        raise ValueError(
            f"{plan.lane_id} rejection declares no remediation; "
            "recovery cannot derive a candidate (fail-closed)"
        )
    if plan.explorer != "board":
        raise ValueError(
            f"{plan.lane_id} declares an unsupported recovery explorer: {plan.explorer}"
        )
    return explore_board_candidates(
        graph_path,
        config.fixture_dir,
        round_out,
        config.max_exploration_candidates,
        max_passes=config.max_passes,
        dry_run=False,
        pipeline_runner=board_pipeline_runner,
        remediation=remediation,
    )


def run_firmware_exploration(
    config: DesignLoopConfig,
    plan: LaneRecoveryPlan,
    graph_path: Path,
    round_out: Path,
    pipeline_runner: Callable[[Path, Path], object],
) -> ExplorationResult:
    """Route a firmware lane rejection to the firmware-only explorer.

    The firmware lane writes ``firmware-coverage.json`` instead of predicate
    gate evidence, so remediation comes from either artifact; a rejection with
    neither cannot derive a candidate and fails closed.
    """
    lane_output = config.lane_plan.stage(plan.lane_id).output_path
    if lane_output is None:
        raise ValueError(f"{plan.lane_id} has no declared output path (fail-closed)")
    graph = DesignGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    evidence = lane_output / "gate-evidence" / "design-predicates.json"
    remediation: tuple[RemediationRequest, ...] = (
        load_remediation_requests(evidence, graph.revision) if evidence.is_file() else ()
    )
    coverage_path = lane_output / "firmware-coverage.json"
    coverage_findings: tuple[FirmwareCoverageFinding, ...] = (
        load_firmware_coverage_findings(coverage_path) if coverage_path.is_file() else ()
    )
    if not evidence.is_file() and not coverage_path.is_file():
        raise ValueError(
            "firmware-pipeline rejection has neither predicate evidence nor "
            "firmware coverage report; recovery cannot derive a candidate "
            "(fail-closed)"
        )
    return explore_firmware_candidates(
        graph_path,
        config.fixture_dir,
        round_out,
        config.max_exploration_candidates,
        dry_run=False,
        pipeline_runner=pipeline_runner,
        remediation=remediation,
        coverage_findings=coverage_findings,
        max_passes=config.max_passes,
    )


CandidatePipelineRunner = Callable[[Path, Path], object]


def _timed_candidate_run(
    run: Callable[[TimingRecorder], object], candidate_out: Path, *, lane_id: str
) -> object:
    candidate_timing = TimingRecorder()
    try:
        result = run(candidate_timing)
    except Exception as exc:
        try:
            write_candidate_timing_record(candidate_timing, candidate_out, lane_id=lane_id)
        except Exception as write_exc:
            raise RuntimeObservationError(
                f"candidate timing record could not be written: {write_exc}; pipeline error: {exc}"
            ) from exc
        raise
    write_candidate_timing_record(candidate_timing, candidate_out, lane_id=lane_id)
    return result


def candidate_board_runner(config: DesignLoopConfig) -> CandidatePipelineRunner:
    """Return a board candidate runner that records per-candidate timing."""

    def runner(working_fixture: Path, candidate_out: Path) -> object:
        return _timed_candidate_run(
            lambda timing: run_board_pipeline(
                working_fixture,
                candidate_out,
                config.max_passes,
                config.fab_profile,
                fab_profile_id=config.fab_profile_id,
                cache_dir=config.cache_dir,
                timing_recorder=timing,
            ),
            candidate_out,
            lane_id="board-pipeline",
        )

    return runner


def candidate_enclosure_runner(config: DesignLoopConfig) -> CandidatePipelineRunner:
    """Return an enclosure candidate runner that records per-candidate timing."""

    def runner(working_fixture: Path, candidate_out: Path) -> object:
        return _timed_candidate_run(
            lambda timing: run_enclosure_pipeline(
                working_fixture,
                candidate_out,
                timing_recorder=timing,
            ),
            candidate_out,
            lane_id="enclosure-pipeline",
        )

    return runner


def run_exploration_stage(
    config: DesignLoopConfig,
    plan: LaneRecoveryPlan,
    round_out: Path | None,
    *,
    remediation_driven: bool,
) -> dict[str, Any]:
    """Run one recovery exploration round and return its L3 stage record."""
    stage_id = RECOVERY_EXPLORATION_STAGE_IDS[plan.lane_id]
    if round_out is None:
        return stage_failure(stage_id, f"{stage_id} output path is undeclared (fail-closed)")
    try:
        exploration = run_lane_exploration(
            config,
            plan,
            round_out,
            board_pipeline_runner=candidate_board_runner(config),
            enclosure_pipeline_runner=candidate_enclosure_runner(config),
            remediation_driven=remediation_driven,
        )
    except Exception as exc:
        return stage_failure(
            stage_id,
            f"{type(exc).__name__}: {exc}",
            record_class="L3",
            report_status="unknown",
            report_path=str(round_out / "exploration-report.json"),
            evaluated_candidates=0,
            diagnostic_dimensions=[],
            **recovery_fields(plan),
        )
    report = exploration.report
    diagnostic_dimensions_set: set[str] = set()
    candidates = report.get("candidates", [])
    if isinstance(candidates, list):
        for candidate in cast(list[object], candidates):
            if not isinstance(candidate, dict):
                continue
            candidate_body = cast(dict[str, Any], candidate)
            outcome = candidate_body.get("outcome")
            if not isinstance(outcome, dict):
                continue
            dimensions = cast(dict[str, Any], outcome).get("diagnostic_dimensions", [])
            if isinstance(dimensions, list):
                diagnostic_dimensions_set.update(
                    dimension
                    for dimension in cast(list[object], dimensions)
                    if isinstance(dimension, str)
                )
    status = report.get("status", "unknown")
    fields = {
        "record_class": "L3",
        "report_path": str(exploration.report_path),
        "report_status": status,
        "target_revision": report.get("target_revision"),
        "evaluated_candidates": report.get("evaluated_candidates", 0),
        "diagnostic_dimensions": sorted(diagnostic_dimensions_set),
        "required_declarations": report.get("required_declarations", []),
        "winner_written": report.get("winner_written", False),
        **recovery_fields(plan),
    }
    if status != "candidate_found" or fields["winner_written"] is not True:
        return stage_failure(
            stage_id,
            f"exploration did not produce a writable candidate: status={status!r}",
            **fields,
        )
    return stage_success(stage_id, **fields)
