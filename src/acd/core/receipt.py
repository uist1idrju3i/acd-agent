"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.receipt``.
"""

from acd.core.manufacturing.receipt import (
    REVISION_ADAPTER,
    ReceiptReconciliationError,
    build_receipt_evidence,
    reconcile_files,
    reconcile_receipt,
)

__all__ = [
    "REVISION_ADAPTER",
    "ReceiptReconciliationError",
    "build_receipt_evidence",
    "reconcile_files",
    "reconcile_receipt",
]
