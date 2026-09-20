"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.spice``.
"""

from acd.core.electrical.spice import (
    SpiceNetlist,
    SpiceNetlistError,
    SpiceRawResult,
    evaluate_spice,
    extract_power_netlist,
    run_ngspice,
)

__all__ = [
    "SpiceNetlist",
    "SpiceNetlistError",
    "SpiceRawResult",
    "evaluate_spice",
    "extract_power_netlist",
    "run_ngspice",
]
