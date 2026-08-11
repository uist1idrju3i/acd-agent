"""Deterministic gate tests: ERC/DRC violations and router convergence stop."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd_adapter_kicad.cli import RuleCheckResult
from acd_adapter_kicad.gates import GateError, assert_converged, assert_rule_check_passed
from acd_core.process import ToolRun
from acd_schema import ToolEnvelope


def _result(
    violations: tuple[dict[str, object], ...] = (),
    unconnected: tuple[dict[str, object], ...] = (),
) -> RuleCheckResult:
    zero_hash = "sha256:" + "0" * 64
    envelope = ToolEnvelope.model_validate(
        {
            "tool_name": "kicad-cli",
            "tool_version": "10.0.5",
            "format_version": "10.0.5",
            "config_hash": zero_hash,
            "input_hash": zero_hash,
            "output_hash": zero_hash,
            "execution_env": "test",
            "measurement_conditions": "test",
            "convergence_state": "not_applicable",
            "target_revision": "r1",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "exit_code": 0,
        }
    )
    run = ToolRun(envelope=envelope, stdout="", stderr="", skipped=False)
    return RuleCheckResult(
        run=run,
        report_path=Path("report.json"),
        violations=violations,
        unconnected_items=unconnected,
    )


def test_gate_passes_clean_result() -> None:
    assert_rule_check_passed("DRC", _result(), require_connected=True)


def test_gate_stops_on_error_violation() -> None:
    result = _result(violations=({"severity": "error", "description": "short"},))
    with pytest.raises(GateError, match="error violations"):
        assert_rule_check_passed("ERC", result, require_connected=False)


def test_gate_ignores_warnings() -> None:
    result = _result(violations=({"severity": "warning", "description": "silk"},))
    assert_rule_check_passed("DRC", result, require_connected=True)


def test_gate_stops_on_unconnected_items() -> None:
    result = _result(unconnected=({"description": "missing"},))
    with pytest.raises(GateError, match="unconnected"):
        assert_rule_check_passed("DRC", result, require_connected=True)


def test_convergence_gate_fails_closed() -> None:
    assert_converged("converged")
    for state in ("not_converged", "unknown", "not_applicable"):
        with pytest.raises(GateError):
            assert_converged(state)
