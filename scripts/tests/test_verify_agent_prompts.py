"""Tests for the role prompt manifest verification CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scripts.tests.cli_runner import CliRunner
from scripts.verify_agent_prompts import main

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/verify_agent_prompts.py"
AGENTS = ROOT / "plugins/acd/agents"
MANIFEST = AGENTS / "prompt-manifest.json"


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


def test_cli_check_is_stable_and_does_not_write_assets(
    tmp_path: Path, run_cli: CliRunner
) -> None:
    tracked = [*sorted(AGENTS.glob("acd-*.md")), MANIFEST]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}
    result = run_cli(main, "--check", cwd=ROOT)
    report = result.json()
    assert result.returncode == 0
    assert report["status"] == "pass"
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked} == before
    other_cwd = run_cli(main, "--check", cwd=tmp_path)
    assert other_cwd.returncode == 0
    assert other_cwd.json() == report


def test_cli_drift_returns_exit_two_without_traceback(
    tmp_path: Path, run_cli: CliRunner
) -> None:
    agent_dir = tmp_path / "agents"
    agent_dir.mkdir()
    for source in AGENTS.glob("acd-*.md"):
        (agent_dir / source.name).write_bytes(source.read_bytes())
    changed = agent_dir / "acd-electrical.md"
    changed.write_text(changed.read_text(encoding="utf-8") + "x", encoding="utf-8")
    manifest = tmp_path / "prompt-manifest.json"
    written = run_cli(
        main,
        "--write",
        "--agent-dir",
        str(agent_dir),
        "--manifest",
        str(manifest),
        "--root",
        str(tmp_path),
        cwd=ROOT,
    )
    assert written.returncode == 0
    changed.write_text(changed.read_text(encoding="utf-8") + "y", encoding="utf-8")
    result = run_cli(
        main,
        "--check",
        "--agent-dir",
        str(agent_dir),
        "--manifest",
        str(manifest),
        "--root",
        str(tmp_path),
        cwd=ROOT,
    )
    report = result.json()
    assert result.returncode == 2
    assert report["status"] == "fail"
    assert report["drifted_roles"] == ["acd-electrical"]
    assert report["unregistered_roles"] == []
    assert report["missing_roles"] == []


def test_cli_malformed_or_missing_inputs_return_report_without_traceback(
    tmp_path: Path, run_cli: CliRunner
) -> None:
    result = run_cli(
        main,
        "--check",
        "--agent-dir",
        str(tmp_path / "missing-agents"),
        "--manifest",
        str(tmp_path / "missing-manifest.json"),
        cwd=ROOT,
    )
    assert result.returncode == 2
    assert result.json()["status"] == "unknown"

    manifest = tmp_path / "malformed.json"
    manifest.write_text("{not-json", encoding="utf-8")
    result = run_cli(
        main,
        "--check",
        "--agent-dir",
        str(AGENTS),
        "--manifest",
        str(manifest),
        cwd=ROOT,
    )
    assert result.returncode == 2
    assert result.json()["status"] == "unknown"
