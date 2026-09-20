"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.order_execution``.
"""

from acd.core.manufacturing.order_execution import (
    build_dry_run_order_payload,
)

__all__ = [
    "build_dry_run_order_payload",
]
