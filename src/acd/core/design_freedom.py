"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.design_freedom``.
"""

from acd.core.knowledge.design_freedom import (
    DesignFreedomDeclaration,
    DesignFreedomDeclarationError,
    design_freedom_dimension,
    load_design_freedom_declaration,
    searchable_dimensions,
    validate_change_dimension_alignment,
)

__all__ = [
    "DesignFreedomDeclaration",
    "DesignFreedomDeclarationError",
    "design_freedom_dimension",
    "load_design_freedom_declaration",
    "searchable_dimensions",
    "validate_change_dimension_alignment",
]
