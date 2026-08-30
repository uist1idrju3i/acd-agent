"""Tests for deterministic parallel pipeline stage execution."""

# pyright: reportPrivateUsage=false, reportMissingTypeStubs=false

from __future__ import annotations

import argparse
import json
import os
import shutil
from concurrent.futures import Future
from functools import partial
from pathlib import Path
from typing import cast

import pytest

from acd.core.parallel import (
    DEFAULT_CAD_STAGE_WORKERS,
    PipelineStageRunner,
    _warm_up_worker,
)
from acd.pipeline.enclosure import run_pipeline as run_enclosure_pipeline
from acd.pipeline.gd1_board import (
    _parse_cached_router_record,
    _positive_int,
    _run_ordered_stages,
    _write_router_pass_progression,
    run_pipeline,
)


def _stage_pid() -> int:
    return os.getpid()


def _stage_value(value: str) -> str:
    return value


def _stage_failure() -> None:
    raise ValueError("stage failed")


def test_cached_timed_out_router_record_is_ignored() -> None:
    record = json.dumps({"ses": "(session)", "convergence_state": "timed_out"}).encode()
    assert _parse_cached_router_record(record) is None


def test_router_pass_progression_is_l3_only(tmp_path: Path) -> None:
    _write_router_pass_progression(tmp_path, "r1", "timed_out", (8, 3))
    report = json.loads((tmp_path / "l3" / "router-pass-progress.json").read_text())
    assert report == {
        "authority": "L3 observation; not gate authority",
        "convergence_state": "timed_out",
        "target_revision": "r1",
        "tool_name": "freerouting",
        "unrouted": [8, 3],
    }
    assert not (tmp_path / "hashes.json").exists()


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


def test_freerouting_threads_argument_requires_positive_integer() -> None:
    assert _positive_int("1") == 1
    with pytest.raises(argparse.ArgumentTypeError, match="positive"):
        _positive_int("0")
    with pytest.raises(argparse.ArgumentTypeError, match="integer"):
        _positive_int("not-an-integer")


def test_pipeline_stage_runner_reuses_spawn_pool() -> None:
    with PipelineStageRunner(2) as runner:
        runner.warm_up(("json",))
        assert len(runner._warmup_futures) == 2
        runner.wait_for_warm_up()
        first = runner.run_ordered_stages(
            (
                ("first", _stage_pid),
                ("second", _stage_pid),
            )
        )
        second = runner.run_ordered_stages(
            (
                ("third", _stage_pid),
                ("fourth", _stage_pid),
            )
        )

    parent_pid = os.getpid()
    assert all(pid != parent_pid for pid in first + second)
    assert set(first) & set(second)


def test_warm_up_timeout_is_nonfatal() -> None:
    class TimeoutBarrier:
        def wait(self, *, timeout: float) -> None:
            raise TimeoutError("warm-up barrier timed out")

    result = _warm_up_worker(("json",), TimeoutBarrier(), 0.01)

    assert result is not None
    assert result.startswith("barrier TimeoutError")


def test_warm_up_import_failure_is_nonfatal() -> None:
    class PassingBarrier:
        def wait(self, *, timeout: float) -> None:
            return None

    result = _warm_up_worker(
        ("acd_test_missing_warm_up_module",),
        PassingBarrier(),
        0.01,
    )

    assert result is not None
    assert result.startswith("ModuleNotFoundError")


def test_warm_up_failure_is_reported_without_raising() -> None:
    future: Future[str | None] = Future()
    future.set_exception(RuntimeError("warm-up failed"))
    with PipelineStageRunner(1) as runner:
        runner._warmup_futures = [future]
        with pytest.warns(RuntimeWarning, match="warm-up failed"):
            runner.wait_for_warm_up()


def test_cad_stage_workers_default_to_serial() -> None:
    assert DEFAULT_CAD_STAGE_WORKERS == 1


def test_pipeline_worker_count_must_be_positive() -> None:
    with pytest.raises(ValueError, match="worker count must be at least 1"):
        _run_ordered_stages((), 0)


def test_enclosure_pipeline_outputs_are_stable_across_worker_counts(
    tmp_path: Path,
) -> None:
    fixture_dir = Path("fixtures/golden-design-1")
    serial_dir = tmp_path / "serial"
    parallel_dir = tmp_path / "parallel"
    serial = run_enclosure_pipeline(
        fixture_dir,
        serial_dir,
        pipeline_workers=1,
    )
    parallel = run_enclosure_pipeline(
        fixture_dir,
        parallel_dir,
        pipeline_workers=4,
    )
    assert not (serial_dir / "preflight-mechanical.json").exists()
    assert not (parallel_dir / "preflight-mechanical.json").exists()

    for key in (
        "normalized_output_hash",
        "visual_projection_identity_hash",
        "visual_crosscheck_identity_hash",
        "authoritative",
        "provisional",
        "measured_volume_mm3",
        "measured_min_wall_mm",
        "measured_min_clearance_mm",
        "measured_max_interference_volume_mm3",
        "shell_measured_volume_mm3",
        "lid_measured_volume_mm3",
        "assembly_measured_volume_mm3",
    ):
        assert parallel[key] == serial[key]

    def without_timestamps(value: object, *, drop_hashes: bool = False) -> object:
        if isinstance(value, dict):
            mapping = cast(dict[str, object], value)
            return {
                key: without_timestamps(item, drop_hashes=drop_hashes)
                for key, item in mapping.items()
                if not key.endswith("_at") and not (drop_hashes and key == "canonical_hash")
            }
        if isinstance(value, list):
            items = cast(list[object], value)
            return [without_timestamps(item, drop_hashes=drop_hashes) for item in items]
        return value

    serial_evidence = cast(
        dict[str, object],
        json.loads(
            (serial_dir / "evidence-mechanical.json").read_text(encoding="utf-8")
        ),
    )
    parallel_evidence = cast(
        dict[str, object],
        json.loads(
            (parallel_dir / "evidence-mechanical.json").read_text(encoding="utf-8")
        ),
    )
    assert without_timestamps(serial_evidence) == without_timestamps(parallel_evidence)

    for filename in (
        "visual-projections-mechanical.json",
        "visual-crosscheck-mechanical.json",
    ):
        serial_payload = cast(
            dict[str, object],
            json.loads((serial_dir / filename).read_text(encoding="utf-8")),
        )
        parallel_payload = cast(
            dict[str, object],
            json.loads((parallel_dir / filename).read_text(encoding="utf-8")),
        )
        assert without_timestamps(serial_payload, drop_hashes=True) == without_timestamps(
            parallel_payload,
            drop_hashes=True,
        )


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
