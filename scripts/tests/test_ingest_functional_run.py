"""End-to-end tests for deterministic functional-run ingestion."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def invoke(
    run_dir: str,
    output_dir: Path,
    report: Path,
) -> subprocess.CompletedProcess[str]:
    root = Path("fixtures/functional") / run_dir
    return subprocess.run(
        [
            sys.executable,
            "scripts/ingest_functional_run.py",
            "--run",
            str(root / "run.json"),
            "--logs-dir",
            str(root / "logs"),
            "--evidence-dir",
            str(output_dir),
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_ingest_functional_run_is_byte_stable(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_report = tmp_path / "first-report.json"
    second_report = tmp_path / "second-report.json"
    first = invoke("valid", first_dir, first_report)
    second = invoke("valid", second_dir, second_report)

    assert first.returncode == 0
    assert second.returncode == 0
    assert first_report.read_bytes() == second_report.read_bytes()
    for name in ("build", "flash", "led", "serial"):
        assert (first_dir / f"{name}.json").read_bytes() == (
            second_dir / f"{name}.json"
        ).read_bytes()
    assert len(list(first_dir.glob("*.json"))) == 4


def test_ingest_functional_run_reports_frequency_failure(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    result = invoke("invalid/led-frequency-out", tmp_path / "evidence", report)

    assert result.returncode == 2
    value = json.loads(report.read_text())
    assert value["status"] == "fail"
    assert value["led"]["status"] == "fail"
    assert "frequency" in value["led"]["reason"]


def test_ingest_functional_run_hash_mismatch_has_no_traceback(
    tmp_path: Path,
) -> None:
    report = tmp_path / "report.json"
    result = invoke("invalid/hash-mismatch", tmp_path / "evidence", report)

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    value = json.loads(report.read_text())
    assert value["status"] == "unknown"
    assert value["input_hash"] == "unknown"
