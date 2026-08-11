"""Firmware package projection (mirrors ``schemas/fw-package.schema.json``)."""

from __future__ import annotations

from pydantic import Field, model_validator

from acd_schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    HashOrUnknown,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    VersionOrUnknown,
)


class PinAssignment(AcdModel):
    pin: NonEmptyStr
    net: NodeId
    function: NonEmptyStr


class BuildInfo(AcdModel):
    toolchain_version: VersionOrUnknown
    source_hash: HashOrUnknown
    artifact_hash: HashOrUnknown

    def has_unknown(self) -> bool:
        return "unknown" in {self.toolchain_version, self.source_hash, self.artifact_hash}


class FwPackage(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    package_id: NonEmptyStr
    target_revision: Revision
    modules: list[NodeId] = Field(default_factory=list[NodeId])
    pin_assignments: list[PinAssignment] = Field(default_factory=list[PinAssignment])
    build: BuildInfo

    @model_validator(mode="after")
    def _unique_modules_and_pins(self) -> FwPackage:
        if len(set(self.modules)) != len(self.modules):
            raise ValueError("modules must be unique")
        pins = [assignment.pin for assignment in self.pin_assignments]
        if len(set(pins)) != len(pins):
            raise ValueError("pin assignments must not assign the same pin twice")
        return self
