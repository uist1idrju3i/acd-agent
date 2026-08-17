"""Tests for SDK git-backed Evidence checks."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from openhands.sdk.git.exceptions import GitError

from acd.openhands.evidence_git import check_evidence_with_git

SOURCE = Path("fixtures/contracts/valid/evidence.json")


def _write_evidence(tmp_path: Path, *, revision: str = "r3") -> Path:
    value = json.loads(SOURCE.read_text(encoding="utf-8"))
    value["target_revision"] = revision
    value["envelope"]["target_revision"] = revision
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=test",
            "commit",
            "-qm",
            "test",
        ],
        cwd=repo,
        check=True,
    )
    return repo


def test_invalid_revision_fails_closed(tmp_path: Path) -> None:
    path = _write_evidence(tmp_path)
    repo = _init_repo(tmp_path)
    result = check_evidence_with_git(path, "ev-erc-r3-0001", "not-a-revision", repo)
    assert result["passed"] is False


def test_clean_design_input_and_valid_evidence_pass(tmp_path: Path) -> None:
    path = _write_evidence(tmp_path)
    repo = _init_repo(tmp_path)
    result = check_evidence_with_git(path, "ev-erc-r3-0001", "r3", repo)
    assert result["passed"] is True


def test_malformed_evidence_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    path.write_text("{", encoding="utf-8")
    result = check_evidence_with_git(path, "ev-erc-r3-0001", "r3", _init_repo(tmp_path))
    assert result["passed"] is False


def test_revision_mismatch_fails_closed(tmp_path: Path) -> None:
    path = _write_evidence(tmp_path, revision="r2")
    result = check_evidence_with_git(path, "ev-erc-r3-0001", "r3", _init_repo(tmp_path))
    assert result["passed"] is False


def test_missing_ref_fails_closed(tmp_path: Path) -> None:
    path = _write_evidence(tmp_path)
    result = check_evidence_with_git(
        path,
        "ev-erc-r3-0001",
        "r3",
        _init_repo(tmp_path),
        ref="does-not-exist",
    )
    assert result["passed"] is False


def test_sdk_git_error_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def raise_git_error(_: str | Path, *, ref: str | None) -> list[object]:
        raise GitError("git unavailable")

    monkeypatch.setattr("acd.openhands.evidence_git.get_git_changes", raise_git_error)
    result = check_evidence_with_git(
        _write_evidence(tmp_path),
        "ev-erc-r3-0001",
        "r3",
        tmp_path,
    )
    assert result["passed"] is False


def test_design_input_change_is_stale(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    profiles = repo / "profiles"
    profiles.mkdir()
    design_input = profiles / "test.json"
    design_input.write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=test",
            "commit",
            "-qm",
            "profile",
        ],
        cwd=repo,
        check=True,
    )
    design_input.write_text('{"changed": true}\n', encoding="utf-8")
    result = check_evidence_with_git(
        _write_evidence(tmp_path),
        "ev-erc-r3-0001",
        "r3",
        repo,
    )
    assert result["passed"] is False
    assert result["reason"] == "design input is stale"


def test_non_repository_fails_closed(tmp_path: Path) -> None:
    path = _write_evidence(tmp_path)
    result = check_evidence_with_git(path, "ev-erc-r3-0001", "r3", tmp_path)
    assert result["passed"] is False
