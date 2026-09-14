"""Contract models for deterministic post-design rework differences."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
)
from acd.schema.design_graph import AttrValue, GraphNode

WorkaroundId = Annotated[str, StringConstraints(pattern=r"^WA-[0-9]{3,}$")]
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
    operations: list[ReworkOperation]
    touches_safety_boundary: bool

    @model_validator(mode="after")
    def validate_collections(self) -> ReworkDiff:
        if not self.defect_ids:
            raise ValueError("defect_ids must not be empty")
        if len(set(self.defect_ids)) != len(self.defect_ids):
            raise ValueError("defect_ids must be unique")
        if not self.operations:
            raise ValueError("operations must not be empty")
        return self

    @property
    def derived_revision(self) -> str:
        return f"{self.base_revision}+{self.workaround_id}"


__all__ = [
    "REPLACEABLE_ATTRS",
    "REWORK_ADD_KINDS",
    "ReworkAdd",
    "ReworkCut",
    "ReworkDiff",
    "ReworkMechanical",
    "ReworkOperation",
    "ReworkRemove",
    "ReworkReplace",
    "WorkaroundId",
]
