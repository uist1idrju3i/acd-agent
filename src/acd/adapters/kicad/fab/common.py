"""Shared fabrication errors and measurement models."""
# ruff: noqa

from __future__ import annotations

from dataclasses import dataclass


class FabOutputError(ValueError):
    """Raised when manufacturing output cannot be proven correct."""


class UncoveredStitchViasError(FabOutputError):
    """Raised when filled Gerbers do not cover requested stitch vias."""

    def __init__(self, locations: tuple[tuple[float, float], ...]) -> None:
        self.locations = locations
        locations_text = ", ".join(f"({x}, {y})" for x, y in locations)
        super().__init__(f"stitch vias lack copper coverage (fail-closed): {locations_text}")


class UncoveredGroundRegionsError(FabOutputError):
    """Raised when a conductor region has no GND connection point."""

    def __init__(
        self,
        regions: tuple[tuple[str, tuple[float, float, float, float]], ...],
    ) -> None:
        self.regions = regions
        regions_text = ", ".join(
            f"layer={layer}, bbox_mm={bbox_mm}" for layer, bbox_mm in regions
        )
        super().__init__(
            "Conductor region lacks a GND connection point (fail-closed): "
            f"{regions_text}"
        )


@dataclass(frozen=True)
class GerberRegionRecord:
    function: str
    points_mm: tuple[tuple[float, float], ...]
    area_mm2: float
    bbox_mm: tuple[float, float, float, float]


class CplBasisError(FabOutputError):
    """Raised when CPL basis or provenance is unknown."""

    def __init__(self, message: str, report: dict[str, object]) -> None:
        super().__init__(message)
        self.report = report


@dataclass(frozen=True)
class PadMeasurement:
    refdes: str
    kind: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    size_x_mm: float
    size_y_mm: float
    drill_mm: float | None
    net: str | None
    drill_x_mm: float | None = None
    drill_y_mm: float | None = None
    number: str | None = None
    layers: tuple[str, ...] = ()

    @property
    def annular_ring_mm(self) -> float | None:
        if self.drill_mm is None:
            return None
        drill_x = self.drill_x_mm if self.drill_x_mm is not None else self.drill_mm
        drill_y = self.drill_y_mm if self.drill_y_mm is not None else self.drill_mm
        assert drill_x is not None and drill_y is not None
        return min(
            (self.size_x_mm - drill_x) / 2.0,
            (self.size_y_mm - drill_y) / 2.0,
        )


@dataclass(frozen=True)
class ViaMeasurement:
    x_mm: float
    y_mm: float
    diameter_mm: float
    hole_mm: float
    layers: tuple[str, ...]


@dataclass(frozen=True)
class SegmentMeasurement:
    net: str
    layer: str
    width_mm: float
    start: tuple[float, float]
    end: tuple[float, float]


@dataclass(frozen=True)
class FootprintMeasurement:
    refdes: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    layer: str
    pads: tuple[PadMeasurement, ...]
    courtyard_bbox_mm: tuple[float, float, float, float] | None = None
    body_bbox_mm: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class BoardMeasurement:
    footprints: tuple[FootprintMeasurement, ...]
    vias: tuple[ViaMeasurement, ...]
    min_track_width_mm: float | None
    silk_min_height_mm: float | None
    silk_min_width_mm: float | None
    outline_bbox_mm: tuple[float, float, float, float] | None
    drill_tool_diameters_mm: tuple[float, ...]
    drill_object_count: int
    net_name_source: str = "unknown"
    segments: tuple[SegmentMeasurement, ...] = ()

    @property
    def pads(self) -> tuple[PadMeasurement, ...]:
        return tuple(pad for fp in self.footprints for pad in fp.pads)
