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
    assert report.led.measured_values["frequency_hz"] == pytest.approx(1.0)
    assert report.serial.measured_values["period_s"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("variant", "expected_status"),
    [
        ("hash-mismatch", "unknown"),
        ("build-artifact-missing", "unknown"),
        ("flash-verify-missing", "fail"),
        ("flash-wrong-chip", "fail"),
        ("led-time-reversed", "fail"),
        ("led-frequency-out", "fail"),
        ("led-samples-insufficient", "fail"),
        ("serial-parse-failure", "fail"),
        ("serial-temperature-out", "fail"),
        ("serial-period-out", "fail"),
    ],
)
def test_functional_run_negative_fixtures(
    variant: str, expected_status: str
) -> None:
    run_path, logs_dir = run_paths(f"invalid/{variant}")
    _run, report, evidences = load_and_evaluate_functional_run(run_path, logs_dir)
    assert report.status == expected_status
    assert evidences == {} if expected_status == "unknown" else len(evidences) < 4


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
