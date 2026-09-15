"""Firmware security declaration contract tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from acd.schema.fw_security import FirmwareSecurityDeclaration

FIXTURE = Path("fixtures/golden-design-1/fw-security.json")


def _payload() -> dict[str, object]:
    return cast(dict[str, object], json.loads(FIXTURE.read_text(encoding="utf-8")))


def _overlap(value: dict[str, Any]) -> None:
    value["partition_table"].append(
        {
            "name": "overlap",
            "type": "data",
            "subtype": "spiffs",
            "offset_hex": "0x9000",
            "size_hex": "0x1000",
            "encrypted": False,
        }
    )


def _without_otadata(value: dict[str, Any]) -> None:
    value["partition_table"].remove(
        next(item for item in value["partition_table"] if item["subtype"] == "otadata")
    )


def _release_without_secure_boot(value: dict[str, Any]) -> None:
    value["flash_encryption"].update({"mode": "release"})
    value["secure_boot"].update(
        {
            "enabled": False,
            "scheme": "none",
            "key_boundary": "none",
            "signing_key_id": "none",
        }
    )


def _key_like(value: dict[str, Any]) -> None:
    value["secure_boot"].update({"signing_key_id": "a" * 32})


_INVALID_MUTATIONS: list[Callable[[dict[str, Any]], None]] = [
    _overlap,
    _without_otadata,
    _release_without_secure_boot,
    _key_like,
]


def test_gd1_security_declaration_is_strict_and_valid() -> None:
    declaration = FirmwareSecurityDeclaration.model_validate(_payload())
    assert declaration.ota.slots == 2
    assert declaration.secure_boot.key_boundary == "external_hsm"


@pytest.mark.parametrize(
    "mutate",
    _INVALID_MUTATIONS,
)
def test_invalid_security_declarations_are_rejected(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    value = _payload()
    mutate(value)
    with pytest.raises(ValidationError):
        FirmwareSecurityDeclaration.model_validate(value)


def test_unknown_fields_are_rejected() -> None:
    value = _payload()
    value["unexpected"] = True
    with pytest.raises(ValidationError):
        FirmwareSecurityDeclaration.model_validate(value)
