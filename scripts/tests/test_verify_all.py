"""Tests for the canonical verification entrypoint."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from scripts import verify_all

from acd.core import command_runner


def test_list_matches_stage_definitions(capsys: pytest.CaptureFixture[str]) -> None:
    assert verify_all.main(["--list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed == {
        stage: [
            {
                "command": list(spec.command),
                "barrier": spec.barrier,
            }
            for spec in commands
        ]
        for stage, commands in verify_all.STAGES.items()
    }


def test_documents_and_ci_reference_defined_stages() -> None:
    repository = Path(__file__).parents[2]
    documents = (
        (repository / "AGENTS.md").read_text(encoding="utf-8"),
        (repository / "docs/operations.md").read_text(encoding="utf-8"),
    )
    for document in documents:
        assert "scripts/verify_all.py --list" in document
        for stage in verify_all.STAGES:
            assert f"scripts/verify_all.py --stage {stage}" in document
    workflow = (repository / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "scripts/verify_all.py --stage standard" in workflow


def test_unknown_stage_fails_closed() -> None:
    with pytest.raises(SystemExit) as error:
        verify_all.main(["--stage", "unknown"])
    assert error.value.code == 2


def test_failed_command_stops_stage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(
        command: Sequence[str], check: bool, **kwargs: object
    ) -> command_runner.subprocess.CompletedProcess[str]:
        assert check is False
        assert kwargs == {}
        calls.append(tuple(command))
        print(f"child {command[0]}")
        return command_runner.subprocess.CompletedProcess(
            command, 7 if len(calls) == 2 else 0
        )

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)
    assert verify_all.run_stage((("first",), ("second",), ("third",))) == 7
    assert calls == [("first",), ("second",)]
    output = capsys.readouterr().out
    assert "child first" in output
    assert "child second" in output
    assert "FAIL (exit=7)" in output


def test_success_output_is_identical_for_sequential_and_parallel_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    commands = (("first",), ("second",), ("third",))

    def fake_run(command: Sequence[str], **kwargs: object) -> object:
        return command_runner.subprocess.CompletedProcess(
            command, 0, stdout=f"{command[0]} output\n", stderr=""
        )

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)
    assert verify_all.run_stage(commands, jobs=1) == 0
    sequential = capsys.readouterr()
    assert verify_all.run_stage(commands, jobs=4) == 0
    parallel = capsys.readouterr()

    def result_lines(output: str) -> list[str]:
        return [
            line
            for line in output.splitlines()
            if " START $ " not in line
            and ("] $ " in line or "] PASS" in line or "] FAIL" in line)
        ]

    assert result_lines(sequential.out) == result_lines(parallel.out)
    assert sequential.err == parallel.err
    assert "[1/3] START $ first" in parallel.out
    assert "[3/3] START $ third" in parallel.out


def test_parallel_stage_reports_all_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    commands = (("sync",), ("bad-first",), ("ok",), ("bad-second",))

    def fake_run(command: Sequence[str], **kwargs: object) -> object:
        return command_runner.subprocess.CompletedProcess(
            command,
            9 if command[0].startswith("bad") else 0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)
    assert verify_all.run_stage(commands, jobs=4) == 9
    output = capsys.readouterr().out
    assert output.count("FAIL (exit=9)") == 2
    assert "[2/4] FAIL (exit=9)" in output
    assert "[4/4] FAIL (exit=9)" in output


def test_parallel_commands_wait_for_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_finished = False
    commands = (verify_all.SYNC_COMMAND, verify_all.CommandSpec(("worker",)))

    def fake_run(command: Sequence[str], **kwargs: object) -> object:
        nonlocal sync_finished
        if tuple(command) == ("uv", "sync"):
            sync_finished = True
        else:
            assert sync_finished
        return command_runner.subprocess.CompletedProcess(
            command, 0, stdout="", stderr=""
        )

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)
    assert verify_all.run_stage(commands, jobs=4) == 0


def test_barriers_flush_parallel_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running: set[tuple[str, ...]] = set()
    calls: list[tuple[str, ...]] = []

    def fake_run(command: Sequence[str], **kwargs: object) -> object:
        command_tuple = tuple(command)
        calls.append(command_tuple)
        if command_tuple == ("barrier",):
            assert running == set()
        else:
            running.add(command_tuple)
            running.remove(command_tuple)
        return command_runner.subprocess.CompletedProcess(
            command, 0, stdout="", stderr=""
        )

    commands = (
        verify_all.CommandSpec(("first",)),
        verify_all.CommandSpec(("second",)),
        verify_all.CommandSpec(("barrier",), barrier=True),
        verify_all.CommandSpec(("third",)),
    )
    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)
    assert verify_all.run_stage(commands, jobs=4) == 0
    assert set(calls[:2]) == {("first",), ("second",)}
    assert calls[2:] == [("barrier",), ("third",)]
