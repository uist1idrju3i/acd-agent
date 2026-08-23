"""Tests for deterministic workspace initialization records."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[5]
SCRIPT = ROOT / "plugins/acd/skills/acd-install-doctor/scripts/init_workspace.py"


@pytest.fixture
def init_module() -> Any:
    spec = importlib.util.spec_from_file_location("init_workspace", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_record_hash_is_deterministic(init_module: Any) -> None:
    record = {
        "schema_version": "0.1",
        "workspace_path": "/work/acd",
        "repo_url": "https://example.test/acd.git",
        "requested_revision": "main",
        "resolved_revision": "a" * 40,
        "lock_digest": "sha256:" + "b" * 64,
        "pass_evidence": False,
        "record_class": "L3",
        "content_sha256": "unknown",
    }
    first = init_module._canonical_hash(record)
    second = init_module._canonical_hash(dict(record))
    assert first == second
    assert first.startswith("sha256:")


def test_init_refuses_dirty_or_foreign_directory(
    init_module: Any,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "foreign.txt").write_text("foreign", encoding="utf-8")
    report = init_module.initialize(
        repo_url="https://example.test/acd.git",
        revision="a" * 40,
        workspace=workspace,
    )
    assert report["ok"] is False
    assert report["fail_closed"] is True
    assert report["failed_step"] == "repository"
    assert report["steps"][0]["name"] == "workspace_dir"


def test_init_workspace_file_failure_propagates(
    init_module: Any,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.write_text("not a directory", encoding="utf-8")
    report = init_module.initialize(
        repo_url="https://example.test/acd.git",
        revision="a" * 40,
        workspace=workspace,
    )
    assert report == {
        "ok": False,
        "fail_closed": True,
        "failure_reason": f"workspace is not a directory: {workspace}",
        "failed_step": "workspace_dir",
        "steps": [],
    }


def test_command_result_reports_subprocess_failure(
    init_module: Any,
    tmp_path: Path,
) -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(command, 2, "", "failed")

    result = init_module._command_result(["uv", "sync"], cwd=tmp_path, runner=runner)
    assert result["status"] == "fail"
    assert result["returncode"] == 2


@pytest.mark.parametrize(
    ("failed_step", "failed_command"),
    [
        ("submodules", "submodule"),
        ("uv_sync", "sync"),
    ],
)
def test_init_stops_on_step_failure(
    init_module: Any,
    tmp_path: Path,
    failed_step: str,
    failed_command: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def clone_or_reuse(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        return {"status": "pass", "resolved_revision": "a" * 40, "state": "checkout"}

    init_module._clone_or_reuse = clone_or_reuse

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        if failed_command in command:
            return subprocess.CompletedProcess(command, 2, "", "injected failure")
        return subprocess.CompletedProcess(command, 0, "", "")

    report = init_module.initialize(
        repo_url="https://example.test/acd.git",
        revision="a" * 40,
        workspace=workspace,
        runner=runner,
    )
    assert report["ok"] is False
    assert report["fail_closed"] is True
    assert report["failed_step"] == failed_step


@pytest.mark.parametrize("failed_step", ["plugin_load", "doctor"])
def test_init_stops_on_doctor_boundary_failure(
    init_module: Any,
    tmp_path: Path,
    failed_step: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def clone_or_reuse(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        return {"status": "pass", "resolved_revision": "a" * 40, "state": "checkout"}

    init_module._clone_or_reuse = clone_or_reuse
    calls = 0

    def doctor(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        del args, kwargs
        calls += 1
        return {
            "status": "fail" if calls == 1 and failed_step == "plugin_load" else (
                "fail" if calls == 2 and failed_step == "doctor" else "pass"
            )
        }

    init_module._doctor = doctor

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(command, 0, "", "")

    report = init_module.initialize(
        repo_url="https://example.test/acd.git",
        revision="a" * 40,
        workspace=workspace,
        runner=runner,
    )
    assert report["ok"] is False
    assert report["failed_step"] == failed_step
