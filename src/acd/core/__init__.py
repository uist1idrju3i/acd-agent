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
from acd.core.feedback import (
    FeedbackError,
    propose_input_feedback,
    validate_applied_feedback,
)
from acd.core.firmware import (
    FunctionalRunError,
    evaluate_functional_run,
    load_and_evaluate_functional_run,
)
from acd.core.order_execution import build_dry_run_order_payload
from acd.core.order_total import (
    OrderSubtotal,
    OrderTotalError,
    OrderTotalResult,
    QuoteCanonicalHash,
    aggregate_order_total,
    order_total_breakdown_hash,
    order_total_result_from_document,
    order_total_result_to_document,
)
from acd.core.quote import QuoteFeeSet, QuoteReadError, load_quote, read_quote
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
from acd.core.side_effect_journal import (
    JournalOrderReconstruction,
    SideEffectJournalError,
    append_post_order,
    append_pre_order,
    read_journal,
    reconstruct_order,
)

__all__ = [
    "RATIONALE_EXEMPT_ATTRS",
    "REQUIRED_RATIONALE_ATTRS",
    "CadNormalizationError",
    "FabOrderIntentView",
    "FabProfile",
    "FeedbackError",
    "FunctionalRunError",
    "JournalOrderReconstruction",
    "OrderSubtotal",
    "OrderTotalError",
    "OrderTotalResult",
    "ProcessAllowanceView",
    "QuoteCanonicalHash",
    "QuoteFeeSet",
    "QuoteReadError",
    "ReceiptReconciliationError",
    "ReconciliationReport",
    "SideEffectJournalError",
    "aggregate_order_total",
    "append_post_order",
    "append_pre_order",
    "build_dry_run_order_payload",
    "build_receipt_evidence",
    "check_rationale_coverage",
    "evaluate_functional_run",
    "extract_fab_intent",
    "load_and_evaluate_functional_run",
    "load_fab_profile",
    "load_quote",
    "normalize_3mf",
    "normalize_step",
    "order_total_breakdown_hash",
    "order_total_result_from_document",
    "order_total_result_to_document",
    "propose_input_feedback",
    "read_journal",
    "read_quote",
    "reconcile_files",
    "reconcile_receipt",
    "reconstruct_order",
    "subject_hash_for",
    "validate_allowances_against_profile",
    "validate_applied_feedback",
]
