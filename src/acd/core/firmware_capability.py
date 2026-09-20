"""Compatibility re-export.

The implementation lives in ``acd.core.firmware.firmware_capability``.
"""

from acd.core.firmware.firmware_capability import (
    FirmwareCapabilityContractError,
    FirmwareCapabilityRegistry,
    load_firmware_capability_registry,
)

__all__ = [
    "FirmwareCapabilityContractError",
    "FirmwareCapabilityRegistry",
    "load_firmware_capability_registry",
]
