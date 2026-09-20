"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.eco_gate``.
"""

from acd.core.knowledge.eco_gate import (
    MINIMUM_GATES,
    EcoGateError,
    evaluate_eco,
)

__all__ = [
    "MINIMUM_GATES",
    "EcoGateError",
    "evaluate_eco",
]
