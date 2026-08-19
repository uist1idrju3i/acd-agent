"""Deterministic pass/fail gates over external tool results.

Gates only consume already-enveloped tool results; unknown or missing states
never pass. The AI proposes, these functions decide.
"""

from __future__ import annotations

from pathlib import Path

from acd.adapters.kicad.cli import RuleCheckResult
from acd.core.process import sha256_paths


class GateError(RuntimeError):
    """A deterministic gate rejected the current state (fail-closed)."""


def assert_rule_check_input_matches(
    name: str, result: RuleCheckResult, expected_input_paths: list[Path]
) -> None:
    """Require a rule-check result to correspond to the current input bytes."""
    for input_path in expected_input_paths:
        if not input_path.is_file():
            raise GateError(f"{name}: gate not executed (input file missing: {input_path})")
    envelope = result.run.envelope
    if envelope.input_hash == "unknown":
        raise GateError(f"{name}: gate not executed (input hash is unknown)")
    measured_hash = sha256_paths(expected_input_paths)
    if envelope.input_hash != measured_hash:
        raise GateError(f"{name}: gate not executed (input hash mismatch)")


def assert_rule_check_passed(
    name: str, result: RuleCheckResult, *, require_connected: bool
) -> None:
    errors = [v for v in result.violations if v.get("severity") == "error"]
    if errors:
        details = "; ".join(str(v.get("description", v.get("type"))) for v in errors[:5])
        raise GateError(f"{name}: {len(errors)} error violations: {details}")
    if require_connected and result.unconnected_items:
        raise GateError(f"{name}: {len(result.unconnected_items)} unconnected items")


def assert_converged(convergence_state: str) -> None:
    if convergence_state != "converged":
        raise GateError(f"router convergence_state={convergence_state!r} (fail-closed)")
