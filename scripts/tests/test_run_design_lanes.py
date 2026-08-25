"""Tests for the GD1 lane orchestrator."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from scripts import run_design_lanes

from acd.core import command_runner
from acd.core.command_runner import CommandSpec
from acd.pipeline.lane_plan import build_lane_plan

FIXTURE = Path("fixtures/golden-design-1")


def _commands(out_root: Path = Path("out")) -> tuple[CommandSpec, ...]:
    plan = build_lane_plan("golden-design-1", out_root)
    return run_design_lanes.build_lane_commands(plan, FIXTURE)


def test_list_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_design_lanes.main(["--list"]) == 0
    listed = json.loads(capsys.readouterr().out)

    assert listed == [
        {
            "command": list(spec.command),
            "barrier": spec.barrier,
        }
        for spec in _commands()
    ]


def test_list_does_not_create_output_root(tmp_path: Path) -> None:
    out_root = tmp_path / "out"

    assert run_design_lanes.main(["--list", "--out-root", str(out_root)]) == 0
    assert not out_root.exists()


def test_parallel_lanes_wait_for_resolver(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, ...]] = []
    resolver = _commands()[0].command

    def fake_run(command: Sequence[str], **kwargs: object) -> object:
        command_tuple = tuple(command)
        calls.append(command_tuple)
        if command_tuple != resolver:
            assert resolver in calls
        return command_runner.subprocess.CompletedProcess(
            command, 0, stdout=f"{command_tuple[-1]} output\n", stderr=""
        )

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    assert run_design_lanes.main(["--jobs", "3"]) == 0

    assert calls[0] == resolver
    assert set(calls[1:]) == {spec.command for spec in _commands()[1:]}
    assert "[1/5] PASS" in capsys.readouterr().out


def test_sequential_lanes_keep_declared_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(
        command: Sequence[str], **kwargs: object
    ) -> command_runner.subprocess.CompletedProcess[str]:
        command_tuple = tuple(command)
        calls.append(command_tuple)
        return command_runner.subprocess.CompletedProcess(
            command, 0, stdout="", stderr=""
        )

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    assert run_design_lanes.main(["--jobs", "1"]) == 0

    assert calls == [spec.command for spec in _commands()]


def test_parallel_lanes_report_all_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(command: Sequence[str], **kwargs: object) -> object:
        command_tuple = tuple(command)
        return command_runner.subprocess.CompletedProcess(
            command,
            5 if command_tuple in {
                _commands()[1].command,
                _commands()[3].command,
            } else 0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    assert run_design_lanes.main(["--jobs", "3"]) == 5

    output = capsys.readouterr().out
    assert output.count("FAIL (exit=5)") == 2
    assert "[2/5] FAIL (exit=5)" in output
    assert "[4/5] FAIL (exit=5)" in output


def test_commands_use_plan_outputs_and_cache_target(tmp_path: Path) -> None:
    plan = build_lane_plan("golden-design-1", tmp_path)
    commands = run_design_lanes.build_lane_commands(
        plan,
        FIXTURE,
        tmp_path / "cache",
    )

    assert str(tmp_path / "gd1-silkscreen-resolve") in commands[0].command
    assert str(tmp_path / "gd1") in commands[1].command
    assert str(tmp_path / "gd1-enclosure") in commands[2].command
    assert str(tmp_path / "gd1-fw") in commands[3].command
    assert "--cache-dir" in commands[1].command
    assert "--cache-dir" not in commands[0].command
    assert all("--cache-dir" not in command.command for command in commands[2:])


def test_failure_logs_are_summarized_with_a_full_log_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    noisy = "\n".join(f"line {index}" for index in range(200))

    def fake_run(command: Sequence[str], **kwargs: object) -> object:
        return command_runner.subprocess.CompletedProcess(
            command, 7, stdout="", stderr=noisy
        )

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    assert (
        run_design_lanes.main(
            ["--jobs", "3", "--out-root", str(tmp_path), "--log-tail-lines", "5"]
        )
        == 7
    )

    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    failure = summary["failures"][0]
    assert failure["stderr_dropped_lines"] == 195
    assert "line 199" in failure["stderr_tail"]
    assert "line 0" not in failure["stderr_tail"]
    log_path = Path(failure["log_path"])
    assert log_path.is_relative_to(tmp_path)
    assert noisy in log_path.read_text(encoding="utf-8")


def test_full_logs_flag_keeps_the_whole_failure_log(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    noisy = "\n".join(f"line {index}" for index in range(60))

    def fake_run(command: Sequence[str], **kwargs: object) -> object:
        return command_runner.subprocess.CompletedProcess(
            command, 3, stdout="", stderr=noisy
        )

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    assert (
        run_design_lanes.main(
            ["--jobs", "3", "--out-root", str(tmp_path), "--full-logs"]
        )
        == 3
    )

    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary["failures"][0]["stderr"] == noisy
