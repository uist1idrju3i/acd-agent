"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.board_model``.
"""

from acd.core.electrical.board_model import (
    BoardModel,
    BoardNet,
    ComponentPlacement,
    CopperZone,
    EdgeOverhangDeclaration,
    FootprintShape,
    KeepoutRect,
    MountHole,
    NetClass,
    PadShape,
    PlacementAnnotations,
    RoutedDesign,
    RoutedVia,
    RoutedWire,
)

__all__ = [
    "BoardModel",
    "BoardNet",
    "ComponentPlacement",
    "CopperZone",
    "EdgeOverhangDeclaration",
    "FootprintShape",
    "KeepoutRect",
    "MountHole",
    "NetClass",
    "PadShape",
    "PlacementAnnotations",
    "RoutedDesign",
    "RoutedVia",
    "RoutedWire",
]
