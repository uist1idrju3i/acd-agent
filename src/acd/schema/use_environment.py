"""Declared installation and operating environment for a design graph."""

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

Installation = Literal[
    "indoor_residential",
    "indoor_commercial",
    "indoor_industrial",
    "outdoor_sheltered",
    "outdoor_exposed",
    "vehicle",
    "unknown",
]
PowerSystem = Literal[
    "usb_host",
    "ac_adapter_class2",
    "mains_direct",
    "battery",
    "poe",
    "unknown",
]
Vibration = Literal["stationary", "handheld", "vehicle_mounted", "unknown"]
PortExposure = Literal["user_accessible", "internal", "unknown"]


class TemperatureRange(AcdModel):
    min: float
    max: float

    @model_validator(mode="after")
    def validate_range(self) -> TemperatureRange:
        if not all(math.isfinite(value) for value in (self.min, self.max)):
            raise ValueError("temperature range must be finite")
        if self.min > self.max:
            raise ValueError("temperature range min must not exceed max")
        return self


class HumidityRange(AcdModel):
    min: float = Field(ge=0, le=100)
    max: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_range(self) -> HumidityRange:
        if self.min > self.max:
            raise ValueError("humidity range min must not exceed max")
        return self


class ExternalPort(AcdModel):
    connector_node_id: NodeId
    exposure: PortExposure


class UseEnvironment(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["use_environment"] = "use_environment"
    graph_id: NonEmptyStr
    revision: Revision
    installation: Installation
    power_system: PowerSystem
    temperature_c: TemperatureRange
    humidity_rh_pct: HumidityRange
    vibration: Vibration
    external_ports: list[ExternalPort] = Field(default_factory=list[ExternalPort])

    @model_validator(mode="after")
    def validate_ports(self) -> UseEnvironment:
        connector_ids = [port.connector_node_id for port in self.external_ports]
        if len(connector_ids) != len(set(connector_ids)):
            raise ValueError("external_ports connector_node_id entries must be unique")
        return self
