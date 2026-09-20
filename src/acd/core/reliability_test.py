"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.reliability_test``.
"""

from acd.core.manufacturing.reliability_test import (
    BOLTZMANN_EV_PER_K,
    DFT_CHECKS,
    EMC_PREDICATES,
    HARNESS_CHECKS,
    KNOWN_TARGETS,
    evaluate_reliability_test_plan,
)

__all__ = [
    "BOLTZMANN_EV_PER_K",
    "DFT_CHECKS",
    "EMC_PREDICATES",
    "HARNESS_CHECKS",
    "KNOWN_TARGETS",
    "evaluate_reliability_test_plan",
]
