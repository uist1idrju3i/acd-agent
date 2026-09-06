"""Tests for the machine-readable record of the ambient tool availability check."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import verify_acd_tool_registration as checker


def _command(tmp_path: Path, tools: list[str]) -> Path:
    body = ["---", "description: test", "allowed-tools:"]
    body.extend(f"  - {name}" for name in tools)
    body.extend(["---", "", "# test"])
    path = tmp_path / "command.md"
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def test_command_check_saves_missing_tools_as_l3_json(tmp_path: Path) -> None:
    command = _command(tmp_path, ["acd_run_design_loop"])
    record = tmp_path / "workspace" / "tool-availability.json"
    code = checker.main(
        [
            "--command",
            str(command),
            "--available",
            "terminal",
            "--record",
            str(record),
        ]
    )
    assert code == 2
    body = json.loads(record.read_text(encoding="utf-8"))
    assert body["status"] == "fail"
    assert body["missing_tools"] == ["acd_run_design_loop"]
    assert body["available_tools"] == ["terminal"]
    assert body["record_class"] == "L3"
    assert body["pass_evidence"] is False
    assert body["fallbacks"][0]["tool_name"] == "acd_run_design_loop"


def test_command_check_saves_undetermined_outcome_as_unknown(tmp_path: Path) -> None:
    command = tmp_path / "broken.md"
    command.write_text("---\nnot: closed\n", encoding="utf-8")
    record = tmp_path / "record.json"
    code = checker.main(
        ["--command", str(command), "--available", "terminal", "--record", str(record)]
    )
    assert code == 2
    body = json.loads(record.read_text(encoding="utf-8"))
    assert body["status"] == "unknown"
    assert body["record_class"] == "L3"
    assert body["pass_evidence"] is False
    assert body["reason"]


def test_default_record_path_is_under_workspace_out() -> None:
    path = checker.availability_record_path(Path("plugins/acd/commands/x.md"), None)
    assert path == checker.REPO_ROOT / "out" / "tool-availability" / "x.json"
