"""Graph-driven VibeBB design loop orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from acd.adapters.freerouting.router import DEFAULT_ROUTER_MAX_PASSES
from acd.core.exploration import explore_board_candidates
from acd.core.order_total import (
    aggregate_order_total,
    order_total_result_from_document,
    order_total_result_to_document,
)
from acd.core.requirement_compiler import compile_requirement_change
from acd.core.requirements import (
    default_requirements_path,
    load_requirements,
    validate_requirements,
)
from acd.core.runtime_records import TimingRecorder, write_timing_record
from acd.openhands.order_gate import evaluate_pre_order_gate
from acd.pipeline import lane_plan
from acd.pipeline.fixture_builder import build_design_fixture
from acd.pipeline.gd1_board import run_pipeline as run_board_pipeline
from acd.pipeline.gd1_enclosure import run_pipeline as run_enclosure_pipeline
from acd.pipeline.lane_plan import (
    DESIGN_LOOP_LANE_IDS,
    LanePlan,
    build_lane_plan,
)
from acd.pipeline.silkscreen_resolve import resolve_silkscreen
from acd.schema import (
    DesignFixtureSpec,
    DesignGraph,
    FabProfileDocument,
    OrderPolicy,
    OrderScope,
    OrderTotalDocument,
    QuoteRecord,
)
from acd.schema.common import canonical_json_sha256

DEFAULT_DESIGN_LOOP_JOBS = min(os.cpu_count() or 1, 3)
DESIGN_LOOP_STAGE_IDS = lane_plan.DESIGN_LOOP_STAGE_IDS

StageRunner = Callable[["DesignLoopConfig"], Any]


@dataclass(frozen=True)
class DesignLoopConfig:
    """Inputs for one graph-driven design loop."""

    fixture_dir: Path
    out_root: Path
    order_total: Path | None
    policy: Path
    repository: Path
    graph_id: str
    output_prefix: str
    artifact_prefix: str
    lane_plan: LanePlan
    fab_profile: Path | None
    fab_profile_id: str | None
    max_passes: int
    max_silkscreen_iterations: int
    run_seconds: int
    evaluated_at: datetime
    cache_dir: Path | None = None
    resume: bool = False
    jobs: int = DEFAULT_DESIGN_LOOP_JOBS
    timing_recorder: TimingRecorder | None = None
    max_exploration_candidates: int = 3
    max_exploration_rounds: int = 1
    requirement: Path | None = None
    fixture_spec: Path | None = None
    quote_records: tuple[Path, ...] = ()
    order_scope: Path | None = None
    design_only: bool = False


def _success(stage_id: str, **fields: Any) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "ok": True,
        "fail_closed": False,
        "pass_evidence": False,
        **fields,
    }


def _failure(stage_id: str, reason: str, **fields: Any) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "ok": False,
        "fail_closed": True,
        "pass_evidence": False,
        "failure_reason": reason,
        **fields,
    }


def _firmware_script(repository: Path) -> Path:
    return (
        repository
        / "plugins/acd/skills/acd-firmware-esp32c3/scripts/run_fw_pipeline.py"
    )


def _file_sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _run_silkscreen(config: DesignLoopConfig) -> dict[str, Any]:
    output = config.lane_plan.stage("silkscreen-resolve").output_path
    if output is None:
        raise ValueError("silkscreen stage has no output path")
    result = resolve_silkscreen(
        config.fixture_dir,
        output,
        config.fab_profile,
        config.max_silkscreen_iterations,
        config.fab_profile_id,
    )
    return _success("silkscreen-resolve", output_path=str(output), summary=result)


def _run_board(config: DesignLoopConfig) -> dict[str, Any]:
    output = config.lane_plan.stage("board-pipeline").output_path
    if output is None:
        raise ValueError("board stage has no output path")
    result = run_board_pipeline(
        config.fixture_dir,
        output,
        config.max_passes,
        config.fab_profile,
        fab_profile_id=config.fab_profile_id,
        cache_dir=(
            config.cache_dir
            if config.lane_plan.stage("board-pipeline").cacheable
            else None
        ),
        timing_recorder=config.timing_recorder,
    )
    return _success("board-pipeline", output_path=str(output), summary=result)


def _run_enclosure(config: DesignLoopConfig) -> dict[str, Any]:
    output = config.lane_plan.stage("enclosure-pipeline").output_path
    if output is None:
        raise ValueError("enclosure stage has no output path")
    result = run_enclosure_pipeline(
        config.fixture_dir,
        output,
        timing_recorder=config.timing_recorder,
    )
    return _success("enclosure-pipeline", output_path=str(output), summary=result)


def _run_firmware(config: DesignLoopConfig) -> dict[str, Any]:
    script = _firmware_script(config.repository)
    output = config.lane_plan.stage("firmware-pipeline").output_path
    if output is None:
        raise ValueError("firmware stage has no output path")
    if not script.is_file():
        return _failure("firmware-pipeline", f"firmware Skill script is missing: {script}")
    if config.run_seconds <= 0:
        return _failure("firmware-pipeline", "run_seconds must be positive")
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--script",
            str(script),
            "--fixture",
            str(config.fixture_dir),
            "--out",
            str(output),
            "--run-seconds",
            str(config.run_seconds),
        ],
        cwd=config.repository,
        capture_output=True,
        text=True,
        check=False,
        timeout=3600,
    )
    if completed.returncode != 0:
        return _failure(
            "firmware-pipeline",
            completed.stderr.strip()
            or f"firmware Skill exited with code {completed.returncode}",
            output_path=str(output),
        )
    summary_path = output / "summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _failure("firmware-pipeline", f"firmware Skill summary is invalid: {exc}")
    if not isinstance(summary, dict):
        return _failure("firmware-pipeline", "firmware Skill summary must be an object")
    return _success(
        "firmware-pipeline",
        output_path=str(output),
        summary=summary,
        provenance={
            "skill_name": "acd-firmware-esp32c3",
            "script_name": str(script.relative_to(config.repository)),
            "script_sha256": _file_sha256(script),
            "pass_evidence": False,
        },
    )


def _order_readiness_not_executed(config: DesignLoopConfig) -> dict[str, Any]:
    """Record that order readiness was never executed in design-only mode.

    Design-only mode iterates the design stages without any order path. The
    absence of an executed order gate is a failure, never a pass: no order
    result is synthesized here.
    """
    return _failure(
        "order-readiness",
        "order readiness was not executed in design-only mode",
        execution_status="not_executed",
        order_readiness_status="not_executed",
        design_only=True,
    )


def _run_order_readiness(config: DesignLoopConfig) -> dict[str, Any]:
    if config.order_total is None:
        return _failure(
            "order-readiness",
            "order-total document is undeclared (fail-closed)",
            execution_status="not_executed",
            order_readiness_status="not_executed",
        )
    try:
        policy_path = (
            config.policy
            if config.policy.is_absolute()
            else config.repository / config.policy
        )
        order_total_path = (
            config.order_total
            if config.order_total.is_absolute()
            else config.repository / config.order_total
        )
        policy = OrderPolicy.model_validate_json(
            policy_path.read_text(encoding="utf-8")
        )
        order_total = order_total_result_from_document(
            OrderTotalDocument.model_validate_json(
                order_total_path.read_text(encoding="utf-8")
            )
        )
        record = evaluate_pre_order_gate(
            repository=config.repository,
            policy=policy,
            order_total=order_total,
            evidence_paths=sorted(config.repository.glob(policy.evidence_paths)),
            evaluated_at=config.evaluated_at,
        )
    except Exception as exc:
        return _failure("order-readiness", str(exc))
    return _success(
        "order-readiness",
        summary=record.model_dump(mode="json"),
        output_path=None,
    )


def _run_order_total_aggregation(config: DesignLoopConfig) -> dict[str, Any]:
    """Aggregate caller-provided quote paths without producing readiness evidence."""
    output_path = config.lane_plan.stage("order-total-aggregation").output_path
    if output_path is None:
        return _failure(
            "order-total-aggregation",
            "order-total aggregation output path is undeclared (fail-closed)",
            record_class="L2",
        )
    if not config.quote_records or config.order_scope is None:
        return _failure(
            "order-total-aggregation",
            "quote records and order scope are required for aggregation",
            record_class="L2",
        )
    if config.fab_profile is None:
        return _failure(
            "order-total-aggregation",
            "fab profile is required for aggregation",
            record_class="L2",
        )
    try:
        records = [
            QuoteRecord.model_validate_json(
                quote_path.read_text(encoding="utf-8")
            )
            for quote_path in config.quote_records
        ]
        scope = OrderScope.model_validate_json(
            config.order_scope.read_text(encoding="utf-8")
        )
        fab_profile = FabProfileDocument.model_validate_json(
            config.fab_profile.read_text(encoding="utf-8")
        )
        graph = _load_graph(config.fixture_dir)
        result = aggregate_order_total(
            records,
            scope,
            fab_profile=fab_profile,
            evaluated_at=config.evaluated_at,
            target_revision=graph.revision,
        )
        document = order_total_result_to_document(result)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(document.model_dump_json(indent=2) + "\n")
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, output_path)
    except Exception as exc:
        return _failure(
            "order-total-aggregation",
            f"{type(exc).__name__}: {exc}",
            record_class="L2",
            output_path=str(output_path),
        )
    return _success(
        "order-total-aggregation",
        record_class="L2",
        output_path=str(output_path),
        quote_count=len(records),
        target_revision=result.target_revision,
        evaluated_at=config.evaluated_at.isoformat(),
        breakdown_hash=result.breakdown_hash,
    )


def _graph_id(fixture_dir: Path) -> str:
    graph_path = fixture_dir / "graph.json"
    graph = DesignGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    return graph.graph_id


def _load_graph(fixture_dir: Path) -> DesignGraph:
    return DesignGraph.model_validate_json(
        (fixture_dir / "graph.json").read_text(encoding="utf-8")
    )


def _run_fixture_generation(config: DesignLoopConfig) -> dict[str, Any]:
    if config.fixture_spec is None:
        raise ValueError("fixture spec is not configured")
    graph_path = config.fixture_dir / "graph.json"
    if graph_path.exists():
        return _failure(
            "fixture-generation",
            "fixture directory already contains graph.json (fail-closed)",
        )
    try:
        spec = DesignFixtureSpec.model_validate_json(
            config.fixture_spec.read_text(encoding="utf-8")
        )
        graph = build_design_fixture(spec, config.fixture_dir)
    except Exception as exc:
        return _failure("fixture-generation", f"{type(exc).__name__}: {exc}")
    return _success(
        "fixture-generation",
        graph_id=graph.graph_id,
        revision=graph.revision,
        output_path=str(config.fixture_dir),
    )


def _run_requirement_compile(config: DesignLoopConfig) -> dict[str, Any]:
    if config.requirement is None:
        raise ValueError("requirement update is not configured")
    try:
        before_graph = _load_graph(config.fixture_dir)
        compilation = compile_requirement_change(
            config.fixture_dir,
            config.requirement,
            dry_run=False,
        )
        after_graph = _load_graph(config.fixture_dir)
    except Exception as exc:
        return _failure(
            "requirement-compile",
            f"{type(exc).__name__}: {exc}",
            record_class="L2",
        )
    if after_graph.graph_id != before_graph.graph_id:
        return _failure(
            "requirement-compile",
            "compiled graph ID changed (fail-closed)",
            record_class="L2",
            before_graph_sha256=canonical_json_sha256(
                before_graph.model_dump(mode="json")
            ),
            after_graph_sha256=canonical_json_sha256(
                after_graph.model_dump(mode="json")
            ),
        )
    report = dict(compilation.report)
    report.update(
        {
            "stage_id": "requirement-compile",
            "ok": True,
            "fail_closed": False,
            "pass_evidence": False,
            "record_class": "L2",
        }
    )
    return report


def _run_requirement_entry_validation(config: DesignLoopConfig) -> dict[str, Any]:
    """Validate loop inputs before L1 stages; never replace gates or Evidence."""
    requirements_path = default_requirements_path(config.fixture_dir)
    try:
        loaded = load_requirements(requirements_path)
        graph = _load_graph(config.fixture_dir)
        validate_requirements(loaded.document, graph)
    except Exception as exc:
        return _failure(
            "requirement-entry-validation",
            f"{type(exc).__name__}: {exc}",
            requirements_path=str(requirements_path),
        )
    return _success(
        "requirement-entry-validation",
        requirements_path=str(requirements_path),
        requirements_sha256=loaded.document_hash,
        graph_id=graph.graph_id,
        revision=graph.revision,
        requirement_count=len(loaded.document.records),
    )


def _resolve_evaluated_at(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("evaluated-at must include a timezone")
    return value


DEFAULT_STAGE_RUNNERS: dict[str, StageRunner] = {
    "requirement-entry-validation": _run_requirement_entry_validation,
    "silkscreen-resolve": _run_silkscreen,
    "board-pipeline": _run_board,
    "enclosure-pipeline": _run_enclosure,
    "firmware-pipeline": _run_firmware,
    "order-readiness": _run_order_readiness,
}


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
    design_only: bool = False,
    max_exploration_candidates: int = 3,
    max_exploration_rounds: int = 1,
    requirement: Path | None = None,
    fixture_spec: Path | None = None,
    quote_records: Sequence[Path] | None = None,
    order_scope: Path | None = None,
) -> dict[str, Any]:
    """Run all design stages in their fixed fail-closed order."""
    timing = TimingRecorder()
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
    }
    if explore_board:
        result["explore_board"] = True
    if design_only:
        result["design_only"] = True
    if requirement is not None:
        result["requirement"] = str(requirement)
    if fixture_spec is not None:
        result["fixture_spec"] = str(fixture_spec)
    timing_record: Path | None = None
    timing_record_error: str | None = None
    config: DesignLoopConfig | None = None
    try:
        out_root.mkdir(parents=True, exist_ok=True)
        if fixture_spec is not None:
            spec = DesignFixtureSpec.model_validate_json(
                fixture_spec.read_text(encoding="utf-8")
            )
            graph_id = spec.graph_id or spec.design_name
        else:
            graph_id = _graph_id(fixture_dir)
        plan = build_lane_plan(graph_id, out_root)
        aggregation_requested = (
            quote_records is not None or order_scope is not None
        )
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
                raise ValueError(
                    "aggregation mode requires quote records and order scope"
                )
            if fab_profile is None:
                raise ValueError("aggregation mode requires a fab profile")
            aggregation_output = plan.stage(
                "order-total-aggregation"
            ).output_path
            if aggregation_output is None:
                raise ValueError("order-total aggregation output is undeclared")
            resolved_order_total = aggregation_output
        else:
            if order_total is None:
                raise ValueError(
                    "order-total document is required when aggregation is disabled"
                )
            resolved_order_total = order_total
        prefix = plan.output_prefix
        artifact = plan.artifact_prefix
        evaluated = _resolve_evaluated_at(evaluated_at)
        if jobs < 1:
            raise ValueError("jobs must be a positive integer")
        if max_exploration_candidates < 1:
            raise ValueError("max_exploration_candidates must be a positive integer")
        if max_exploration_rounds < 1:
            raise ValueError("max_exploration_rounds must be a positive integer")
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
            quote_records=tuple(quote_records or ()),
            order_scope=order_scope,
            design_only=design_only,
        )
        result.update(
            {
                "graph_id": graph_id,
                "output_prefix": prefix,
                "artifact_prefix": artifact,
                "cache_dir": (
                    str(resolved_cache_dir) if resolved_cache_dir is not None else None
                ),
            }
        )
        if aggregation_requested:
            result["order_total_mode"] = "aggregation"
    except Exception as exc:
        failure_stage = "fixture-generation" if fixture_spec is not None else "input"
        failure = _failure(
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
            try:
                timing.start(timing_name)
                started = True
            except Exception as exc:
                timing_error = f"{type(exc).__name__}: {exc}"
            try:
                stage_result = (runner or DEFAULT_STAGE_RUNNERS[stage_id])(
                    active_config
                )
            except Exception as exc:
                stage_result = _failure(stage_id, f"{type(exc).__name__}: {exc}")
            finally:
                if started:
                    try:
                        timing.finish(timing_name)
                    except Exception as exc:
                        timing_error = f"{type(exc).__name__}: {exc}"
            if not isinstance(stage_result, dict):
                stage_result = _failure(
                    stage_id, "stage runner returned a non-object result"
                )
            normalized = {**stage_result, "pass_evidence": False}
            if timing_error is not None:
                normalized["timing_error"] = timing_error
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
            with ThreadPoolExecutor(
                max_workers=min(jobs, len(DESIGN_LOOP_LANE_IDS))
            ) as executor:
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
            timing_prefix = (
                f"round-{execution_round}" if execution_round > 1 else None
            )
            requirement_entry = run_stage(
                "requirement-entry-validation",
                timing_prefix=timing_prefix,
            )
            once_results.append(requirement_entry)
            if not requirement_entry.get("ok") or requirement_entry.get("fail_closed"):
                return once_results, requirement_entry
            silkscreen = run_stage(
                "silkscreen-resolve",
                timing_prefix=timing_prefix,
            )
            once_results.append(silkscreen)
            if not silkscreen.get("ok") or silkscreen.get("fail_closed"):
                return once_results, silkscreen

            lane_results = run_lanes(timing_prefix)
            once_results.extend(lane_results)
            failed = next(
                (
                    stage_result
                    for stage_result in lane_results
                    if not stage_result.get("ok") or stage_result.get("fail_closed")
                ),
                None,
            )
            if failed is not None:
                return once_results, failed

            aggregation_result: dict[str, Any] | None = None
            if active_config.quote_records:
                aggregation_result = run_stage(
                    "order-total-aggregation",
                    runner=_run_order_total_aggregation,
                    timing_prefix=timing_prefix,
                )
                once_results.append(aggregation_result)
                if not aggregation_result.get("ok") or aggregation_result.get(
                    "fail_closed"
                ):
                    return once_results, aggregation_result
            order_readiness_result = run_stage(
                "order-readiness",
                runner=(
                    _order_readiness_not_executed
                    if active_config.design_only
                    else None
                ),
                timing_prefix=timing_prefix,
            )
            once_results.append(order_readiness_result)
            if not order_readiness_result.get("ok") or order_readiness_result.get(
                "fail_closed"
            ):
                return once_results, order_readiness_result
            return once_results, None

        def exploration_stage(round_number: int) -> dict[str, Any]:
            stage = active_config.lane_plan.stage("board-exploration")
            round_out = (
                stage.output_path / f"round-{round_number}"
                if stage.output_path is not None
                else None
            )

            def runner(config: DesignLoopConfig) -> dict[str, Any]:
                if round_out is None:
                    return _failure(
                        "board-exploration",
                        "board exploration output path is undeclared (fail-closed)",
                    )

                def pipeline_runner(
                    working_fixture: Path, candidate_out: Path
                ) -> object:
                    return run_board_pipeline(
                        working_fixture,
                        candidate_out,
                        config.max_passes,
                        config.fab_profile,
                        fab_profile_id=config.fab_profile_id,
                        cache_dir=config.cache_dir,
                        timing_recorder=config.timing_recorder,
                    )

                try:
                    exploration = explore_board_candidates(
                        config.fixture_dir / "graph.json",
                        config.fixture_dir,
                        round_out,
                        config.max_exploration_candidates,
                        max_passes=config.max_passes,
                        dry_run=False,
                        pipeline_runner=pipeline_runner,
                    )
                except Exception as exc:
                    return _failure(
                        "board-exploration",
                        f"{type(exc).__name__}: {exc}",
                        record_class="L3",
                        report_status="unknown",
                        report_path=str(round_out / "exploration-report.json"),
                        evaluated_candidates=0,
                        diagnostic_dimensions=[],
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
                        dimensions = cast(dict[str, Any], outcome).get(
                            "diagnostic_dimensions", []
                        )
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
                    "winner_written": report.get("winner_written", False),
                }
                if status != "candidate_found" or fields["winner_written"] is not True:
                    return _failure(
                        "board-exploration",
                        (
                            f"exploration did not produce a writable candidate: "
                            f"status={status!r}"
                        ),
                        **fields,
                    )
                return _success("board-exploration", **fields)

            return run_stage(
                "board-exploration",
                runner=runner,
                timing_prefix=f"round-{round_number}",
            )

        def board_rejection(stage_result: dict[str, Any] | None) -> bool:
            return bool(
                stage_result is not None
                and stage_result.get("stage_id") == "board-pipeline"
                and not stage_result.get("ok")
                and stage_result.get("fail_closed")
            )

        results: list[dict[str, Any]] = []
        failed: dict[str, Any] | None = None
        if fixture_spec is not None:
            fixture_result = run_stage(
                "fixture-generation",
                runner=_run_fixture_generation,
            )
            results.append(fixture_result)
            if not fixture_result.get("ok") or fixture_result.get("fail_closed"):
                failed = fixture_result
            else:
                generated_graph = _load_graph(fixture_dir)
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
                runner=_run_requirement_compile,
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
            explore_board
            and board_rejection(failed)
            and round_number < max_exploration_rounds
        ):
            round_number += 1
            if failed is None:
                break
            board_failure = failed
            before_graph = _load_graph(active_config.fixture_dir)
            before_graph_hash = canonical_json_sha256(
                before_graph.model_dump(mode="json")
            )
            exploration_result = exploration_stage(round_number)
            results.append(exploration_result)
            exploration_rounds.append(
                {
                    "round": round_number,
                    "status": exploration_result.get("report_status", "unknown"),
                    "report_path": exploration_result.get("report_path"),
                    "target_revision": exploration_result.get("target_revision"),
                    "evaluated_candidates": exploration_result.get(
                        "evaluated_candidates", 0
                    ),
                    "diagnostic_dimensions": exploration_result.get(
                        "diagnostic_dimensions", []
                    ),
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
                        f"{board_failure.get('failure_reason', 'board stage failed')}; "
                        f"board exploration failed: "
                        f"{exploration_result.get('failure_reason', 'unknown error')}"
                    ),
                }
                break

            def graph_validation_failure(
                detail: str,
                board_failure: dict[str, Any] = board_failure,
                exploration_result: dict[str, Any] = exploration_result,
            ) -> dict[str, Any]:
                record = _failure(
                    "board-exploration",
                    (
                        f"{board_failure.get('failure_reason', 'board stage failed')}; "
                        f"{detail}"
                    ),
                    report_path=exploration_result.get("report_path"),
                    report_status=exploration_result.get("report_status"),
                    target_revision=exploration_result.get("target_revision"),
                )
                results.append(record)
                result["exploration_termination"] = "graph_validation_failed"
                return record

            try:
                after_graph = _load_graph(active_config.fixture_dir)
            except Exception as exc:
                failed = graph_validation_failure(
                    f"updated graph is invalid (fail-closed): {exc}"
                )
                break
            after_graph_hash = canonical_json_sha256(after_graph.model_dump(mode="json"))
            if after_graph.graph_id != before_graph.graph_id:
                failed = graph_validation_failure(
                    "updated graph ID does not match the explored graph (fail-closed)"
                )
                break
            if after_graph.revision != before_graph.revision:
                failed = graph_validation_failure(
                    "updated graph revision changed from "
                    f"{before_graph.revision!r} to {after_graph.revision!r} "
                    "(fail-closed)"
                )
                break
            if after_graph_hash == before_graph_hash:
                failed = graph_validation_failure(
                    "updated graph content hash did not change (fail-closed)"
                )
                break
            if exploration_result.get("target_revision") != after_graph.revision:
                failed = graph_validation_failure(
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

        if explore_board:
            result["exploration_rounds"] = exploration_rounds
            if (
                failed is not None
                and board_rejection(failed)
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
        else:
            result.update(
                {
                    "ok": True,
                    "fail_closed": False,
                    "results": results,
                }
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
    return result
