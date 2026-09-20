"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.pdn``.
"""

from acd.core.electrical.pdn import (
    analyze_pdn,
    pdn_markdown,
)

__all__ = [
    "analyze_pdn",
    "pdn_markdown",
]
