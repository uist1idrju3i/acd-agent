"""Tests for deterministic parallel width positive-control collection."""

# pyright: reportPrivateUsage=false, reportMissingTypeStubs=false

from __future__ import annotations

import pytest

from acd_pipeline.gd1_board import _run_ordered_arms


def test_width_controls_keep_deterministic_arm_order() -> None:
    def run_arm(name: str, board_minimum: bool) -> dict[str, object]:
        return {"name": name, "board_minimum": board_minimum}

    sequential = _run_ordered_arms(run_arm, 1)
    parallel = _run_ordered_arms(run_arm, 4)
    assert sequential == parallel
    assert [item["name"] for item in parallel] == [
        "arm-a-class-only",
        "arm-b-class-and-board-minimum",
    ]


def test_width_control_worker_failure_is_not_suppressed() -> None:
    def run_arm(name: str, board_minimum: bool) -> dict[str, object]:
        if board_minimum:
            raise ValueError(f"{name}: failed")
        return {"name": name}

    with pytest.raises(ValueError, match="arm-b-class-and-board-minimum: failed"):
        _run_ordered_arms(run_arm, 4)


def test_width_control_worker_count_must_be_positive() -> None:
    with pytest.raises(ValueError, match="worker count must be at least 1"):
        _run_ordered_arms(lambda name, board_minimum: {}, 0)
