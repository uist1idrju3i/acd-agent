from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.core.firmware_capability import load_firmware_capability_registry
from acd.schema.firmware_capability import (
    FirmwareCapabilityRegistryDocument,
)


def _registry_payload() -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "registry_id": "test-firmware",
        "pin_role_order": ["led"],
        "capabilities": [
            {
                "capability_id": "led",
                "actions": ["toggle_led"],
                "required_pin_roles": ["led"],
                "requires_device": False,
            }
        ],
        "devices": [],
    }


def test_firmware_capability_registry_accepts_valid_document() -> None:
    document = FirmwareCapabilityRegistryDocument.model_validate(_registry_payload())
    assert document.capabilities[0].actions == ["toggle_led"]


def test_firmware_capability_accepts_emits_triggers() -> None:
    payload = _registry_payload()
    payload["capabilities"] = [
        {
            "capability_id": "led",
            "actions": ["toggle_led"],
            "required_pin_roles": ["led"],
            "emits_triggers": ["blink_tick"],
            "requires_device": False,
        }
    ]
    document = FirmwareCapabilityRegistryDocument.model_validate(payload)
    assert document.capabilities[0].emits_triggers == ["blink_tick"]


def test_firmware_capability_rejects_duplicate_emits_triggers() -> None:
    payload = _registry_payload()
    payload["capabilities"] = [
        {
            "capability_id": "led",
            "actions": ["toggle_led"],
            "required_pin_roles": ["led"],
            "emits_triggers": ["blink_tick", "blink_tick"],
            "requires_device": False,
        }
    ]
    with pytest.raises(ValidationError, match="emits_triggers"):
        FirmwareCapabilityRegistryDocument.model_validate(payload)


def test_firmware_capability_allows_shared_triggers_across_capabilities() -> None:
    payload = _registry_payload()
    payload["capabilities"] = [
        {
            "capability_id": "first",
            "actions": ["act_a"],
            "required_pin_roles": [],
            "emits_triggers": ["shared_trigger"],
            "requires_device": False,
        },
        {
            "capability_id": "second",
            "actions": ["act_b"],
            "required_pin_roles": [],
            "emits_triggers": ["shared_trigger"],
            "requires_device": False,
        },
    ]
    document = FirmwareCapabilityRegistryDocument.model_validate(payload)
    assert len(document.capabilities) == 2


def test_committed_registry_loads_with_emits_triggers() -> None:
    registry = load_firmware_capability_registry()
    emitted = {
        trigger
        for capability in registry.capabilities
        for trigger in capability.emits_triggers
    }
    assert "boot_complete" in emitted


def test_firmware_capability_registry_rejects_duplicate_actions() -> None:
    payload = _registry_payload()
    payload["capabilities"] = [
        {
            "capability_id": "first",
            "actions": ["same"],
            "required_pin_roles": [],
            "requires_device": False,
        },
        {
            "capability_id": "second",
            "actions": ["same"],
            "required_pin_roles": [],
            "requires_device": False,
        },
    ]
    with pytest.raises(ValidationError, match="action values"):
        FirmwareCapabilityRegistryDocument.model_validate(payload)
