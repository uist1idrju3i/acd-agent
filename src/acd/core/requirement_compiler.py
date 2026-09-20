"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.requirement_compiler``.
"""

from acd.core.knowledge.requirement_compiler import (
    RequirementCompilationError,
    RequirementCompilationResult,
    compile_requirement_change,
)

__all__ = [
    "RequirementCompilationError",
    "RequirementCompilationResult",
    "compile_requirement_change",
]
