"""Mechanical lane: CAD normalization, enclosure, FEM, structural safety."""

from acd.core.mechanical.mechanical import (
    MECHANISM_DIMENSIONS,
    MECHANISM_FACES,
    MECHANISM_FEATURE_TYPES,
    REQUIRED_MECHANICAL_ATTRS,
    SUPPORTED_OPENING_FACES,
    BoardEdgeOverhangView,
    ComponentBodyView,
    ConnectorOpeningView,
    EnclosureView,
    MechanicalLane,
    MechanismFeatureView,
    MotionCheckView,
    MountHoleView,
    OutlineView,
    extract_mechanical_lane,
    placement_annotations,
)

__all__ = [
    "MECHANISM_DIMENSIONS",
    "MECHANISM_FACES",
    "MECHANISM_FEATURE_TYPES",
    "REQUIRED_MECHANICAL_ATTRS",
    "SUPPORTED_OPENING_FACES",
    "BoardEdgeOverhangView",
    "ComponentBodyView",
    "ConnectorOpeningView",
    "EnclosureView",
    "MechanicalLane",
    "MechanismFeatureView",
    "MotionCheckView",
    "MountHoleView",
    "OutlineView",
    "extract_mechanical_lane",
    "placement_annotations",
]
