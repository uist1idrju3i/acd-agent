"""Tests for the display-only event view verification CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "fixtures/context"
EVENT_VIEW = FIXTURES / "valid/event-view.json"


def _invoke(
    *args: str, cwd: Path = ROOT
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_context_view.py"), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    return result, json.loads(result.stdout)


def test_cli_check_replays_the_tracked_view(tmp_path: Path) -> None:
    before = hashlib.sha256(EVENT_VIEW.read_bytes()).hexdigest()
    result, report = _invoke("--check")
    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["pass_evidence"] is False
    other, other_report = _invoke("--check", cwd=tmp_path)
    assert other.returncode == 0
    assert other_report == report
    assert hashlib.sha256(EVENT_VIEW.read_bytes()).hexdigest() == before


def test_cli_hash_mismatch_returns_exit_two(tmp_path: Path) -> None:
    result, report = _invoke(
        "--check",
        "--event-view",
        str(FIXTURES / "invalid/event-view-hash-mismatch.json"),
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert report["status"] == "unknown"
    assert report["canonical_hash"] == "unknown"


def test_cli_detects_a_view_that_left_its_event_log(tmp_path: Path) -> None:
    truncated = tmp_path / "event-log.json"
    events = json.loads(
        (FIXTURES / "valid/event-log.json").read_text(encoding="utf-8")
    )
    truncated.write_text(json.dumps(events[:1]), encoding="utf-8")
    result, report = _invoke("--check", "--event-log", str(truncated), cwd=tmp_path)
    assert result.returncode == 2
    assert report["status"] == "unknown"
    assert "EventLog" in str(report["reason"])


def test_cli_unknown_event_log_returns_exit_two(tmp_path: Path) -> None:
    result, report = _invoke(
        "--check", "--event-log", str(tmp_path / "absent.json"), cwd=tmp_path
    )
    assert result.returncode == 2
    assert report["status"] == "unknown"


def test_cli_write_reproduces_the_tracked_view(tmp_path: Path) -> None:
    written = tmp_path / "event-view.json"
    result, report = _invoke("--write", "--event-view", str(written), cwd=tmp_path)
    assert result.returncode == 0
    assert report["status"] == "pass"
    assert written.read_text(encoding="utf-8") == EVENT_VIEW.read_text(
        encoding="utf-8"
    )
