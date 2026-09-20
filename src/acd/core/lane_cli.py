"""Compatibility re-export.

The implementation lives in ``acd.core.runtime.lane_cli``.
"""

from acd.core.runtime.lane_cli import (
    FIXTURE_HELP,
    LEGACY_FIXTURE_FLAGS,
    LEGACY_OUT_FLAGS,
    OUT_HELP,
    add_lane_io_arguments,
    add_legacy_flags,
)

__all__ = [
    "FIXTURE_HELP",
    "LEGACY_FIXTURE_FLAGS",
    "LEGACY_OUT_FLAGS",
    "OUT_HELP",
    "add_lane_io_arguments",
    "add_legacy_flags",
]
