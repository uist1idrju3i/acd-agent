"""Contract models for deterministic post-design rework differences."""

from __future__ import annotations

from typing import Annotated, Literal

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
from acd.schema.design_graph import AttrValue, GraphNode
from acd.schema.rationale import RationaleRecord

REPLACEABLE_ATTRS = frozenset(
    {"value", "mpn", "lcsc", "footprint", "jlcpcb_class", "assembly"}
)
REWORK_ADD_KINDS = frozenset(
    {
        "electrical.component",
        "electrical.pin",
        "electrical.net",
        "mechanical.component_body",
    }
)


class ReworkCut(AcdModel):
    op: Literal["cut"] = "cut"
    pin_id: NodeId
    reason: NonEmptyStr


class ReworkAdd(AcdModel):
    op: Literal["add"] = "add"
    node: GraphNode
    reason: NonEmptyStr

    @model_validator(mode="after")
    def validate_kind(self) -> ReworkAdd:
        if self.node.kind not in REWORK_ADD_KINDS:
            raise ValueError("added node kind is not permitted for rework")
        return self


class ReworkRemove(AcdModel):
    op: Literal["remove"] = "remove"
    component_id: NodeId
    reason: NonEmptyStr


class ReworkReplace(AcdModel):
    op: Literal["replace"] = "replace"
    component_id: NodeId
    attrs: dict[str, AttrValue]
    reason: NonEmptyStr

    @model_validator(mode="after")
    def validate_attrs(self) -> ReworkReplace:
        if not self.attrs:
            raise ValueError("replace attrs must not be empty")
        unknown = sorted(set(self.attrs) - REPLACEABLE_ATTRS)
        if unknown:
            raise ValueError(
                "replace attrs contain unsupported keys: " + ", ".join(unknown)
            )
        return self


class ReworkMechanical(AcdModel):
    op: Literal["mechanical"] = "mechanical"
    target_id: NodeId
    attrs: dict[str, AttrValue]
    reason: NonEmptyStr

    @model_validator(mode="after")
    def validate_attrs(self) -> ReworkMechanical:
        if not self.attrs:
            raise ValueError("mechanical attrs must not be empty")
        return self


class FirmwareChange(AcdModel):
    change_id: NonEmptyStr
    kind: Literal["pin_reassignment", "timing", "threshold", "degrade", "disable"]
    description: NonEmptyStr
    affected_functions: list[NonEmptyStr]

    @model_validator(mode="after")
    def validate_functions(self) -> FirmwareChange:
        if not self.affected_functions:
            raise ValueError("firmware change affected_functions must not be empty")
        if len(set(self.affected_functions)) != len(self.affected_functions):
            raise ValueError("firmware change affected_functions must be unique")
        return self


ReworkOperation = Annotated[
    ReworkCut | ReworkAdd | ReworkRemove | ReworkReplace | ReworkMechanical,
    Field(discriminator="op"),
]


class ReworkDiff(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["rework_diff"] = "rework_diff"
    pass_evidence: Literal[False] = False
    workaround_id: WorkaroundId
    graph_id: NonEmptyStr
    base_revision: Revision
    defect_ids: list[NonEmptyStr]
    operations: list[ReworkOperation] = Field(default_factory=list[ReworkOperation])
    touches_safety_boundary: bool
    firmware_changes: list[FirmwareChange] = Field(
        default_factory=list[FirmwareChange]
    )
    rationale_records: list[RationaleRecord] = Field(
        default_factory=list[RationaleRecord]
    )
    degraded_functions: list[NonEmptyStr] = Field(
        default_factory=list[NonEmptyStr]
    )

    @model_validator(mode="after")
    def validate_collections(self) -> ReworkDiff:
        if "+" in self.base_revision:
            raise ValueError("base_revision must not be a derived revision")
        if not self.defect_ids:
            raise ValueError("defect_ids must not be empty")
        if len(set(self.defect_ids)) != len(self.defect_ids):
            raise ValueError("defect_ids must be unique")
        if not self.operations and not self.firmware_changes:
            raise ValueError("operations or firmware_changes must not be empty")
        change_ids = [change.change_id for change in self.firmware_changes]
        if len(set(change_ids)) != len(change_ids):
            raise ValueError("firmware change_id entries must be unique")
        rationale_ids = [record.rationale_id for record in self.rationale_records]
        if len(set(rationale_ids)) != len(rationale_ids):
            raise ValueError("rationale_id entries must be unique")
        degraded = set(self.degraded_functions)
        if len(degraded) != len(self.degraded_functions):
            raise ValueError("degraded_functions must be unique")
        degraded_kinds = {"degrade", "disable"}
        degraded_allowed = {
            function
            for change in self.firmware_changes
            if change.kind in degraded_kinds
            for function in change.affected_functions
        }
        has_degraded_change = bool(
            degraded_kinds & {change.kind for change in self.firmware_changes}
        )
        if bool(degraded) != has_degraded_change:
            raise ValueError(
                "degraded_functions must be non-empty exactly for degrade or disable changes"
            )
        if not degraded.issubset(degraded_allowed):
            raise ValueError(
                "degraded_functions must be affected by a degrade or disable change"
            )
        return self

    @property
    def derived_revision(self) -> str:
        return f"{self.base_revision}+{self.workaround_id}"


__all__ = [
    "REPLACEABLE_ATTRS",
    "REWORK_ADD_KINDS",
    "FirmwareChange",
    "ReworkAdd",
    "ReworkCut",
    "ReworkDiff",
    "ReworkMechanical",
    "ReworkOperation",
    "ReworkRemove",
    "ReworkReplace",
    "WorkaroundId",
]
