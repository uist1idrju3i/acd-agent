"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.design_predicate_profile``.
"""

from acd.core.knowledge.design_predicate_profile import (
    DEFAULT_DESIGN_PREDICATE_PROFILE_RELPATH,
    DesignPredicateProfile,
    DesignPredicateProfileDocument,
    DesignPredicateProfileError,
    ImpedanceFormulaConstants,
    default_design_predicate_profile,
    load_design_predicate_profile,
)

__all__ = [
    "DEFAULT_DESIGN_PREDICATE_PROFILE_RELPATH",
    "DesignPredicateProfile",
    "DesignPredicateProfileDocument",
    "DesignPredicateProfileError",
    "ImpedanceFormulaConstants",
    "default_design_predicate_profile",
    "load_design_predicate_profile",
]
