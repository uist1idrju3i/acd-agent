"""Compatibility re-export.

The implementation lives in ``acd.core.firmware.firmware_consistency``.
"""

from acd.core.firmware.firmware_consistency import (
    FirmwareConsistencyReport,
    check_firmware_graph_consistency,
    evaluate_firmware_graph_consistency,
)

__all__ = [
    "FirmwareConsistencyReport",
    "check_firmware_graph_consistency",
    "evaluate_firmware_graph_consistency",
]
