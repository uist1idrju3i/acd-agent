"""Tests for the role prompt manifest verification CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
AGENTS = ROOT / "plugins/acd/agents"
MANIFEST = AGENTS / "prompt-manifest.json"


def _invoke(
    *args: str, cwd: Path = ROOT
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    command = [sys.executable, str(ROOT / "scripts/verify_agent_prompts.py"), *args]
    result = subprocess.run(
        command, capture_output=True, text=True, check=False, cwd=cwd
    )
    return result, json.loads(result.stdout)


def test_cli_check_is_stable_and_does_not_write_assets(tmp_path: Path) -> None:
    tracked = [*sorted(AGENTS.glob("acd-*.md")), MANIFEST]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}
    result, report = _invoke("--check")
    assert result.returncode == 0
    assert report["status"] == "pass"
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked} == before
    other_cwd, other_report = _invoke("--check", cwd=tmp_path)
    assert other_cwd.returncode == 0
    assert other_report == report


def test_cli_drift_returns_exit_two_without_traceback(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents"
    agent_dir.mkdir()
    for source in AGENTS.glob("acd-*.md"):
        (agent_dir / source.name).write_bytes(source.read_bytes())
    changed = agent_dir / "acd-electrical.md"
    changed.write_text(changed.read_text(encoding="utf-8") + "x", encoding="utf-8")
    manifest = tmp_path / "prompt-manifest.json"
    write_command = [
        sys.executable,
        "scripts/verify_agent_prompts.py",
        "--write",
        "--agent-dir",
        str(agent_dir),
        "--manifest",
        str(manifest),
        "--root",
        str(tmp_path),
    ]
    written = subprocess.run(write_command, capture_output=True, text=True, check=False)
    assert written.returncode == 0
    changed.write_text(changed.read_text(encoding="utf-8") + "y", encoding="utf-8")
    result, report = _invoke(
        "--check",
        "--agent-dir",
        str(agent_dir),
        "--manifest",
        str(manifest),
        "--root",
        str(tmp_path),
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert report["status"] == "fail"
    assert report["drifted_roles"] == ["acd-electrical"]
    assert report["unregistered_roles"] == []
    assert report["missing_roles"] == []


def test_cli_malformed_or_missing_inputs_return_report_without_traceback(
    tmp_path: Path,
) -> None:
    result, report = _invoke(
        "--check",
        "--agent-dir",
        str(tmp_path / "missing-agents"),
        "--manifest",
        str(tmp_path / "missing-manifest.json"),
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert report["status"] == "unknown"

    manifest = tmp_path / "malformed.json"
    manifest.write_text("{not-json", encoding="utf-8")
    result, report = _invoke(
        "--check",
        "--agent-dir",
        str(AGENTS),
        "--manifest",
        str(manifest),
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert report["status"] == "unknown"
