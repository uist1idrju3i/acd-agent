"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.functional_blocks``.
"""

from acd.core.knowledge.functional_blocks import (
    FunctionalBlockContractError,
    FunctionalBlockRegistry,
    block_path,
    declared_functional_blocks,
    load_functional_block_registry,
    remediation_declarations,
    required_predicate_names,
    unknown_block_message,
    validate_predicate_coverage,
)

__all__ = [
    "FunctionalBlockContractError",
    "FunctionalBlockRegistry",
    "block_path",
    "declared_functional_blocks",
    "load_functional_block_registry",
    "remediation_declarations",
    "required_predicate_names",
    "unknown_block_message",
    "validate_predicate_coverage",
]
