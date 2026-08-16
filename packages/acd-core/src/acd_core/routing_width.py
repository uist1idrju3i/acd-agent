"""Declared routing-width derivation and deterministic netclass grouping."""

from __future__ import annotations

import math
from dataclasses import dataclass

from acd_core.electrical import ElectricalLane, GraphExtractionError

MM_TO_MIL = 39.37007874015748


@dataclass(frozen=True)
class NetWidthRequirement:
    net_name: str
    basis: str
    current_max_a: float | None
    width_basis_source: str
    derived_width_mm: float
    graph_minimum_mm: float
    profile_minimum_mm: float
    adopted_width_mm: float
    capability_or_minimum_governed: bool
    formula_source: str = ""

    def evidence(self) -> dict[str, object]:
        return {
            "net": self.net_name,
            "basis": self.basis,
            "current_max_a": self.current_max_a,
            "width_basis_source": self.width_basis_source,
            "derived_width_mm": self.derived_width_mm,
            "graph_minimum_mm": self.graph_minimum_mm,
            "profile_minimum_mm": self.profile_minimum_mm,
            "adopted_width_mm": self.adopted_width_mm,
            "capability_or_minimum_governed": self.capability_or_minimum_governed,
            "formula_source": self.formula_source,
        }


def _positive(value: float | None, label: str) -> float:
    if value is None or not math.isfinite(value) or value <= 0:
        raise GraphExtractionError(f"{label} must be positive (fail-closed)")
    return value


def derive_net_widths(
    lane: ElectricalLane,
    profile_minimum_mm: float,
) -> tuple[NetWidthRequirement, ...]:
    """Derive every net width exclusively from declared graph/profile inputs."""
    profile_min = _positive(profile_minimum_mm, "profile min_track_width")
    board = lane.board
    thickness_um = _positive(board.outer_copper_thickness_um, "outer copper thickness")
    if not board.copper_thickness_source:
        raise GraphExtractionError("copper thickness source is missing (fail-closed)")
    _positive(board.allowable_temperature_rise_k, "allowable temperature rise")
    source = board.width_basis_source
    if not source or "A = (I / (k * ΔT^b))^(1/c)" not in source:
        raise GraphExtractionError("IPC-2221 width basis equation/source is missing")
    _positive(board.width_measurement_tolerance_mm, "width measurement tolerance")
    constants = (
        board.ipc2221_external_k,
        board.ipc2221_external_b,
        board.ipc2221_external_c,
        board.ipc2221_internal_k,
        board.ipc2221_internal_b,
        board.ipc2221_internal_c,
    )
    if any(value is None or not math.isfinite(value) or value <= 0 for value in constants):
        raise GraphExtractionError("IPC-2221 constants are incomplete (fail-closed)")
    temperature_rise = board.allowable_temperature_rise_k
    external_k = board.ipc2221_external_k
    external_b = board.ipc2221_external_b
    external_c = board.ipc2221_external_c
    if temperature_rise is None or external_k is None or external_b is None or external_c is None:
        raise GraphExtractionError("IPC-2221 external constants are incomplete (fail-closed)")
    thickness_mil = thickness_um * MM_TO_MIL / 1000.0
    requirements: list[NetWidthRequirement] = []
    for net in sorted(lane.nets, key=lambda item: item.name):
        if net.width_basis not in {"current_ipc2221", "manufacturing_minimum"}:
            raise GraphExtractionError(
                f"net {net.name!r}: unsupported width_basis {net.width_basis!r}"
            )
        reason = net.width_basis_source
        if not reason:
            raise GraphExtractionError(
                f"net {net.name!r}: width_basis_source is required (fail-closed)"
            )
        if net.width_basis == "current_ipc2221":
            current = _positive(net.current_max_a, f"net {net.name} current_max_a")
            area_mil2 = (
                current / (external_k * temperature_rise**external_b)
            ) ** (1.0 / external_c)
            derived = area_mil2 / thickness_mil / MM_TO_MIL
        else:
            if net.manufacturing_minimum_mm is None or net.manufacturing_margin_mm is None:
                raise GraphExtractionError(
                    f"net {net.name!r}: manufacturing minimum and margin are required"
                )
            minimum = _positive(
                net.manufacturing_minimum_mm, f"net {net.name} manufacturing minimum"
            )
            margin = net.manufacturing_margin_mm
            if not math.isfinite(margin) or margin < 0:
                raise GraphExtractionError(
                    f"net {net.name!r}: manufacturing margin is invalid"
                )
            current = None
            derived = minimum + margin
        adopted = max(derived, lane.board.min_track_mm, profile_min)
        requirements.append(
            NetWidthRequirement(
                net_name=net.name,
                basis=net.width_basis,
                current_max_a=current,
                width_basis_source=reason,
                derived_width_mm=derived,
                graph_minimum_mm=lane.board.min_track_mm,
                profile_minimum_mm=profile_min,
                adopted_width_mm=adopted,
                capability_or_minimum_governed=adopted > derived + 1e-9,
                formula_source=source,
            )
        )
    return tuple(requirements)


def group_netclasses(
    requirements: tuple[NetWidthRequirement, ...],
) -> tuple[tuple[str, tuple[str, ...], float], ...]:
    groups: dict[float, list[str]] = {}
    for requirement in requirements:
        groups.setdefault(round(requirement.adopted_width_mm, 6), []).append(
            requirement.net_name
        )
    return tuple(
        (f"ACD_{round(width * 1000):04d}um", tuple(sorted(names)), width)
        for width, names in sorted(groups.items())
    )
