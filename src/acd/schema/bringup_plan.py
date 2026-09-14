"""Contracts for deterministic bring-up test plans."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from acd.schema.common import AcdModel, NodeId, NonEmptyStr, Revision, SchemaVersion
from acd.schema.shipping_inspection import CriterionSource

BringUpPhase = Literal["unpowered", "power_up", "flash_boot", "peripheral", "self_test"]
BringUpInstrument = Literal[
    "multimeter",
    "current_limited_supply",
    "serial_console",
    "visual",
    "unknown",
]


class MeasurementTemplate(AcdModel):
    name: NonEmptyStr
    unit: NonEmptyStr
    expected_min: float
    expected_max: float
    tolerance: float

    @field_validator("expected_min", "expected_max", "tolerance")
    @classmethod
    def reject_non_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("measurement template values must be finite")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> MeasurementTemplate:
        if self.expected_min > self.expected_max:
            raise ValueError("measurement template minimum must not exceed maximum")
        if self.tolerance < 0:
            raise ValueError("measurement template tolerance must be non-negative")
        return self


class BringUpItem(AcdModel):
    item_id: NonEmptyStr
    phase: BringUpPhase
    order: int
    source_inspection_item_id: NonEmptyStr
    subject_node_ids: list[NodeId]
    probe_points: list[NodeId]
    instrument: BringUpInstrument
    procedure_key: NonEmptyStr
    measurement: MeasurementTemplate | None = None
    expected_text: NonEmptyStr | None = None
    criterion_source: CriterionSource | None = None
    unknown_reason: NonEmptyStr | None = None
    feeds_feedback_rule_ids: list[NonEmptyStr] = Field(default_factory=list)
    stop_on_fail: bool

    @model_validator(mode="after")
    def validate_item(self) -> BringUpItem:
        if not self.subject_node_ids:
            raise ValueError("bring-up item requires subject nodes")
        if len(set(self.subject_node_ids)) != len(self.subject_node_ids):
            raise ValueError("bring-up item subject nodes must be unique")
        if len(set(self.probe_points)) != len(self.probe_points):
            raise ValueError("bring-up item probe points must be unique")
        if len(set(self.feeds_feedback_rule_ids)) != len(
            self.feeds_feedback_rule_ids
        ):
            raise ValueError("bring-up feedback rule IDs must be unique")
        known_values = sum(
            value is not None
            for value in (self.measurement, self.expected_text, self.unknown_reason)
        )
        if known_values != 1:
            raise ValueError(
                "bring-up item requires exactly one measurement, expected_text, or "
                "unknown_reason"
            )
        if self.measurement is not None or self.expected_text is not None:
            if self.criterion_source is None:
                raise ValueError("known bring-up item requires criterion source")
        elif self.criterion_source is not None:
            raise ValueError("unknown bring-up item must not have criterion source")
        if self.phase in {"power_up", "flash_boot"} and not self.stop_on_fail:
            raise ValueError(
                "power_up and flash_boot bring-up items must stop on failure"
            )
        return self


class BringUpTestPlan(AcdModel):
    schema_version: SchemaVersion
    artifact_kind: Literal["bringup_test_plan"] = "bringup_test_plan"
    pass_evidence: Literal[False] = False
    record_class: Literal["L3"] = "L3"
    graph_id: NonEmptyStr
    target_revision: Revision
    items: list[BringUpItem] = Field(min_length=1)
    uncovered_feedback_rules: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_plan(self) -> BringUpTestPlan:
        phase_order = {
            "unpowered": 0,
            "power_up": 1,
            "flash_boot": 2,
            "peripheral": 3,
            "self_test": 4,
        }
        keys = [(phase_order[item.phase], item.order) for item in self.items]
        if keys != sorted(keys):
            raise ValueError("bring-up items must be ordered by phase and order")
        if len(set((item.phase, item.order) for item in self.items)) != len(keys):
            raise ValueError("bring-up item phase/order pairs must be unique")
        ids = [item.item_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("bring-up item IDs must be unique")
        if len(set(self.uncovered_feedback_rules)) != len(
            self.uncovered_feedback_rules
        ):
            raise ValueError("uncovered feedback rule IDs must be unique")
        return self


__all__ = [
    "BringUpInstrument",
    "BringUpItem",
    "BringUpPhase",
    "BringUpTestPlan",
    "MeasurementTemplate",
]
