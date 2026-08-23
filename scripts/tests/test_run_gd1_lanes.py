"""Tests for the GD1 lane orchestrator."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest
from scripts import run_gd1_lanes

from acd.core import command_runner


def test_list_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_gd1_lanes.main(["--list"]) == 0
    listed = json.loads(capsys.readouterr().out)

    assert listed == [
        {
            "command": list(spec.command),
            "barrier": spec.barrier,
        }
        for spec in run_gd1_lanes.LANE_COMMANDS
    ]


def test_parallel_lanes_wait_for_resolver(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, ...]] = []
    resolver = run_gd1_lanes.LANE_COMMANDS[0].command

    def fake_run(command: Sequence[str], **kwargs: object) -> object:
        command_tuple = tuple(command)
        calls.append(command_tuple)
        if command_tuple != resolver:
            assert resolver in calls
        return command_runner.subprocess.CompletedProcess(
            command, 0, stdout=f"{command_tuple[-1]} output\n", stderr=""
        )

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    assert run_gd1_lanes.main(["--jobs", "3"]) == 0

    assert calls[0] == resolver
    assert set(calls[1:]) == {spec.command for spec in run_gd1_lanes.LANE_COMMANDS[1:]}
    assert "[1/4] PASS" in capsys.readouterr().out


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

    assert run_gd1_lanes.main(["--jobs", "1"]) == 0

    assert calls == [spec.command for spec in run_gd1_lanes.LANE_COMMANDS]


def test_parallel_lanes_report_all_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(command: Sequence[str], **kwargs: object) -> object:
        command_tuple = tuple(command)
        return command_runner.subprocess.CompletedProcess(
            command,
            5 if command_tuple in {
                run_gd1_lanes.LANE_COMMANDS[1].command,
                run_gd1_lanes.LANE_COMMANDS[3].command,
            } else 0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    assert run_gd1_lanes.main(["--jobs", "3"]) == 5

    output = capsys.readouterr().out
    assert output.count("FAIL (exit=5)") == 2
    assert "[2/4] FAIL (exit=5)" in output
    assert "[4/4] FAIL (exit=5)" in output
