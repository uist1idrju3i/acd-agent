"""Shared deterministic copper geometry and resistance calculations."""

from __future__ import annotations

import math


def copper_cross_section_mm2(width_mm: float, thickness_um: float) -> float:
    if not math.isfinite(width_mm) or width_mm <= 0:
        raise ValueError("copper width must be positive")
    if not math.isfinite(thickness_um) or thickness_um <= 0:
        raise ValueError("copper thickness must be positive")
    return width_mm * (thickness_um / 1000.0)


def temperature_adjusted_resistivity(
    resistivity_ohm_mm: float,
    temperature_c: float,
    temp_coeff_per_c: float,
) -> float:
    if not math.isfinite(resistivity_ohm_mm) or resistivity_ohm_mm <= 0:
        raise ValueError("resistivity must be positive")
    if not math.isfinite(temperature_c):
        raise ValueError("temperature must be finite")
    if not math.isfinite(temp_coeff_per_c) or temp_coeff_per_c < 0:
        raise ValueError("temperature coefficient must be non-negative")
    return resistivity_ohm_mm * (1.0 + temp_coeff_per_c * (temperature_c - 20.0))


def copper_resistance_ohm(
    length_mm: float,
    width_mm: float,
    thickness_um: float,
    resistivity_ohm_mm: float,
    temperature_c: float,
    temp_coeff_per_c: float,
) -> float:
    if not math.isfinite(length_mm) or length_mm <= 0:
        raise ValueError("copper length must be positive")
    rho = temperature_adjusted_resistivity(
        resistivity_ohm_mm,
        temperature_c,
        temp_coeff_per_c,
    )
    return rho * length_mm / copper_cross_section_mm2(width_mm, thickness_um)


def via_resistance_ohm(
    drill_mm: float,
    plating_um: float,
    resistivity_ohm_mm: float,
    temperature_c: float,
    temp_coeff_per_c: float,
) -> float:
    if not math.isfinite(drill_mm) or drill_mm <= 0:
        raise ValueError("via drill must be positive")
    if not math.isfinite(plating_um) or plating_um <= 0:
        raise ValueError("via plating must be positive")
    rho = temperature_adjusted_resistivity(
        resistivity_ohm_mm,
        temperature_c,
        temp_coeff_per_c,
    )
    radius_mm = drill_mm / 2.0
    plated_radius_mm = radius_mm + plating_um / 1000.0
    barrel_area_mm2 = math.pi * (plated_radius_mm**2 - radius_mm**2)
    return rho * drill_mm / barrel_area_mm2
