"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.workaround_ledger``.
"""

from acd.core.manufacturing.workaround_ledger import (
    WorkaroundLedgerError,
    evaluate_workaround_retirement,
)

__all__ = [
    "WorkaroundLedgerError",
    "evaluate_workaround_retirement",
]
