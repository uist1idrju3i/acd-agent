"""Tests for the firmware capability declaration entrypoint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.firmware_capability import (
    FirmwareCapabilityContractError,
    load_firmware_capability_registry,
)
from acd.core.firmware_capability_entry import register_firmware_capability

REGISTRY_SOURCE = (
    Path(__file__).parents[2] / "contracts" / "firmware-capability-registry.json"
)


def _capability(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "capability_id": "uart_echo",
        "actions": ["echo_uart_line"],
        "required_pin_roles": ["uart_tx", "uart_rx"],
        "requires_device": False,
    }
    value.update(overrides)
    return value


def _registry_copy(tmp_path: Path) -> Path:
    path = tmp_path / "firmware-capability-registry.json"
    path.write_text(REGISTRY_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_dry_run_reports_hashes_without_writing(tmp_path: Path) -> None:
    registry_path = _registry_copy(tmp_path)
    before = registry_path.read_text(encoding="utf-8")

    result = register_firmware_capability(
        _capability(), registry_path, dry_run=True
    )

    assert result.written is False
    assert result.capability_source == "mapping"
    assert result.prior_registry_hash != result.new_registry_hash
    assert registry_path.read_text(encoding="utf-8") == before


def test_registers_capability_atomically(tmp_path: Path) -> None:
    registry_path = _registry_copy(tmp_path)
    capability_path = tmp_path / "capability.json"
    capability_path.write_text(json.dumps(_capability()), encoding="utf-8")

    result = register_firmware_capability(capability_path, registry_path)

    assert result.written is True
    assert result.capability_source == str(capability_path)
    registry = load_firmware_capability_registry(registry_path)
    assert "uart_echo" in {item.capability_id for item in registry.capabilities}
    assert registry.registry_hash == result.new_registry_hash


def test_inline_json_declaration_is_accepted(tmp_path: Path) -> None:
    registry_path = _registry_copy(tmp_path)

    result = register_firmware_capability(
        json.dumps(_capability()), registry_path
    )

    assert result.capability_source == "inline"
    assert result.written is True


def test_duplicate_capability_id_is_rejected(tmp_path: Path) -> None:
    registry_path = _registry_copy(tmp_path)
    before = registry_path.read_text(encoding="utf-8")

    with pytest.raises(FirmwareCapabilityContractError, match="already registered"):
        register_firmware_capability(
            _capability(capability_id="led_blink", actions=["blink_twice"]),
            registry_path,
        )

    assert registry_path.read_text(encoding="utf-8") == before


def test_duplicate_action_is_rejected(tmp_path: Path) -> None:
    registry_path = _registry_copy(tmp_path)

    with pytest.raises(FirmwareCapabilityContractError, match="actions"):
        register_firmware_capability(
            _capability(actions=["toggle_led"]), registry_path
        )


def test_unknown_pin_role_is_rejected(tmp_path: Path) -> None:
    registry_path = _registry_copy(tmp_path)

    with pytest.raises(FirmwareCapabilityContractError, match="pin roles"):
        register_firmware_capability(
            _capability(required_pin_roles=["spi_sck"]), registry_path
        )


def test_device_requirement_without_declared_device_is_rejected(
    tmp_path: Path,
) -> None:
    document = json.loads(REGISTRY_SOURCE.read_text(encoding="utf-8"))
    document["devices"] = []
    document["capabilities"] = [
        item
        for item in document["capabilities"]
        if not item["requires_device"]
    ]
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FirmwareCapabilityContractError, match="declares none"):
        register_firmware_capability(
            _capability(requires_device=True), registry_path
        )


def test_malformed_declaration_is_rejected(tmp_path: Path) -> None:
    registry_path = _registry_copy(tmp_path)

    with pytest.raises(FirmwareCapabilityContractError, match="JSON is invalid"):
        register_firmware_capability("{not json", registry_path)

    with pytest.raises(FirmwareCapabilityContractError, match="readable"):
        register_firmware_capability("missing-capability", registry_path)
