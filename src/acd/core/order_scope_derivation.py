"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.order_scope_derivation``.
"""

from acd.core.manufacturing.order_scope_derivation import (
    MECHANICAL_ENCLOSURE_ITEM_ID,
    OrderScopeDerivationError,
    build_quote_request,
    derive_order_scope,
)

__all__ = [
    "MECHANICAL_ENCLOSURE_ITEM_ID",
    "OrderScopeDerivationError",
    "build_quote_request",
    "derive_order_scope",
]
