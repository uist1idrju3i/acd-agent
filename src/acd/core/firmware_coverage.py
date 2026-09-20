"""Compatibility re-export.

The implementation lives in ``acd.core.firmware.firmware_coverage``.
"""

from acd.core.firmware.firmware_coverage import (
    FirmwareCoverageCode,
    FirmwareCoverageFinding,
    FirmwareCoverageReport,
    check_firmware_coverage,
)

__all__ = [
    "FirmwareCoverageCode",
    "FirmwareCoverageFinding",
    "FirmwareCoverageReport",
    "check_firmware_coverage",
]
