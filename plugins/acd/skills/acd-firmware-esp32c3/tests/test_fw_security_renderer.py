"""Firmware security Skill renderer tests."""

from __future__ import annotations

from pathlib import Path

from acd.schema.fw_security import FirmwareSecurityDeclaration
from fw_security import render_partitions_csv, render_sdkconfig_security

ROOT = Path(__file__).resolve().parents[5] / "fixtures" / "golden-design-1"


def test_renderers_match_recorded_fixture() -> None:
    declaration = FirmwareSecurityDeclaration.model_validate_json(
        (ROOT / "fw-security.json").read_text(encoding="utf-8")
    )
    assert render_partitions_csv(declaration) == (
        ROOT / "fw-security-partitions.csv"
    ).read_text(encoding="utf-8")
    assert "CONFIG_SECURE_BOOT_SIGNING_KEY" not in render_sdkconfig_security(
        declaration
    )


def test_security_renderer_is_deterministic() -> None:
    declaration = FirmwareSecurityDeclaration.model_validate_json(
        (ROOT / "fw-security.json").read_text(encoding="utf-8")
    )
    assert render_sdkconfig_security(declaration) == render_sdkconfig_security(
        declaration
    )
