"""Tests for design-loop budgets and checkpoints."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import pytest

import acd.pipeline.design_loop as design_loop
from acd.pipeline.design_loop import DesignLoopConfig, run_design_loop

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "golden-design-1"


def _runners(monkeypatch: pytest.MonkeyPatch) -> None:
    def runner(config: DesignLoopConfig) -> dict[str, Any]:
        stage_id = "stub"
        del config
        return {"stage_id": stage_id, "ok": True, "fail_closed": False}

    monkeypatch.setattr(
        design_loop.loop,
        "DEFAULT_STAGE_RUNNERS",
        {stage_id: runner for stage_id in design_loop.DESIGN_LOOP_STAGE_IDS},
    )


def test_budget_is_always_present_and_checkpoint_is_l3(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _runners(monkeypatch)
    result = run_design_loop(
        FIXTURE,
        tmp_path,
        policy=tmp_path / "policy.json",
        design_only=True,
        jobs=1,
    )
    assert result["budget"] == {
        "wall_clock_seconds": None,
        "token": None,
        "enforcement": "stage-boundary",
    }
    checkpoint = json.loads(
        (tmp_path / "design-loop-checkpoint.json").read_text(encoding="utf-8")
    )
    assert checkpoint["record_class"] == "L3"
    assert checkpoint["pass_evidence"] is False
    assert len(checkpoint["stages"]) == len(result["results"])
    assert checkpoint["stages"][-1]["stage_id"] == "order-readiness"


def test_wall_clock_budget_stops_at_stage_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _runners(monkeypatch)
    clock = itertools.chain([0.0, 0.0, 0.0], itertools.repeat(2.0))
    monkeypatch.setattr(design_loop.loop, "_MONOTONIC", lambda: next(clock))
    result = run_design_loop(
        FIXTURE,
        tmp_path,
        policy=tmp_path / "policy.json",
        design_only=True,
        jobs=1,
        wall_clock_budget_seconds=1.0,
    )
    assert result["ok"] is False
    assert result["budget_exhausted"] is True
    exhausted = next(stage for stage in result["results"] if stage.get("budget_exhausted"))
    assert exhausted["fail_closed"] is True
    assert "wall-clock budget exhausted" in exhausted["failure_reason"]
    assert len(result["results"]) == 2


@pytest.mark.parametrize("field", ["wall_clock_budget_seconds", "token_budget"])
@pytest.mark.parametrize("value", [0, -1])
def test_budget_must_be_positive(
    field: str, value: int, tmp_path: Path
) -> None:
    kwargs: dict[str, object] = {field: value}
    result = run_design_loop(
        FIXTURE,
        tmp_path,
        policy=tmp_path / "policy.json",
        design_only=True,
        **kwargs,  # pyright: ignore[reportArgumentType]
    )
    assert result["ok"] is False
    assert result["failed_stage"] == "input"
    assert "must be positive" in result["failure_reason"]
