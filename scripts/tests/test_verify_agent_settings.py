"""Tests for the agent settings, profile, and credential verification CLI."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
SETTINGS = ROOT / "plugins/acd/agent-settings.json"
FIXTURES = ROOT / "fixtures/settings"


def _invoke(
    *args: str, cwd: Path = ROOT
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_agent_settings.py"), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    return result, json.loads(result.stdout)


def test_cli_check_is_stable_and_cwd_independent(tmp_path: Path) -> None:
    before = hashlib.sha256(SETTINGS.read_bytes()).hexdigest()
    result, report = _invoke("--check")
    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["pass_evidence"] is False
    other, other_report = _invoke("--check", cwd=tmp_path)
    assert other.returncode == 0
    assert other_report == report
    assert hashlib.sha256(SETTINGS.read_bytes()).hexdigest() == before


def test_cli_tracked_valid_fixture_matches_tracked_settings() -> None:
    fixture = json.loads(
        (FIXTURES / "valid/agent-settings.json").read_text(encoding="utf-8")
    )
    tracked = json.loads(SETTINGS.read_text(encoding="utf-8"))
    assert fixture == tracked


def test_cli_hash_mismatch_returns_exit_two(tmp_path: Path) -> None:
    result, report = _invoke(
        "--check",
        "--settings",
        str(FIXTURES / "invalid/hash-mismatch.json"),
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert report["status"] == "unknown"
    assert report["manifest_hash"] == "unknown"


def test_cli_profile_drift_returns_exit_two(tmp_path: Path) -> None:
    result, report = _invoke(
        "--check",
        "--settings",
        str(FIXTURES / "invalid/profile-drift.json"),
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert report["status"] == "unknown"
    assert "drifted" in str(report["reason"])


def test_cli_credential_outside_allowlist_returns_exit_two(tmp_path: Path) -> None:
    result, report = _invoke(
        "--check",
        "--settings",
        str(FIXTURES / "invalid/credential-outside-allowlist.json"),
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert report["status"] == "unknown"
    assert "allowlist" in str(report["reason"])


def test_cli_unknown_configuration_returns_exit_two(tmp_path: Path) -> None:
    result, report = _invoke(
        "--check",
        "--settings",
        str(FIXTURES / "invalid/unknown-role.json"),
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert report["status"] == "unknown"


def test_cli_report_never_prints_credential_values(tmp_path: Path) -> None:
    env_settings = tmp_path / "agent-settings.json"
    env_settings.write_text(SETTINGS.read_text(encoding="utf-8"), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_agent_settings.py"),
            "--check",
            "--settings",
            str(env_settings),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        env={**os.environ, "LLM_API_KEY": "cli-secret-value"},
    )
    assert result.returncode == 0
    assert "cli-secret-value" not in result.stdout
    assert "cli-secret-value" not in result.stderr
