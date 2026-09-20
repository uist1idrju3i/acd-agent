"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.salvage_gate``.
"""

from acd.core.manufacturing.salvage_gate import (
    SalvageGateError,
    evaluate_salvage,
)

__all__ = [
    "SalvageGateError",
    "evaluate_salvage",
]
