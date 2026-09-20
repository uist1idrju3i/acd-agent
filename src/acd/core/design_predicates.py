"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.design_predicates``.
"""

from acd.core.knowledge.design_predicates import (
    PREDICATE_CATALOG,
    PREDICATE_EVALUATION_STAGE,
    PREDICATE_EVALUATION_STAGES,
    PredicateMeasurement,
    PredicateRemediation,
    PredicateResult,
    PredicateStatus,
    PredicateSubject,
    RemediationDimensionsSource,
    SafetyBoundaryResult,
    evaluate_design_predicates,
    evaluate_differential_pair,
    evaluate_i2c_pullup,
    evaluate_impedance_geometry,
    evaluate_led_series_element,
    evaluate_pin_firmware_alignment,
    evaluate_power_boundary,
    evaluate_power_decoupling,
    evaluate_strapping_pin,
    evaluate_usb_cc,
    validate_predicate_stage_coverage,
)

__all__ = [
    "PREDICATE_CATALOG",
    "PREDICATE_EVALUATION_STAGE",
    "PREDICATE_EVALUATION_STAGES",
    "PredicateMeasurement",
    "PredicateRemediation",
    "PredicateResult",
    "PredicateStatus",
    "PredicateSubject",
    "RemediationDimensionsSource",
    "SafetyBoundaryResult",
    "evaluate_design_predicates",
    "evaluate_differential_pair",
    "evaluate_i2c_pullup",
    "evaluate_impedance_geometry",
    "evaluate_led_series_element",
    "evaluate_pin_firmware_alignment",
    "evaluate_power_boundary",
    "evaluate_power_decoupling",
    "evaluate_strapping_pin",
    "evaluate_usb_cc",
    "validate_predicate_stage_coverage",
]
