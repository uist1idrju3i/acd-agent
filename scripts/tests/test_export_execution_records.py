"""Tests for the sanitized execution-record export entry point."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import export_execution_records


def _write(path: Path, body: dict[str, object]) -> Path:
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_export_keeps_only_the_publishable_minimum(tmp_path: Path) -> None:
    _write(
        tmp_path / "run.json",
        {
            "run_id": "run-1",
            "status": "pass",
            "serial_capture_route": "/dev/ttyUSB0",
            "host": "workstation.local",
        },
    )
    out = tmp_path / "export" / "records.json"

    assert export_execution_records.main([str(tmp_path), "--out", str(out)]) == 0

    exported = json.loads(out.read_text(encoding="utf-8"))
    assert exported == [{"run_id": "run-1", "status": "pass"}]


def test_leaky_record_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("acd.core.execution_export._REDACTIONS", ())
    record = _write(tmp_path / "run.json", {"status": "https://runner.internal:3000"})
    out = tmp_path / "records.json"

    assert export_execution_records.main([str(record), "--out", str(out)]) == 1
    assert "redaction is incomplete" in capsys.readouterr().err
    assert not out.exists()


def test_unreadable_record_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")

    assert (
        export_execution_records.main(
            [str(broken), "--out", str(tmp_path / "records.json")]
        )
        == 2
    )
    assert "could not be read" in capsys.readouterr().err
