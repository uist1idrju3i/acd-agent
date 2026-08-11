"""Deterministic pass/fail gates over external tool results.

Gates only consume already-enveloped tool results; unknown or missing states
never pass. The AI proposes, these functions decide.
"""

from __future__ import annotations

from acd_adapter_kicad.cli import RuleCheckResult


class GateError(RuntimeError):
    """A deterministic gate rejected the current state (fail-closed)."""


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
