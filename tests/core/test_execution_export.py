"""Tests for the sanitized execution-record export."""

from __future__ import annotations

import pytest

from acd.core.execution_export import (
    REDACTED,
    ExecutionExportError,
    export_execution_record,
    find_leaks,
    redact_text,
)


def test_only_allowlisted_fields_survive() -> None:
    exported = export_execution_record(
        {
            "run_id": "run-1",
            "status": "pass",
            "serial_capture_route": "/dev/ttyUSB0 via workstation.local",
            "operator": "yamashiro",
            "logs": [{"log_type": "serial", "content_hash": "sha256:" + "a" * 64}],
        }
    )

    assert exported == {
        "run_id": "run-1",
        "status": "pass",
        "logs": [{"log_type": "serial", "content_hash": "sha256:" + "a" * 64}],
    }


def test_publishable_versions_are_not_redacted() -> None:
    exported = export_execution_record(
        {
            "esp_idf_version": "v5.2.1",
            "toolchain_version": "riscv32-esp-elf 13.2.0",
            "image_digest": "sha256:" + "b" * 64,
        }
    )

    assert exported["esp_idf_version"] == "v5.2.1"
    assert exported["toolchain_version"] == "riscv32-esp-elf 13.2.0"
    assert exported["image_digest"] == "sha256:" + "b" * 64


@pytest.mark.parametrize(
    "value",
    [
        "http://192.168.0.5:8000/api",
        "/home/ubuntu/repos/acd-agent/out",
        "operator@lab.example.com",
        "runner.internal:3000",
    ],
)
def test_secrets_are_redacted_by_default(value: str) -> None:
    redacted = redact_text(value)

    assert REDACTED in redacted
    assert find_leaks(redacted) == ()


def test_incomplete_redaction_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("acd.core.execution_export._REDACTIONS", ())

    with pytest.raises(ExecutionExportError, match="redaction is incomplete"):
        export_execution_record({"status": "served from https://runner.internal:3000"})


def test_leak_finder_reports_the_location() -> None:
    findings = find_leaks({"stages": [{"stage": "gate at 10.0.0.1"}]})

    assert findings == ("stages[0].stage: ip_address",)
