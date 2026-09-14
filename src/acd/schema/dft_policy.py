"""Contracts for opt-in design-for-test coverage checks."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
)

DftNetClass = Literal[
    "power_rail",
    "ground",
    "i2c",
    "uart",
    "gpio_firmware",
    "usb_data",
    "all_signals",
]
DftProbeSide = Literal["top", "bottom", "either"]


class DftPolicy(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["dft_policy"] = "dft_policy"
    graph_id: NonEmptyStr
    revision: Revision
    required_net_classes: list[DftNetClass] = Field(default_factory=list[DftNetClass])
    required_net_ids: list[NodeId] = Field(default_factory=list[NodeId])
    min_probe_pitch_mm: float
    min_pad_diameter_mm: float
    probe_side: DftProbeSide
    keepout_from_components_mm: float

    @model_validator(mode="after")
    def validate_policy(self) -> DftPolicy:
        for name, value in (
            ("min_probe_pitch_mm", self.min_probe_pitch_mm),
            ("min_pad_diameter_mm", self.min_pad_diameter_mm),
            ("keepout_from_components_mm", self.keepout_from_components_mm),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.min_probe_pitch_mm <= 0:
            raise ValueError("min_probe_pitch_mm must be positive")
        if self.min_pad_diameter_mm <= 0:
            raise ValueError("min_pad_diameter_mm must be positive")
        if self.keepout_from_components_mm < 0:
            raise ValueError("keepout_from_components_mm must not be negative")
        if not self.required_net_classes and not self.required_net_ids:
            raise ValueError("DFT policy must require a net class or explicit net")
        if len(set(self.required_net_classes)) != len(self.required_net_classes):
            raise ValueError("required_net_classes entries must be unique")
        if len(set(self.required_net_ids)) != len(self.required_net_ids):
            raise ValueError("required_net_ids entries must be unique")
        return self
