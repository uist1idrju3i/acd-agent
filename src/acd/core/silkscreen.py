"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.silkscreen``.
"""

from acd.core.electrical.silkscreen import (
    SilkGraphicPartView,
    SilkGraphicView,
    SilkscreenLane,
    SilkTextView,
    extract_silkscreen_lane,
)

__all__ = [
    "SilkGraphicPartView",
    "SilkGraphicView",
    "SilkTextView",
    "SilkscreenLane",
    "extract_silkscreen_lane",
]
