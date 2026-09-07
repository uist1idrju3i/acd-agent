"""Tests for the agent settings, profile, and credential verification CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scripts.tests.cli_runner import CliRunner
from scripts.verify_agent_settings import main

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/verify_agent_settings.py"
SETTINGS = ROOT / "plugins/acd/agent-settings.json"
FIXTURES = ROOT / "fixtures/settings"


def test_script_entrypoint_check_passes(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "pass"


def test_cli_check_is_stable_and_cwd_independent(
    tmp_path: Path, run_cli: CliRunner
) -> None:
    before = hashlib.sha256(SETTINGS.read_bytes()).hexdigest()
    result = run_cli(main, "--check", cwd=ROOT)
    report = result.json()
    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["pass_evidence"] is False
    other = run_cli(main, "--check", cwd=tmp_path)
    assert other.returncode == 0
    assert other.json() == report
    assert hashlib.sha256(SETTINGS.read_bytes()).hexdigest() == before


def test_cli_tracked_valid_fixture_matches_tracked_settings() -> None:
    fixture = json.loads(
        (FIXTURES / "valid/agent-settings.json").read_text(encoding="utf-8")
    )
    tracked = json.loads(SETTINGS.read_text(encoding="utf-8"))
    assert fixture == tracked


def test_cli_hash_mismatch_returns_exit_two(
    tmp_path: Path, run_cli: CliRunner
) -> None:
    result = run_cli(
        main,
        "--check",
        "--settings",
        str(FIXTURES / "invalid/hash-mismatch.json"),
        cwd=tmp_path,
    )
    report = result.json()
    assert result.returncode == 2
    assert report["status"] == "unknown"
    assert report["manifest_hash"] == "unknown"


def test_cli_profile_drift_returns_exit_two(
    tmp_path: Path, run_cli: CliRunner
) -> None:
    result = run_cli(
        main,
        "--check",
        "--settings",
        str(FIXTURES / "invalid/profile-drift.json"),
        cwd=tmp_path,
    )
    report = result.json()
    assert result.returncode == 2
    assert report["status"] == "unknown"
    assert "drifted" in str(report["reason"])


def test_cli_credential_outside_allowlist_returns_exit_two(
    tmp_path: Path, run_cli: CliRunner
) -> None:
    result = run_cli(
        main,
        "--check",
        "--settings",
        str(FIXTURES / "invalid/credential-outside-allowlist.json"),
        cwd=tmp_path,
    )
    report = result.json()
    assert result.returncode == 2
    assert report["status"] == "unknown"
    assert "allowlist" in str(report["reason"])


def test_cli_unknown_configuration_returns_exit_two(
    tmp_path: Path, run_cli: CliRunner
) -> None:
    result = run_cli(
        main,
        "--check",
        "--settings",
        str(FIXTURES / "invalid/unknown-role.json"),
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert result.json()["status"] == "unknown"


def test_cli_report_never_prints_credential_values(
    tmp_path: Path, run_cli: CliRunner
) -> None:
    env_settings = tmp_path / "agent-settings.json"
    env_settings.write_text(SETTINGS.read_text(encoding="utf-8"), encoding="utf-8")
    result = run_cli(
        main,
        "--check",
        "--settings",
        str(env_settings),
        cwd=ROOT,
        env={"LLM_API_KEY": "cli-secret-value"},
    )
    assert result.returncode == 0
    assert "cli-secret-value" not in result.stdout
    assert "cli-secret-value" not in result.stderr
