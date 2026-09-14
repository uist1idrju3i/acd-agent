"""Tests for the lane resource measurement wrapper."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from scripts import measure_lane_resources


class _FakeProcess:
    def __init__(self, returncode: int = 0, polls: int = 2) -> None:
        self.returncode: int | None = None
        self._returncode = returncode
        self._polls = polls

    def poll(self) -> int | None:
        if self._polls > 0:
            self._polls -= 1
            return None
        self.returncode = self._returncode
        return self._returncode

    def wait(self) -> int:
        self.returncode = self._returncode
        return self._returncode


def _args(tmp_path: Path, *extra: str) -> list[str]:
    image = "example/acd-server@sha256:" + "a" * 64
    return [
        "--repo",
        str(tmp_path),
        "--image",
        image,
        "--interval",
        "1.5",
        "--out",
        str(tmp_path / "record.json"),
        *extra,
    ]


def _no_sleep(_seconds: float) -> None:
    return None


def _host_samples() -> list[dict[str, float | int]]:
    return [
        {
            "cpu_cores": 1.0,
            "mem_total_bytes": 8000,
            "mem_used_bytes": 1000,
            "mem_available_bytes": 7000,
            "swap_used_bytes": 10,
        },
        {
            "cpu_cores": 3.0,
            "mem_total_bytes": 8000,
            "mem_used_bytes": 2500,
            "mem_available_bytes": 5500,
            "swap_used_bytes": 30,
        },
        {
            "cpu_cores": 0.5,
            "mem_total_bytes": 8000,
            "mem_used_bytes": 1200,
            "mem_available_bytes": 6800,
            "swap_used_bytes": 20,
        },
    ]


def test_peaks_recorded_and_exit_code_propagated(tmp_path: Path) -> None:
    samples = iter(_host_samples())
    calls: list[list[str]] = []

    def spawn(argv: Sequence[str], cwd: Path) -> _FakeProcess:
        calls.append(list(argv))
        return _FakeProcess(returncode=1, polls=2)

    def host_sample() -> dict[str, float | int]:
        return next(samples)

    def one_mib() -> int:
        return 1 << 20

    code = measure_lane_resources.main(
        _args(tmp_path, "--label", "8GiB", "--", "true"),
        spawn=spawn,
        host_sampler=host_sample,
        docker_sampler=one_mib,
        sleep=_no_sleep,
        monotonic=iter([0.0, 4.5]).__next__,
    )
    assert code == 1
    record = json.loads((tmp_path / "record.json").read_text(encoding="utf-8"))
    assert record["record_class"] == "L3"
    assert record["pass_evidence"] is False
    assert record["exit_code"] == 1
    assert record["sample_count"] == 3
    assert record["wall_clock_seconds"] == 4.5
    assert record["label"] == "8GiB"
    host = record["host"]
    assert host["cpu_cores_peak"] == 3.0
    assert host["mem_used_peak_bytes"] == 2500
    assert host["mem_available_min_bytes"] == 5500
    assert host["swap_used_peak_bytes"] == 30
    assert record["docker"]["stats_available"] is True
    assert record["docker"]["mem_usage_peak_bytes"] == 1 << 20


def test_docker_stats_failure_is_recorded_not_fatal(tmp_path: Path) -> None:
    samples = iter(_host_samples())

    def spawn(_argv: Sequence[str], _cwd: Path) -> _FakeProcess:
        return _FakeProcess(returncode=0, polls=1)

    def host_sample() -> dict[str, float | int]:
        return next(samples)

    def docker() -> None:
        return None

    code = measure_lane_resources.main(
        _args(tmp_path, "--", "true"),
        spawn=spawn,
        host_sampler=host_sample,
        docker_sampler=docker,
        sleep=_no_sleep,
    )
    assert code == 0
    record = json.loads((tmp_path / "record.json").read_text(encoding="utf-8"))
    assert record["docker"]["stats_available"] is False
    assert record["docker"]["mem_usage_peak_bytes"] is None


def test_argv_forwarding(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path]] = []

    def spawn(argv: Sequence[str], cwd: Path) -> _FakeProcess:
        calls.append((list(argv), cwd))
        return _FakeProcess(returncode=0, polls=0)

    measure_lane_resources.main(
        _args(
            tmp_path,
            "--download",
            "out/gd1/evidence-electrical.json",
            "--download-root",
            "out/gd1",
            "--log",
            str(tmp_path / "lane.log"),
            "--memory-limit",
            "8g",
            "--jvm-max-heap",
            "2g",
            "--",
            "uv",
            "run",
            "pytest",
        ),
        spawn=spawn,
        host_sampler=lambda: _host_samples()[0],
        docker_sampler=lambda: 0,
        sleep=_no_sleep,
    )
    argv, cwd = calls[0]
    assert cwd == tmp_path
    assert argv[0] == sys.executable
    assert argv[1].endswith("run_in_workspace.py")
    for flag, value in (
        ("--image", f"example/acd-server@sha256:{'a' * 64}"),
        ("--repo", str(tmp_path)),
        ("--download", "out/gd1/evidence-electrical.json"),
        ("--download-root", "out/gd1"),
        ("--log", str(tmp_path / "lane.log")),
        ("--memory-limit", "8g"),
        ("--jvm-max-heap", "2g"),
    ):
        index = argv.index(flag)
        assert argv[index + 1] == value
    assert argv[-3:] == ["uv", "run", "pytest"]


def test_invalid_interval_and_image_fail(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        measure_lane_resources.main(
            [*_args(tmp_path)[:4], "--interval", "0", *_args(tmp_path)[6:]]
        )
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        measure_lane_resources.main(
            [
                "--repo",
                str(tmp_path),
                "--image",
                "acd-server:local",
                "--out",
                str(tmp_path / "r.json"),
            ]
        )
    assert exc.value.code == 2


def test_parse_docker_mem_usage() -> None:
    assert measure_lane_resources.parse_docker_mem_usage("512MiB / 8GiB") == (
        512 * 1024 * 1024
    )
    assert measure_lane_resources.parse_docker_mem_usage("1.5GiB / 8GiB") == int(
        1.5 * 1024**3
    )
    with pytest.raises(ValueError):
        measure_lane_resources.parse_docker_mem_usage("unavailable")
