"""Compatibility re-export.

The implementation lives in ``acd.core.firmware.firmware_capability_entry``.
"""

from acd.core.firmware.firmware_capability_entry import (
    FirmwareCapabilityEntryResult,
    register_firmware_capability,
)

__all__ = [
    "FirmwareCapabilityEntryResult",
    "register_firmware_capability",
]
