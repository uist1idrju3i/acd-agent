"""Tests for the fixed graph-driven VibeBB design loop."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from acd.core.naming import artifact_prefix, output_prefix
from acd.pipeline.design_loop import (  # pyright: ignore[reportMissingTypeStubs]
    DESIGN_LOOP_STAGE_IDS,
    DesignLoopConfig,
    _run_firmware,  # pyright: ignore[reportPrivateUsage]
    run_design_loop,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "golden-design-1"


def _successful_runner(
    stage_id: str,
    seen: list[str],
) -> Callable[[DesignLoopConfig], dict[str, Any]]:
    def runner(config: DesignLoopConfig) -> dict[str, Any]:
        del config
        seen.append(stage_id)
        return {
            "stage_id": stage_id,
            "ok": True,
            "fail_closed": False,
            "pass_evidence": False,
        }

    return runner


def test_design_loop_keeps_fixed_stage_order_and_graph_derived_names(
    tmp_path: Path,
) -> None:
    seen: list[str] = []
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        runners={
            stage_id: _successful_runner(stage_id, seen)
            for stage_id in DESIGN_LOOP_STAGE_IDS
        },
    )

    assert result["ok"] is True
    assert seen == list(DESIGN_LOOP_STAGE_IDS)
    assert result["graph_id"] == "golden-design-1"
    assert result["output_prefix"] == output_prefix("golden-design-1")
    assert result["artifact_prefix"] == artifact_prefix("golden-design-1") == "gd1"


def test_design_loop_stops_after_first_failed_stage(tmp_path: Path) -> None:
    seen: list[str] = []

    def failing_board(config: DesignLoopConfig) -> dict[str, Any]:
        del config
        seen.append("board-pipeline")
        return {
            "stage_id": "board-pipeline",
            "ok": False,
            "fail_closed": True,
            "pass_evidence": False,
            "failure_reason": "intentional test failure",
        }

    runners = {
        stage_id: _successful_runner(stage_id, seen)
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }
    runners["board-pipeline"] = failing_board
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        runners=runners,
    )

    assert result["ok"] is False
    assert result["fail_closed"] is True
    assert result["failed_stage"] == "board-pipeline"
    assert result["failure_reason"] == "intentional test failure"
    assert seen == ["silkscreen-resolve", "board-pipeline"]
    assert [item["stage_id"] for item in result["results"]] == [
        "silkscreen-resolve",
        "board-pipeline",
    ]
    assert all(item["pass_evidence"] is False for item in result["results"])


def test_missing_firmware_skill_fails_closed_without_running_order_gate(
    tmp_path: Path,
) -> None:
    seen: list[str] = []
    runners = {
        stage_id: _successful_runner(stage_id, seen)
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }
    runners["firmware-pipeline"] = _run_firmware
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        repository=tmp_path / "repository",
        runners=runners,
    )

    assert result["ok"] is False
    assert result["fail_closed"] is True
    assert result["failed_stage"] == "firmware-pipeline"
    assert "Skill script is missing" in result["failure_reason"]
    assert seen == ["silkscreen-resolve", "board-pipeline", "enclosure-pipeline"]


def test_design_loop_rejects_partial_stage_selection(tmp_path: Path) -> None:
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        stages=DESIGN_LOOP_STAGE_IDS[:-1],
    )

    assert result["ok"] is False
    assert result["fail_closed"] is True
    assert result["failed_stage"] == "stage-selection"
    assert result["results"] == []


def test_invalid_graph_input_fails_closed(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "graph.json").write_text("{", encoding="utf-8")

    result = run_design_loop(
        fixture,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
    )

    assert result["ok"] is False
    assert result["fail_closed"] is True
    assert result["failed_stage"] == "input"
    assert result["results"] == []
