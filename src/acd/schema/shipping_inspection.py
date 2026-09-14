"""Contract for deterministic shipping inspection documents."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import AcdModel, NodeId, NonEmptyStr, Revision, SchemaVersion

InspectionCategory = Literal[
    "visual",
    "continuity",
    "power",
    "flash_boot",
    "led",
    "sensor",
    "serial",
]


class CriterionSource(AcdModel):
    kind: Literal["graph", "gate_threshold", "firmware_projection"]
    ref: NonEmptyStr


class InspectionCriterion(AcdModel):
    kind: Literal["value", "range", "string", "boolean", "unknown"]
    expected: str | float | int | bool | None
    unit: str | None = None
    lower: float | None = None
    upper: float | None = None
    source: CriterionSource | None = None
    unknown_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_criterion(self) -> InspectionCriterion:
        unknown = self.kind == "unknown"
        if unknown != (
            self.expected is None
            and self.source is None
            and self.unknown_reason is not None
        ):
            raise ValueError(
                "unknown criterion requires a reason and no expected value or source"
                if unknown
                else "known criterion requires expected value and source and no reason"
            )
        if not unknown and (self.expected is None or self.source is None):
            raise ValueError("known criterion requires expected value and source")
        if unknown and self.unknown_reason is None:
            raise ValueError("unknown criterion requires a reason")
        if not unknown and self.unknown_reason is not None:
            raise ValueError("known criterion must not declare an unknown reason")
        if self.kind == "range":
            if self.lower is None or self.upper is None:
                raise ValueError("range criterion requires lower and upper")
            if self.lower > self.upper:
                raise ValueError("range criterion lower must not exceed upper")
        elif self.lower is not None or self.upper is not None:
            raise ValueError("only range criterion may declare lower or upper")
        if unknown and self.unit is not None:
            raise ValueError("unknown criterion must not declare a unit")
        return self


class InspectionItem(AcdModel):
    item_id: NonEmptyStr = Field(pattern=r"^SI-[0-9]{3}$")
    category: InspectionCategory
    subject_node_ids: list[NodeId]
    method_key: NonEmptyStr
    criterion: InspectionCriterion
    manual_decision_required: bool

    @model_validator(mode="after")
    def validate_item(self) -> InspectionItem:
        if not self.subject_node_ids:
            raise ValueError("inspection item requires subject nodes")
        if len(set(self.subject_node_ids)) != len(self.subject_node_ids):
            raise ValueError("inspection item subject nodes must be unique")
        expected_manual = self.criterion.kind == "unknown"
        if self.manual_decision_required != expected_manual:
            raise ValueError(
                "manual_decision_required must match unknown criterion"
            )
        return self


class ShippingInspectionDocument(AcdModel):
    schema_version: SchemaVersion
    artifact_kind: Literal["shipping_inspection"] = "shipping_inspection"
    pass_evidence: Literal[False] = False
    record_class: Literal["L3"] = "L3"
    graph_id: NonEmptyStr
    revision: Revision
    items: list[InspectionItem]
    unknown_count: int

    @model_validator(mode="after")
    def validate_document(self) -> ShippingInspectionDocument:
        if not self.items:
            raise ValueError("shipping inspection document requires items")
        ids = [item.item_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("shipping inspection item IDs must be unique")
        if self.unknown_count != sum(
            item.manual_decision_required for item in self.items
        ):
            raise ValueError("unknown_count must match manual decision rows")
        if self.unknown_count < 0:
            raise ValueError("unknown_count must not be negative")
        return self


__all__ = [
    "CriterionSource",
    "InspectionCategory",
    "InspectionCriterion",
    "InspectionItem",
    "ShippingInspectionDocument",
]
