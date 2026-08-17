"""Core CAD, electrical, and manufacturing operations."""

from acd_core.cad_normalize import CadNormalizationError, normalize_3mf, normalize_step
from acd_core.fab import (
    FabOrderIntentView,
    FabProfile,
    ProcessAllowanceView,
    extract_fab_intent,
    load_fab_profile,
    validate_allowances_against_profile,
)
from acd_core.rationale import (
    RATIONALE_EXEMPT_ATTRS,
    REQUIRED_RATIONALE_ATTRS,
    check_rationale_coverage,
    subject_hash_for,
)

__all__ = [
    "RATIONALE_EXEMPT_ATTRS",
    "REQUIRED_RATIONALE_ATTRS",
    "CadNormalizationError",
    "FabOrderIntentView",
    "FabProfile",
    "ProcessAllowanceView",
    "check_rationale_coverage",
    "extract_fab_intent",
    "load_fab_profile",
    "normalize_3mf",
    "normalize_step",
    "subject_hash_for",
    "validate_allowances_against_profile",
]
