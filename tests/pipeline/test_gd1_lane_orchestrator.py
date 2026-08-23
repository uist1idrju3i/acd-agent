import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from scripts import run_gd1_lanes

from acd.core.command_runner import CommandResult, CommandSpec
from acd.core.runtime_records import TimingRecorder


def test_orchestrator_declares_firmware_after_barrier_and_before_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, Sequence[CommandSpec] | int] = {}

    def fake_run_stage(
        commands: Sequence[CommandSpec],
        *,
        jobs: int,
        timing: TimingRecorder,
        results: list[tuple[CommandSpec, CommandResult]],
    ) -> int:
        seen["commands"] = commands
        seen["jobs"] = jobs
        return 0

    monkeypatch.setattr(run_gd1_lanes, "run_stage", fake_run_stage)
    assert run_gd1_lanes.main(["--jobs", "2", "--out-root", str(tmp_path)]) == 0
    commands = seen["commands"]
    assert isinstance(commands, Sequence)
    assert commands[0].barrier is True
    assert any("run_gd1_pipeline.py" in item for item in commands[1].command)
    assert any("run_gd1_enclosure_pipeline.py" in item for item in commands[2].command)
    assert any("run_fw_pipeline.py" in item for item in commands[3].command)
    assert commands[4].command[2] == "pytest"
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary["ok"] is True
    timing = json.loads((tmp_path / "timing-record.json").read_text(encoding="utf-8"))
    assert timing["record_class"] == "L3"


def test_resume_enables_default_cache_and_reports_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, Sequence[CommandSpec]] = {}

    def fake_run_stage(
        commands: Sequence[CommandSpec],
        *,
        jobs: int,
        timing: TimingRecorder,
        results: list[tuple[CommandSpec, CommandResult]],
    ) -> int:
        seen["commands"] = commands
        results.append((commands[1], CommandResult(1, "", "broken")))
        return 1

    monkeypatch.setattr(run_gd1_lanes, "run_stage", fake_run_stage)
    assert (
        run_gd1_lanes.main(["--resume", "--out-root", str(tmp_path), "--jobs", "1"])
        == 1
    )
    board_command = seen["commands"][1].command
    assert "--cache-dir" in board_command
    assert str(tmp_path / ".stage-cache") in board_command
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary["ok"] is False
    assert summary["failures"][0]["returncode"] == 1
