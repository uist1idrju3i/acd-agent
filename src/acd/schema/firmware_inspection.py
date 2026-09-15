"""Contracts for the opt-in firmware inspection sequence."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import AcdModel, NodeId, NonEmptyStr, Revision, SchemaVersion
from acd.schema.shipping_inspection import CriterionSource


class FirmwareInspectionItem(AcdModel):
    item_id: NonEmptyStr
    kind: Literal["led", "i2c_probe", "power_self_check", "serial_echo"]
    subject_node_ids: list[NodeId]
    source: CriterionSource | None = None
    expected_line: NonEmptyStr | None = None
    failure_line: NonEmptyStr | None = None
    status: Literal["derived", "unknown"]
    unknown_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_item(self) -> FirmwareInspectionItem:
        if not self.subject_node_ids:
            raise ValueError("firmware inspection item requires subject nodes")
        derived = self.status == "derived"
        if derived:
            if self.source is None or self.expected_line is None:
                raise ValueError("derived item requires source and expected_line")
            if self.unknown_reason is not None:
                raise ValueError("derived item must not have unknown_reason")
        else:
            if self.unknown_reason is None:
                raise ValueError("unknown item requires unknown_reason")
            if self.source is not None or self.expected_line is not None:
                raise ValueError("unknown item must not have source or expected_line")
        if self.kind != "i2c_probe" and self.failure_line is not None:
            raise ValueError("only i2c_probe may have failure_line")
        return self


class FirmwareInspectionSequence(AcdModel):
    schema_version: SchemaVersion
    artifact_kind: Literal["firmware_inspection_sequence"] = (
        "firmware_inspection_sequence"
    )
    pass_evidence: Literal[False] = False
    record_class: Literal["L3"] = "L3"
    graph_id: NonEmptyStr
    target_revision: Revision
    entry_command: NonEmptyStr
    begin_line: NonEmptyStr
    end_line: NonEmptyStr
    items: list[FirmwareInspectionItem] = Field(
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_sequence(self) -> FirmwareInspectionSequence:
        item_ids = [item.item_id for item in self.items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("firmware inspection item IDs must be unique")
        if self.end_line != f"ACD_INSPECT end items={len(self.items)}":
            raise ValueError("firmware inspection end_line must match item count")
        return self


__all__ = ["FirmwareInspectionItem", "FirmwareInspectionSequence"]
