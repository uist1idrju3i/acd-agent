"""Bounded virtual run termination reporting tests."""

from __future__ import annotations

from pathlib import Path

from fw_qemu import INTENDED_TIMEOUT_EXIT_CODE, VirtualRunResult
from fw_run import CommandRecord


def _result(exit_code: int, run_seconds: int = 15) -> VirtualRunResult:
    return VirtualRunResult(
        record=CommandRecord(
            command=["timeout", str(run_seconds), "qemu-system-riscv32"],
            tool_version="10.1.0",
            exit_code=exit_code,
            input_hash="sha256:" + "0" * 64,
            output_hash="sha256:" + "1" * 64,
        ),
        log_path=Path("qemu-serial.log"),
        run_seconds=run_seconds,
    )


def test_intended_timeout_is_reported_as_normal_completion() -> None:
    result = _result(INTENDED_TIMEOUT_EXIT_CODE)

    assert result.stopped_by_intended_timeout is True
    condition = result.termination_condition()
    assert "intended 15s bound" in condition
    assert f"exit code {INTENDED_TIMEOUT_EXIT_CODE}" in condition
    assert "normal completion condition of the bounded virtual run" in condition
    assert "not a failure" in condition


def test_self_exit_is_reported_without_the_timeout_wording() -> None:
    result = _result(0)

    assert result.stopped_by_intended_timeout is False
    condition = result.termination_condition()
    assert condition == "exited on its own before the 15s bound (exit code 0)"


def test_termination_condition_uses_the_declared_bound() -> None:
    condition = _result(INTENDED_TIMEOUT_EXIT_CODE, run_seconds=30).termination_condition()

    assert "intended 30s bound" in condition
