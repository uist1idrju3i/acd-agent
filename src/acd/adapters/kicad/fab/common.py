"""Shared fabrication errors and measurement models."""
# ruff: noqa

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from acd.adapters.kicad.placement import placed_rect
from acd.core.electrical.board_model import BoardModel, RoutedDesign


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
        details: tuple[UncoveredGroundRegion, ...] = (),
    ) -> None:
        self.regions = regions
        self.details = details
        regions_text = ", ".join(
            f"layer={layer}, bbox_mm={bbox_mm}" for layer, bbox_mm in regions
        )
        message = (
            "Conductor region lacks a GND connection point (fail-closed): "
            f"{regions_text}"
        )
        if details:
            message += "\n" + "\n".join(
                "  "
                f"{detail.layer} bbox_mm={detail.bbox_mm} "
                f"area_mm2={detail.area_mm2:.3f} "
                f"enclosing_refdes={','.join(detail.enclosing_refdes) or 'none'} "
                f"nearby_tracks={','.join(detail.nearby_tracks) or 'none'} "
                f"levers: {'; '.join(detail.levers)}"
                for detail in details
            )
        super().__init__(message)


@dataclass(frozen=True)
class UncoveredGroundRegion:
    layer: str
    bbox_mm: tuple[float, float, float, float]
    area_mm2: float
    enclosing_refdes: tuple[str, ...]
    nearby_tracks: tuple[str, ...]
    levers: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "layer": self.layer,
            "bbox_mm": list(self.bbox_mm),
            "area_mm2": self.area_mm2,
            "enclosing_refdes": list(self.enclosing_refdes),
            "nearby_tracks": list(self.nearby_tracks),
            "levers": list(self.levers),
        }


def _expanded_bbox(
    bbox_mm: tuple[float, float, float, float], margin_mm: float
) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = bbox_mm
    return x1 - margin_mm, y1 - margin_mm, x2 + margin_mm, y2 + margin_mm


def _bboxes_intersect(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


def describe_uncovered_ground_regions(
    model: BoardModel,
    routes: RoutedDesign,
    regions: Sequence[tuple[object, GerberRegionRecord]],
    *,
    layer_of_region: Callable[[object], str],
) -> tuple[UncoveredGroundRegion, ...]:
    """Describe the physical objects enclosing and approaching each copper island."""
    details: list[UncoveredGroundRegion] = []
    for region_source, region in regions:
        layer = layer_of_region(region_source)
        enclosing: set[str] = set()
        for placement in model.placements:
            rect = placed_rect(
                placement.footprint,
                placement.x_mm,
                placement.y_mm,
                placement.rotation_deg,
            )
            rect_bbox = _expanded_bbox(
                (rect.x1, rect.y1, rect.x2, rect.y2),
                model.min_clearance_mm,
            )
            if _bboxes_intersect(rect_bbox, region.bbox_mm):
                enclosing.add(placement.refdes)

        nearby: set[str] = set()
        nearby_nets: set[str] = set()
        for wire in routes.wires:
            if wire.layer != layer:
                continue
            for start, end in zip(wire.points, wire.points[1:]):
                segment_bbox = (
                    min(start[0], end[0]),
                    min(start[1], end[1]),
                    max(start[0], end[0]),
                    max(start[1], end[1]),
                )
                expanded = _expanded_bbox(
                    segment_bbox,
                    wire.width_mm / 2.0 + model.min_clearance_mm,
                )
                if _bboxes_intersect(expanded, region.bbox_mm):
                    nearby.add(f"{wire.net}@{wire.layer} w={wire.width_mm}")
                    nearby_nets.add(wire.net)
                    break
        via_margin = model.via_diameter_mm / 2.0 + model.min_clearance_mm
        expanded_region = _expanded_bbox(region.bbox_mm, via_margin)
        for via in routes.vias:
            if (
                expanded_region[0] <= via.x_mm <= expanded_region[2]
                and expanded_region[1] <= via.y_mm <= expanded_region[3]
            ):
                nearby.add(f"via:{via.net}")
                nearby_nets.add(via.net)

        enclosing_refdes = tuple(sorted(enclosing))
        nearby_tracks = tuple(sorted(nearby))
        levers: list[str] = []
        if enclosing_refdes:
            levers.append(
                "move or rotate "
                f"{','.join(enclosing_refdes)} so pads no longer fence the region"
            )
        if nearby_nets:
            levers.append(
                "reroute "
                f"{','.join(sorted(nearby_nets))} on the other layer or away from the region"
            )
        levers.append(
            "add a GND connection inside the region "
            "(GND pad, test point or stitch via) — "
            "the region is not merged by stitch-via pitch alone"
        )
        levers.append(
            "lower board min_clearance_mm "
            f"(currently {model.min_clearance_mm}) only down to the fab profile minimum; "
            "gate thresholds and fab minimums are not adjustable"
        )
        details.append(
            UncoveredGroundRegion(
                layer=layer,
                bbox_mm=region.bbox_mm,
                area_mm2=region.area_mm2,
                enclosing_refdes=enclosing_refdes,
                nearby_tracks=nearby_tracks,
                levers=tuple(levers),
            )
        )
    return tuple(details)


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
