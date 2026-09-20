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
    monkeypatch.setattr("acd.core.runtime.execution_export._REDACTIONS", ())
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


_LANE_LOG = """=== acd-lane-log 0.1 ===
image: acd-server@sha256:{digest}
revision: {revision}
command: docker run --workdir /home/user/ws true
started_at: 2026-01-01T00:00:00Z
=== output ===
pulled from ghcr.io cache
done
=== result ===
exit_code: 0
image_digest: sha256:{digest}
execution_context: container
failure_kind: none
finished_at: 2026-01-01T00:05:00Z
"""


def _lane_log(**kwargs: object) -> str:
    return _LANE_LOG.format(
        digest="d" * 64, revision="b" * 40, **kwargs
    )


def test_lane_log_is_exported_with_redaction(tmp_path: Path) -> None:
    (tmp_path / "lane.log").write_text(_lane_log(), encoding="utf-8")
    out = tmp_path / "records.json"

    assert export_execution_records.main([str(tmp_path / "lane.log"), "--out", str(out)]) == 0

    exported = json.loads(out.read_text(encoding="utf-8"))
    (record,) = exported
    assert record["log_type"] == "lane_log"
    assert record["command"] == "docker run --workdir /[redacted]/ws true"
    assert "ghcr.io" not in json.dumps(exported)
    assert "/home/user" not in json.dumps(exported)
    assert record["failure_kind"] == "none"
    assert "acd-server@" not in json.dumps(exported)


def test_interrupted_lane_log_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "lane.log").write_text(
        "=== acd-lane-log 0.1 ===\nimage: i\nrevision: r\ncommand: c\n"
        "started_at: s\n=== output ===\npartial\n",
        encoding="utf-8",
    )
    out = tmp_path / "records.json"

    assert export_execution_records.main([str(tmp_path), "--out", str(out)]) == 2
    assert not out.exists()


def test_mixed_json_and_log_directory_is_sorted_by_name(tmp_path: Path) -> None:
    _write(
        tmp_path / "b.json",
        {"run_id": "json-b", "status": "pass"},
    )
    (tmp_path / "a.log").write_text(_lane_log(), encoding="utf-8")
    _write(tmp_path / "c.json", {"run_id": "json-c", "status": "pass"})
    out = tmp_path / "records.json"

    assert export_execution_records.main([str(tmp_path), "--out", str(out)]) == 0

    exported = json.loads(out.read_text(encoding="utf-8"))
    assert [item.get("log_type", item.get("run_id")) for item in exported] == [
        "lane_log",
        "json-b",
        "json-c",
    ]
