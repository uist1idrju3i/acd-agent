"""Firmware security build consistency gate tests."""

from __future__ import annotations

import json
from pathlib import Path

from acd.core.firmware.fw_security_gate import (
    check_build_config_consistency,
    validate_security_gate_result,
)
from acd.schema.fw_security import FirmwareSecurityDeclaration

ROOT = Path("fixtures/golden-design-1")


def _declaration() -> FirmwareSecurityDeclaration:
    return FirmwareSecurityDeclaration.model_validate_json(
        (ROOT / "fw-security.json").read_text(encoding="utf-8")
    )


def test_rendered_build_pair_passes() -> None:
    result = check_build_config_consistency(
        _declaration(),
        ROOT / "fw-security-sdkconfig",
        ROOT / "fw-security-partitions.csv",
    )
    assert result.status == "pass"
    assert result.authority == "gate"


def test_missing_secure_boot_fails(tmp_path: Path) -> None:
    sdkconfig = (ROOT / "fw-security-sdkconfig").read_text(encoding="utf-8")
    sdkconfig = sdkconfig.replace("CONFIG_SECURE_BOOT=y\n", "")
    config_path = tmp_path / "sdkconfig"
    config_path.write_text(sdkconfig, encoding="utf-8")
    result = check_build_config_consistency(
        _declaration(), config_path, ROOT / "fw-security-partitions.csv"
    )
    assert result.status == "fail"


def test_missing_sdkconfig_is_unknown(tmp_path: Path) -> None:
    result = check_build_config_consistency(
        _declaration(), tmp_path / "missing", ROOT / "fw-security-partitions.csv"
    )
    assert result.status == "unknown"


def test_undeclared_flash_encryption_fails(tmp_path: Path) -> None:
    declaration = json.loads((ROOT / "fw-security.json").read_text(encoding="utf-8"))
    declaration["flash_encryption"] = {
        "enabled": False,
        "mode": "none",
        "key_boundary": "none",
    }
    result = check_build_config_consistency(
        FirmwareSecurityDeclaration.model_validate(declaration),
        ROOT / "fw-security-sdkconfig",
        ROOT / "fw-security-partitions.csv",
    )
    assert result.status == "fail"


def test_gate_result_revision_mismatch_is_rejected(tmp_path: Path) -> None:
    result = check_build_config_consistency(
        _declaration(),
        ROOT / "fw-security-sdkconfig",
        ROOT / "fw-security-partitions.csv",
    )
    path = tmp_path / "result.json"
    path.write_text(result.model_dump_json(), encoding="utf-8")
    try:
        validate_security_gate_result(
            path, graph_id="golden-design-1", revision="r2"
        )
    except ValueError as exc:
        assert "revision mismatch" in str(exc)
    else:
        raise AssertionError("revision mismatch must be rejected")
