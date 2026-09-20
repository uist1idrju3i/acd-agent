"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.projection_format_check``.
"""

from acd.core.electrical.projection_format_check import (
    CHECKER_NAME,
    CHECKER_VERSION,
    ProjectionFormatError,
    ProjectionKind,
    check_projection,
    check_projections,
)

__all__ = [
    "CHECKER_NAME",
    "CHECKER_VERSION",
    "ProjectionFormatError",
    "ProjectionKind",
    "check_projection",
    "check_projections",
]
