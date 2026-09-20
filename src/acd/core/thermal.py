"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.thermal``.
"""

from acd.core.electrical.thermal import (
    ThermalAnalysisError,
    estimate_thermal,
    thermal_markdown,
)

__all__ = [
    "ThermalAnalysisError",
    "estimate_thermal",
    "thermal_markdown",
]
