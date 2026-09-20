"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.wca``.
"""

from acd.core.electrical.wca import (
    WcaInputError,
    evaluate_wca,
)

__all__ = [
    "WcaInputError",
    "evaluate_wca",
]
