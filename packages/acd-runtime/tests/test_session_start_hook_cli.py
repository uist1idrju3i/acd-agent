"""End-to-end test of the SessionStart hook CLI contract (exit 0 allow / 2 deny)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_hook(event: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "acd_runtime.session_start_hook"],
        input=json.dumps(event),
        capture_output=True,
        text=True,
    )


def test_hook_allows_with_default_expectations(tmp_path: Path) -> None:
    result = run_hook({"event_type": "SessionStart", "working_dir": str(tmp_path)})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"] == "allow"


def test_hook_denies_on_unknown_required_tool(tmp_path: Path) -> None:
    (tmp_path / "acd-startup.json").write_text(
        json.dumps({"required_tools": ["kicad-cli"]}), encoding="utf-8"
    )
    result = run_hook({"event_type": "SessionStart", "working_dir": str(tmp_path)})
    assert result.returncode == 2
    assert "deny: tool:kicad-cli" in result.stderr


def test_hook_denies_on_missing_resolved_ref(tmp_path: Path) -> None:
    openhands_dir = tmp_path / ".openhands"
    openhands_dir.mkdir()
    (openhands_dir / ".installed.json").write_text(
        json.dumps(
            {
                "extensions": {
                    "acd": {
                        "name": "acd",
                        "source": "github:uist1idrju3i/acd-agent",
                        "requested_ref": "main",
                        "install_path": str(tmp_path / "ext"),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    result = run_hook({"event_type": "SessionStart", "working_dir": str(tmp_path)})
    assert result.returncode == 2
    assert "deny: extension:acd" in result.stderr


def test_hook_fails_closed_on_broken_expectations(tmp_path: Path) -> None:
    (tmp_path / "acd-startup.json").write_text("{not json", encoding="utf-8")
    result = run_hook({"event_type": "SessionStart", "working_dir": str(tmp_path)})
    assert result.returncode == 2
    assert "validation error" in result.stderr
