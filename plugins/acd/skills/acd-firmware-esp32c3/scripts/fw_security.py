# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@5ef3cbc14db5e30d65fc47a51aca475b8298f890",
# ]
# ///
"""Render and check the opt-in ESP32-C3 firmware security design."""

from __future__ import annotations

import json
from pathlib import Path

from acd.core.fw_security_gate import check_build_config_consistency as _check
from acd.schema.fw_security import FirmwareSecurityDeclaration


def _hex(value: str) -> str:
    return f"0x{int(value, 16):x}"


def render_partitions_csv(declaration: FirmwareSecurityDeclaration) -> str:
    """Render the canonical ESP-IDF partition CSV without key material."""
    lines = ["# Name, Type, SubType, Offset, Size, Flags"]
    for item in sorted(
        declaration.partition_table,
        key=lambda part: (int(part.offset_hex, 16), part.name),
    ):
        flags = "encrypted" if item.encrypted else ""
        lines.append(
            ",".join(
                [
                    item.name,
                    item.type,
                    item.subtype,
                    _hex(item.offset_hex),
                    _hex(item.size_hex),
                    flags,
                ]
            ).rstrip(",")
        )
    return "\n".join(lines) + "\n"


def render_sdkconfig_security(declaration: FirmwareSecurityDeclaration) -> str:
    """Render only build flags; signing key provisioning stays external."""
    lines = [
        f"CONFIG_SECURE_BOOT={'y' if declaration.secure_boot.enabled else 'n'}",
        (
            "CONFIG_SECURE_BOOT_V2_ENABLED="
            f"{'y' if declaration.secure_boot.scheme == 'secure_boot_v2' else 'n'}"
        ),
        (
            "CONFIG_SECURE_FLASH_ENC_ENABLED="
            f"{'y' if declaration.flash_encryption.enabled else 'n'}"
        ),
        "CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE="
        f"{'y' if declaration.flash_encryption.mode == 'release' else 'n'}",
        "CONFIG_SECURE_FLASH_ENCRYPTION_MODE_DEVELOPMENT="
        f"{'y' if declaration.flash_encryption.mode == 'development' else 'n'}",
        "CONFIG_PARTITION_TABLE_CUSTOM=y",
        'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"',
        (
            "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE="
            f"{'y' if declaration.ota.rollback_enabled else 'n'}"
        ),
        (
            "CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK="
            f"{'y' if declaration.ota.anti_rollback_enabled else 'n'}"
        ),
        f"CONFIG_BOOTLOADER_APP_SECURE_VERSION={declaration.ota.secure_version}",
    ]
    return "\n".join(lines) + "\n"


def check_build_config_consistency(
    declaration: FirmwareSecurityDeclaration,
    sdkconfig_path: Path,
    partition_table_path: Path,
    *,
    size_json_path: Path | None = None,
):
    return _check(
        declaration,
        sdkconfig_path,
        partition_table_path,
        size_json_path=size_json_path,
    )


def load_declaration(path: Path) -> FirmwareSecurityDeclaration:
    return FirmwareSecurityDeclaration.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


__all__ = [
    "check_build_config_consistency",
    "load_declaration",
    "render_partitions_csv",
    "render_sdkconfig_security",
]
