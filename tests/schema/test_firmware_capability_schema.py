from __future__ import annotations

import pytest
from pydantic import ValidationError

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
