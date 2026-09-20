"""Compatibility re-export.

The implementation lives in ``acd.core.mechanical.structural_safety``.
"""

from acd.core.mechanical.structural_safety import (
    evaluate_protection_selectivity,
    evaluate_signal_class_segregation,
    evaluate_single_point_of_failure,
    evaluate_sneak_path,
    evaluate_trapezoid_current_capacity,
)

__all__ = [
    "evaluate_protection_selectivity",
    "evaluate_signal_class_segregation",
    "evaluate_single_point_of_failure",
    "evaluate_sneak_path",
    "evaluate_trapezoid_current_capacity",
]
