"""Contracts for deterministic workaround work instructions."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    WorkaroundId,
)
from acd.schema.shipping_inspection import InspectionItem


class TargetUnits(AcdModel):
    lots: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    serials: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    scope_status: Literal["declared", "unknown"]

    @model_validator(mode="after")
    def validate_scope(self) -> TargetUnits:
        if len(set(self.lots)) != len(self.lots):
            raise ValueError("target lots must be unique")
        if len(set(self.serials)) != len(self.serials):
            raise ValueError("target serials must be unique")
        if self.scope_status == "declared" and not (self.lots or self.serials):
            raise ValueError("declared target units require lots or serials")
        if self.scope_status == "unknown" and (self.lots or self.serials):
            raise ValueError("unknown target units must not list lots or serials")
        return self


class RequiredPart(AcdModel):
    refdes: NonEmptyStr
    mpn: NonEmptyStr | None = None
    value: str | None = None
    footprint: NonEmptyStr | None = None
    source_op_index: int = Field(ge=0)
    unknown_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_mpn(self) -> RequiredPart:
        if self.mpn is None and self.unknown_reason is None:
            raise ValueError("missing MPN requires unknown_reason")
        if self.mpn is not None and self.unknown_reason is not None:
            raise ValueError("known MPN must not declare unknown_reason")
        return self


class RequiredTool(AcdModel):
    op_index: int = Field(ge=0)
    tool_access: Literal["yes", "no", "not_applicable", "unknown"]
    hand_solderable: Literal["yes", "no", "not_applicable", "unknown"]
    enclosure_disassembly: Literal[
        "not_required", "reversible", "destructive", "unknown"
    ]
    basis: NonEmptyStr


class WorkStep(AcdModel):
    step_index: int = Field(ge=0)
    op_index: int | None = Field(default=None, ge=0)
    op: Literal["cut", "add", "remove", "replace", "mechanical", "firmware"]
    subject_node_ids: list[NodeId]
    refdes: str | None = None
    position_mm: tuple[float, float] | None = None
    instruction_key: NonEmptyStr
    reason: NonEmptyStr

    @model_validator(mode="after")
    def validate_step(self) -> WorkStep:
        if not self.subject_node_ids:
            raise ValueError("work step subject_node_ids must not be empty")
        if self.op == "firmware" and self.op_index is not None:
            raise ValueError("firmware work step must not have an operation index")
        if self.op != "firmware" and self.op_index is None:
            raise ValueError("rework work step requires an operation index")
        return self


class PostWorkInspection(AcdModel):
    items: list[InspectionItem]

    @model_validator(mode="after")
    def validate_items(self) -> PostWorkInspection:
        if not self.items:
            raise ValueError("post-work inspection must not be empty")
        return self


class WorkInstructionDocument(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["work_instruction"] = "work_instruction"
    pass_evidence: Literal[False] = False
    record_class: Literal["L3"] = "L3"
    graph_id: NonEmptyStr
    base_revision: Revision
    derived_revision: Revision
    workaround_id: WorkaroundId
    defect_ids: list[NonEmptyStr]
    salvage_verdict: Literal["salvageable", "constrained_salvage"]
    degraded_functions: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    target_units: TargetUnits
    required_parts: list[RequiredPart]
    required_tools: list[RequiredTool]
    steps: list[WorkStep]
    highlight_projection: NonEmptyStr | None = None
    post_work_inspection: PostWorkInspection

    @model_validator(mode="after")
    def validate_document(self) -> WorkInstructionDocument:
        if "+" not in self.derived_revision:
            raise ValueError("work instruction requires a derived revision")
        if not self.defect_ids:
            raise ValueError("work instruction defect_ids must not be empty")
        if not self.steps:
            raise ValueError("work instruction steps must not be empty")
        if self.salvage_verdict == "constrained_salvage" and not self.degraded_functions:
            raise ValueError("constrained salvage requires degraded_functions")
        if self.salvage_verdict == "salvageable" and self.degraded_functions:
            raise ValueError("salvageable instruction must not degrade functions")
        return self


__all__ = [
    "PostWorkInspection",
    "RequiredPart",
    "RequiredTool",
    "TargetUnits",
    "WorkInstructionDocument",
    "WorkStep",
]
