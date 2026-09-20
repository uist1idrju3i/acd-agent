"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.responsibility_gate``.
"""

from acd.core.knowledge.responsibility_gate import (
    ResponsibilityGateError,
    check_responsibility,
    load_responsibility_declaration,
)

__all__ = [
    "ResponsibilityGateError",
    "check_responsibility",
    "load_responsibility_declaration",
]
