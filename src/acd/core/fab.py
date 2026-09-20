"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.fab``.
"""

from acd.core.manufacturing.fab import (
    FabOrderIntentView,
    FabProfile,
    FabProfileRegistry,
    ProcessAllowanceView,
    extract_fab_intent,
    load_fab_profile,
    load_fab_profile_by_id,
    load_fab_profile_registry,
    resolve_fab_profile_path,
    validate_allowances_against_profile,
)

__all__ = [
    "FabOrderIntentView",
    "FabProfile",
    "FabProfileRegistry",
    "ProcessAllowanceView",
    "extract_fab_intent",
    "load_fab_profile",
    "load_fab_profile_by_id",
    "load_fab_profile_registry",
    "resolve_fab_profile_path",
    "validate_allowances_against_profile",
]
