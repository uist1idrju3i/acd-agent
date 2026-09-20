"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.copper``.
"""

from acd.core.electrical.copper import (
    copper_cross_section_mm2,
    copper_resistance_ohm,
    temperature_adjusted_resistivity,
    via_resistance_ohm,
)

__all__ = [
    "copper_cross_section_mm2",
    "copper_resistance_ohm",
    "temperature_adjusted_resistivity",
    "via_resistance_ohm",
]
