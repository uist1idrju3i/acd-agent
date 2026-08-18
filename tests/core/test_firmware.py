"""Tests for deterministic firmware functional-run evaluation."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd.core.firmware import (
    FunctionalRunError,
    load_and_evaluate_functional_run,
)

ROOT = Path(__file__).parents[2]


def run_paths(kind: str) -> tuple[Path, Path]:
    root = ROOT / "fixtures/functional" / kind
    return root / "run.json", root / "logs"


def test_functional_run_builds_four_provisional_evidences() -> None:
    run_path, logs_dir = run_paths("valid")
    run, report, evidences = load_and_evaluate_functional_run(run_path, logs_dir)

    assert report.status == "pass"
    assert all(
        check.status == "pass"
        for check in (report.build, report.flash, report.led, report.serial)
    )
    assert set(evidences) == {"build", "flash", "led", "serial"}
    assert all(evidence.supports_pass(run.target_revision) for evidence in evidences.values())
    assert all(
        not evidence.supports_authoritative_pass(run.target_revision)
        for evidence in evidences.values()
    )
    assert all(evidence.instrument == run.instrument for evidence in evidences.values())
    assert all(evidence.envelope.tool_version == "0.1" for evidence in evidences.values())
    assert all(
        "esp_idf=v5.2.1" in evidence.envelope.measurement_conditions
        and "toolchain=xtensa-esp-elf-13.2.0"
        in evidence.envelope.measurement_conditions
        and "project_git_commit=0123456789abcdef0123456789abcdef01234567"
        in evidence.envelope.measurement_conditions
        for evidence in evidences.values()
    )
    assert report.led.measured_values["frequency_hz"] == pytest.approx(1.0)
    assert report.serial.measured_values["period_s"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("variant", "expected_status"),
    [
        ("hash-mismatch", "unknown"),
        ("build-artifact-missing", "unknown"),
        ("flash-verify-missing", "fail"),
        ("flash-wrong-chip", "fail"),
        ("led-time-reversed", "unknown"),
        ("led-frequency-out", "fail"),
        ("led-samples-insufficient", "fail"),
        ("serial-parse-failure", "unknown"),
        ("serial-temperature-out", "fail"),
        ("serial-period-out", "fail"),
        ("build-version-missing", "unknown"),
        ("build-version-mismatch", "fail"),
    ],
)
def test_functional_run_negative_fixtures(
    variant: str, expected_status: str
) -> None:
    run_path, logs_dir = run_paths(f"invalid/{variant}")
    _run, report, evidences = load_and_evaluate_functional_run(run_path, logs_dir)
    assert report.status == expected_status
    assert len(evidences) < 4


def test_build_version_reason_distinguishes_missing_and_mismatch() -> None:
    missing_run, missing_logs = run_paths("invalid/build-version-missing")
    _run, missing_report, _evidences = load_and_evaluate_functional_run(
        missing_run, missing_logs
    )
    mismatch_run, mismatch_logs = run_paths("invalid/build-version-mismatch")
    _run, mismatch_report, _evidences = load_and_evaluate_functional_run(
        mismatch_run, mismatch_logs
    )

    assert missing_report.build.status == "unknown"
    assert missing_report.build.reason == "build log ESP-IDF version line is missing"
    assert mismatch_report.build.status == "fail"
    assert "does not match" in (mismatch_report.build.reason or "")


def test_functional_run_invalid_contract_has_no_evaluation() -> None:
    run_path, logs_dir = run_paths("invalid/idf-unknown")
    with pytest.raises(FunctionalRunError):
        load_and_evaluate_functional_run(run_path, logs_dir)


def test_functional_run_is_deterministic() -> None:
    run_path, logs_dir = run_paths("valid")
    first = load_and_evaluate_functional_run(run_path, logs_dir)
    second = load_and_evaluate_functional_run(run_path, logs_dir)
    assert first[1].model_dump(mode="json") == second[1].model_dump(mode="json")
    assert {
        name: evidence.canonical_hash() for name, evidence in first[2].items()
    } == {name: evidence.canonical_hash() for name, evidence in second[2].items()}
