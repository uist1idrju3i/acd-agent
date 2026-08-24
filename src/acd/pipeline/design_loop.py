"""Graph-driven VibeBB design loop orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from acd.core.order_total import order_total_result_from_document
from acd.core.runtime_records import TimingRecorder, write_timing_record
from acd.openhands.order_gate import evaluate_pre_order_gate
from acd.pipeline import lane_plan
from acd.pipeline.gd1_board import run_pipeline as run_board_pipeline
from acd.pipeline.gd1_enclosure import run_pipeline as run_enclosure_pipeline
from acd.pipeline.lane_plan import (
    DESIGN_LOOP_LANE_IDS,
    LanePlan,
    build_lane_plan,
)
from acd.pipeline.silkscreen_resolve import resolve_silkscreen
from acd.schema import DesignGraph, OrderPolicy, OrderTotalDocument

DEFAULT_DESIGN_LOOP_JOBS = min(os.cpu_count() or 1, 3)
DESIGN_LOOP_STAGE_IDS = lane_plan.DESIGN_LOOP_STAGE_IDS

StageRunner = Callable[["DesignLoopConfig"], Any]


@dataclass(frozen=True)
class DesignLoopConfig:
    """Inputs for one graph-driven design loop."""

    fixture_dir: Path
    out_root: Path
    order_total: Path
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


def _run_order_readiness(config: DesignLoopConfig) -> dict[str, Any]:
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


def _graph_id(fixture_dir: Path) -> str:
    graph_path = fixture_dir / "graph.json"
    graph = DesignGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    return graph.graph_id


def _resolve_evaluated_at(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("evaluated-at must include a timezone")
    return value


DEFAULT_STAGE_RUNNERS: dict[str, StageRunner] = {
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
    order_total: Path,
    policy: Path,
    repository: Path | None = None,
    fab_profile: Path | None = None,
    fab_profile_id: str | None = None,
    max_passes: int = 3,
    max_silkscreen_iterations: int = 5,
    run_seconds: int = 15,
    evaluated_at: datetime | None = None,
    cache_dir: Path | None = None,
    resume: bool = False,
    jobs: int = DEFAULT_DESIGN_LOOP_JOBS,
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
    timing_record: Path | None = None
    timing_record_error: str | None = None
    config: DesignLoopConfig | None = None
    try:
        out_root.mkdir(parents=True, exist_ok=True)
        graph_id = _graph_id(fixture_dir)
        plan = build_lane_plan(graph_id, out_root)
        prefix = plan.output_prefix
        artifact = plan.artifact_prefix
        evaluated = _resolve_evaluated_at(evaluated_at)
        if jobs < 1:
            raise ValueError("jobs must be a positive integer")
        if resolved_cache_dir is not None:
            resolved_cache_dir.mkdir(parents=True, exist_ok=True)
        config = DesignLoopConfig(
            fixture_dir=fixture_dir,
            out_root=out_root,
            order_total=order_total,
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
    except Exception as exc:
        result.update(
            {
                "failed_stage": "input",
                "failure_reason": f"{type(exc).__name__}: {exc}",
            }
        )
    else:
        results: list[dict[str, Any]] = []

        def run_stage(stage_id: str) -> dict[str, Any]:
            timing_error: str | None = None
            started = False
            try:
                timing.start(f"design-loop/{stage_id}")
                started = True
            except Exception as exc:
                timing_error = f"{type(exc).__name__}: {exc}"
            try:
                stage_result = DEFAULT_STAGE_RUNNERS[stage_id](config)
            except Exception as exc:
                stage_result = _failure(stage_id, f"{type(exc).__name__}: {exc}")
            finally:
                if started:
                    try:
                        timing.finish(f"design-loop/{stage_id}")
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

        def run_lanes() -> list[dict[str, Any]]:
            if jobs == 1:
                lane_results: list[dict[str, Any]] = []
                for stage_id in DESIGN_LOOP_LANE_IDS:
                    stage_result = run_stage(stage_id)
                    lane_results.append(stage_result)
                    if not stage_result.get("ok") or stage_result.get("fail_closed"):
                        break
                return lane_results
            with ThreadPoolExecutor(
                max_workers=min(jobs, len(DESIGN_LOOP_LANE_IDS))
            ) as executor:
                futures = {
                    stage_id: executor.submit(run_stage, stage_id)
                    for stage_id in DESIGN_LOOP_LANE_IDS
                }
                return [futures[stage_id].result() for stage_id in DESIGN_LOOP_LANE_IDS]

        silkscreen = run_stage("silkscreen-resolve")
        results.append(silkscreen)
        if not silkscreen.get("ok") or silkscreen.get("fail_closed"):
            result.update(
                {
                    "failed_stage": "silkscreen-resolve",
                    "failure_reason": silkscreen.get(
                        "failure_reason", "stage failed"
                    ),
                    "results": results,
                }
            )
        else:
            lane_results = run_lanes()
            results.extend(lane_results)
            failed = next(
                (
                    stage_result
                    for stage_result in lane_results
                    if not stage_result.get("ok") or stage_result.get("fail_closed")
                ),
                None,
            )
            if failed is not None:
                result.update(
                    {
                        "failed_stage": str(failed.get("stage_id", "unknown")),
                        "failure_reason": failed.get("failure_reason", "stage failed"),
                        "results": results,
                    }
                )
            else:
                order_result = run_stage("order-readiness")
                results.append(order_result)
                if not order_result.get("ok") or order_result.get("fail_closed"):
                    result.update(
                        {
                            "failed_stage": "order-readiness",
                            "failure_reason": order_result.get(
                                "failure_reason", "stage failed"
                            ),
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
