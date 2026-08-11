"""Design-graph revision, patch, and impact/stale derivation."""

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
    "GraphPatch",
    "PatchOp",
    "RemoveNode",
    "RevisionMismatchError",
    "SetAttrs",
    "affected_node_ids",
    "apply_patch",
    "gates_to_rerun",
    "next_revision",
    "revision_number",
    "stale_evidence_ids",
]
