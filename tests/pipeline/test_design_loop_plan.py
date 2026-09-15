"""Regression tests for the declared design-loop execution plan and facade."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import acd.pipeline.design_loop as design_loop
from acd.pipeline.design_loop import loop, stages
from acd.pipeline.lane_plan import DESIGN_LOOP_LANE_IDS, DESIGN_LOOP_STAGE_IDS


def test_execute_once_plan_covers_every_loop_stage_in_declaration_order() -> None:
    expanded: list[str] = []
    for step in loop.EXECUTE_ONCE_PLAN:
        if step.stage_id == loop.LANES_STEP_ID:
            expanded.extend(DESIGN_LOOP_LANE_IDS)
        else:
            expanded.append(step.stage_id)
    optional = [
        step.stage_id for step in loop.EXECUTE_ONCE_PLAN if step.enabled is not loop.always_enabled
    ]
    assert optional == ["order-total-aggregation"]
    assert [stage_id for stage_id in expanded if stage_id not in optional] == list(
        DESIGN_LOOP_STAGE_IDS
    )


def test_execute_once_plan_stop_conditions_fail_closed() -> None:
    by_id = {step.stage_id: step for step in loop.EXECUTE_ONCE_PLAN}
    fail_closed = {"ok": True, "fail_closed": True}
    not_ok = {"ok": False, "fail_closed": False}
    for step in loop.EXECUTE_ONCE_PLAN:
        assert step.stops(fail_closed), step.stage_id
        assert not step.stops({"ok": True, "fail_closed": False}), step.stage_id
    assert by_id["lane-preflight"].stops(not_ok)
    assert not by_id["graph-diff-projection"].stops(not_ok)


def _config(tmp_path: Path) -> design_loop.DesignLoopConfig:
    return design_loop.DesignLoopConfig(
        fixture_dir=tmp_path / "fixture",
        out_root=tmp_path / "out",
        order_total=None,
        policy=tmp_path / "policy.json",
        repository=tmp_path,
        graph_id="golden-design-1",
        output_prefix="golden-design-1",
        artifact_prefix="golden-design-1",
        lane_plan=design_loop.build_lane_plan("golden-design-1", tmp_path / "out"),
        fab_profile=None,
        fab_profile_id=None,
        max_passes=1,
        max_silkscreen_iterations=1,
        run_seconds=1,
        evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_execute_once_plan_conditional_steps(tmp_path: Path) -> None:
    by_id = {step.stage_id: step for step in loop.EXECUTE_ONCE_PLAN}
    aggregation = by_id["order-total-aggregation"]
    readiness = by_id["order-readiness"]
    config = _config(tmp_path)

    assert not aggregation.enabled(config)
    assert aggregation.enabled(replace(config, quote_records=(tmp_path / "q.json",)))
    assert aggregation.runner_override(config) is stages.run_order_total_aggregation
    assert readiness.enabled(config)
    assert readiness.runner_override(config) is None
    assert (
        readiness.runner_override(replace(config, design_only=True))
        is stages.order_readiness_not_executed
    )


def test_facade_exports_historical_surface() -> None:
    assert design_loop.run_design_loop is loop.run_design_loop
    assert design_loop.DEFAULT_STAGE_RUNNERS is stages.DEFAULT_STAGE_RUNNERS
    assert set(design_loop.DEFAULT_STAGE_RUNNERS) == set(DESIGN_LOOP_STAGE_IDS)
    for name in design_loop.__all__:
        assert hasattr(design_loop, name), name
