"""Deterministic gate tests: ERC/DRC violations and router convergence stop."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd.adapters.kicad.cli import RuleCheckResult
from acd.adapters.kicad.gates import (
    GateError,
    assert_converged,
    assert_rule_check_input_matches,
    assert_rule_check_passed,
)
from acd.core.process import ToolRun, sha256_paths
from acd.schema import ToolEnvelope


def _result(
    violations: tuple[dict[str, object], ...] = (),
    unconnected: tuple[dict[str, object], ...] = (),
    *,
    input_hash: str | None = None,
) -> RuleCheckResult:
    zero_hash = "sha256:" + "0" * 64
    envelope = ToolEnvelope.model_validate(
        {
            "tool_name": "kicad-cli",
            "tool_version": "10.0.5",
            "format_version": "10.0.5",
            "config_hash": zero_hash,
            "input_hash": input_hash or zero_hash,
            "output_hash": zero_hash,
            "execution_env": "test",
            "execution_context": "host",
            "container_image_digest": None,
            "measurement_conditions": "test",
            "convergence_state": "not_applicable",
            "target_revision": "r1",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "exit_code": 0,
        }
    )
    run = ToolRun(envelope=envelope, stdout="", stderr="")
    return RuleCheckResult(
        run=run,
        report_path=Path("report.json"),
        violations=violations,
        unconnected_items=unconnected,
    )


def test_gate_passes_clean_result() -> None:
    assert_rule_check_passed("DRC", _result(), require_connected=True)


def test_drc_input_correspondence_passes_for_current_board(tmp_path: Path) -> None:
    board = tmp_path / "board.kicad_pcb"
    board.write_bytes(b"board")
    result = _result(input_hash=sha256_paths([board]))
    assert_rule_check_input_matches("DRC", result, [board])


def test_drc_input_correspondence_rejects_unknown_hash(tmp_path: Path) -> None:
    board = tmp_path / "board.kicad_pcb"
    board.write_bytes(b"board")
    result = _result(input_hash="unknown")
    with pytest.raises(GateError, match="gate not executed"):
        assert_rule_check_input_matches("DRC", result, [board])


def test_drc_input_correspondence_rejects_hash_mismatch(tmp_path: Path) -> None:
    board = tmp_path / "board.kicad_pcb"
    board.write_bytes(b"board")
    result = _result()
    with pytest.raises(GateError, match="gate not executed"):
        assert_rule_check_input_matches("DRC", result, [board])


def test_drc_input_correspondence_rejects_different_input_filename(tmp_path: Path) -> None:
    judged_board = tmp_path / "judged.kicad_pcb"
    judged_board.write_bytes(b"board")
    board = tmp_path / "board.kicad_pcb"
    board.write_bytes(b"board")
    result = _result(input_hash=sha256_paths([judged_board]))
    with pytest.raises(GateError, match="gate not executed"):
        assert_rule_check_input_matches("DRC", result, [board])


def test_drc_input_correspondence_rejects_missing_board(tmp_path: Path) -> None:
    board = tmp_path / "missing.kicad_pcb"
    result = _result()
    with pytest.raises(GateError, match="gate not executed"):
        assert_rule_check_input_matches("DRC", result, [board])


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
