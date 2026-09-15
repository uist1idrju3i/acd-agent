"""Deterministic firmware security declaration/build consistency gate."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Literal, cast

from pydantic import ValidationError

from acd.core.fileio import read_json
from acd.schema.fw_security import (
    FirmwareSecurityDeclaration,
    FirmwareSecurityFinding,
    FirmwareSecurityGateResult,
)

_FLASH_SIZE_RE = re.compile(r"CONFIG_ESPTOOLPY_FLASHSIZE_(\d+)MB=y")
_CONFIG_RE = re.compile(r"^([A-Z0-9_]+)=(.*)$")


def _parse_sdkconfig(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _CONFIG_RE.fullmatch(line)
        if match is not None:
            values[match.group(1)] = match.group(2).strip('"')
    return values


def _parse_partitions(path: Path) -> list[dict[str, str | bool]]:
    rows: list[dict[str, str | bool]] = []
    for row in csv.reader(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ):
        if len(row) < 5:
            raise ValueError("partition CSV row has fewer than five columns")
        name, kind, subtype, offset, size = (item.strip() for item in row[:5])
        flags = row[5].strip().lower() if len(row) > 5 else ""
        rows.append(
            {
                "name": name,
                "type": "app" if kind == "app" else "data",
                "subtype": subtype,
                "offset_hex": offset.lower(),
                "size_hex": size.lower(),
                "encrypted": "encrypted" in flags.split(),
            }
        )
    if not rows:
        raise ValueError("partition CSV is empty")
    return rows


def _finding(
    rule_id: str, status: Literal["fail", "unknown"], message: str
) -> FirmwareSecurityFinding:
    return FirmwareSecurityFinding(rule_id=rule_id, status=status, message=message)


def _text_field(item: dict[str, str | bool], key: str) -> str:
    value = item[key]
    if not isinstance(value, str):
        raise ValueError(f"partition field {key} is not text")
    return value


def check_build_config_consistency(
    declaration: FirmwareSecurityDeclaration,
    sdkconfig_path: Path,
    partition_table_path: Path,
    *,
    size_json_path: Path | None = None,
) -> FirmwareSecurityGateResult:
    """Compare a security declaration with generated ESP-IDF build inputs."""
    findings: list[FirmwareSecurityFinding] = []
    try:
        config = _parse_sdkconfig(sdkconfig_path)
        actual_partitions = _parse_partitions(partition_table_path)
        declared = [item.model_dump(mode="json") for item in declaration.partition_table]
        normalized_actual = sorted(actual_partitions, key=lambda item: str(item["name"]))
        normalized_declared = sorted(declared, key=lambda item: str(item["name"]))
        if normalized_actual != normalized_declared:
            findings.append(
                _finding(
                    "partition_table_mismatch",
                    "fail",
                    "effective partition table differs from declaration",
                )
            )
        expected_flags = {
            "CONFIG_SECURE_BOOT": declaration.secure_boot.enabled,
            "CONFIG_SECURE_BOOT_V2_ENABLED": declaration.secure_boot.scheme
            == "secure_boot_v2",
            "CONFIG_SECURE_FLASH_ENC_ENABLED": declaration.flash_encryption.enabled,
            "CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE": declaration.flash_encryption.mode
            == "release",
            "CONFIG_SECURE_FLASH_ENCRYPTION_MODE_DEVELOPMENT": declaration.flash_encryption.mode
            == "development",
            "CONFIG_PARTITION_TABLE_CUSTOM": True,
            "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE": declaration.ota.rollback_enabled,
            "CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK": declaration.ota.anti_rollback_enabled,
        }
        if declaration.ota.enabled:
            expected_flags["CONFIG_BOOTLOADER_APP_SECURE_VERSION"] = True
        for key, expected in expected_flags.items():
            actual = config.get(key) == "y" if key != "CONFIG_BOOTLOADER_APP_SECURE_VERSION" else (
                config.get(key) == str(declaration.ota.secure_version)
            )
            if actual != expected:
                findings.append(
                    _finding(
                        "sdkconfig_mismatch",
                        "fail",
                        f"{key} does not match declaration",
                    )
                )
        security_keys = {
            "CONFIG_SECURE_BOOT",
            "CONFIG_SECURE_BOOT_V2_ENABLED",
            "CONFIG_SECURE_FLASH_ENC_ENABLED",
            "CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE",
            "CONFIG_SECURE_FLASH_ENCRYPTION_MODE_DEVELOPMENT",
            "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE",
            "CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK",
        }
        undeclared = [
            key for key in sorted(security_keys)
            if config.get(key) == "y" and not expected_flags.get(key, False)
        ]
        if undeclared:
            findings.append(
                _finding(
                    "undeclared_security_config",
                    "fail",
                    "build enables undeclared security settings: " + ", ".join(undeclared),
                )
            )
        flash_size = next(
            (int(match.group(1)) * 1024 * 1024
             for key, value in config.items()
             if value == "y"
             for match in [_FLASH_SIZE_RE.fullmatch(key)]
             if match is not None),
            None,
        )
        if flash_size is not None:
            end = max(
                int(_text_field(item, "offset_hex"), 16)
                + int(_text_field(item, "size_hex"), 16)
                for item in normalized_actual
            )
            if end > flash_size:
                findings.append(
                    _finding(
                        "flash_size_exceeded",
                        "fail",
                        "partitions exceed configured flash size",
                    )
                )
        if size_json_path is not None:
            size_data = read_json(size_json_path)
            if not isinstance(size_data, dict):
                raise ValueError("size report must be an object")
            size_values = cast(dict[str, object], size_data)
            app_bytes = size_values.get("app_bin_bytes")
            headroom = size_values.get("headroom_bytes", 0)
            if not isinstance(app_bytes, int) or not isinstance(headroom, int):
                raise ValueError("size report requires app_bin_bytes and headroom_bytes")
            capacity = max(
                int(_text_field(item, "size_hex"), 16)
                for item in normalized_actual
                if item["type"] == "app"
            )
            if capacity < app_bytes + headroom:
                findings.append(
                    _finding(
                        "app_partition_size",
                        "fail",
                        "app partition is smaller than firmware plus headroom",
                    )
                )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, csv.Error) as exc:
        findings.append(_finding("security_inputs", "unknown", str(exc)))
    status = "fail" if any(item.status == "fail" for item in findings) else (
        "unknown" if findings else "pass"
    )
    return FirmwareSecurityGateResult(
        graph_id=declaration.graph_id,
        revision=declaration.revision,
        status=status,
        declaration_sha256="sha256:" + hashlib.sha256(
            declaration.model_dump_json(by_alias=False).encode("utf-8")
        ).hexdigest(),
        findings=findings,
    )


def validate_security_gate_result(
    path: Path,
    *,
    graph_id: str,
    revision: str,
) -> FirmwareSecurityGateResult:
    """Load and strictly validate a Skill-emitted gate result."""
    try:
        result = FirmwareSecurityGateResult.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError, ValidationError) as exc:
        raise ValueError(f"firmware security gate result is invalid: {exc}") from exc
    if result.graph_id != graph_id or result.revision != revision:
        raise ValueError("firmware security gate result revision mismatch")
    return result


__all__ = ["check_build_config_consistency", "validate_security_gate_result"]
