"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.order_submission``.
"""

from acd.core.manufacturing.order_submission import (
    DeclaredProviderUnavailable,
    OrderSubmissionProvider,
    OrderSubmissionRecord,
    build_order_submission_record,
    resolve_order_provider,
)

__all__ = [
    "DeclaredProviderUnavailable",
    "OrderSubmissionProvider",
    "OrderSubmissionRecord",
    "build_order_submission_record",
    "resolve_order_provider",
]
