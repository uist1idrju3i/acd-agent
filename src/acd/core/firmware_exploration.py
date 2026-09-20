"""Compatibility re-export.

The implementation lives in ``acd.core.firmware.firmware_exploration``.
"""

from acd.core.firmware.firmware_exploration import (
    FIRMWARE_SEARCHABLE_DIMENSIONS,
    RequiredDeclaration,
    explore_firmware_candidates,
    load_firmware_coverage_findings,
)

__all__ = [
    "FIRMWARE_SEARCHABLE_DIMENSIONS",
    "RequiredDeclaration",
    "explore_firmware_candidates",
    "load_firmware_coverage_findings",
]
