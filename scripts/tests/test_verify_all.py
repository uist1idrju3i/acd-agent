"""Tests for the canonical verification entrypoint."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from scripts import verify_all


def test_list_matches_stage_definitions(capsys: pytest.CaptureFixture[str]) -> None:
    assert verify_all.main(["--list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed == {
        stage: [
            {
                "command": list(spec.command),
                "requires_sync": spec.requires_sync,
                "requires_previous": spec.requires_previous,
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

    class Result:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def fake_run(command: Sequence[str], check: bool, **kwargs: object) -> Result:
        assert check is False
        assert kwargs == {"capture_output": True, "text": True}
        calls.append(tuple(command))
        return Result(7 if len(calls) == 2 else 0)

    monkeypatch.setattr(verify_all.subprocess, "run", fake_run)
    assert verify_all.run_stage((("first",), ("second",), ("third",))) == 7
    assert calls == [("first",), ("second",)]
    assert "FAIL (exit=7)" in capsys.readouterr().out


def test_success_output_is_identical_for_sequential_and_parallel_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    commands = (("first",), ("second",), ("third",))

    def fake_run(command: Sequence[str], **kwargs: object) -> object:
        return verify_all.subprocess.CompletedProcess(
            command, 0, stdout=f"{command[0]} output\n", stderr=""
        )

    monkeypatch.setattr(verify_all.subprocess, "run", fake_run)
    assert verify_all.run_stage(commands, jobs=1) == 0
    sequential = capsys.readouterr()
    assert verify_all.run_stage(commands, jobs=4) == 0
    parallel = capsys.readouterr()
    assert sequential.out == parallel.out
    assert sequential.err == parallel.err


def test_parallel_stage_reports_all_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    commands = (("sync",), ("bad-first",), ("ok",), ("bad-second",))

    def fake_run(command: Sequence[str], **kwargs: object) -> object:
        return verify_all.subprocess.CompletedProcess(
            command,
            9 if command[0].startswith("bad") else 0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(verify_all.subprocess, "run", fake_run)
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
        return verify_all.subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(verify_all.subprocess, "run", fake_run)
    assert verify_all.run_stage(commands, jobs=4) == 0
