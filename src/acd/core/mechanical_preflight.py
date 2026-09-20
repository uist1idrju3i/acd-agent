"""Compatibility re-export.

The implementation lives in ``acd.core.mechanical.mechanical_preflight``.
"""

from acd.core.mechanical.mechanical_preflight import (
    MechanicalPreflightReport,
    RequirementCode,
    RequirementFinding,
    check_mechanical_preflight,
    collect_mechanical_findings,
)

__all__ = [
    "MechanicalPreflightReport",
    "RequirementCode",
    "RequirementFinding",
    "check_mechanical_preflight",
    "collect_mechanical_findings",
]
