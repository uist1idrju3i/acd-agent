"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.routing_width``.
"""

from acd.core.electrical.routing_width import (
    MM_TO_MIL,
    NetWidthRequirement,
    derive_net_widths,
    group_netclasses,
)

__all__ = [
    "MM_TO_MIL",
    "NetWidthRequirement",
    "derive_net_widths",
    "group_netclasses",
]
