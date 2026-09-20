"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.functional_block_entry``.
"""

from acd.core.knowledge.functional_block_entry import (
    FunctionalBlockEntryResult,
    register_functional_block_contract,
)

__all__ = [
    "FunctionalBlockEntryResult",
    "register_functional_block_contract",
]
