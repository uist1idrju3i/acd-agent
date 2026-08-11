"""Design-graph revision, patch, and impact/stale derivation."""

from acd_core.cad_normalize import CadNormalizationError, normalize_3mf, normalize_step
from acd_core.fab import (
    FabOrderIntentView,
    FabProfile,
    ProcessAllowanceView,
    extract_fab_intent,
    load_fab_profile,
    validate_allowances_against_profile,
)
from acd_core.impact import (
    GATES_BY_NODE_KIND,
    affected_node_ids,
    gates_to_rerun,
    stale_evidence_ids,
)
from acd_core.patch import (
    AddNode,
    GraphPatch,
    PatchOp,
    RemoveNode,
    RevisionMismatchError,
    SetAttrs,
    apply_patch,
)
from acd_core.revision import next_revision, revision_number

__all__ = [
    "GATES_BY_NODE_KIND",
    "AddNode",
    "CadNormalizationError",
    "FabOrderIntentView",
    "FabProfile",
    "GraphPatch",
    "PatchOp",
    "ProcessAllowanceView",
    "RemoveNode",
    "RevisionMismatchError",
    "SetAttrs",
    "affected_node_ids",
    "apply_patch",
    "extract_fab_intent",
    "gates_to_rerun",
    "load_fab_profile",
    "next_revision",
    "normalize_3mf",
    "normalize_step",
    "revision_number",
    "stale_evidence_ids",
    "validate_allowances_against_profile",
]
