"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.requirements``.
"""

from acd.core.knowledge.requirements import (
    LoadedRequirements,
    RequirementError,
    default_requirements_path,
    load_requirements,
    validate_requirement_graph_consistency,
    validate_requirements,
)

__all__ = [
    "LoadedRequirements",
    "RequirementError",
    "default_requirements_path",
    "load_requirements",
    "validate_requirement_graph_consistency",
    "validate_requirements",
]
