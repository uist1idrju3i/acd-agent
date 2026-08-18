"""Core CAD, electrical, and manufacturing operations."""

from acd.core.cad_normalize import CadNormalizationError, normalize_3mf, normalize_step
from acd.core.fab import (
    FabOrderIntentView,
    FabProfile,
    ProcessAllowanceView,
    extract_fab_intent,
    load_fab_profile,
    validate_allowances_against_profile,
)
from acd.core.firmware import (
    FunctionalRunError,
    evaluate_functional_run,
    load_and_evaluate_functional_run,
)
from acd.core.rationale import (
    RATIONALE_EXEMPT_ATTRS,
    REQUIRED_RATIONALE_ATTRS,
    check_rationale_coverage,
    subject_hash_for,
)
from acd.core.receipt import (
    ReceiptReconciliationError,
    ReconciliationReport,
    build_receipt_evidence,
    reconcile_files,
    reconcile_receipt,
)

__all__ = [
    "RATIONALE_EXEMPT_ATTRS",
    "REQUIRED_RATIONALE_ATTRS",
    "CadNormalizationError",
    "FabOrderIntentView",
    "FabProfile",
    "FunctionalRunError",
    "ProcessAllowanceView",
    "ReceiptReconciliationError",
    "ReconciliationReport",
    "build_receipt_evidence",
    "check_rationale_coverage",
    "evaluate_functional_run",
    "extract_fab_intent",
    "load_and_evaluate_functional_run",
    "load_fab_profile",
    "normalize_3mf",
    "normalize_step",
    "reconcile_files",
    "reconcile_receipt",
    "subject_hash_for",
    "validate_allowances_against_profile",
]
