"""Subprocess tests for the bundled workspace initialization script."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "plugins/acd/skills/acd-install-doctor/scripts/init_workspace.py"
)

# The real install doctor emits a report well above the step stdout limit, so the
# stub keeps the same shape while exceeding that limit.
DOCTOR_STUB = """import json

print(json.dumps({"status": "ok", "authority": "stub", "padding": "x" * 8000}))
"""

PYPROJECT = """[project]
name = "acd-init-workspace-fixture"
version = "0.0.0"
requires-python = ">=3.12"
dependencies = []

[tool.uv]
package = false
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _init_repository(path: Path) -> None:
    _git(path, "init", "--initial-branch", "main")
    _git(path, "config", "user.email", "acd@example.test")
    _git(path, "config", "user.name", "ACD Test")


def _head_revision(path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout.strip()


def _origin_repository(path: Path) -> Path:
    scripts_dir = path / "plugins/acd/skills/acd-install-doctor/scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "install_doctor.py").write_text(DOCTOR_STUB, encoding="utf-8")
    (path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    _init_repository(path)
    _git(path, "add", ".")
    _git(path, "commit", "-m", "initial")
    return path


def _run_init(repo_url: str, revision: str, workspace: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-url",
            repo_url,
            "--revision",
            revision,
            "--workspace",
            str(workspace),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=1800,
    )
    document: dict[str, Any] = json.loads(result.stdout)
    return document


def _step(document: dict[str, Any], name: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = document["steps"]
    matches = [step for step in steps if step.get("name") == name]
    assert matches, f"step {name} is missing from {[s.get('name') for s in steps]}"
    return matches[0]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required")
def test_empty_git_workspace_is_initialized_and_large_doctor_report_parses(
    tmp_path: Path,
) -> None:
    origin = _origin_repository(tmp_path / "origin")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_repository(workspace)

    document = _run_init(origin.as_uri(), _head_revision(origin), workspace)

    assert document["ok"] is True, document
    assert document["fail_closed"] is False
    assert _step(document, "repository")["state"] == "initialized"
    plugin_load = _step(document, "plugin_load")
    assert plugin_load["status"] == "pass"
    assert plugin_load["report"]["status"] == "ok"
    assert (workspace / ".openhands/bootstrap-record.json").is_file()


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required")
def test_workspace_with_commits_and_no_origin_fails_closed(tmp_path: Path) -> None:
    origin = _origin_repository(tmp_path / "origin")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_repository(workspace)
    (workspace / "README.md").write_text("local\n", encoding="utf-8")
    _git(workspace, "add", "README.md")
    _git(workspace, "commit", "-m", "local")

    document = _run_init(origin.as_uri(), _head_revision(origin), workspace)

    assert document["ok"] is False
    assert document["fail_closed"] is True
    assert document["failed_step"] == "repository"
    assert "without an origin remote" in document["failure_reason"]
