from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.firmware_capability import (
    FirmwareCapabilityContractError,
    load_firmware_capability_registry,
)


def test_firmware_capability_registry_loads_with_canonical_hash() -> None:
    registry = load_firmware_capability_registry()
    assert registry.registry_hash.startswith("sha256:")
    assert registry.document.registry_id == "acd-firmware-capabilities-14.14"


def test_firmware_capability_registry_rejects_unreadable_json(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(FirmwareCapabilityContractError, match="invalid"):
        load_firmware_capability_registry(path)


def test_firmware_capability_registry_hash_is_stable(tmp_path: Path) -> None:
    source = load_firmware_capability_registry()
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(source.document.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    copied = load_firmware_capability_registry(path)
    assert copied.registry_hash == source.registry_hash
