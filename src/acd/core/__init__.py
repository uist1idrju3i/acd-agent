"""Core CAD, electrical, and manufacturing operations."""

from acd.core.electrical.pdn import analyze_pdn, pdn_markdown
from acd.core.electrical.spice import evaluate_spice, extract_power_netlist, run_ngspice
from acd.core.electrical.thermal import estimate_thermal, thermal_markdown
from acd.core.firmware.firmware import (
    FunctionalRunError,
    evaluate_functional_run,
    load_and_evaluate_functional_run,
)
from acd.core.firmware.firmware_capability import (
    FirmwareCapabilityContractError,
    FirmwareCapabilityRegistry,
    load_firmware_capability_registry,
)
from acd.core.firmware.firmware_consistency import (
    FirmwareConsistencyReport,
    check_firmware_graph_consistency,
    evaluate_firmware_graph_consistency,
)
from acd.core.knowledge.eco_gate import MINIMUM_GATES, EcoGateError, evaluate_eco
from acd.core.knowledge.functional_block_entry import (
    FunctionalBlockEntryResult,
    register_functional_block_contract,
)
from acd.core.knowledge.functional_blocks import (
    FunctionalBlockContractError,
    FunctionalBlockRegistry,
    block_path,
    declared_functional_blocks,
    load_functional_block_registry,
    required_predicate_names,
    validate_predicate_coverage,
)
from acd.core.knowledge.graph_diff import GraphDiffError, build_graph_diff, unknown_graph_diff
from acd.core.knowledge.rationale import (
    RATIONALE_EXEMPT_ATTRS,
    REQUIRED_RATIONALE_ATTRS,
    RationaleRefreshError,
    check_rationale_coverage,
    refresh_rationale_document,
    subject_hash_for,
    summarize_rationale_coverage,
)
from acd.core.manufacturing.defect_records import (
    DefectCheckResult,
    DefectFinding,
    DefectRecordError,
    LoadedDefectDocument,
    check_defect_records,
    compute_horizontal_scope,
    load_defect_document,
)
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
from acd.core.manufacturing.feedback import (
    FeedbackError,
    propose_input_feedback,
    validate_applied_feedback,
)
from acd.core.manufacturing.order_execution import build_dry_run_order_payload
from acd.core.manufacturing.order_submission import (
    DeclaredProviderUnavailable,
    OrderSubmissionProvider,
    build_order_submission_record,
    resolve_order_provider,
)
from acd.core.manufacturing.order_total import (
    OrderSubtotal,
    OrderTotalError,
    OrderTotalResult,
    QuoteCanonicalHash,
    aggregate_order_total,
    order_total_breakdown_hash,
    order_total_result_from_document,
    order_total_result_to_document,
)
from acd.core.manufacturing.quote import (
    FixtureQuoteProvider,
    QuoteFeeSet,
    QuoteProvider,
    QuoteReadError,
    load_quote,
    quote_provider_from_config,
    read_quote,
)
from acd.core.manufacturing.receipt import (
    ReceiptReconciliationError,
    ReconciliationReport,
    build_receipt_evidence,
    reconcile_files,
    reconcile_receipt,
)
from acd.core.manufacturing.rework_diff import (
    DerivedGraph,
    LoadedReworkDiff,
    ReworkDiffError,
    apply_rework_diff,
    load_rework_diff,
    safety_related_node_ids,
    write_derived_graph,
)
from acd.core.manufacturing.workaround_ledger import (
    WorkaroundLedgerError,
    evaluate_workaround_retirement,
)
from acd.core.mechanical.cad_normalize import (
    CadNormalizationError,
    normalize_3mf,
    normalize_step,
    normalize_stl,
)
from acd.core.mechanical.fem import (
    FemAnalysisError,
    evaluate_fem,
    generate_ccx_input,
    run_ccx,
)
from acd.core.mechanical.mechanical import REQUIRED_MECHANICAL_ATTRS
from acd.core.mechanical.mechanical_preflight import (
    MechanicalPreflightReport,
    RequirementFinding,
    check_mechanical_preflight,
)
from acd.core.runtime.gate_evidence_run import external_gate_run
from acd.core.runtime.side_effect_journal import (
    JournalOrderReconstruction,
    SideEffectJournalError,
    append_post_order,
    append_pre_order,
    read_journal,
    reconstruct_order,
)

__all__ = [
    "MINIMUM_GATES",
    "RATIONALE_EXEMPT_ATTRS",
    "REQUIRED_MECHANICAL_ATTRS",
    "REQUIRED_RATIONALE_ATTRS",
    "CadNormalizationError",
    "DeclaredProviderUnavailable",
    "DefectCheckResult",
    "DefectFinding",
    "DefectRecordError",
    "DerivedGraph",
    "EcoGateError",
    "FabOrderIntentView",
    "FabProfile",
    "FabProfileRegistry",
    "FeedbackError",
    "FemAnalysisError",
    "FirmwareCapabilityContractError",
    "FirmwareCapabilityRegistry",
    "FirmwareConsistencyReport",
    "FixtureQuoteProvider",
    "FunctionalBlockContractError",
    "FunctionalBlockEntryResult",
    "FunctionalBlockRegistry",
    "FunctionalRunError",
    "GraphDiffError",
    "JournalOrderReconstruction",
    "LoadedDefectDocument",
    "LoadedReworkDiff",
    "MechanicalPreflightReport",
    "OrderSubmissionProvider",
    "OrderSubtotal",
    "OrderTotalError",
    "OrderTotalResult",
    "ProcessAllowanceView",
    "QuoteCanonicalHash",
    "QuoteFeeSet",
    "QuoteProvider",
    "QuoteReadError",
    "RationaleRefreshError",
    "ReceiptReconciliationError",
    "ReconciliationReport",
    "RequirementFinding",
    "ReworkDiffError",
    "SideEffectJournalError",
    "WorkaroundLedgerError",
    "aggregate_order_total",
    "analyze_pdn",
    "append_post_order",
    "append_pre_order",
    "apply_rework_diff",
    "block_path",
    "build_dry_run_order_payload",
    "build_graph_diff",
    "build_order_submission_record",
    "build_receipt_evidence",
    "check_defect_records",
    "check_firmware_graph_consistency",
    "check_mechanical_preflight",
    "check_rationale_coverage",
    "compute_horizontal_scope",
    "declared_functional_blocks",
    "estimate_thermal",
    "evaluate_eco",
    "evaluate_fem",
    "evaluate_firmware_graph_consistency",
    "evaluate_functional_run",
    "evaluate_spice",
    "evaluate_workaround_retirement",
    "external_gate_run",
    "extract_fab_intent",
    "extract_power_netlist",
    "generate_ccx_input",
    "load_and_evaluate_functional_run",
    "load_defect_document",
    "load_fab_profile",
    "load_fab_profile_by_id",
    "load_fab_profile_registry",
    "load_firmware_capability_registry",
    "load_functional_block_registry",
    "load_quote",
    "load_rework_diff",
    "normalize_3mf",
    "normalize_step",
    "normalize_stl",
    "order_total_breakdown_hash",
    "order_total_result_from_document",
    "order_total_result_to_document",
    "pdn_markdown",
    "propose_input_feedback",
    "quote_provider_from_config",
    "read_journal",
    "read_quote",
    "reconcile_files",
    "reconcile_receipt",
    "reconstruct_order",
    "refresh_rationale_document",
    "register_functional_block_contract",
    "required_predicate_names",
    "resolve_fab_profile_path",
    "resolve_order_provider",
    "run_ccx",
    "run_ngspice",
    "safety_related_node_ids",
    "subject_hash_for",
    "summarize_rationale_coverage",
    "thermal_markdown",
    "unknown_graph_diff",
    "validate_allowances_against_profile",
    "validate_applied_feedback",
    "validate_predicate_coverage",
    "write_derived_graph",
]


def __getattr__(name: str) -> object:
    if name in {"ManufacturingSubmissionError", "evaluate_manufacturing_submission"}:
        from acd.core.manufacturing.manufacturing_submission import (
            ManufacturingSubmissionError,
            evaluate_manufacturing_submission,
        )

        return {
            "ManufacturingSubmissionError": ManufacturingSubmissionError,
            "evaluate_manufacturing_submission": evaluate_manufacturing_submission,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
