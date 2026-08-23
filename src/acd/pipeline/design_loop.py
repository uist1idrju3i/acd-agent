"""Graph-driven VibeBB design loop orchestration."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from acd.core.naming import artifact_prefix, output_prefix
from acd.core.order_total import order_total_result_from_document
from acd.openhands.order_gate import evaluate_pre_order_gate
from acd.pipeline.gd1_board import run_pipeline as run_board_pipeline
from acd.pipeline.gd1_enclosure import run_pipeline as run_enclosure_pipeline
from acd.pipeline.silkscreen_resolve import resolve_silkscreen
from acd.schema import DesignGraph, OrderPolicy, OrderTotalDocument

DESIGN_LOOP_STAGE_IDS: tuple[str, ...] = (
    "silkscreen-resolve",
    "board-pipeline",
    "enclosure-pipeline",
    "firmware-pipeline",
    "order-readiness",
)

StageRunner = Callable[["DesignLoopConfig"], Any]


class DesignLoopConfig:
    """Inputs for one graph-driven design loop."""

    def __init__(
        self,
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
    ) -> None:
        self.fixture_dir = fixture_dir
        self.out_root = out_root
        self.order_total = order_total
        self.policy = policy
        self.repository = repository or Path.cwd()
        self.fab_profile = fab_profile
        self.fab_profile_id = fab_profile_id
        self.max_passes = max_passes
        self.max_silkscreen_iterations = max_silkscreen_iterations
        self.run_seconds = run_seconds
        self.evaluated_at = evaluated_at or datetime.now(UTC)


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
    output = config.out_root / f"{artifact_prefix(_graph_id(config.fixture_dir))}-silkscreen"
    result = resolve_silkscreen(
        config.fixture_dir,
        output,
        config.fab_profile,
        config.max_silkscreen_iterations,
        config.fab_profile_id,
    )
    return _success("silkscreen-resolve", output_path=str(output), summary=result)


def _run_board(config: DesignLoopConfig) -> dict[str, Any]:
    output = config.out_root / artifact_prefix(_graph_id(config.fixture_dir))
    result = run_board_pipeline(
        config.fixture_dir,
        output,
        config.max_passes,
        config.fab_profile,
        fab_profile_id=config.fab_profile_id,
    )
    return _success("board-pipeline", output_path=str(output), summary=result)


def _run_enclosure(config: DesignLoopConfig) -> dict[str, Any]:
    output = config.out_root / f"{artifact_prefix(_graph_id(config.fixture_dir))}-enclosure"
    result = run_enclosure_pipeline(config.fixture_dir, output)
    return _success("enclosure-pipeline", output_path=str(output), summary=result)


def _run_firmware(config: DesignLoopConfig) -> dict[str, Any]:
    script = _firmware_script(config.repository)
    output = config.out_root / f"{artifact_prefix(_graph_id(config.fixture_dir))}-fw"
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
        policy = OrderPolicy.model_validate_json(
            config.policy.read_text(encoding="utf-8")
        )
        order_total = order_total_result_from_document(
            OrderTotalDocument.model_validate_json(
                config.order_total.read_text(encoding="utf-8")
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
    stages: Sequence[str] | None = None,
    runners: dict[str, StageRunner] | None = None,
) -> dict[str, Any]:
    """Run all design stages in their fixed fail-closed order."""
    config = DesignLoopConfig(
        fixture_dir,
        out_root,
        order_total=order_total,
        policy=policy,
        repository=repository,
        fab_profile=fab_profile,
        fab_profile_id=fab_profile_id,
        max_passes=max_passes,
        max_silkscreen_iterations=max_silkscreen_iterations,
        run_seconds=run_seconds,
        evaluated_at=evaluated_at,
    )
    try:
        graph_id = _graph_id(fixture_dir)
        prefix = output_prefix(graph_id)
        artifact = artifact_prefix(graph_id)
    except Exception as exc:
        return {
            "ok": False,
            "fail_closed": True,
            "pass_evidence": False,
            "failed_stage": "input",
            "failure_reason": f"{type(exc).__name__}: {exc}",
            "results": [],
        }
    selected = tuple(stages) if stages is not None else DESIGN_LOOP_STAGE_IDS
    if selected != DESIGN_LOOP_STAGE_IDS:
        return {
            "ok": False,
            "fail_closed": True,
            "pass_evidence": False,
            "graph_id": graph_id,
            "output_prefix": prefix,
            "failed_stage": "stage-selection",
            "failure_reason": "design loop stages cannot be skipped or reordered",
            "results": [],
        }
    try:
        out_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {
            "ok": False,
            "fail_closed": True,
            "pass_evidence": False,
            "graph_id": graph_id,
            "output_prefix": prefix,
            "artifact_prefix": artifact,
            "failed_stage": "input",
            "failure_reason": f"output root is not usable: {exc}",
            "results": [],
        }
    default_runners: dict[str, StageRunner] = {
        "silkscreen-resolve": _run_silkscreen,
        "board-pipeline": _run_board,
        "enclosure-pipeline": _run_enclosure,
        "firmware-pipeline": _run_firmware,
        "order-readiness": _run_order_readiness,
    }
    if runners:
        default_runners.update(runners)
    results: list[dict[str, Any]] = []
    for stage_id in DESIGN_LOOP_STAGE_IDS:
        try:
            result = default_runners[stage_id](config)
        except Exception as exc:
            result = _failure(stage_id, f"{type(exc).__name__}: {exc}")
        if not isinstance(result, dict):
            result = _failure(stage_id, "stage runner returned a non-object result")
        else:
            result = {**result, "pass_evidence": False}
        results.append(result)
        if not result.get("ok") or result.get("fail_closed"):
            return {
                "ok": False,
                "fail_closed": True,
                "pass_evidence": False,
                "graph_id": graph_id,
                "output_prefix": prefix,
                "artifact_prefix": artifact,
                "failed_stage": stage_id,
                "failure_reason": result.get("failure_reason", "stage failed"),
                "results": results,
            }
    return {
        "ok": True,
        "fail_closed": False,
        "pass_evidence": False,
        "graph_id": graph_id,
        "output_prefix": prefix,
        "artifact_prefix": artifact,
        "results": results,
    }
