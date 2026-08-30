"""Load the canonical firmware capability registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from acd.pipeline.repository import repository_root
from acd.schema.common import canonical_json_sha256
from acd.schema.firmware_capability import (
    FirmwareCapabilityContract,
    FirmwareCapabilityRegistryDocument,
    FirmwareDeviceContract,
)


class FirmwareCapabilityContractError(ValueError):
    """Raised when firmware capability declarations cannot be resolved safely."""


@dataclass(frozen=True)
class FirmwareCapabilityRegistry:
    document: FirmwareCapabilityRegistryDocument
    registry_hash: str
    path: Path

    @property
    def capabilities(self) -> list[FirmwareCapabilityContract]:
        return self.document.capabilities

    @property
    def devices(self) -> list[FirmwareDeviceContract]:
        return self.document.devices


def load_firmware_capability_registry(
    path: Path | None = None,
) -> FirmwareCapabilityRegistry:
    registry_path = path or repository_root() / "contracts" / "firmware-capability-registry.json"
    try:
        value = json.loads(registry_path.read_text(encoding="utf-8"))
        document = FirmwareCapabilityRegistryDocument.model_validate(value)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise FirmwareCapabilityContractError(
            f"firmware capability registry is invalid: {registry_path}: {exc}"
        ) from exc
    return FirmwareCapabilityRegistry(
        document=document,
        registry_hash=canonical_json_sha256(document.model_dump(mode="json")),
        path=registry_path,
    )


__all__ = [
    "FirmwareCapabilityContractError",
    "FirmwareCapabilityRegistry",
    "load_firmware_capability_registry",
]
