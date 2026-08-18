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
        stage: [list(command) for command in commands]
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

    def fake_run(command: Sequence[str], check: bool) -> Result:
        assert check is False
        calls.append(tuple(command))
        return Result(7 if len(calls) == 2 else 0)

    monkeypatch.setattr(verify_all.subprocess, "run", fake_run)
    assert verify_all.run_stage((("first",), ("second",), ("third",))) == 7
    assert calls == [("first",), ("second",)]
    assert "FAIL (exit=7)" in capsys.readouterr().out
