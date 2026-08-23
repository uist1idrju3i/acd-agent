"""Tests for deterministic parallel pipeline stage execution."""

# pyright: reportPrivateUsage=false, reportMissingTypeStubs=false

from __future__ import annotations

import json
import os
import shutil
from functools import partial
from pathlib import Path

import pytest

from acd.pipeline.gd1_board import _run_ordered_stages, run_pipeline


def _stage_pid() -> int:
    return os.getpid()


def _stage_value(value: str) -> str:
    return value


def _stage_failure() -> None:
    raise ValueError("stage failed")


def test_ordered_stages_keep_declared_order() -> None:
    stages = (
        ("first", partial(_stage_value, "first")),
        ("second", partial(_stage_value, "second")),
        ("third", partial(_stage_value, "third")),
    )
    assert _run_ordered_stages(stages, 1) == _run_ordered_stages(stages, 3)
    assert _run_ordered_stages(stages, 3) == ["first", "second", "third"]


def test_ordered_stage_failure_is_not_suppressed() -> None:
    stages = (
        ("passing", partial(_stage_value, "passing")),
        ("failing", _stage_failure),
    )
    with pytest.raises(ValueError, match="stage failed"):
        _run_ordered_stages(stages, 2)


def test_pipeline_worker_count_must_be_positive() -> None:
    with pytest.raises(ValueError, match="worker count must be at least 1"):
        _run_ordered_stages((), 0)


def test_ordered_stages_run_in_child_processes() -> None:
    stages = (
        ("first", _stage_pid),
        ("second", _stage_pid),
    )
    parent_pid = os.getpid()
    child_pids = _run_ordered_stages(stages, 2)
    assert all(pid != parent_pid for pid in child_pids)


@pytest.mark.skipif(
    os.environ.get("ACD_PIPELINE_PARALLEL_TEST") != "1"
    or shutil.which("kicad-cli") is None
    or shutil.which("freerouting") is None,
    reason=(
        "opt-in integration test requires ACD_PIPELINE_PARALLEL_TEST=1, "
        "kicad-cli, and freerouting"
    ),
)
def test_pipeline_parallel_hashes_match_sequential(tmp_path: Path) -> None:
    """Compare worker counts while allowing KiCad refill_zones UUID regeneration."""
    fixture_dir = Path("fixtures/golden-design-1")
    fab_profile = Path("profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json")
    run_pipeline(
        fixture_dir,
        tmp_path / "sequential-a",
        99999,
        fab_profile,
        pipeline_workers=1,
    )
    run_pipeline(
        fixture_dir,
        tmp_path / "sequential-b",
        99999,
        fab_profile,
        pipeline_workers=1,
    )
    run_pipeline(
        fixture_dir,
        tmp_path / "parallel-c",
        99999,
        fab_profile,
        pipeline_workers=4,
    )

    def read_hashes(out_dir: Path) -> dict[str, str]:
        manifest = json.loads((out_dir / "hashes.json").read_text())
        return {str(key): str(value) for key, value in manifest.items()}

    hashes_a = read_hashes(tmp_path / "sequential-a")
    hashes_b = read_hashes(tmp_path / "sequential-b")
    hashes_c = read_hashes(tmp_path / "parallel-c")

    def differing_keys(left: dict[str, str], right: dict[str, str]) -> set[str]:
        return {
            key
            for key in set(left) | set(right)
            if left.get(key) != right.get(key)
        }

    sequential_difference_keys = differing_keys(hashes_a, hashes_b)
    parallel_difference_keys = differing_keys(hashes_a, hashes_c)
    assert parallel_difference_keys == sequential_difference_keys
    for key in set(hashes_a) | set(hashes_c):
        if key not in parallel_difference_keys:
            assert hashes_a.get(key) == hashes_c.get(key)
