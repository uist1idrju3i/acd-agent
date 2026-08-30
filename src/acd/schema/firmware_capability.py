"""Pydantic contracts for graph-driven firmware capabilities."""

from __future__ import annotations

from pydantic import Field, model_validator

from acd.schema.common import AcdModel, NonEmptyStr, SchemaVersion


class FirmwareCapabilityContract(AcdModel):
    capability_id: NonEmptyStr
    actions: list[NonEmptyStr] = Field(min_length=1)
    required_pin_roles: list[NonEmptyStr] = Field(default_factory=list)
    requires_device: bool = False

    @model_validator(mode="after")
    def _unique_values(self) -> FirmwareCapabilityContract:
        if len(self.actions) != len(set(self.actions)):
            raise ValueError("firmware capability actions must be unique")
        if len(self.required_pin_roles) != len(set(self.required_pin_roles)):
            raise ValueError("firmware capability pin roles must be unique")
        return self


class FirmwareDeviceContract(AcdModel):
    mpn: NonEmptyStr
    driver_id: NonEmptyStr
    i2c_address: int = Field(ge=0, le=0x7F)
    measurement_command: int = Field(ge=0, le=0xFF)
    source_url: NonEmptyStr
    source_ref: NonEmptyStr


class FirmwareCapabilityRegistryDocument(AcdModel):
    schema_version: SchemaVersion
    registry_id: NonEmptyStr
    pin_role_order: list[NonEmptyStr] = Field(min_length=1)
    capabilities: list[FirmwareCapabilityContract] = Field(min_length=1)
    devices: list[FirmwareDeviceContract] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_registry_values(self) -> FirmwareCapabilityRegistryDocument:
        if len(self.pin_role_order) != len(set(self.pin_role_order)):
            raise ValueError("firmware pin_role_order values must be unique")
        capability_ids = [item.capability_id for item in self.capabilities]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("firmware capability_id values must be unique")
        actions = [action for item in self.capabilities for action in item.actions]
        if len(actions) != len(set(actions)):
            raise ValueError("firmware capability action values must be unique")
        mpns = [item.mpn for item in self.devices]
        if len(mpns) != len(set(mpns)):
            raise ValueError("firmware device mpn values must be unique")
        return self


__all__ = [
    "FirmwareCapabilityContract",
    "FirmwareCapabilityRegistryDocument",
    "FirmwareDeviceContract",
]
