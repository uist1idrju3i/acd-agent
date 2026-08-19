"""Deterministic pass/fail gates over external tool results.

Gates only consume already-enveloped tool results; unknown or missing states
never pass. The AI proposes, these functions decide.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from acd.adapters.kicad.cli import RuleCheckResult
from acd.core.process import sha256_paths


class GateError(RuntimeError):
    """A deterministic gate rejected the current state (fail-closed)."""


def assert_rule_check_input_matches(
    name: str, result: RuleCheckResult, input_path: Path
) -> None:
    """Require a rule-check result to correspond to the current input bytes."""
    if not input_path.is_file():
        raise GateError(f"{name}: gate not executed (input file missing: {input_path})")
    envelope = result.run.envelope
    input_paths = getattr(envelope, "input_paths", ())
    declared_paths: list[str] = []
    if isinstance(input_paths, tuple):
        for candidate in cast(tuple[object, ...], input_paths):
            if isinstance(candidate, str):
                declared_paths.append(candidate)
    if not any(Path(path).resolve() == input_path.resolve() for path in declared_paths):
        raise GateError(f"{name}: gate not executed (input path is not declared)")
    input_hash = getattr(envelope, "input_hash", None)
    if not isinstance(input_hash, str) or input_hash == "unknown":
        raise GateError(f"{name}: gate not executed (input hash is unknown)")
    measured_hash = sha256_paths([input_path])
    if input_hash != measured_hash:
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
