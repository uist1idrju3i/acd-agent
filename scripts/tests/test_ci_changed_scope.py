"""Tests for the CI changed-scope classifier."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from scripts.ci_changed_scope import main


def _run_with(output: str) -> Callable[[list[str]], str]:
    def run(command: list[str]) -> str:
        assert command[:3] == ["git", "diff", "--name-only"]
        return output

    return run


def _set_revisions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("BASE_SHA", "base")
    monkeypatch.setenv("HEAD_SHA", "head")
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    return output


def test_markdown_only_change_skips_code_jobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = _set_revisions(monkeypatch, tmp_path)
    assert main(run=_run_with("README.md\ndocs/operations.md\n")) == 0
    assert output.read_text(encoding="utf-8") == "code=false\n"


def test_mixed_change_runs_code_jobs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = _set_revisions(monkeypatch, tmp_path)
    assert main(run=_run_with("docs/operations.md\nsrc/acd/core/model.py\n")) == 0
    assert output.read_text(encoding="utf-8") == "code=true\n"


def test_non_markdown_docs_change_runs_code_jobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = _set_revisions(monkeypatch, tmp_path)
    assert main(run=_run_with("docs/openhands-sdk-capabilities.json\n")) == 0
    assert output.read_text(encoding="utf-8") == "code=true\n"


def test_git_failure_runs_code_jobs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = _set_revisions(monkeypatch, tmp_path)

    def failing_run(_command: list[str]) -> str:
        raise RuntimeError("git failed")

    assert main(run=failing_run) == 0
    assert output.read_text(encoding="utf-8") == "code=true\n"


def test_empty_diff_runs_code_jobs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = _set_revisions(monkeypatch, tmp_path)
    assert main(run=_run_with("")) == 0
    assert output.read_text(encoding="utf-8") == "code=true\n"


def test_missing_revision_runs_code_jobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = _set_revisions(monkeypatch, tmp_path)
    monkeypatch.delenv("BASE_SHA")
    assert main(run=_run_with("README.md\n")) == 0
    assert output.read_text(encoding="utf-8") == "code=true\n"
