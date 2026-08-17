"""Tests for SDK git-backed Evidence checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openhands.sdk.git.models import GitChange, GitChangeStatus

from acd_tools.evidence_git import check_evidence_with_git

SOURCE = Path("fixtures/contracts/valid/evidence.json")


def _write_evidence(tmp_path: Path, *, revision: str = "r3") -> Path:
    value = json.loads(SOURCE.read_text(encoding="utf-8"))
    value["target_revision"] = revision
    value["envelope"]["target_revision"] = revision
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_invalid_ref_fails_closed(tmp_path: Path) -> None:
    path = _write_evidence(tmp_path)
    result = check_evidence_with_git(path, "ev-erc-r3-0001", "not-a-revision", Path.cwd())
    assert result["passed"] is False


def test_clean_design_input_and_valid_evidence_pass(tmp_path: Path) -> None:
    path = _write_evidence(tmp_path)
    result = check_evidence_with_git(path, "ev-erc-r3-0001", "r3", Path.cwd())
    assert result["passed"] is True


def test_malformed_evidence_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    path.write_text("{", encoding="utf-8")
    result = check_evidence_with_git(path, "ev-erc-r3-0001", "r3", Path.cwd())
    assert result["passed"] is False


def test_revision_mismatch_fails_closed(tmp_path: Path) -> None:
    path = _write_evidence(tmp_path, revision="r2")
    result = check_evidence_with_git(path, "ev-erc-r3-0001", "r3", Path.cwd())
    assert result["passed"] is False


def test_design_input_change_is_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from openhands.sdk.workspace import LocalWorkspace

    def changed_inputs(
        _: str | Path, *, ref: str | None
    ) -> list[GitChange]:
        return [
            GitChange(status=GitChangeStatus.UPDATED, path=Path("profiles/test.json"))
        ]

    def read_diff(_: LocalWorkspace, __: str | Path) -> None:
        return None

    monkeypatch.setattr("acd_tools.evidence_git.get_git_changes", changed_inputs)
    monkeypatch.setattr(LocalWorkspace, "git_diff", read_diff)
    path = _write_evidence(tmp_path)
    result = check_evidence_with_git(path, "ev-erc-r3-0001", "r3", Path.cwd())
    assert result["passed"] is False
    assert result["reason"] == "design input is stale"


def test_non_repository_fails_closed(tmp_path: Path) -> None:
    path = _write_evidence(tmp_path)
    result = check_evidence_with_git(path, "ev-erc-r3-0001", "r3", tmp_path)
    assert result["passed"] is False
