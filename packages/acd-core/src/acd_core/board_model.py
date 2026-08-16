"""Tool-neutral physical board model shared by ECAD adapters.

Coordinates are millimetres in the KiCad board frame: origin at the board
upper-left corner, X to the right, Y downward. Rotations are degrees
counter-clockwise. Adapters translate this model into tool-specific formats
(KiCad board files, Specctra DSN) without owning pass/fail decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PadShape:
    """Pad geometry relative to the footprint origin (unrotated)."""

    number: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    shape: str  # circle | rect | roundrect | oval | custom
    size_x_mm: float
    size_y_mm: float
    through_hole: bool
    drill_mm: float | None
    on_front: bool
    on_back: bool


@dataclass(frozen=True)
class FootprintShape:
    """Pad set of one footprint, parsed from a pinned library file."""

    library_ref: str  # e.g. "Espressif:ESP32-C3-MINI-1"
    pads: tuple[PadShape, ...]
    courtyard_bbox_mm: tuple[float, float, float, float] | None = None
    body_bbox_mm: tuple[float, float, float, float] | None = None
    keepout_bboxes_mm: tuple[tuple[float, float, float, float], ...] = ()


@dataclass(frozen=True)
class ComponentPlacement:
    refdes: str
    footprint: FootprintShape
    x_mm: float
    y_mm: float
    rotation_deg: float
    side: str = "front"


@dataclass(frozen=True)
class BoardNet:
    """One electrical net with its pad connections (refdes, pad number)."""

    name: str
    pads: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class NetClass:
    """Deterministic routing class and its net membership."""

    name: str
    width_mm: float
    nets: tuple[str, ...]


@dataclass(frozen=True)
class KeepoutRect:
    """Rectangular all-layer keepout (no copper, tracks, or vias)."""

    name: str
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float


@dataclass(frozen=True)
class CopperZone:
    """Copper pour declaration projected into a KiCad zone."""

    net: str
    layers: tuple[str, ...]
    inset_mm: float
    min_island_area_mm2: float
    thermal_relief: bool = True


@dataclass(frozen=True)
class RoutedWire:
    """One routed wire polyline on a copper layer (mm, KiCad frame)."""

    net: str
    layer: str
    width_mm: float
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class RoutedVia:
    net: str
    x_mm: float
    y_mm: float


@dataclass(frozen=True)
class RoutedDesign:
    wires: tuple[RoutedWire, ...]
    vias: tuple[RoutedVia, ...]
    observed_min_width_mm: float | None = None
    normalized_wire_count: int = 0


@dataclass(frozen=True)
class BoardModel:
    width_mm: float
    height_mm: float
    layers: int
    min_track_mm: float
    min_clearance_mm: float
    via_drill_mm: float
    via_diameter_mm: float
    edge_clearance_mm: float
    placements: tuple[ComponentPlacement, ...]
    nets: tuple[BoardNet, ...]
    keepouts: tuple[KeepoutRect, ...] = field(default_factory=tuple)
    copper_zones: tuple[CopperZone, ...] = field(default_factory=tuple)
    stitch_via_pitch_mm: float | None = None
    stitch_via_net: str | None = None
    stitch_via_refill_max_iterations: int | None = None
    netclasses: tuple[NetClass, ...] = ()

    def placement_by_refdes(self, refdes: str) -> ComponentPlacement:
        for placement in self.placements:
            if placement.refdes == refdes:
                return placement
        raise KeyError(refdes)
