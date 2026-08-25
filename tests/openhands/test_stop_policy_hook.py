"""Tests for the stop policy hook's fail-closed stop permission."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path.cwd() / "plugins/acd/hooks/scripts/stop_policy.py"


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "fixtures/demo").mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    (root / "fixtures/demo/graph.json").write_text("{}\n", encoding="utf-8")
    return root


def _run(root: Path) -> tuple[int, dict[str, Any]]:
    completed = subprocess.run(
        ["python3", str(SCRIPT)],
        cwd=root,
        input="{}",
        capture_output=True,
        text=True,
        check=False,
        env={"OPENHANDS_PROJECT_DIR": str(root), "PATH": "/usr/bin:/bin"},
    )
    payload: dict[str, Any] = json.loads(completed.stdout) if completed.stdout else {}
    return completed.returncode, payload


def test_changed_design_input_without_evidence_is_denied(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    code, payload = _run(root)
    assert code == 2
    assert payload["decision"] == "deny"
    assert "newer valid evidence record" in payload["reason"]
    assert "commit" not in payload["reason"].lower()


def test_declared_fail_closed_stop_report_is_accepted(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    report = root / "out/stop-report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps(
            {
                "status": "failed",
                "failure_reason": "ERC reported 3 errors",
                "failed_stage": "board-pipeline",
                "evidence_absent": True,
            }
        ),
        encoding="utf-8",
    )
    code, payload = _run(root)
    assert code == 0
    assert payload["decision"] == "allow"
    assert "no pass authority" in payload["reason"]
    assert "board-pipeline" in payload["reason"]


@pytest.mark.parametrize(
    "report",
    [
        {"status": "passed", "failure_reason": "x", "failed_stage": "y", "evidence_absent": True},
        {"status": "failed", "failure_reason": "x", "failed_stage": "y"},
        {"status": "failed", "failure_reason": " ", "failed_stage": "y", "evidence_absent": True},
    ],
)
def test_incomplete_stop_report_does_not_permit_stopping(
    tmp_path: Path, report: dict[str, Any]
) -> None:
    root = _repository(tmp_path)
    path = root / "out/stop-report.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(report), encoding="utf-8")
    code, payload = _run(root)
    assert code == 2
    assert payload["decision"] == "deny"


def test_repeated_identical_denial_escalates_to_a_human_handoff(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    for _ in range(3):
        code, payload = _run(root)
        assert code == 2
        assert payload["decision"] == "deny"
    code, payload = _run(root)
    assert code == 0
    assert payload["decision"] == "allow"
    assert payload["escalation"] == "human_handoff"
    assert "remains failed" in payload["reason"]
