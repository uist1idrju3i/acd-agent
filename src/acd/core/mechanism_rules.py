"""Compatibility re-export.

The implementation lives in ``acd.core.mechanical.mechanism_rules``.
"""

from acd.core.mechanical.mechanism_rules import (
    MATERIAL_ALLOWABLE_STRAIN,
    MechanismFinding,
    MechanismStatus,
    check_mechanism_features,
)

__all__ = [
    "MATERIAL_ALLOWABLE_STRAIN",
    "MechanismFinding",
    "MechanismStatus",
    "check_mechanism_features",
]
