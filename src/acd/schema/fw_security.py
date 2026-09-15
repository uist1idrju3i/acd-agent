"""Strict declarations for ESP32-C3 firmware security design."""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Literal, cast

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
)

SecurityStatus = Literal["pass", "fail", "unknown"]
KeyBoundary = Literal[
    "none", "external_hsm", "factory_provisioning", "dev_only_unsigned"
]

_HEX = re.compile(r"^0x[0-9a-fA-F]+$")
_IDENTIFIER = re.compile(r"^[a-z0-9_.-]{1,64}$")
_KEY_HEX = re.compile(r"^[0-9a-fA-F]{32,}$")


class SecureBootDeclaration(AcdModel):
    enabled: bool
    scheme: Literal["none", "secure_boot_v2"]
    key_boundary: KeyBoundary
    signing_key_id: str

    @model_validator(mode="after")
    def validate_secure_boot(self) -> SecureBootDeclaration:
        if not _IDENTIFIER.fullmatch(self.signing_key_id):
            raise ValueError("signing_key_id must be a lowercase identifier")
        if self.enabled and (
            self.scheme != "secure_boot_v2" or self.key_boundary == "none"
        ):
            raise ValueError(
                "enabled secure boot requires secure_boot_v2 and a key boundary"
            )
        if not self.enabled and self.scheme != "none":
            raise ValueError("disabled secure boot must use scheme none")
        if self.key_boundary == "none" and self.signing_key_id != "none":
            raise ValueError("key_boundary none requires signing_key_id none")
        return self


class FlashEncryptionDeclaration(AcdModel):
    enabled: bool
    mode: Literal["none", "development", "release"]
    key_boundary: KeyBoundary

    @model_validator(mode="after")
    def validate_flash_encryption(self) -> FlashEncryptionDeclaration:
        if not self.enabled and self.mode != "none":
            raise ValueError("disabled flash encryption must use mode none")
        if self.enabled and self.mode == "none":
            raise ValueError("enabled flash encryption requires a mode")
        if self.enabled and self.key_boundary == "none":
            raise ValueError("enabled flash encryption requires a key boundary")
        return self


class PartitionDeclaration(AcdModel):
    name: NonEmptyStr
    type: Literal["app", "data"]
    subtype: Literal[
        "factory",
        "ota_0",
        "ota_1",
        "otadata",
        "nvs",
        "nvs_keys",
        "phy_init",
        "spiffs",
        "custom",
    ]
    offset_hex: str
    size_hex: str
    encrypted: bool

    @model_validator(mode="after")
    def validate_partition(self) -> PartitionDeclaration:
        if not _HEX.fullmatch(self.offset_hex) or not _HEX.fullmatch(self.size_hex):
            raise ValueError("partition offsets and sizes must be hexadecimal")
        if int(self.size_hex, 16) <= 0:
            raise ValueError("partition size must be positive")
        offset = int(self.offset_hex, 16)
        alignment = 0x10000 if self.type == "app" else 0x1000
        if offset % alignment:
            raise ValueError(
                f"{self.type} partition offset must align to 0x{alignment:x}"
            )
        if int(self.size_hex, 16) % 0x1000:
            raise ValueError("partition size must align to 0x1000")
        if self.subtype in {"factory", "ota_0", "ota_1"} and self.type != "app":
            raise ValueError("application subtype requires app partition type")
        if self.subtype not in {"factory", "ota_0", "ota_1"} and self.type != "data":
            raise ValueError("data subtype requires data partition type")
        return self


class OtaDeclaration(AcdModel):
    enabled: bool
    slots: int = Field(ge=0)
    rollback_enabled: bool
    anti_rollback_enabled: bool
    secure_version: int = Field(ge=0)


class FirmwareSecurityDeclaration(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["firmware_security_declaration"] = (
        "firmware_security_declaration"
    )
    graph_id: NonEmptyStr
    revision: Revision
    secure_boot: SecureBootDeclaration
    flash_encryption: FlashEncryptionDeclaration
    partition_table: list[PartitionDeclaration] = Field(min_length=1)
    ota: OtaDeclaration

    @model_validator(mode="before")
    @classmethod
    def reject_key_material(cls, value: object) -> object:
        def visit(item: object, path: str = "") -> None:
            if isinstance(item, str) and (
                "-----BEGIN" in item or _KEY_HEX.fullmatch(item)
            ):
                raise ValueError(f"key material is forbidden at {path or 'value'}")
            if isinstance(item, dict):
                mapping = cast(dict[object, object], item)
                for key, child in mapping.items():
                    visit(child, f"{path}.{key}" if path else str(key))
            elif isinstance(item, list):
                children = cast(list[object], item)
                for index, child in enumerate(children):
                    visit(child, f"{path}[{index}]")

        visit(value)
        return value

    @model_validator(mode="after")
    def validate_declaration(self) -> FirmwareSecurityDeclaration:
        names = [item.name for item in self.partition_table]
        if len(names) != len(set(names)):
            raise ValueError("partition names must be unique")
        ranges = sorted(
            (int(item.offset_hex, 16), int(item.offset_hex, 16) + int(item.size_hex, 16), item.name)
            for item in self.partition_table
        )
        for previous, current in pairwise(ranges):
            if current[0] < previous[1]:
                raise ValueError(
                    f"partition ranges overlap: {previous[2]} and {current[2]}"
                )
        if self.ota.enabled:
            ota_parts = [
                part for part in self.partition_table if part.subtype in {"ota_0", "ota_1"}
            ]
            if self.ota.slots < 2 or len(ota_parts) < 2:
                raise ValueError("enabled OTA requires at least two OTA app partitions")
            if len({int(part.size_hex, 16) for part in ota_parts}) != 1:
                raise ValueError("OTA app partitions must have equal size")
            if not any(part.subtype == "otadata" for part in self.partition_table):
                raise ValueError("enabled OTA requires an otadata partition")
        if self.flash_encryption.enabled:
            if not any(part.subtype == "nvs_keys" for part in self.partition_table):
                raise ValueError("flash encryption requires an nvs_keys partition")
            required = {"otadata"} | (
                {part.subtype for part in self.partition_table if part.type == "app"}
            )
            for part in self.partition_table:
                if part.subtype in required and not part.encrypted:
                    raise ValueError(f"encrypted flag required for {part.name}")
        if self.flash_encryption.mode == "release" and not self.secure_boot.enabled:
            raise ValueError("release flash encryption requires secure boot")
        return self


class FirmwareSecurityFinding(AcdModel):
    rule_id: NonEmptyStr
    status: Literal["fail", "unknown"]
    message: NonEmptyStr


class FirmwareSecurityGateResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["firmware_security_gate_result"] = (
        "firmware_security_gate_result"
    )
    graph_id: NonEmptyStr
    revision: Revision
    status: SecurityStatus
    authority: Literal["gate"] = "gate"
    declaration_sha256: Sha256
    findings: list[FirmwareSecurityFinding] = Field(
        default_factory=list[FirmwareSecurityFinding]
    )


__all__ = [
    "FirmwareSecurityDeclaration",
    "FirmwareSecurityFinding",
    "FirmwareSecurityGateResult",
    "FlashEncryptionDeclaration",
    "KeyBoundary",
    "OtaDeclaration",
    "PartitionDeclaration",
    "SecureBootDeclaration",
    "SecurityStatus",
]
