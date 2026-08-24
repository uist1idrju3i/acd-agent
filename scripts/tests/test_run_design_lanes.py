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

    assert str(tmp_path / "gd1-silkscreen") in commands[0].command
    assert str(tmp_path / "gd1") in commands[1].command
    assert str(tmp_path / "gd1-enclosure") in commands[2].command
    assert str(tmp_path / "gd1-fw") in commands[3].command
    assert "--cache-dir" in commands[1].command
    assert "--cache-dir" not in commands[0].command
    assert all("--cache-dir" not in command.command for command in commands[2:])
