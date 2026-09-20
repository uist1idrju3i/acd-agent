"""Deterministic pass/fail gates over external tool results.

Gates only consume already-enveloped tool results; unknown or missing states
never pass. The AI proposes, these functions decide.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from acd.adapters.kicad.cli import RuleCheckResult
from acd.core.runtime.process import sha256_paths


class GateError(RuntimeError):
    """A deterministic gate rejected the current state (fail-closed)."""


_REFDES_PHRASE_RE = re.compile(r"\b(?:of|Footprint) ([A-Z]+[0-9]+[A-Z0-9]*)\b")
_REFDES_TOKEN_RE = re.compile(r"^[A-Z]{1,4}[0-9]+$")
_REFDES_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")


def _string_field(value: object, fallback: str = "unknown") -> str:
    return value if isinstance(value, str) and value else fallback


def _position(value: object) -> tuple[str, str]:
    if not isinstance(value, Mapping):
        return "unknown", "unknown"
    position = cast(Mapping[str, object], value)
    x = position.get("x")
    y = position.get("y")
    x_text = str(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else "unknown"
    y_text = str(y) if isinstance(y, (int, float)) and not isinstance(y, bool) else "unknown"
    return x_text, y_text


def _violation_detail(violation: Mapping[str, object]) -> tuple[str, set[str]]:
    violation_type = _string_field(violation.get("type"))
    description = _string_field(violation.get("description", violation_type))
    x_text, y_text = _position(violation.get("pos"))
    refs: set[str] = set()
    item_descriptions: list[str] = []
    raw_items = violation.get("items")
    if isinstance(raw_items, list):
        raw_items = cast(list[object], raw_items)
        for item in raw_items:
            if not isinstance(item, Mapping):
                item_descriptions.append("unknown")
                continue
            item_description = _string_field(
                cast(Mapping[str, object], item).get("description")
            )
            item_descriptions.append(item_description)
            refs.update(_REFDES_PHRASE_RE.findall(item_description))
            refs.update(
                token
                for token in _REFDES_SPLIT_RE.split(item_description)
                if _REFDES_TOKEN_RE.fullmatch(token)
                and not re.search(rf"\bPad\s+{re.escape(token)}\b", item_description)
            )
    if not item_descriptions:
        item_descriptions.append("unknown")
    return (
        f"{violation_type}: {description} "
        f"refdes={','.join(sorted(refs)) or 'unknown'} "
        f"at=({x_text},{y_text}) items: {' | '.join(item_descriptions)}",
        {violation_type},
    )


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
        detail_lines: list[str] = []
        violation_types: set[str] = set()
        for violation in errors[:5]:
            detail, types = _violation_detail(violation)
            detail_lines.append(detail)
            violation_types.update(types)
        for violation in errors[5:]:
            violation_types.add(_string_field(violation.get("type")))
        details = "; ".join(detail_lines)
        if len(errors) > 5:
            details += f" (+{len(errors) - 5} more)"
        hints = {
            "starved_thermal": (
                "starved_thermal: the GND pad gets fewer thermal spokes than required; "
                "free copper around the pad (move/rotate the refdes, reroute adjacent tracks) "
                "or connect the pad with a track — do not lower spoke requirements"
            ),
            "courtyards_overlap": (
                "courtyards_overlap: move or rotate one of the listed refdes so courtyards "
                "separate; do not shrink courtyards"
            ),
            "clearance": (
                "clearance: move the listed refdes/tracks apart; "
                "do not lower min_clearance_mm below the fab minimum"
            ),
        }
        hint_lines = [
            hint for violation_type, hint in hints.items() if violation_type in violation_types
        ]
        message = f"{name}: {len(errors)} error violations: {details}"
        if hint_lines:
            message += "\n" + "\n".join(hint_lines)
        raise GateError(message)
    if require_connected and result.unconnected_items:
        raise GateError(f"{name}: {len(result.unconnected_items)} unconnected items")


def assert_converged(convergence_state: str) -> None:
    if convergence_state != "converged":
        if convergence_state == "timed_out":
            raise GateError("router timed out before convergence (fail-closed)")
        raise GateError(f"router convergence_state={convergence_state!r} (fail-closed)")
