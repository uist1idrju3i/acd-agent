"""Source-tree provenance collection tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

from acd.core.source_tree import (
    SOURCE_TREE_PATHS,
    SourceProvenance,
    collect_source_provenance,
    source_provenance_env,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src" / "acd").mkdir(parents=True)
    (repo / "src" / "acd" / "module.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "src/acd/module.py")
    _git(repo, "commit", "-qm", "init")
    return repo


def test_clean_repo_reports_clean_revision(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    provenance = collect_source_provenance(repo)
    assert provenance.revision == head
    assert provenance.tree_state == "clean"
    assert provenance.dirty_digest is None
    assert provenance.changed_paths == ()
    assert source_provenance_env(provenance) == {
        "ACD_SOURCE_GIT_SHA": head,
        "ACD_SOURCE_TREE_STATE": "clean",
    }


def test_tracked_modification_is_dirty_with_deterministic_digest(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    target = repo / "src" / "acd" / "module.py"
    target.write_text("x = 2\n", encoding="utf-8")
    first = collect_source_provenance(repo)
    second = collect_source_provenance(repo)
    assert first.tree_state == "dirty"
    assert first.dirty_digest is not None and first.dirty_digest.startswith(
        "sha256:"
    )
    assert first.dirty_digest == second.dirty_digest
    assert first.changed_paths == ("src/acd/module.py",)
    env = source_provenance_env(first)
    assert env["ACD_SOURCE_TREE_STATE"] == "dirty"
    assert env["ACD_SOURCE_DIRTY_DIGEST"] == first.dirty_digest


def test_untracked_file_under_scripts_is_dirty(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "scratch.py").write_text("y = 1\n", encoding="utf-8")
    provenance = collect_source_provenance(repo)
    assert provenance.tree_state == "dirty"
    assert "scripts/scratch.py" in provenance.changed_paths


def test_changes_outside_source_tree_stay_clean(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "fixtures").mkdir()
    (repo / "fixtures" / "note.json").write_text("{}\n", encoding="utf-8")
    (repo / "out").mkdir()
    (repo / "out" / "log.txt").write_text("log\n", encoding="utf-8")
    provenance = collect_source_provenance(repo)
    assert provenance.tree_state == "clean"
    assert provenance.dirty_digest is None


def test_non_git_directory_is_unknown(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    provenance = collect_source_provenance(plain)
    assert provenance == SourceProvenance(
        revision="unknown",
        tree_state="unknown",
        dirty_digest=None,
        changed_paths=(),
    )


def test_git_failure_is_unknown(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    def failing(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git")

    provenance = collect_source_provenance(repo, run=failing)
    assert provenance.tree_state == "unknown"
    assert provenance.revision == "unknown"


def test_source_tree_paths_cover_expected_roots() -> None:
    assert "src" in SOURCE_TREE_PATHS
    assert "scripts" in SOURCE_TREE_PATHS
    assert "fixtures" not in SOURCE_TREE_PATHS
    assert "out" not in SOURCE_TREE_PATHS
