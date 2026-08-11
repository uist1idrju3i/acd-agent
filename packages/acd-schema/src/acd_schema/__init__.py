"""Pydantic models for the canonical ACD JSON Schema contracts in ``schemas/``."""

from acd_schema.common import CURRENT_SCHEMA_VERSION, UNKNOWN, AcdModel, is_unknown
from acd_schema.design_graph import DesignGraph, GraphNode, NodeKind
from acd_schema.error import AcdError, ErrorCategory, ErrorSeverity
from acd_schema.event_payload import (
    AcdEventPayload,
    ApprovalPayload,
    CommitSideEffectReceiptPayload,
    GateResultPayload,
    parse_event_payload,
)
from acd_schema.evidence import Evidence, EvidenceClaim, EvidenceStatus
from acd_schema.fw_package import BuildInfo, FwPackage, PinAssignment
from acd_schema.gate_matrix import Gate, GateKind, GateMatrix, GateStatus, Waiver
from acd_schema.review_finding import (
    Disposition,
    FindingSeverity,
    ProjectionKind,
    ProjectionRef,
    ReviewFinding,
    ReviewView,
)
from acd_schema.tool_envelope import ConvergenceState, ToolEnvelope

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "UNKNOWN",
    "AcdError",
    "AcdEventPayload",
    "AcdModel",
    "ApprovalPayload",
    "BuildInfo",
    "CommitSideEffectReceiptPayload",
    "ConvergenceState",
    "DesignGraph",
    "Disposition",
    "ErrorCategory",
    "ErrorSeverity",
    "Evidence",
    "EvidenceClaim",
    "EvidenceStatus",
    "FindingSeverity",
    "FwPackage",
    "Gate",
    "GateKind",
    "GateMatrix",
    "GateResultPayload",
    "GateStatus",
    "GraphNode",
    "NodeKind",
    "PinAssignment",
    "ProjectionKind",
    "ProjectionRef",
    "ReviewFinding",
    "ReviewView",
    "ToolEnvelope",
    "Waiver",
    "is_unknown",
    "parse_event_payload",
]
