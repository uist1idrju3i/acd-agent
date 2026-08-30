"""Tests for the rationale validation CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_check_rationale_missing_file_returns_hook_blocking_exit_code(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_rationale.py",
            "--graph",
            "fixtures/golden-design-1/graph.json",
            "--rationale",
            str(tmp_path / "missing.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_check_rationale_if_present_is_not_applicable(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_rationale.py",
            "--graph",
            str(tmp_path / "missing-graph.json"),
            "--rationale",
            str(tmp_path / "missing.json"),
            "--if-present",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_check_rationale_if_present_accepts_missing_graph(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_rationale.py",
            "--graph",
            str(tmp_path / "missing-graph.json"),
            "--rationale",
            str(tmp_path / "missing-rationale.json"),
            "--if-present",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_check_rationale_warn_only_does_not_block(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_rationale.py",
            "--graph",
            "fixtures/golden-design-1/graph.json",
            "--rationale",
            str(tmp_path / "missing.json"),
            "--warn-only",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_check_rationale_requires_graph_and_rationale() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_rationale.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_check_rationale_reports_target_graph_and_revision(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_rationale.py",
            "--graph",
            "fixtures/golden-design-1/graph.json",
            "--rationale",
            "fixtures/golden-design-1/rationale.json",
            "--report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Rationale validation target: fixtures/golden-design-1/graph.json" in result.stdout
    assert "Rationale validation revision:" in result.stdout
    assert (
        "Rationale coverage: pass "
        "(diagnostic only; this is not an L1 gate pass)"
    ) in result.stdout
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["graph_path"] == "fixtures/golden-design-1/graph.json"
    assert report["revision"] == "r1"
