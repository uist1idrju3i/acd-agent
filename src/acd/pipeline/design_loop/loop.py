"""Graph-driven VibeBB design loop orchestration."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from acd.adapters.freerouting.router import DEFAULT_ROUTER_MAX_PASSES
from acd.core.runtime.lane_recovery import (
    LaneRecoveryDeclarations,
    LaneRecoveryPlan,
    load_lane_recovery_declarations,
    resolve_lane_recovery,
)
from acd.core.runtime.runtime_records import (
    TimingRecorder,
    write_loop_summary_record,
    write_timing_record,
)
from acd.pipeline.lane_plan import (
    DESIGN_LOOP_LANE_IDS,
    RECOVERY_EXPLORATION_STAGE_IDS,
    build_lane_plan,
)
from acd.schema import (
    DesignFixtureSpec,
)
from acd.schema.common import canonical_json_sha256
from acd.schema.stage_result import normalize_stage_result

from .config import (
    DEFAULT_DESIGN_LOOP_JOBS,
    DesignLoopConfig,
    StageRunner,
    graph_id_of,
    load_graph,
    resolve_evaluated_at,
    stage_failure,
)
from .recovery import (
    recovery_fields,
    recovery_rerun_arguments,
    run_exploration_stage,
)
from .stages import (
    DEFAULT_STAGE_RUNNERS,
    order_readiness_not_executed,
    run_fixture_generation,
    run_order_total_aggregation,
    run_requirement_compile,
)
from .summary import (
    manufacturing_submission_summary,
    projection_docs_summary,
    surface_router_diagnostics,
    visual_review_summary,
)

_MONOTONIC = time.monotonic

LANES_STEP_ID = "lanes"


def _stops_unless_ok(result: dict[str, Any]) -> bool:
    return not result.get("ok") or bool(result.get("fail_closed"))


def _stops_on_fail_closed(result: dict[str, Any]) -> bool:
    return bool(result.get("fail_closed"))


def always_enabled(_config: DesignLoopConfig) -> bool:
    return True


def _no_override(_config: DesignLoopConfig) -> StageRunner | None:
    return None


@dataclass(frozen=True)
class ExecuteOnceStep:
    """One step of a single design-loop pass, evaluated in declaration order.

    `stage_id == LANES_STEP_ID` expands to the `DESIGN_LOOP_LANE_IDS` lanes, which run
    sequentially or in parallel but are always reduced in declaration order.
    """

    stage_id: str
    stops: Callable[[dict[str, Any]], bool] = _stops_unless_ok
    enabled: Callable[[DesignLoopConfig], bool] = always_enabled
    runner_override: Callable[[DesignLoopConfig], StageRunner | None] = _no_override


EXECUTE_ONCE_PLAN: tuple[ExecuteOnceStep, ...] = (
    ExecuteOnceStep("requirement-entry-validation"),
    ExecuteOnceStep("lane-preflight"),
    ExecuteOnceStep("silkscreen-resolve"),
    ExecuteOnceStep(LANES_STEP_ID),
    ExecuteOnceStep("graph-diff-projection", stops=_stops_on_fail_closed),
    # Mandatory visual review handoff: the manifest stage derives the PNGs the
    # agent must inspect; the inspection and its verification stay agent-side
    # steps and cannot grant pass authority.
    ExecuteOnceStep("visual-review-manifest"),
    ExecuteOnceStep("projection-docs"),
    ExecuteOnceStep("manufacturing-submission"),
    ExecuteOnceStep(
        "order-total-aggregation",
        enabled=lambda config: bool(config.quote_records),
        runner_override=lambda _config: run_order_total_aggregation,
    ),
    ExecuteOnceStep(
        "order-readiness",
        runner_override=lambda config: order_readiness_not_executed if config.design_only else None,
    ),
)


def run_design_loop(
    fixture_dir: Path,
    out_root: Path,
    *,
    order_total: Path | None = None,
    policy: Path,
    repository: Path | None = None,
    fab_profile: Path | None = None,
    fab_profile_id: str | None = None,
    max_passes: int = DEFAULT_ROUTER_MAX_PASSES,
    max_silkscreen_iterations: int = 5,
    run_seconds: int = 15,
    evaluated_at: datetime | None = None,
    cache_dir: Path | None = None,
    resume: bool = False,
    jobs: int = DEFAULT_DESIGN_LOOP_JOBS,
    explore_board: bool = False,
    recover_lanes: bool = False,
    fixture_overwrite: bool = False,
    design_only: bool = False,
    max_exploration_candidates: int = 3,
    max_exploration_rounds: int = 1,
    requirement: Path | None = None,
    wall_clock_budget_seconds: float | None = None,
    token_budget: int | None = None,
    fixture_spec: Path | None = None,
    cpl_evidence_dir: Path | None = None,
    quote_records: Sequence[Path] | None = None,
    order_scope: Path | None = None,
    previous_graph_path: Path | None = None,
    document_languages: Sequence[str] = ("ja",),
) -> dict[str, Any]:
    """Run stages in fixed order with stop-only stage-boundary budgets.

    ``token_budget`` is declaration-only here; token enforcement belongs to the
    OpenHands L2 conversation layer because this loop does not consume LLM
    tokens. The checkpoint is an L3 human/reporting record and is never read by
    resume; resume only reuses the StageArtifactCache and re-executes gates.
    """
    timing = TimingRecorder()
    loop_start = _MONOTONIC()
    budget = {
        "wall_clock_seconds": wall_clock_budget_seconds,
        "token": token_budget,
        "enforcement": "stage-boundary",
    }
    checkpoint_lock = threading.Lock()
    checkpoint_stages: list[dict[str, Any]] = []

    def write_checkpoint() -> str | None:
        try:
            checkpoint = {
                "schema_version": "0.1",
                "record_class": "L3",
                "pass_evidence": False,
                "graph_id": result.get("graph_id"),
                "resume": resume,
                "cache_dir": str(resolved_cache_dir) if resolved_cache_dir else None,
                "budget": budget,
                "elapsed_seconds": _MONOTONIC() - loop_start,
                "stages": list(checkpoint_stages),
                "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            (out_root / "design-loop-checkpoint.json").write_text(
                json.dumps(checkpoint, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return None
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"

    resolved_cache_dir = cache_dir
    if resume and resolved_cache_dir is None:
        resolved_cache_dir = out_root / ".stage-cache"
    result: dict[str, Any] = {
        "ok": False,
        "fail_closed": True,
        "pass_evidence": False,
        "cache_dir": str(resolved_cache_dir) if resolved_cache_dir is not None else None,
        "resume": resume,
        "jobs": jobs,
        "results": [],
        "budget": budget,
    }
    recovery_enabled = explore_board or recover_lanes
    recovery_declarations: LaneRecoveryDeclarations | None = None
    if explore_board:
        result["explore_board"] = True
    if recover_lanes:
        result["recover_lanes"] = True
    if fixture_overwrite:
        result["fixture_overwrite"] = True
    if design_only:
        result["design_only"] = True
    if requirement is not None:
        result["requirement"] = str(requirement)
    if fixture_spec is not None:
        result["fixture_spec"] = str(fixture_spec)
    if cpl_evidence_dir is not None:
        result["cpl_evidence_dir"] = str(cpl_evidence_dir)
    timing_record: Path | None = None
    timing_record_error: str | None = None
    config: DesignLoopConfig | None = None
    diagnostics_config: DesignLoopConfig | None = None
    try:
        out_root.mkdir(parents=True, exist_ok=True)
        if fixture_spec is not None:
            spec = DesignFixtureSpec.model_validate_json(fixture_spec.read_text(encoding="utf-8"))
            graph_id = spec.graph_id or spec.design_name
        else:
            graph_id = graph_id_of(fixture_dir)
        plan = build_lane_plan(graph_id, out_root)
        aggregation_requested = quote_records is not None or order_scope is not None
        if design_only and aggregation_requested:
            raise ValueError("design-only mode does not accept order aggregation inputs")
        if design_only:
            resolved_order_total = order_total
        elif aggregation_requested:
            if order_total is not None:
                raise ValueError(
                    "order-total document and aggregation inputs are mutually exclusive"
                )
            if not quote_records or order_scope is None:
                raise ValueError("aggregation mode requires quote records and order scope")
            if fab_profile is None:
                raise ValueError("aggregation mode requires a fab profile")
            aggregation_output = plan.stage("order-total-aggregation").output_path
            if aggregation_output is None:
                raise ValueError("order-total aggregation output is undeclared")
            resolved_order_total = aggregation_output
        else:
            if order_total is None:
                raise ValueError(
                    "order-total document is required when aggregation is disabled; "
                    "pass design_only (CLI: --design-only) to run the design stages "
                    "without order inputs, or supply --order-total / aggregation inputs"
                )
            resolved_order_total = order_total
        prefix = plan.output_prefix
        artifact = plan.artifact_prefix
        evaluated = resolve_evaluated_at(evaluated_at)
        if jobs < 1:
            raise ValueError("jobs must be a positive integer")
        if max_exploration_candidates < 1:
            raise ValueError("max_exploration_candidates must be a positive integer")
        if max_exploration_rounds < 1:
            raise ValueError("max_exploration_rounds must be a positive integer")
        if wall_clock_budget_seconds is not None and wall_clock_budget_seconds <= 0:
            raise ValueError("wall_clock_budget_seconds must be positive")
        if token_budget is not None and token_budget <= 0:
            raise ValueError("token_budget must be positive")
        if resolved_cache_dir is not None:
            resolved_cache_dir.mkdir(parents=True, exist_ok=True)
        config = DesignLoopConfig(
            fixture_dir=fixture_dir,
            out_root=out_root,
            order_total=resolved_order_total,
            policy=policy,
            repository=(repository or Path.cwd()).resolve(),
            graph_id=graph_id,
            output_prefix=prefix,
            artifact_prefix=artifact,
            lane_plan=plan,
            fab_profile=fab_profile,
            fab_profile_id=fab_profile_id,
            max_passes=max_passes,
            max_silkscreen_iterations=max_silkscreen_iterations,
            run_seconds=run_seconds,
            evaluated_at=evaluated,
            cache_dir=resolved_cache_dir,
            resume=resume,
            jobs=jobs,
            timing_recorder=timing,
            max_exploration_candidates=max_exploration_candidates,
            max_exploration_rounds=max_exploration_rounds,
            requirement=requirement,
            fixture_spec=fixture_spec,
            cpl_evidence_dir=cpl_evidence_dir,
            quote_records=tuple(quote_records or ()),
            order_scope=order_scope,
            design_only=design_only,
            fixture_overwrite=fixture_overwrite,
            wall_clock_budget_seconds=wall_clock_budget_seconds,
            token_budget=token_budget,
            previous_graph_path=previous_graph_path,
            document_languages=tuple(document_languages),
        )
        if recovery_enabled:
            recovery_declarations = load_lane_recovery_declarations()
        result.update(
            {
                "graph_id": graph_id,
                "output_prefix": prefix,
                "artifact_prefix": artifact,
                "cache_dir": (str(resolved_cache_dir) if resolved_cache_dir is not None else None),
            }
        )
        if aggregation_requested:
            result["order_total_mode"] = "aggregation"
    except Exception as exc:
        failure_stage = "fixture-generation" if fixture_spec is not None else "input"
        failure = stage_failure(
            failure_stage,
            f"{type(exc).__name__}: {exc}",
        )
        result["results"] = [failure] if fixture_spec is not None else []
        result.update(
            {
                "failed_stage": failure_stage,
                "failure_reason": f"{type(exc).__name__}: {exc}",
            }
        )
    else:
        active_config = config

        def run_stage(
            stage_id: str,
            runner: StageRunner | None = None,
            *,
            timing_prefix: str | None = None,
        ) -> dict[str, Any]:
            timing_name = (
                f"design-loop/{timing_prefix}/{stage_id}"
                if timing_prefix is not None
                else f"design-loop/{stage_id}"
            )
            timing_error: str | None = None
            started = False
            elapsed = _MONOTONIC() - loop_start
            if wall_clock_budget_seconds is not None and elapsed > wall_clock_budget_seconds:
                stage_result = stage_failure(
                    stage_id,
                    f"wall-clock budget exhausted before {stage_id}: "
                    f"{elapsed:.1f}s > {wall_clock_budget_seconds:.1f}s",
                    budget_exhausted=True,
                )
                with checkpoint_lock:
                    checkpoint_stages.append(
                        {
                            "stage_id": stage_id,
                            "ok": False,
                            "fail_closed": True,
                            "timing_name": timing_name,
                        }
                    )
                    checkpoint_error = write_checkpoint()
                if checkpoint_error is not None:
                    stage_result["checkpoint_error"] = checkpoint_error
                return stage_result
            try:
                timing.start(timing_name)
                started = True
            except Exception as exc:
                timing_error = f"{type(exc).__name__}: {exc}"
            try:
                stage_result = (runner or DEFAULT_STAGE_RUNNERS[stage_id])(active_config)
            except Exception as exc:
                stage_result = stage_failure(stage_id, f"{type(exc).__name__}: {exc}")
            finally:
                if started:
                    try:
                        timing.finish(timing_name)
                    except Exception as exc:
                        timing_error = f"{type(exc).__name__}: {exc}"
            normalized = normalize_stage_result(stage_id, stage_result)
            if timing_error is not None:
                normalized["timing_error"] = timing_error
            with checkpoint_lock:
                checkpoint_stages.append(
                    {
                        "stage_id": stage_id,
                        "ok": bool(normalized.get("ok")),
                        "fail_closed": bool(normalized.get("fail_closed")),
                        "timing_name": timing_name,
                    }
                )
                checkpoint_error = write_checkpoint()
            if checkpoint_error is not None:
                normalized["checkpoint_error"] = checkpoint_error
            return normalized

        def run_lanes(
            timing_prefix: str | None = None,
        ) -> list[dict[str, Any]]:
            if jobs == 1:
                lane_results: list[dict[str, Any]] = []
                for stage_id in DESIGN_LOOP_LANE_IDS:
                    stage_result = run_stage(
                        stage_id,
                        timing_prefix=timing_prefix,
                    )
                    lane_results.append(stage_result)
                    if not stage_result.get("ok") or stage_result.get("fail_closed"):
                        break
                return lane_results
            with ThreadPoolExecutor(max_workers=min(jobs, len(DESIGN_LOOP_LANE_IDS))) as executor:
                futures = {
                    stage_id: executor.submit(
                        run_stage,
                        stage_id,
                        timing_prefix=timing_prefix,
                    )
                    for stage_id in DESIGN_LOOP_LANE_IDS
                }
                return [futures[stage_id].result() for stage_id in DESIGN_LOOP_LANE_IDS]

        def execute_once(
            execution_round: int = 1,
        ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
            once_results: list[dict[str, Any]] = []
            timing_prefix = f"round-{execution_round}" if execution_round > 1 else None
            for step in EXECUTE_ONCE_PLAN:
                if not step.enabled(active_config):
                    continue
                if step.stage_id == LANES_STEP_ID:
                    step_results = run_lanes(timing_prefix)
                else:
                    step_results = [
                        run_stage(
                            step.stage_id,
                            runner=step.runner_override(active_config),
                            timing_prefix=timing_prefix,
                        )
                    ]
                once_results.extend(step_results)
                failed = next(
                    (result for result in step_results if step.stops(result)),
                    None,
                )
                if failed is not None:
                    return once_results, failed
            return once_results, None

        def exploration_stage(round_number: int, plan: LaneRecoveryPlan) -> dict[str, Any]:
            stage_id = RECOVERY_EXPLORATION_STAGE_IDS[plan.lane_id]
            stage = active_config.lane_plan.stage(stage_id)
            round_out = (
                stage.output_path / f"round-{round_number}"
                if stage.output_path is not None
                else None
            )

            def runner(config: DesignLoopConfig) -> dict[str, Any]:
                return run_exploration_stage(
                    config, plan, round_out, remediation_driven=recover_lanes
                )

            return run_stage(
                stage_id,
                runner=runner,
                timing_prefix=f"round-{round_number}",
            )

        def rejected_recovery_lane(stage_result: dict[str, Any] | None) -> str | None:
            """Return the rejected lane ID that recovery may explore, if any."""
            if stage_result is None:
                return None
            if stage_result.get("ok") and not stage_result.get("fail_closed"):
                return None
            stage_id = stage_result.get("stage_id")
            if not isinstance(stage_id, str):
                return None
            if stage_id not in RECOVERY_EXPLORATION_STAGE_IDS:
                return None
            if not recover_lanes and stage_id != "board-pipeline":
                return None
            return stage_id

        results: list[dict[str, Any]] = []
        failed: dict[str, Any] | None = None
        if fixture_spec is not None:
            fixture_result = run_stage(
                "fixture-generation",
                runner=run_fixture_generation,
            )
            results.append(fixture_result)
            if not fixture_result.get("ok") or fixture_result.get("fail_closed"):
                failed = fixture_result
            else:
                generated_graph = load_graph(fixture_dir)
                generated_plan = build_lane_plan(
                    generated_graph.graph_id,
                    out_root,
                )
                active_config = replace(
                    active_config,
                    graph_id=generated_graph.graph_id,
                    output_prefix=generated_plan.output_prefix,
                    artifact_prefix=generated_plan.artifact_prefix,
                    lane_plan=generated_plan,
                )
                result.update(
                    {
                        "graph_id": generated_graph.graph_id,
                        "output_prefix": generated_plan.output_prefix,
                        "artifact_prefix": generated_plan.artifact_prefix,
                    }
                )
        if failed is None and requirement is not None:
            compile_result = run_stage(
                "requirement-compile",
                runner=run_requirement_compile,
            )
            results.append(compile_result)
            if not compile_result.get("ok") or compile_result.get("fail_closed"):
                failed = compile_result
        if failed is None:
            first_results, failed = execute_once()
            results.extend(first_results)
        exploration_rounds: list[dict[str, Any]] = []
        round_number = 0
        while (
            recovery_enabled
            and rejected_recovery_lane(failed) is not None
            and round_number < max_exploration_rounds
        ):
            round_number += 1
            if failed is None:
                break
            board_failure = failed
            lane_id = cast(str, rejected_recovery_lane(failed))
            try:
                recovery_plan = resolve_lane_recovery(lane_id, declarations=recovery_declarations)
            except Exception as exc:
                record = stage_failure(
                    lane_id,
                    (
                        f"{board_failure.get('failure_reason', 'stage failed')}; "
                        f"lane recovery declarations are unusable: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    record_class="L3",
                )
                results.append(record)
                result["exploration_termination"] = "recovery_declaration_invalid"
                failed = record
                break
            if not recovery_plan.supported:
                record = stage_failure(
                    lane_id,
                    (
                        f"{board_failure.get('failure_reason', 'stage failed')}; "
                        f"lane recovery is not declared for {lane_id}: "
                        f"{recovery_plan.reason or 'undeclared'}"
                    ),
                    record_class="L3",
                    **recovery_fields(recovery_plan),
                )
                results.append(record)
                result["exploration_termination"] = "recovery_not_declared"
                failed = record
                break
            before_graph = load_graph(active_config.fixture_dir)
            before_graph_hash = canonical_json_sha256(before_graph.model_dump(mode="json"))
            exploration_result = exploration_stage(round_number, recovery_plan)
            results.append(exploration_result)
            exploration_rounds.append(
                {
                    "round": round_number,
                    "lane_id": lane_id,
                    "recovery_explorer": recovery_plan.explorer,
                    "recovery_dimensions": list(recovery_plan.dimensions),
                    "status": exploration_result.get("report_status", "unknown"),
                    "report_path": exploration_result.get("report_path"),
                    "target_revision": exploration_result.get("target_revision"),
                    "evaluated_candidates": exploration_result.get("evaluated_candidates", 0),
                    "diagnostic_dimensions": exploration_result.get("diagnostic_dimensions", []),
                }
            )
            if not exploration_result.get("ok"):
                status = exploration_result.get("report_status", "unknown")
                if status in {"exhausted", "stopped"}:
                    result["exploration_termination"] = status
                elif status == "candidate_found":
                    result["exploration_termination"] = "candidate_not_written"
                else:
                    result["exploration_termination"] = "error"
                failed = {
                    **board_failure,
                    "failure_reason": (
                        f"{board_failure.get('failure_reason', 'stage failed')}; "
                        f"{lane_id} recovery exploration failed: "
                        f"{exploration_result.get('failure_reason', 'unknown error')}"
                    ),
                }
                break

            def graph_validationstage_failure(
                detail: str,
                board_failure: dict[str, Any] = board_failure,
                exploration_result: dict[str, Any] = exploration_result,
                stage_id: str = RECOVERY_EXPLORATION_STAGE_IDS[lane_id],
            ) -> dict[str, Any]:
                record = stage_failure(
                    stage_id,
                    (f"{board_failure.get('failure_reason', 'board stage failed')}; {detail}"),
                    report_path=exploration_result.get("report_path"),
                    report_status=exploration_result.get("report_status"),
                    target_revision=exploration_result.get("target_revision"),
                )
                results.append(record)
                result["exploration_termination"] = "graph_validation_failed"
                return record

            try:
                after_graph = load_graph(active_config.fixture_dir)
            except Exception as exc:
                failed = graph_validationstage_failure(
                    f"updated graph is invalid (fail-closed): {exc}"
                )
                break
            after_graph_hash = canonical_json_sha256(after_graph.model_dump(mode="json"))
            if after_graph.graph_id != before_graph.graph_id:
                failed = graph_validationstage_failure(
                    "updated graph ID does not match the explored graph (fail-closed)"
                )
                break
            if after_graph.revision != before_graph.revision:
                failed = graph_validationstage_failure(
                    "updated graph revision changed from "
                    f"{before_graph.revision!r} to {after_graph.revision!r} "
                    "(fail-closed)"
                )
                break
            if after_graph_hash == before_graph_hash:
                failed = graph_validationstage_failure(
                    "updated graph content hash did not change (fail-closed)"
                )
                break
            if exploration_result.get("target_revision") != after_graph.revision:
                failed = graph_validationstage_failure(
                    "exploration report target_revision does not match "
                    f"updated graph revision {after_graph.revision!r} (fail-closed)"
                )
                break
            new_plan = build_lane_plan(after_graph.graph_id, active_config.out_root)
            active_config = replace(
                active_config,
                graph_id=after_graph.graph_id,
                output_prefix=new_plan.output_prefix,
                artifact_prefix=new_plan.artifact_prefix,
                lane_plan=new_plan,
            )
            rerun_results, failed = execute_once(round_number + 1)
            results.extend(rerun_results)

        if recovery_enabled:
            result["exploration_rounds"] = exploration_rounds
            if (
                failed is not None
                and rejected_recovery_lane(failed) is not None
                and round_number >= max_exploration_rounds
                and "exploration_termination" not in result
            ):
                result["exploration_termination"] = "max_rounds_reached"
        if failed is not None:
            result.update(
                {
                    "failed_stage": str(failed.get("stage_id", "unknown")),
                    "failure_reason": failed.get("failure_reason", "stage failed"),
                    "results": results,
                }
            )
            if isinstance(failed.get("next_step_action"), str):
                result["next_step_action"] = failed["next_step_action"]
            rerun = recovery_rerun_arguments(
                failed, max_exploration_candidates, max_exploration_rounds
            )
            if rerun is not None:
                if "next_step_action" in rerun:
                    existing_action = result.get("next_step_action")
                    if isinstance(existing_action, str) and existing_action:
                        result["next_step_action"] = (
                            existing_action + "; " + rerun["next_step_action"]
                        )
                    else:
                        result["next_step_action"] = rerun["next_step_action"]
                if not recovery_enabled:
                    result["recovery_rerun"] = rerun
        else:
            result.update(
                {
                    "ok": True,
                    "fail_closed": False,
                    "results": results,
                }
            )
        diagnostics_config = active_config
        stages = result.get("results", [])
        result["budget_exhausted"] = any(
            cast(dict[str, Any], stage).get("budget_exhausted", False)
            for stage in cast(list[object], stages)
            if isinstance(stage, dict)
        )
    finally:
        try:
            timing.finish_open()
        except Exception as exc:
            timing_record_error = f"{type(exc).__name__}: {exc}"
        try:
            timing_record = write_timing_record(out_root, timing)
        except Exception as exc:
            write_error = f"{type(exc).__name__}: {exc}"
            timing_record_error = (
                f"{timing_record_error}; {write_error}"
                if timing_record_error is not None
                else write_error
            )
        if timing_record is not None:
            result["timing_record"] = str(timing_record)
        if timing_record_error is not None:
            result["timing_record_error"] = timing_record_error
        try:
            surface_router_diagnostics(result, diagnostics_config or config)
        except Exception as exc:
            result["router_diagnostics_error"] = f"{type(exc).__name__}: {exc}"
        try:
            loop_summary = write_loop_summary_record(
                out_root,
                {
                    "schema_version": "0.1",
                    "artifact_kind": "design_loop_summary",
                    "record_class": "L3",
                    "pass_evidence": False,
                    "ok": bool(result.get("ok", False)),
                    "failed_stage": result.get("failed_stage"),
                    "failure_reason": result.get("failure_reason"),
                    "next_step_action": result.get("next_step_action"),
                    "exploration_rounds": (
                        len(result.get("exploration_rounds", [])) if recovery_enabled else None
                    ),
                    "max_exploration_candidates": max_exploration_candidates,
                    "max_exploration_rounds": max_exploration_rounds,
                    "graph_id": result.get("graph_id"),
                    "router_diagnostics": result.get("router_diagnostics"),
                    "candidate_router_diagnostics": result.get("candidate_router_diagnostics"),
                    "visual_review": visual_review_summary(result),
                    "projection_docs": projection_docs_summary(result),
                    "manufacturing_submission": manufacturing_submission_summary(result),
                    "timing_record": (str(timing_record) if timing_record is not None else None),
                },
            )
        except Exception as exc:
            result["loop_summary_error"] = f"{type(exc).__name__}: {exc}"
        else:
            result["loop_summary"] = str(loop_summary)
    return result
