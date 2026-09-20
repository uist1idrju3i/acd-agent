"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.troubleshooting``.
"""

from acd.core.knowledge.troubleshooting import (
    PIN_PROJECTION_NAME,
    TroubleshootingDerivationError,
    derive_troubleshooting_knowledge,
    load_pin_macros,
    parse_pin_macros,
)

__all__ = [
    "PIN_PROJECTION_NAME",
    "TroubleshootingDerivationError",
    "derive_troubleshooting_knowledge",
    "load_pin_macros",
    "parse_pin_macros",
]
