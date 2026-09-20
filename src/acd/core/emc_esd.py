"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.emc_esd``.
"""

from acd.core.electrical.emc_esd import (
    EMC_RULES,
    evaluate_emc_esd,
)

__all__ = [
    "EMC_RULES",
    "evaluate_emc_esd",
]
