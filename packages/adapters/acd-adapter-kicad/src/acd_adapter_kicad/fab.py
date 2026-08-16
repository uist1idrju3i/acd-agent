"""Independent manufacturing measurements, DFM checks, and JLCPCB exports."""

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
import math
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import sexpdata  # pyright: ignore[reportMissingTypeStubs]
from gerbonara.apertures import (  # pyright: ignore[reportMissingTypeStubs]
    CircleAperture,
    ObroundAperture,
    RectangleAperture,
)
from gerbonara.excellon import ExcellonFile  # pyright: ignore[reportMissingTypeStubs]
from gerbonara.graphic_objects import (  # pyright: ignore[reportMissingTypeStubs]
    Arc,
    Flash,
    Line,
    Region,
)
from gerbonara.rs274x import GerberFile  # pyright: ignore[reportMissingTypeStubs]

from acd_adapter_kicad.library import SymbolLibrary
from acd_adapter_kicad.placement import rotate_point
from acd_core.board_model import BoardModel, RoutedDesign, RoutedVia
from acd_core.bom import refdes_key
from acd_core.electrical import ComponentView, ElectricalLane
from acd_core.fab import (
    FabOrderIntentView,
    FabProfile,
    ProcessAllowanceView,
    validate_allowances_against_profile,
)
from acd_core.routing_width import NetWidthRequirement
from acd_core.silkscreen import SilkscreenLane


class FabOutputError(ValueError):
    """Raised when manufacturing output cannot be proven correct."""


class UncoveredStitchViasError(FabOutputError):
    """Raised when filled Gerbers do not cover requested stitch vias."""

    def __init__(self, locations: tuple[tuple[float, float], ...]) -> None:
        self.locations = locations
        locations_text = ", ".join(f"({x}, {y})" for x, y in locations)
        super().__init__(
            f"stitch vias lack copper coverage (fail-closed): {locations_text}"
        )


def _gerber_to_board_point(x_mm: float, y_mm: float) -> tuple[float, float]:
    """Convert Gerber's Y-up coordinates to the board's Y-down frame."""
    return x_mm, -y_mm


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


@dataclass(frozen=True)
class _SilkObject:
    kind: str
    layer: str
    bbox_mm: tuple[float, float, float, float]
    area_mm2: float
    stroke_width_mm: float | None
    start_mm: tuple[float, float] | None = None
    end_mm: tuple[float, float] | None = None
    center_mm: tuple[float, float] | None = None
    radius_mm: float | None = None


def _bbox_overlap_area(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    width = min(first[2], second[2]) - max(first[0], second[0])
    height = min(first[3], second[3]) - max(first[1], second[1])
    return max(0.0, width) * max(0.0, height)


def _silk_aperture_width(aperture: Any) -> float:
    raw = aperture
    if isinstance(aperture, CircleAperture):
        return float(raw.diameter)
    if isinstance(aperture, RectangleAperture):
        return max(float(raw.w), float(raw.h))
    if isinstance(aperture, ObroundAperture):
        return max(float(raw.w), float(raw.h))
    raise FabOutputError(
        f"unsupported silkscreen aperture {type(aperture).__name__} (fail-closed)"
    )


def _silk_object(obj: Any, layer: str) -> _SilkObject:
    raw = obj
    if isinstance(obj, Line):
        width = _silk_aperture_width(raw.aperture)
        x1, y1 = _gerber_to_board_point(float(raw.x1), float(raw.y1))
        x2, y2 = _gerber_to_board_point(float(raw.x2), float(raw.y2))
        radius = width / 2.0
        bbox = (
            min(x1, x2) - radius,
            min(y1, y2) - radius,
            max(x1, x2) + radius,
            max(y1, y2) + radius,
        )
        length = math.hypot(x2 - x1, y2 - y1)
        return _SilkObject(
            "Line", layer, bbox, max(length * width, 1e-9), width, (x1, y1), (x2, y2)
        )
    if isinstance(obj, Arc):
        width = _silk_aperture_width(raw.aperture)
        x1, y1 = _gerber_to_board_point(float(raw.x1), float(raw.y1))
        x2, y2 = _gerber_to_board_point(float(raw.x2), float(raw.y2))
        center_x = float(raw.x1 + raw.cx)
        center_y = float(raw.y1 + raw.cy)
        center_x, center_y = _gerber_to_board_point(center_x, center_y)
        radius = math.hypot(x1 - center_x, y1 - center_y)
        bbox = (
            center_x - radius - width / 2.0,
            center_y - radius - width / 2.0,
            center_x + radius + width / 2.0,
            center_y + radius + width / 2.0,
        )
        return _SilkObject(
            "Arc",
            layer,
            bbox,
            max(2.0 * math.pi * radius * width, 1e-9),
            width,
            center_mm=(center_x, center_y),
            radius_mm=radius,
        )
    if isinstance(obj, Region):
        outline = cast(list[tuple[Any, Any]], raw.outline)
        points = [_gerber_to_board_point(float(x), float(y)) for x, y in outline]
        if len(points) < 3:
            raise FabOutputError("silkscreen region has insufficient points (fail-closed)")
        xs, ys = zip(*points, strict=True)
        area = abs(
            sum(
                points[index][0] * points[index + 1][1]
                - points[index + 1][0] * points[index][1]
                for index in range(len(points) - 1)
            )
            / 2.0
        )
        return _SilkObject(
            "Region",
            layer,
            (min(xs), min(ys), max(xs), max(ys)),
            max(area, 1e-9),
            None,
        )
    if isinstance(obj, Flash):
        diameter = _silk_aperture_width(raw.aperture)
        x, y = _gerber_to_board_point(float(raw.x), float(raw.y))
        radius = diameter / 2.0
        return _SilkObject(
            "Flash",
            layer,
            (x - radius, y - radius, x + radius, y + radius),
            math.pi * radius * radius,
            diameter,
            center_mm=(x, y),
            radius_mm=radius,
        )
    raise FabOutputError(
        f"unsupported silkscreen object {type(obj).__name__} (fail-closed)"
    )


def _gerber_silk_objects(path: Path, layer: str) -> tuple[_SilkObject, ...]:
    try:
        gerber = cast(Any, GerberFile).open(path)
        objects = cast("list[Any]", gerber.objects)
        return tuple(_silk_object(obj, layer) for obj in objects)
    except FabOutputError:
        raise
    except Exception as exc:
        raise FabOutputError(f"{path.name}: silkscreen parse failed (fail-closed)") from exc


def _declared_bbox(
    x_mm: float,
    y_mm: float,
    text: str,
    height_mm: float,
    rotation_deg: float = 0.0,
) -> tuple[float, float, float, float]:
    estimated_width = max(height_mm * 0.6 * len(text), height_mm)
    if int(rotation_deg) % 180:
        estimated_width, height_mm = height_mm, estimated_width
    return (
        x_mm - estimated_width / 2.0 - 0.4,
        y_mm - height_mm / 2.0 - 0.4,
        x_mm + estimated_width / 2.0 + 0.4,
        y_mm + height_mm / 2.0 + 0.4,
    )


def _union_bbox(
    objects: Sequence[_SilkObject],
) -> tuple[float, float, float, float]:
    if not objects:
        raise FabOutputError("silkscreen declaration has no nearby ink (fail-closed)")
    return (
        min(item.bbox_mm[0] for item in objects),
        min(item.bbox_mm[1] for item in objects),
        max(item.bbox_mm[2] for item in objects),
        max(item.bbox_mm[3] for item in objects),
    )


def _point_rect_distance(
    point: tuple[float, float],
    rect: tuple[float, float, float, float],
) -> float:
    x, y = point
    return math.hypot(
        max(rect[0] - x, 0.0, x - rect[2]),
        max(rect[1] - y, 0.0, y - rect[3]),
    )


def _segment_distance_to_rect(
    start: tuple[float, float],
    end: tuple[float, float],
    rect: tuple[float, float, float, float],
) -> float:
    if (
        min(start[0], end[0]) <= rect[2]
        and max(start[0], end[0]) >= rect[0]
        and min(start[1], end[1]) <= rect[3]
        and max(start[1], end[1]) >= rect[1]
    ):
        return 0.0
    return min(
        _point_rect_distance(start, rect),
        _point_rect_distance(end, rect),
    )


def _silk_overlaps_rect(item: _SilkObject, rect: tuple[float, float, float, float]) -> bool:
    if item.kind == "Arc" and item.center_mm is not None and item.radius_mm is not None:
        center = item.center_mm
        corners = (
            (rect[0], rect[1]),
            (rect[0], rect[3]),
            (rect[2], rect[1]),
            (rect[2], rect[3]),
        )
        minimum = _point_rect_distance(center, rect)
        maximum = max(math.dist(center, corner) for corner in corners)
        half_width = (item.stroke_width_mm or 0.0) / 2.0
        return minimum <= item.radius_mm + half_width and maximum >= item.radius_mm - half_width
    if item.kind == "Line" and item.start_mm is not None and item.end_mm is not None:
        return _segment_distance_to_rect(item.start_mm, item.end_mm, rect) <= (
            item.stroke_width_mm or 0.0
        ) / 2.0
    return _bbox_overlap_area(item.bbox_mm, rect) > 1e-6


def _silk_objects_overlap(first: _SilkObject, second: _SilkObject) -> bool:
    if (
        first.kind == "Arc"
        and second.kind == "Flash"
        and first.center_mm is not None
        and first.radius_mm is not None
        and second.center_mm is not None
        and second.radius_mm is not None
    ):
        distance = math.dist(first.center_mm, second.center_mm)
        stroke_width = first.stroke_width_mm or 0.0
        return (
            distance <= first.radius_mm + stroke_width / 2 + second.radius_mm
            and distance + second.radius_mm >= first.radius_mm - stroke_width / 2
        )
    if (
        first.kind == "Line"
        and second.kind == "Flash"
        and first.start_mm is not None
        and first.end_mm is not None
        and second.center_mm is not None
        and second.radius_mm is not None
    ):
        stroke_width = first.stroke_width_mm or 0.0
        return _segment_distance_to_rect(
            first.start_mm,
            first.end_mm,
            (
                second.center_mm[0] - second.radius_mm,
                second.center_mm[1] - second.radius_mm,
                second.center_mm[0] + second.radius_mm,
                second.center_mm[1] + second.radius_mm,
            ),
        ) <= stroke_width / 2
    if (
        first.kind == "Flash"
        and second.kind == "Flash"
        and first.center_mm is not None
        and first.radius_mm is not None
        and second.center_mm is not None
        and second.radius_mm is not None
    ):
        return math.dist(first.center_mm, second.center_mm) <= first.radius_mm + second.radius_mm
    return _bbox_overlap_area(first.bbox_mm, second.bbox_mm) > 1e-6


def measure_silkscreen(
    silk_paths: Mapping[str, Path],
    mask_paths: Mapping[str, Path],
    edge_path: Path,
    measurement: BoardMeasurement,
    declarations: SilkscreenLane,
    profile: FabProfile,
) -> dict[str, object]:
    """Independently measure declared silk ink and clearance against fab output."""
    min_width = float(profile.data["capabilities"]["min_silk_width"]["value"])
    min_height = float(profile.data["capabilities"]["min_silk_height"]["value"])
    all_silk: list[_SilkObject] = []
    type_counts: dict[str, int] = defaultdict(int)
    for layer, path in silk_paths.items():
        objects = _gerber_silk_objects(path, layer)
        all_silk.extend(objects)
        for item in objects:
            type_counts[item.kind] += 1
    if not all_silk:
        raise FabOutputError("silkscreen Gerber contains no objects (fail-closed)")
    masks: list[_SilkObject] = []
    for layer, path in mask_paths.items():
        masks.extend(_gerber_silk_objects(path, layer))
    edge_objects = _gerber_silk_objects(edge_path, "Edge.Cuts")
    if not edge_objects:
        raise FabOutputError("Edge.Cuts Gerber contains no objects (fail-closed)")
    outline = measurement.outline_bbox_mm
    if outline is None:
        raise FabOutputError("board outline measurement is missing (fail-closed)")
    declared: list[dict[str, object]] = []
    declared_objects: list[_SilkObject] = []
    for text in declarations.texts:
        target = _declared_bbox(
            text.x_mm, text.y_mm, text.text, text.height_mm, text.rotation_deg
        )
        target_half_width = (target[2] - target[0]) / 2.0
        target_half_height = (target[3] - target[1]) / 2.0
        nearby = [
            item
            for item in all_silk
            if item.layer == text.layer
            and (
                item.stroke_width_mm is None
                or item.stroke_width_mm + 1e-6 >= text.stroke_width_mm
            )
            and _bbox_overlap_area(item.bbox_mm, target) > 0
            and abs(
                (item.bbox_mm[0] + item.bbox_mm[2]) / 2.0 - text.x_mm
            )
            <= target_half_width
            and abs(
                (item.bbox_mm[1] + item.bbox_mm[3]) / 2.0 - text.y_mm
            )
            <= target_half_height
        ]
        bbox = _union_bbox(nearby)
        declared_objects.extend(nearby)
        measured_widths = [
            item.stroke_width_mm for item in nearby if item.stroke_width_mm is not None
        ]
        measured_width = min(measured_widths) if measured_widths else None
        area = sum(item.area_mm2 for item in nearby)
        height = bbox[3] - bbox[1]
        if area <= 0 or measured_width is None:
            raise FabOutputError(
                f"silkscreen text {text.node_id!r} has no measurable ink (fail-closed)"
            )
        if text.height_mm < min_height or text.stroke_width_mm < min_width:
            raise FabOutputError(
                f"silkscreen declaration {text.node_id!r} is below fab capability (fail-closed)"
            )
        if measured_width < min_width or height < min_height:
            raise FabOutputError(
                f"silkscreen text {text.node_id!r} measured below fab capability (fail-closed)"
            )
        declared.append(
            {
                "node_id": text.node_id,
                "role": text.role,
                "text": text.text,
                "layer": text.layer,
                "declared_position_mm": [text.x_mm, text.y_mm],
                "measured_bbox_mm": list(bbox),
                "measured_ink_area_mm2": area,
                "measured_height_mm": height,
                "measured_minimum_stroke_width_mm": measured_width,
                "placement_basis": text.placement_basis,
                "placement_search_order": text.placement_search_order,
                "placement_reference": text.placement_reference,
                "placement_offset_step_mm": text.placement_offset_step_mm,
                "placement_search_limit_mm": text.placement_search_limit_mm,
            }
        )
    for graphic in declarations.graphics:
        xs, ys = zip(*graphic.polygon_points, strict=True)
        target = (min(xs) - 0.5, min(ys) - 0.5, max(xs) + 0.5, max(ys) + 0.5)
        target_half_width = (target[2] - target[0]) / 2.0
        target_half_height = (target[3] - target[1]) / 2.0
        nearby = [
            item
            for item in all_silk
            if item.layer == graphic.layer
            and (
                item.stroke_width_mm is None
                or item.stroke_width_mm + 1e-6 >= graphic.stroke_width_mm
            )
            and _bbox_overlap_area(item.bbox_mm, target) > 0
            and abs(
                (item.bbox_mm[0] + item.bbox_mm[2]) / 2.0
                - (min(xs) + max(xs)) / 2.0
            )
            <= target_half_width
            and abs(
                (item.bbox_mm[1] + item.bbox_mm[3]) / 2.0
                - (min(ys) + max(ys)) / 2.0
            )
            <= target_half_height
        ]
        bbox = _union_bbox(nearby)
        declared_objects.extend(nearby)
        measured_widths = [
            item.stroke_width_mm for item in nearby if item.stroke_width_mm is not None
        ]
        measured_width = min(measured_widths) if measured_widths else None
        area = sum(item.area_mm2 for item in nearby)
        if area <= 0 or measured_width is None:
            raise FabOutputError(
                f"silkscreen graphic {graphic.node_id!r} has no measurable ink (fail-closed)"
            )
        if graphic.stroke_width_mm < min_width or measured_width < min_width:
            raise FabOutputError(
                f"silkscreen graphic {graphic.node_id!r} is below fab capability (fail-closed)"
            )
        declared.append(
            {
                "node_id": graphic.node_id,
                "role": graphic.role,
                "layer": graphic.layer,
                "declared_polygon_points": [list(point) for point in graphic.polygon_points],
                "measured_bbox_mm": list(bbox),
                "measured_ink_area_mm2": area,
                "measured_minimum_stroke_width_mm": measured_width,
                "placement_basis": graphic.placement_basis,
                "placement_search_order": graphic.placement_search_order,
            }
        )
    pad_bboxes = [
        (
            pad.x_mm - pad.size_x_mm / 2.0,
            pad.y_mm - pad.size_y_mm / 2.0,
            pad.x_mm + pad.size_x_mm / 2.0,
            pad.y_mm + pad.size_y_mm / 2.0,
        )
        for pad in measurement.pads
    ]
    pad_overlaps = [
        {"silk_bbox_mm": list(item.bbox_mm), "pad_bbox_mm": list(pad_bbox)}
        for item in declared_objects
        for pad_bbox in pad_bboxes
        if _silk_overlaps_rect(item, pad_bbox)
    ]
    mask_overlaps = [
        {"silk_bbox_mm": list(item.bbox_mm), "mask_bbox_mm": list(mask.bbox_mm)}
        for item in declared_objects
        for mask in masks
        if _silk_objects_overlap(item, mask)
    ]
    outside = [
        list(item.bbox_mm)
        for item in declared_objects
        if item.bbox_mm[0] < outline[0]
        or item.bbox_mm[1] < outline[1]
        or item.bbox_mm[2] > outline[2]
        or item.bbox_mm[3] > outline[3]
    ]
    if pad_overlaps or mask_overlaps or outside:
        raise FabOutputError(
            "silkscreen clearance or board-edge overlap detected (fail-closed): "
            f"pad={len(pad_overlaps)}, mask={len(mask_overlaps)}, edge={len(outside)}; "
            f"pad_examples={pad_overlaps[:3]}, mask_examples={mask_overlaps[:3]}, "
            f"edge_examples={outside[:3]}"
        )
    return {
        "measurement_method": (
            "independent gerbonara parse of F.Silkscreen/B.Silkscreen, "
            "F.Mask/B.Mask, and Edge.Cuts with object geometry and bbox overlap checks"
        ),
        "capability_min_silk_width_mm": min_width,
        "capability_min_silk_height_mm": min_height,
        "object_type_counts": dict(sorted(type_counts.items())),
        "recognized_object_count": len(all_silk),
        "declared_elements": declared,
        "placement_evidence": [dict(item) for item in declarations.placement_evidence],
        "pad_to_silk_overlap_count": len(pad_overlaps),
        "mask_to_silk_overlap_count": len(mask_overlaps),
        "board_edge_overflow_count": len(outside),
        "pad_to_silk_overlaps": pad_overlaps,
        "mask_to_silk_overlaps": mask_overlaps,
        "board_edge_overflows": outside,
        "status": "measured_pass",
    }

PAD_SIZE_TOLERANCE_MM = 0.3
# Combined fab-library lands can represent multiple KiCad pads in one outline.
PAD_SIZE_MERGE_RATIO = 5.0


def _items(node: object) -> list[object]:
    return cast("list[object]", node) if isinstance(node, list) else []


def _tag(node: object) -> str | None:
    items = _items(node)
    return str(items[0]) if items and not isinstance(items[0], list) else None


def _direct(node: object, tag: str) -> list[list[object]]:
    return [_items(child) for child in _items(node)[1:] if _tag(child) == tag]


def _one(node: object, tag: str) -> list[object] | None:
    matches = _direct(node, tag)
    return matches[0] if matches else None


def _number(value: object) -> float:
    try:
        return float(cast(str, value))
    except (TypeError, ValueError) as exc:
        raise FabOutputError(f"expected numeric s-expression atom, got {value!r}") from exc


def _at(node: object) -> tuple[float, float, float]:
    values = _one(node, "at")
    if values is None or len(values) < 3:
        raise FabOutputError("missing KiCad position")
    return _number(values[1]), _number(values[2]), _number(values[3]) if len(values) > 3 else 0.0


def _property(node: object, name: str) -> str | None:
    for prop in _direct(node, "property"):
        if len(prop) >= 3 and str(prop[1]) == name:
            return str(prop[2])
    for text in _direct(node, "fp_text"):
        if len(text) >= 3 and str(text[1]) == name.lower():
            return str(text[2])
    return None


def rotate(x: float, y: float, angle: float) -> tuple[float, float]:
    radians = math.radians(angle)
    return (
        x * math.cos(radians) + y * math.sin(radians),
        -x * math.sin(radians) + y * math.cos(radians),
    )


def _inverse_rotate(x: float, y: float, angle: float) -> tuple[float, float]:
    return rotate(x, y, -angle)


def _minimum_matching_error(
    actual: Sequence[tuple[float, float]], expected: Sequence[tuple[float, float]]
) -> float:
    distances = sorted(
        {math.dist(left, right) for left in actual for right in expected}
    )
    for threshold in distances:
        matched: dict[int, int] = {}

        def visit(
            index: int,
            seen: set[int],
            limit: float = threshold,
            assignments: dict[int, int] = matched,
        ) -> bool:
            for candidate, distance in enumerate(
                math.dist(actual[index], point) for point in expected
            ):
                if distance > limit or candidate in seen:
                    continue
                seen.add(candidate)
                previous = assignments.get(candidate)
                if previous is None or visit(previous, seen):
                    assignments[candidate] = index
                    return True
            return False

        if all(visit(index, set()) for index in range(len(expected))):
            return threshold
    raise FabOutputError("pin-function matching has no perfect assignment")


def _normalize_pin_function(name: str, aliases: Mapping[str, str]) -> str:
    normalized = re.sub(r"[^A-Z0-9+_-]", "", name.upper())
    normalized_aliases = {
        re.sub(r"[^A-Z0-9+_-]", "", source.upper()): re.sub(
            r"[^A-Z0-9+_-]", "", target.upper()
        )
        for source, target in aliases.items()
    }
    return normalized_aliases.get(normalized, normalized)


def _minimum_matching_geometry_error(
    actual: Sequence[tuple[tuple[float, float], tuple[float, float]]],
    expected: Sequence[tuple[tuple[float, float], tuple[float, float]]],
    tolerance_mm: float,
) -> float:
    distances = sorted(
        {
            math.dist(left[0], right[0])
            for left in actual
            for right in expected
        }
    )
    for threshold in distances:
        matched: dict[int, int] = {}

        def visit(
            expected_index: int,
            seen: set[int],
            limit: float = threshold,
            assignments: dict[int, int] = matched,
        ) -> bool:
            for candidate, point in enumerate(actual):
                if candidate in seen:
                    continue
                actual_size = point[1]
                expected_size = expected[expected_index][1]
                size_compatible = (
                    abs(actual_size[0] - expected_size[0]) <= tolerance_mm
                    and abs(actual_size[1] - expected_size[1]) <= tolerance_mm
                )
                if not size_compatible:
                    size_compatible = (
                        all(value > 0 for value in actual_size + expected_size)
                        and max(
                            expected_size[0] / actual_size[0],
                            expected_size[1] / actual_size[1],
                        )
                        <= PAD_SIZE_MERGE_RATIO
                    )
                if not size_compatible:
                    continue
                if math.dist(point[0], expected[expected_index][0]) > limit:
                    continue
                seen.add(candidate)
                previous = assignments.get(candidate)
                if previous is None or visit(previous, seen):
                    assignments[candidate] = expected_index
                    return True
            return False

        if all(visit(index, set()) for index in range(len(expected))):
            return threshold
    raise FabOutputError("geometry matching has no compatible perfect assignment")


def _parse_lcsc_pad_shape(shape: str) -> tuple[str, float, float] | None:
    fields = shape.split("~")
    if len(fields) < 9 or fields[0] != "PAD":
        return None
    try:
        return fields[8], float(fields[2]), float(fields[3])
    except ValueError:
        return None


def _parse_lcsc_pad_geometry(
    shape: str,
) -> tuple[str, float, float, float, float] | None:
    fields = shape.split("~")
    if len(fields) < 9 or fields[0] != "PAD":
        return None
    try:
        return fields[8], float(fields[2]), float(fields[3]), float(fields[4]), float(fields[5])
    except ValueError:
        return None


def _parse_lcsc_pin_shape(shape: str) -> tuple[str, str, float, float] | None:
    fields = shape.split("~")
    if len(fields) < 6 or fields[0] != "P":
        return None
    pin_name_match = re.search(r"~([^~]+)~(?:start|end)~", shape)
    if pin_name_match is None:
        return None
    try:
        return fields[3], pin_name_match.group(1), float(fields[4]), float(fields[5])
    except ValueError:
        return None


def load_lcsc_pin_centers(path: Path) -> tuple[tuple[str, str, float, float], ...]:
    """Read pin-function pad centers from an archived EasyEDA package response."""
    document = json.loads(path.read_text(encoding="utf-8"))
    package_shapes = document["response"]["result"]["packageDetail"]["dataStr"]["shape"]
    pad_shapes = [_parse_lcsc_pad_shape(str(shape)) for shape in package_shapes]
    pad_centers = {
        number: (x, y)
        for item in pad_shapes
        if item is not None
        for number, x, y in [item]
    }
    pin_shapes = package_shapes
    if not any(str(shape).startswith("P~") for shape in pin_shapes):
        pin_shapes = document["response"]["result"]["dataStr"]["shape"]
    pins = [_parse_lcsc_pin_shape(str(shape)) for shape in pin_shapes]
    parsed = tuple(
        (number, function, pad_centers[number][0], pad_centers[number][1])
        for item in pins
        if item is not None
        for number, function, _, _ in [item]
        if number in pad_centers
    )
    if not parsed:
        raise FabOutputError(f"{path}: archived LCSC response has no pin-function pads")
    return parsed


def load_lcsc_pin_geometries(
    path: Path,
) -> tuple[tuple[str, str, float, float, float, float], ...]:
    """Read pin functions and pad geometry from an archived EasyEDA response."""
    document = json.loads(path.read_text(encoding="utf-8"))
    package_shapes = document["response"]["result"]["packageDetail"]["dataStr"]["shape"]
    pad_geometries = [_parse_lcsc_pad_geometry(str(shape)) for shape in package_shapes]
    pads = {
        number: (x, y, width, height)
        for item in pad_geometries
        if item is not None
        for number, x, y, width, height in [item]
    }
    pin_shapes = package_shapes
    if not any(str(shape).startswith("P~") for shape in pin_shapes):
        pin_shapes = document["response"]["result"]["dataStr"]["shape"]
    parsed = tuple(
        (number, function, *pads[number])
        for item in [_parse_lcsc_pin_shape(str(shape)) for shape in pin_shapes]
        if item is not None
        for number, function, _, _ in [item]
        if number in pads
    )
    if not parsed:
        raise FabOutputError(f"{path}: archived LCSC response has no pin-function geometry")
    return parsed


def derive_lcsc_rotation_offset(
    footprint: FootprintMeasurement,
    lcsc_pin_centers: Sequence[tuple[str, str, float, float]],
    kicad_pin_functions: Mapping[str, str] | None = None,
    pin_name_aliases: Mapping[str, str] | None = None,
    tolerance_mm: float = 0.3,
    scale: float = 0.254,
    polarized: bool = True,
    lcsc_pin_geometries: Sequence[tuple[str, str, float, float, float, float]] | None = None,
    geometry_exception: bool = False,
) -> tuple[float, str]:
    """Derive a unique quarter-turn offset from pin-function geometry."""
    aliases = pin_name_aliases or {}
    if polarized and not kicad_pin_functions and not geometry_exception:
        raise FabOutputError(f"{footprint.refdes}: KiCad pin functions are required")
    all_kicad = [
        _inverse_rotate(
            pad.x_mm - footprint.x_mm,
            pad.y_mm - footprint.y_mm,
            footprint.rotation_deg,
        )
        for pad in footprint.pads
        if pad.number is not None
    ]
    if geometry_exception:
        if lcsc_pin_geometries is None:
            raise FabOutputError(
                f"{footprint.refdes}: geometry exception requires LCSC pad sizes"
            )
        if len(all_kicad) < len(lcsc_pin_geometries):
            raise FabOutputError(
                f"{footprint.refdes}: geometry pad count mismatch: "
                f"KiCad={len(all_kicad)} LCSC={len(lcsc_pin_geometries)}"
            )
        kicad_center = (
            sum(x for x, _ in all_kicad) / len(all_kicad),
            sum(y for _, y in all_kicad) / len(all_kicad),
        )
        lcsc_values = [(x * scale, y * scale) for _, _, x, y, _, _ in lcsc_pin_geometries]
        lcsc_center = (
            sum(x for x, _ in lcsc_values) / len(lcsc_values),
            sum(y for _, y in lcsc_values) / len(lcsc_values),
        )
        candidates: list[tuple[float, float]] = []
        for angle in (0.0, 90.0, 180.0, 270.0):
            quarter_turn = int(angle) % 180 == 90
            actual = [
                (
                    rotate(x - kicad_center[0], y - kicad_center[1], angle),
                    (pad.size_y_mm, pad.size_x_mm)
                    if quarter_turn
                    else (pad.size_x_mm, pad.size_y_mm),
                )
                for pad, (x, y) in zip(footprint.pads, all_kicad, strict=True)
            ]
            expected = [
                (
                    (x * scale - lcsc_center[0], y * scale - lcsc_center[1]),
                    (width * scale, height * scale),
                )
                for _, _, x, y, width, height in lcsc_pin_geometries
            ]
            try:
                error = _minimum_matching_geometry_error(
                    actual, expected, PAD_SIZE_TOLERANCE_MM
                )
            except FabOutputError:
                continue
            if error <= tolerance_mm:
                candidates.append((angle, error))
        if len(candidates) == 1:
            return candidates[0][0], (
                "unique; basis=declared-geometry-exception; "
                f"max_error_mm={candidates[0][1]:.6f}; "
                f"pad_size_tolerance_mm={PAD_SIZE_TOLERANCE_MM:.3f}"
            )
        if not candidates:
            raise FabOutputError(
                f"{footprint.refdes}: no geometry rotation candidate within tolerance"
            )
        raise FabOutputError(
            f"{footprint.refdes}: ambiguous geometry rotation candidates: {candidates}"
        )
    kicad: dict[str, list[tuple[float, float]]] = defaultdict(list)
    lcsc: dict[str, list[tuple[float, float]]] = defaultdict(list)
    if kicad_pin_functions:
        for pad in footprint.pads:
            if pad.number is not None and pad.number in kicad_pin_functions:
                function = _normalize_pin_function(kicad_pin_functions[pad.number], aliases)
                kicad[function].append(
                    _inverse_rotate(
                        pad.x_mm - footprint.x_mm,
                        pad.y_mm - footprint.y_mm,
                        footprint.rotation_deg,
                    )
                )
        raw_lcsc: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
        for number, function, x, y in lcsc_pin_centers:
            raw_lcsc[_normalize_pin_function(function, aliases)].append(
                (number, x * scale, y * scale)
            )
        for function, target in kicad.items():
            selected = [
                (point[0], point[1])
                for number, *point in raw_lcsc[function]
                if number in kicad_pin_functions
            ]
            if len(selected) < len(target):
                selected.extend(
                    (point[0], point[1])
                    for number, *point in raw_lcsc[function]
                    if number not in kicad_pin_functions
                )
            lcsc[function] = selected[: len(target)]
        if {key: len(value) for key, value in kicad.items()} != {
            key: len(value) for key, value in lcsc.items()
        }:
            raise FabOutputError(
                f"{footprint.refdes}: pin-function mismatch: "
                f"KiCad={sorted(kicad)} LCSC={sorted(lcsc)}"
            )
    else:
        kicad["__geometry__"] = all_kicad
        lcsc["__geometry__"] = [(x * scale, y * scale) for _, _, x, y in lcsc_pin_centers]
    kicad_values = [point for points in kicad.values() for point in points]
    kicad_center = (
        sum(x for x, _ in kicad_values) / len(kicad_values),
        sum(y for _, y in kicad_values) / len(kicad_values),
    )
    lcsc_values = [point for points in lcsc.values() for point in points]
    lcsc_center = (
        sum(x for x, _ in lcsc_values) / len(lcsc_values),
        sum(y for _, y in lcsc_values) / len(lcsc_values),
    )
    candidates: list[tuple[float, float]] = []
    for angle in (0.0, 90.0, 180.0, 270.0):
        error = 0.0
        for function, kicad_points in kicad.items():
            transformed = [
                rotate(x - kicad_center[0], y - kicad_center[1], angle)
                for x, y in kicad_points
            ]
            remaining = [
                (x - lcsc_center[0], y - lcsc_center[1]) for x, y in lcsc[function]
            ]
            error = max(error, _minimum_matching_error(transformed, remaining))
        if error <= tolerance_mm:
            candidates.append((angle, error))
    if len(candidates) == 1:
        basis = "pin-function" if kicad_pin_functions else "geometry-only"
        return candidates[0][0], f"unique; basis={basis}; max_error_mm={candidates[0][1]:.6f}"
    if len(candidates) > 1 and not polarized:
        return 0.0, (
            "ambiguous but non-polarized and symmetric; "
            f"polarity unaffected; candidates={candidates}"
        )
    if not candidates:
        raise FabOutputError(f"{footprint.refdes}: no LCSC rotation candidate within tolerance")
    raise FabOutputError(f"{footprint.refdes}: ambiguous LCSC rotation candidates: {candidates}")


def verify_lcsc_rotation_evidence(
    evidence_dir: Path,
    fixture_dir: Path,
    board: BoardMeasurement,
    lane: ElectricalLane,
    fitted: set[str],
) -> tuple[dict[str, float], dict[str, str], list[str]]:
    """Recompute archived LCSC rotation Evidence without network access."""
    footprints = {footprint.refdes: footprint for footprint in board.footprints}
    offsets: dict[str, float] = {}
    notes: dict[str, str] = {}
    unknowns: list[str] = []
    for component in lane.components:
        if component.refdes not in fitted:
            continue
        path = evidence_dir / f"{component.refdes}.json"
        if not path.exists():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        response = document["response"]
        canonical = json.dumps(
            response, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        expected_hash = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
        if document.get("response_canonical_sha256") != expected_hash:
            raise FabOutputError(f"{component.refdes}: LCSC Evidence response hash mismatch")
        footprint = footprints.get(component.refdes)
        if footprint is None:
            raise FabOutputError(f"{component.refdes}: board footprint missing for LCSC Evidence")
        try:
            symbol_note = verify_cpl_pin_function_declaration(
                component, fixture_dir
            )
            geometry_exception = component.cpl_rotation_geometry_exception
            if geometry_exception and (
                not component.cpl_rotation_geometry_exception_reason
                or not component.cpl_rotation_geometry_exception_source
            ):
                raise FabOutputError(
                    f"{component.refdes}: geometry exception provenance is required"
                )
            offset, note = derive_lcsc_rotation_offset(
                footprint,
                load_lcsc_pin_centers(path),
                component.cpl_rotation_pin_functions,
                component.cpl_rotation_pin_aliases,
                polarized=component.cpl_rotation_polarized,
                lcsc_pin_geometries=(
                    load_lcsc_pin_geometries(path) if geometry_exception else None
                ),
                geometry_exception=geometry_exception,
            )
        except FabOutputError as exc:
            unknowns.append(component.refdes)
            notes[component.refdes] = f"unknown; {exc}"
            continue
        offsets[component.refdes] = offset
        notes[component.refdes] = f"{symbol_note}; {note}"
    return offsets, notes, unknowns


def verify_cpl_pin_function_declaration(
    component: ComponentView,
    fixture_dir: Path,
) -> str:
    """Verify graph CPL pin functions against the pinned KiCad symbol."""
    if not component.cpl_rotation_pin_functions:
        return "no pin-function declaration"
    symbol_path = Path(component.library.symbol_file)
    if not symbol_path.is_absolute():
        symbol_path = fixture_dir / symbol_path
    parsed = SymbolLibrary().load(
        component.library.symbol,
        symbol_path,
        component.library.symbol_sha256,
    )
    symbol_pins = {
        pin.number: _normalize_pin_function(pin.name, component.cpl_rotation_pin_aliases)
        for pin in parsed.pins
    }
    unverified = set(component.cpl_rotation_unverified_pads)
    for number, declared in component.cpl_rotation_pin_functions.items():
        if number not in symbol_pins:
            if (
                number not in unverified
                or not component.cpl_rotation_unverified_pad_reason
                or not component.cpl_rotation_unverified_pad_source
            ):
                raise FabOutputError(
                    f"{component.refdes}: CPL pin {number} is absent from symbol "
                    "without sourced unverified-pad declaration"
                )
            continue
        expected = _normalize_pin_function(declared, component.cpl_rotation_pin_aliases)
        if expected != symbol_pins[number]:
            raise FabOutputError(
                f"{component.refdes}: CPL pin function mismatch for {number}: "
                f"declared={declared!r} symbol={symbol_pins[number]!r}"
            )
    if unverified:
        return (
            f"symbol-verified; unverified_pads={sorted(unverified)}; "
            f"reason={component.cpl_rotation_unverified_pad_reason}"
        )
    return "symbol-verified; all declared CPL pins matched"


def _footprint_bbox(
    node: object, fp_at: tuple[float, float, float], layer_suffix: str
) -> tuple[float, float, float, float] | None:
    points: list[tuple[float, float]] = []
    for tag in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly"):
        for item in _direct(node, tag):
            layer = _one(item, "layer")
            if layer is None or not str(layer[1]).endswith(layer_suffix):
                continue
            for point_tag in ("start", "mid", "end", "center"):
                point = _one(item, point_tag)
                if point is not None and len(point) > 2:
                    points.append((_number(point[1]), _number(point[2])))
            pts_node = _one(item, "pts")
            if pts_node is not None:
                for xy in pts_node[1:]:
                    if isinstance(xy, list):
                        values = cast(list[object], xy)
                        if len(values) <= 2:
                            continue
                        points.append((_number(values[1]), _number(values[2])))
    if not points:
        return None
    transformed = [
        (fp_at[0] + rotate(x, y, fp_at[2])[0], fp_at[1] + rotate(x, y, fp_at[2])[1])
        for x, y in points
    ]
    xs, ys = zip(*transformed, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def _point_in_polygon(x: float, y: float, polygon: Sequence[tuple[float, float]]) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, (*polygon[1:], polygon[0]), strict=True):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def verify_smd_pad_centers_in_gerber(
    gerber_path: Path, measurement: BoardMeasurement
) -> None:
    try:
        layer = GerberFile.open(gerber_path)  # pyright: ignore[reportUnknownMemberType]
        objects = cast("list[Flash | Region | Line]", layer.objects)  # pyright: ignore[reportUnknownMemberType]
    except Exception as exc:
        raise FabOutputError(
            f"{gerber_path.name}: Gerber pad coverage parse failed: {exc}"
        ) from exc

    def covered(x: float, y: float) -> bool:
        for obj in objects:
            if not obj.polarity_dark:
                continue
            if isinstance(obj, Flash):
                if not isinstance(
                    obj.aperture,
                    (CircleAperture, ObroundAperture, RectangleAperture),
                ):
                    raise FabOutputError(
                        f"{gerber_path.name}: unsupported Flash aperture "
                        f"{type(obj.aperture).__name__}; SMD pad coverage is unknown"
                    )
                if isinstance(obj.aperture, CircleAperture):
                    width = height = float(obj.aperture.diameter)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                else:
                    width = float(obj.aperture.w)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                    height = float(obj.aperture.h)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                obj_x = float(obj.x)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                obj_y = float(obj.y)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                if abs(x - obj_x) <= width / 2 and abs(y - obj_y) <= height / 2:
                    return True
            elif isinstance(obj, Region):
                outline = cast("list[tuple[float, float]]", obj.outline)  # pyright: ignore[reportUnknownMemberType]
                if _point_in_polygon(x, y, outline):
                    return True
            else:
                if not isinstance(obj.aperture, CircleAperture):
                    raise FabOutputError(
                        f"{gerber_path.name}: unsupported Line aperture "
                        f"{type(obj.aperture).__name__}; SMD pad coverage is unknown"
                    )
                x1 = float(obj.x1)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                y1 = float(obj.y1)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                x2 = float(obj.x2)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                y2 = float(obj.y2)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                dx, dy = x2 - x1, y2 - y1
                length_sq = dx * dx + dy * dy
                t = (
                    0.0
                    if length_sq == 0
                    else max(
                        0.0,
                        min(1.0, ((x - x1) * dx + (y - y1) * dy) / length_sq),
                    )
                )
                nearest_x, nearest_y = x1 + t * dx, y1 + t * dy
                radius = float(obj.aperture.diameter) / 2  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                if math.hypot(x - nearest_x, y - nearest_y) <= radius:
                    return True
        return False

    missing = [
        pad.refdes
        for pad in measurement.pads
        if pad.kind == "smd"
        and not covered(
            pad.x_mm,
            -pad.y_mm,  # KiCad Y increases downward; Gerber Y increases upward.
        )
    ]
    if missing:
        raise FabOutputError(
            f"{gerber_path.name}: F.Cu does not cover SMD pad centers {sorted(set(missing))}"
        )


def verify_ground_plane_gerbers(
    front_path: Path,
    back_path: Path,
    model: BoardModel,
    stitch_vias: Sequence[tuple[float, float]],
    routes: RoutedDesign,
) -> dict[str, object]:
    """Measure filled copper independently from both plane Gerbers."""
    if not model.copper_zones:
        raise FabOutputError("ground-plane declaration is absent (fail-closed)")
    if not stitch_vias:
        raise FabOutputError("no stitch vias were generated (fail-closed)")

    def read_regions(path: Path) -> tuple[GerberRegionRecord, ...]:
        try:
            text = path.read_text(encoding="ascii")
        except Exception as exc:
            raise FabOutputError(f"{path.name}: copper Gerber parse failed: {exc}") from exc
        fs_match = re.search(r"%FSLAX(\d)(\d)Y(\d)(\d)\*%", text)
        mo_match = re.search(r"%MO(MM|IN)\*%", text)
        if fs_match is None or mo_match is None:
            raise FabOutputError(f"{path.name}: missing Gerber format or units (fail-closed)")
        if (fs_match.group(1), fs_match.group(2), fs_match.group(3), fs_match.group(4)) != (
            "4",
            "6",
            "4",
            "6",
        ):
            raise FabOutputError(f"{path.name}: unsupported Gerber coordinate format (fail-closed)")
        if mo_match.group(1) != "MM":
            raise FabOutputError(f"{path.name}: unsupported Gerber units (fail-closed)")
        scale = 10.0 ** -int(fs_match.group(2))
        current_function: str | None = None
        interpolation = "G01"
        in_region = False
        region_points: list[tuple[float, float]] = []
        regions: list[GerberRegionRecord] = []
        for command in text.split("*"):
            command = command.strip()
            if not command:
                continue
            function_match = re.search(r"G04 #@! TA\.AperFunction,([^*]+)", command)
            if function_match is not None:
                current_function = function_match.group(1).strip()
                continue
            if "G04 #@! TD.AperFunction" in command:
                current_function = None
                continue
            if command == "G36":
                if in_region or current_function is None:
                    raise FabOutputError(
                        f"{path.name}: region without unique AperFunction (fail-closed)"
                    )
                in_region = True
                region_points = []
                continue
            if command == "G37":
                if not in_region or len(region_points) < 3 or current_function is None:
                    raise FabOutputError(f"{path.name}: malformed Gerber region (fail-closed)")
                board_points = tuple((x, -y) for x, y in region_points)
                area = abs(
                    sum(
                        x1 * y2 - x2 * y1
                        for (x1, y1), (x2, y2) in zip(
                            board_points, (*board_points[1:], board_points[0]), strict=True
                        )
                    )
                ) / 2.0
                xs, ys = zip(*board_points, strict=True)
                regions.append(
                    GerberRegionRecord(
                        current_function,
                        board_points,
                        area,
                        (min(xs), min(ys), max(xs), max(ys)),
                    )
                )
                in_region = False
                continue
            if in_region:
                if command in {"G01", "G02", "G03", "G75"}:
                    if command != "G75":
                        interpolation = command
                    continue
                match = re.fullmatch(r"(?:G01)?X(-?\d+)Y(-?\d+)D0([123])", command)
                arc_match = re.fullmatch(
                    r"(?:G0([23]))?X(-?\d+)Y(-?\d+)I(-?\d+)J(-?\d+)D0([123])",
                    command,
                )
                if arc_match is not None:
                    if arc_match.group(6) != "1" or not region_points:
                        raise FabOutputError(
                            f"{path.name}: malformed region arc (fail-closed)"
                        )
                    start = region_points[-1]
                    end = (
                        int(arc_match.group(2)) * scale,
                        int(arc_match.group(3)) * scale,
                    )
                    center = (
                        start[0] + int(arc_match.group(4)) * scale,
                        start[1] + int(arc_match.group(5)) * scale,
                    )
                    start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
                    end_angle = math.atan2(end[1] - center[1], end[0] - center[0])
                    arc_direction = arc_match.group(1) or interpolation.removeprefix("G0")
                    if arc_direction == "2":
                        while end_angle >= start_angle:
                            end_angle -= math.tau
                    else:
                        while end_angle <= start_angle:
                            end_angle += math.tau
                    steps = max(2, int(abs(end_angle - start_angle) / (math.pi / 18)))
                    radius = math.hypot(start[0] - center[0], start[1] - center[1])
                    region_points.extend(
                        (
                            center[0] + radius * math.cos(angle),
                            center[1] + radius * math.sin(angle),
                        )
                        for angle in (
                            start_angle
                            + (end_angle - start_angle) * index / steps
                            for index in range(1, steps + 1)
                        )
                    )
                    continue
                if match is None:
                    raise FabOutputError(
                        f"{path.name}: unsupported region command {command!r} (fail-closed)"
                    )
                point = (int(match.group(1)) * scale, int(match.group(2)) * scale)
                operation = match.group(3)
                if operation == "2":
                    if region_points:
                        raise FabOutputError(
                            f"{path.name}: multiple region contours unsupported (fail-closed)"
                        )
                    region_points.append(point)
                elif operation == "1":
                    region_points.append(point)
        if in_region:
            raise FabOutputError(f"{path.name}: unterminated Gerber region (fail-closed)")
        return tuple(regions)

    def read(path: Path) -> list[object]:
        try:
            layer = GerberFile.open(path)  # pyright: ignore[reportUnknownMemberType]
            return list(cast("Iterable[object]", layer.objects))  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:
            raise FabOutputError(f"{path.name}: copper Gerber parse failed: {exc}") from exc

    def bbox(obj: object) -> tuple[float, float, float, float] | None:
        if isinstance(obj, Flash):
            x = float(cast(float, obj.x))  # pyright: ignore[reportUnknownMemberType]
            y = float(cast(float, obj.y))  # pyright: ignore[reportUnknownMemberType]
            aperture = obj.aperture
            if isinstance(aperture, CircleAperture):
                sx = sy = float(
                    cast(float, aperture.diameter)  # pyright: ignore[reportUnknownMemberType]
                )
            elif isinstance(aperture, (RectangleAperture, ObroundAperture)):
                sx = float(cast(float, aperture.w))  # pyright: ignore[reportUnknownMemberType]
                sy = float(cast(float, aperture.h))  # pyright: ignore[reportUnknownMemberType]
            else:
                raise FabOutputError("unsupported copper flash aperture (fail-closed)")
            return x - sx / 2, y - sy / 2, x + sx / 2, y + sy / 2
        if isinstance(obj, Region):
            points = cast("Sequence[tuple[float, float]]", obj.outline)  # pyright: ignore[reportUnknownMemberType]
            if not points:
                return None
            xs, ys = zip(*points, strict=True)
            return min(xs), min(ys), max(xs), max(ys)
        if isinstance(obj, Line):
            aperture = obj.aperture
            if not isinstance(aperture, CircleAperture):
                raise FabOutputError("unsupported copper line aperture (fail-closed)")
            radius = float(
                cast(float, aperture.diameter)  # pyright: ignore[reportUnknownMemberType]
            ) / 2
            x1 = float(cast(float, obj.x1))  # pyright: ignore[reportUnknownMemberType]
            y1 = float(cast(float, obj.y1))  # pyright: ignore[reportUnknownMemberType]
            x2 = float(cast(float, obj.x2))  # pyright: ignore[reportUnknownMemberType]
            y2 = float(cast(float, obj.y2))  # pyright: ignore[reportUnknownMemberType]
            return (
                min(x1, x2) - radius,
                min(y1, y2) - radius,
                max(x1, x2) + radius,
                max(y1, y2) + radius,
            )
        raise FabOutputError(f"unsupported copper object {type(obj).__name__} (fail-closed)")

    all_boxes: list[tuple[float, float, float, float]] = []
    region_records: list[
        tuple[Path, GerberRegionRecord]
    ] = []
    flash_records: list[tuple[Path, Flash]] = []
    for path in (front_path, back_path):
        raw_regions = read_regions(path)
        for region in raw_regions:
            if region.function not in {
                "Conductor",
                "SMDPad,CuDef",
                "ComponentPad",
                "ViaPad",
            }:
                raise FabOutputError(
                    f"{path.name}: unknown region AperFunction {region.function!r} (fail-closed)"
                )
            region_records.append((path, region))
        for obj in read(path):
            if isinstance(obj, (Flash, Region, Line)) and not obj.polarity_dark:
                continue
            if isinstance(obj, Flash):
                flash_records.append((path, obj))
            box = bbox(obj)
            if box is None:
                continue
            all_boxes.append(box)
    if not all_boxes or not region_records:
        raise FabOutputError("filled copper regions are absent (fail-closed)")
    conductor_records = [
        (path, region) for path, region in region_records if region.function == "Conductor"
    ]
    if not conductor_records:
        raise FabOutputError("zone fill regions are absent (fail-closed)")
    gnd_net = next(
        (net for net in model.nets if net.name == "GND"),
        None,
    )
    if gnd_net is None:
        raise FabOutputError("GND net declaration is absent (fail-closed)")
    gnd_pads: list[tuple[str, float, float]] = []
    for placement in model.placements:
        if placement.side not in {"front", "back"}:
            raise FabOutputError(
                f"{placement.refdes}: unknown placement side (fail-closed)"
            )
        for refdes, pad_number in gnd_net.pads:
            if refdes != placement.refdes:
                continue
            for pad in placement.footprint.pads:
                if pad.number != pad_number:
                    continue
                x, y = rotate_point(pad.x_mm, pad.y_mm, placement.rotation_deg)
                if pad.through_hole:
                    layers = ("F.Cu", "B.Cu")
                elif pad.on_front == pad.on_back:
                    raise FabOutputError(
                        f"{placement.refdes} pad {pad.number}: copper layer is "
                        "ambiguous (fail-closed)"
                    )
                elif placement.side == "front":
                    layers = ("F.Cu",) if pad.on_front else ("B.Cu",)
                else:
                    layers = ("B.Cu",) if pad.on_front else ("F.Cu",)
                gnd_pads.extend((layer, placement.x_mm + x, placement.y_mm + y) for layer in layers)
    gnd_points = [
        *[
            (layer, via.x_mm, via.y_mm)
            for via in routes.vias
            if via.net == "GND"
            for layer in ("F.Cu", "B.Cu")
        ],
        *[(layer, x, y) for x, y in stitch_vias for layer in ("F.Cu", "B.Cu")],
    ]
    inset = model.edge_clearance_mm
    for _, region in conductor_records:
        x1, y1, x2, y2 = region.bbox_mm
        if x1 < inset or y1 < inset or x2 > model.width_mm - inset or y2 > model.height_mm - inset:
            raise FabOutputError("copper violates board edge clearance (fail-closed)")
    declared = min(zone.min_island_area_mm2 for zone in model.copper_zones)
    if min(region.area_mm2 for _, region in conductor_records) < declared:
        raise FabOutputError("copper island is below declared minimum area (fail-closed)")

    def point_in_polygon(
        point: tuple[float, float], polygon: Sequence[tuple[float, float]]
    ) -> bool:
        inside = False
        for first, second in zip(polygon, (*polygon[1:], polygon[0]), strict=True):
            if (first[1] > point[1]) != (second[1] > point[1]):
                x_intersection = (second[0] - first[0]) * (point[1] - first[1]) / (
                    second[1] - first[1]
                ) + first[0]
                if point[0] < x_intersection:
                    inside = not inside
        return inside

    if not model.keepouts:
        raise FabOutputError("antenna keepout declaration is absent (fail-closed)")
    def polygon_area(points: Sequence[tuple[float, float]]) -> float:
        if len(points) < 3:
            return 0.0
        return abs(
            sum(
                x1 * y2 - x2 * y1
                for (x1, y1), (x2, y2) in zip(
                    points, (*points[1:], points[0]), strict=True
                )
            )
        ) / 2.0

    def clip_polygon(
        polygon: Sequence[tuple[float, float]],
        axis: int,
        bound: float,
        keep_greater: bool,
    ) -> list[tuple[float, float]]:
        if not polygon:
            return []
        result: list[tuple[float, float]] = []
        for first, second in zip(polygon, (*polygon[1:], polygon[0]), strict=True):
            first_inside = (
                first[axis] >= bound if keep_greater else first[axis] <= bound
            )
            second_inside = (
                second[axis] >= bound if keep_greater else second[axis] <= bound
            )
            if first_inside != second_inside:
                denominator = second[axis] - first[axis]
                if denominator == 0:
                    continue
                ratio = (bound - first[axis]) / denominator
                result.append(
                    (
                        first[0] + ratio * (second[0] - first[0]),
                        first[1] + ratio * (second[1] - first[1]),
                    )
                )
            if second_inside:
                result.append(second)
        return result

    keepout_measurements: list[dict[str, object]] = []
    keepout_copper_area_mm2 = 0.0
    for keepout in model.keepouts:
        rect = (keepout.x1_mm, keepout.y1_mm, keepout.x2_mm, keepout.y2_mm)
        overlap_area = 0.0
        for _, region in conductor_records:
            clipped = list(region.points_mm)
            for axis, bound, keep_greater in (
                (0, rect[0], True),
                (0, rect[2], False),
                (1, rect[1], True),
                (1, rect[3], False),
            ):
                clipped = clip_polygon(clipped, axis, bound, keep_greater)
            overlap_area += polygon_area(clipped)
        keepout_copper_area_mm2 += overlap_area
        keepout_measurements.append(
            {"name": keepout.name, "copper_area_mm2": overlap_area}
        )
    if keepout_copper_area_mm2 > 1e-9:
        raise FabOutputError(
            "copper inside antenna keepout (fail-closed): "
            f"measured_area_mm2={keepout_copper_area_mm2}"
        )

    uncovered_stitch_vias = [
        (x, y)
        for x, y in stitch_vias
        if not any(
            point_in_polygon((x, y), region.points_mm)
            for _, region in conductor_records
        )
    ]
    if uncovered_stitch_vias:
        raise UncoveredStitchViasError(tuple(uncovered_stitch_vias))

    uncovered_gnd_points = [
        (layer, x, y)
        for layer, x, y in gnd_points
        if not any(
            ("F.Cu" if path == front_path else "B.Cu") == layer
            and point_in_polygon((x, y), region.points_mm)
            for path, region in conductor_records
        )
    ]
    uncovered_gnd_pads = [
        (layer, x, y)
        for layer, x, y in gnd_pads
        if not any(
            ("F.Cu" if path == front_path else "B.Cu") == layer
            and point_in_polygon((x, y), region.points_mm)
            for path, region in region_records
            if region.function
            in {"Conductor", "SMDPad,CuDef", "ComponentPad", "ViaPad"}
        )
            and not any(
                ("F.Cu" if path == front_path else "B.Cu") == layer
                and (
                    flash_box := bbox(flash)
                ) is not None
                and flash_box[0] <= x <= flash_box[2]
                # Gerbonara flash Y is in a Y-up frame; board coordinates are Y-down.
                and flash_box[1] <= -y <= flash_box[3]
                for path, flash in flash_records
            )
    ]
    if uncovered_gnd_points or uncovered_gnd_pads:
        uncovered = (*uncovered_gnd_points, *uncovered_gnd_pads)
        locations = ", ".join(
            f"{layer}@({x}, {y})" for layer, x, y in uncovered
        )
        raise FabOutputError(
            f"GND connection points lack copper coverage (fail-closed): {locations}"
        )
    connection_points = (*gnd_points, *gnd_pads)
    region_connection_points = [
        {
            "layer": "F.Cu" if path == front_path else "B.Cu",
            "area_mm2": region.area_mm2,
            "bbox_mm": region.bbox_mm,
            "gnd_connection_point_count": sum(
                point_layer == ("F.Cu" if path == front_path else "B.Cu")
                and point_in_polygon((x, y), region.points_mm)
                for point_layer, x, y in connection_points
            ),
        }
        for path, region in conductor_records
    ]

    parent = list(range(len(conductor_records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        left, right = find(first), find(second)
        if left != right:
            parent[right] = left

    for layer, x, y in connection_points:
        covered = [
            index
            for index, (path, region) in enumerate(conductor_records)
            if ("F.Cu" if path == front_path else "B.Cu") == layer
            and point_in_polygon((x, y), region.points_mm)
        ]
        if not covered:
            continue
        other_layer = [
            index
            for index, (path, region) in enumerate(conductor_records)
            if ("F.Cu" if path == front_path else "B.Cu") != layer
            and point_in_polygon((x, y), region.points_mm)
        ]
        for first in covered:
            for second in other_layer:
                union(first, second)
    for _index, (path, region) in enumerate(conductor_records):
        layer = "F.Cu" if path == front_path else "B.Cu"
        if not any(
            point_layer == layer and point_in_polygon((x, y), region.points_mm)
            for point_layer, x, y in connection_points
        ):
            raise FabOutputError(
                "Conductor region lacks a GND connection point (fail-closed): "
                f"layer={layer}, bbox_mm={region.bbox_mm}"
            )
    components = len({find(index) for index in range(len(conductor_records))})
    if components != 1:
        raise FabOutputError(
            "GND conductor regions are disconnected (fail-closed): "
            f"connected_components={components}"
        )
    def gerber_point(path: Path, flash: Flash) -> tuple[float, float]:
        x = float(cast(float, flash.x))  # pyright: ignore[reportUnknownMemberType]
        y = float(cast(float, flash.y))  # pyright: ignore[reportUnknownMemberType]
        return _gerber_to_board_point(x, y)

    def matching_flash(
        path: Path, point: tuple[float, float]
    ) -> tuple[float, float] | None:
        gerber_match_tolerance_mm = 1e-4
        matches = [
            gerber_point(path, flash)
            for record_path, flash in flash_records
            if record_path == path
        ]
        if not matches:
            return None
        match = min(
            matches,
            key=lambda candidate: math.hypot(
                candidate[0] - point[0], candidate[1] - point[1]
            ),
        )
        return (
            match
            if math.hypot(match[0] - point[0], match[1] - point[1])
            <= gerber_match_tolerance_mm
            else None
        )

    measured_stitch_points: list[tuple[float, float]] = []
    for stitch_point in stitch_vias:
        front_match = matching_flash(front_path, stitch_point)
        back_match = matching_flash(back_path, stitch_point)
        if front_match is None or back_match is None:
            raise FabOutputError(
                "stitch via flash is absent from filled Gerbers (fail-closed): "
                f"location={stitch_point}"
            )
        measured_stitch_points.append(front_match)
    if len(measured_stitch_points) < 2:
        raise FabOutputError(
            "at least two stitch via flashes are required for pitch measurement "
            "(fail-closed)"
        )
    nearest_distances = [
        min(
            math.hypot(point[0] - other[0], point[1] - other[1])
            for other in measured_stitch_points
            if other != point
        )
        for point in measured_stitch_points
    ]
    edge_x = model.edge_clearance_mm + model.via_diameter_mm / 2.0
    edge_y = edge_x
    edge_points = [
        point
        for point in measured_stitch_points
        if min(
            abs(point[0] - edge_x),
            abs(point[0] - (model.width_mm - edge_x)),
            abs(point[1] - edge_y),
            abs(point[1] - (model.height_mm - edge_y)),
        )
        <= 1e-5
    ]
    if len(edge_points) < 2:
        raise FabOutputError(
            "at least two perimeter stitch via flashes are required for perimeter "
            "pitch measurement (fail-closed)"
        )
    perimeter_width = model.width_mm - 2.0 * edge_x
    perimeter_height = model.height_mm - 2.0 * edge_y

    def perimeter_coordinate(point: tuple[float, float]) -> float:
        x, y = point
        distances = (
            abs(y - edge_y),
            abs(x - (model.width_mm - edge_x)),
            abs(y - (model.height_mm - edge_y)),
            abs(x - edge_x),
        )
        side = min(range(4), key=distances.__getitem__)
        if side == 0:
            return x - edge_x
        if side == 1:
            return perimeter_width + y - edge_y
        if side == 2:
            return perimeter_width + perimeter_height + (model.width_mm - edge_x - x)
        return (
            perimeter_width
            + perimeter_height
            + perimeter_width
            + (model.height_mm - edge_y - y)
        )

    perimeter_length = 2.0 * (perimeter_width + perimeter_height)
    perimeter_coordinates = sorted(perimeter_coordinate(point) for point in edge_points)
    perimeter_gaps = [
        second - first
        for first, second in itertools.pairwise(perimeter_coordinates)
    ]
    perimeter_gaps.append(
        perimeter_length - perimeter_coordinates[-1] + perimeter_coordinates[0]
    )
    declared_pitch = model.stitch_via_pitch_mm
    if declared_pitch is None:
        raise FabOutputError("declared stitch via pitch is unknown (fail-closed)")
    perimeter_max_gap = max(perimeter_gaps)
    nearest_max_distance = max(nearest_distances)
    pitch_measurement = {
        "declared_pitch_mm": declared_pitch,
        "perimeter_adjacent_max_gap_mm": perimeter_max_gap,
        "all_stitch_nearest_neighbor_max_distance_mm": nearest_max_distance,
        "perimeter_stitch_via_count": len(edge_points),
        "stitch_via_count": len(measured_stitch_points),
        "declared_pitch_satisfied": (
            perimeter_max_gap <= declared_pitch + 1e-6
            and nearest_max_distance <= declared_pitch + 1e-6
        ),
        "basis": (
            "Filled F.Cu and B.Cu Gerber flash centers independently matched "
            "to each requested stitch via location."
        ),
    }
    return {
        "front_regions": sum(path == front_path for path, _ in conductor_records),
        "back_regions": sum(path == back_path for path, _ in conductor_records),
        "copper_area_mm2": sum(region.area_mm2 for _, region in conductor_records),
        "connected_components": components,
        "min_island_area_mm2": min(region.area_mm2 for _, region in conductor_records),
        "stitch_via_coverage": len(stitch_vias),
        "zone_regions": [
            {
                "layer": "F.Cu" if path == front_path else "B.Cu",
                "area_mm2": region.area_mm2,
                "bbox_mm": region.bbox_mm,
            }
            for path, region in conductor_records
        ],
        "region_connection_points": region_connection_points,
        "keepout_copper": keepout_copper_area_mm2 > 1e-9,
        "keepout_copper_area_mm2": keepout_copper_area_mm2,
        "keepout_measurements": keepout_measurements,
        "stitch_via_pitch_measurement": pitch_measurement,
    }


def _parse_pad(
    fp_ref: str,
    fp_at: tuple[float, float, float],
    node: object,
    net_names: Mapping[str, str],
) -> PadMeasurement:
    values = _items(node)
    if len(values) < 5:
        raise FabOutputError("malformed KiCad pad")
    pad_at = _one(node, "at")
    size = _one(node, "size")
    if pad_at is None or size is None or len(pad_at) < 3 or len(size) < 3:
        raise FabOutputError(f"{fp_ref}: pad missing at/size")
    local_x, local_y = _number(pad_at[1]), _number(pad_at[2])
    x_off, y_off = rotate(local_x, local_y, fp_at[2])
    drill = _one(node, "drill")
    drill_mm = None
    drill_x_mm = None
    drill_y_mm = None
    if drill is not None and len(drill) > 1:
        drill_values = [
            _number(item) for item in drill[1:] if not isinstance(item, (list, sexpdata.Symbol))
        ]
        if drill_values:
            drill_x_mm = drill_values[0]
            drill_y_mm = drill_values[1] if len(drill_values) > 1 else drill_values[0]
            drill_mm = min(drill_x_mm, drill_y_mm)
    kind = "through-hole" if "thru_hole" in {str(item) for item in values} else "smd"
    if "np_thru_hole" in {str(item) for item in values}:
        kind = "npth"
    net_node = _one(node, "net")
    net_value = (
        net_names.get(str(net_node[1]), str(net_node[1]))
        if net_node is not None and len(net_node) > 1
        else None
    )
    return PadMeasurement(
        refdes=fp_ref,
        kind=kind,
        x_mm=fp_at[0] + x_off,
        y_mm=fp_at[1] + y_off,
        rotation_deg=fp_at[2] + (_number(pad_at[3]) if len(pad_at) > 3 else 0.0),
        size_x_mm=_number(size[1]),
        size_y_mm=_number(size[2]),
        drill_mm=drill_mm,
        net=net_value,
        drill_x_mm=drill_x_mm,
        drill_y_mm=drill_y_mm,
        number=str(values[1]) if len(values) > 1 else None,
    )


def parse_routed_board(path: Path) -> BoardMeasurement:
    try:
        root = cast(
            object,
            sexpdata.loads(path.read_text(encoding="utf-8")),  # pyright: ignore[reportUnknownMemberType]
        )
    except Exception as exc:  # pragma: no cover - parser-specific errors
        raise FabOutputError(f"{path.name}: sexpdata parse failed: {exc}") from exc
    if _tag(root) != "kicad_pcb":
        raise FabOutputError(f"{path.name}: not a kicad_pcb document")
    footprints: list[FootprintMeasurement] = []
    vias: list[ViaMeasurement] = []
    tracks: list[float] = []
    segments: list[SegmentMeasurement] = []
    outline_points: list[tuple[float, float]] = []
    silk_heights: list[float] = []
    silk_widths: list[float] = []
    net_names = {
        str(items[1]): str(items[2])
        for child in _items(root)[1:]
        if _tag(child) == "net"
        for items in [_items(child)]
        if len(items) > 2
    }
    net_name_source = "board_net_declarations"
    if not net_names:
        net_name_source = "pad_net_fallback"
        for footprint in _direct(root, "footprint"):
            for pad in _direct(footprint, "pad"):
                net_node = _one(pad, "net")
                if net_node is not None and len(net_node) > 1:
                    net_names[str(net_node[1])] = str(
                        net_node[2] if len(net_node) > 2 else net_node[1]
                    )
    if not net_names:
        raise FabOutputError(f"{path.name}: net names unavailable (fail-closed)")
    for footprint in _direct(root, "footprint"):
        for pad in _direct(footprint, "pad"):
            net_node = _one(pad, "net")
            if net_node is not None and (
                len(net_node) < 2 or str(net_node[1]) not in net_names
            ):
                raise FabOutputError(
                    f"{path.name}: pad net name unavailable (fail-closed)"
                )
    for node in _items(root)[1:]:
        tag = _tag(node)
        if tag == "footprint":
            refdes = _property(node, "Reference")
            if not refdes:
                continue
            fp_at = _at(node)
            layer_node = _one(node, "layer")
            layer = str(layer_node[1]) if layer_node and len(layer_node) > 1 else "unknown"
            pads = tuple(
                _parse_pad(refdes, fp_at, pad, net_names) for pad in _direct(node, "pad")
            )
            for text in _direct(node, "fp_text") + _direct(node, "property"):
                layer = _one(text, "layer")
                effects = _one(text, "effects")
                font = _one(effects, "font") if effects else None
                size = _one(font, "size") if font else None
                thickness = _one(font, "thickness") if font else None
                if (
                    layer and len(layer) > 1 and str(layer[1]).endswith("SilkS")
                    and size and len(size) > 2
                ):
                    silk_heights.append(_number(size[2]))
                    if thickness and len(thickness) > 1:
                        silk_widths.append(_number(thickness[1]))
            footprints.append(
                FootprintMeasurement(
                    refdes, fp_at[0], fp_at[1], fp_at[2], str(layer), pads,
                    _footprint_bbox(node, fp_at, "CrtYd"),
                    _footprint_bbox(node, fp_at, "Fab"),
                )
            )
        elif tag == "via":
            at = _one(node, "at")
            size = _one(node, "size")
            drill = _one(node, "drill")
            layers = _one(node, "layers")
            if at is None or size is None or drill is None or layers is None:
                raise FabOutputError("via missing at/size/drill/layers")
            vias.append(
                ViaMeasurement(
                    _number(at[1]),
                    _number(at[2]),
                    _number(size[1]),
                    _number(drill[1]),
                    tuple(str(x) for x in layers[1:]),
                )
            )
        elif tag == "segment":
            width = _one(node, "width")
            start = _one(node, "start")
            end = _one(node, "end")
            layer_node = _one(node, "layer")
            net_node = _one(node, "net")
            if (
                width is None
                or len(width) < 2
                or start is None
                or len(start) < 3
                or end is None
                or len(end) < 3
                or layer_node is None
                or len(layer_node) < 2
                or net_node is None
                or len(net_node) < 2
            ):
                raise FabOutputError("segment missing width/start/end/layer/net")
            net_id = str(net_node[1])
            if net_id not in net_names:
                raise FabOutputError("segment net name unavailable (fail-closed)")
            tracks.append(_number(width[1]))
            segments.append(
                SegmentMeasurement(
                    net=net_names[net_id],
                    layer=str(layer_node[1]),
                    width_mm=_number(width[1]),
                    start=(_number(start[1]), _number(start[2])),
                    end=(_number(end[1]), _number(end[2])),
                )
            )
        elif tag in {"gr_line", "gr_rect", "gr_arc", "gr_poly"}:
            layer = _one(node, "layer")
            if layer is None or len(layer) < 2 or str(layer[1]) != "Edge.Cuts":
                continue
            start = _one(node, "start")
            end = _one(node, "end")
            if start and end:
                outline_points.extend(
                    [(_number(start[1]), _number(start[2])), (_number(end[1]), _number(end[2]))]
                )
        elif tag == "gr_text":
            layer = _one(node, "layer")
            effects = _one(node, "effects")
            font = _one(effects, "font") if effects else None
            size = _one(font, "size") if font else None
            thickness = _one(font, "thickness") if font else None
            if (
                layer
                and len(layer) > 1
                and str(layer[1]).endswith("SilkS")
                and size
                and len(size) > 2
            ):
                silk_heights.append(_number(size[2]))
                if thickness and len(thickness) > 1:
                    silk_widths.append(_number(thickness[1]))
    bbox = None
    if outline_points:
        xs, ys = zip(*outline_points, strict=True)
        bbox = (min(xs), min(ys), max(xs), max(ys))
    return BoardMeasurement(
        tuple(footprints),
        tuple(vias),
        min(tracks) if tracks else None,
        min(silk_heights) if silk_heights else None,
        min(silk_widths) if silk_widths else None,
        bbox,
        (),
        0,
        net_name_source,
        tuple(segments),
    )


def measure_net_track_widths(
    gerber_paths: Mapping[str, Path],
    measurement: BoardMeasurement,
    requirements: Sequence[NetWidthRequirement],
    tolerance_mm: float,
) -> dict[str, object]:
    """Match every routed Gerber line to a saved-board segment and measure width."""
    if not math.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise FabOutputError("width measurement tolerance is invalid (fail-closed)")
    segments = measurement.segments
    if not segments:
        raise FabOutputError("saved board has no net segments (fail-closed)")
    matched: dict[str, list[float]] = defaultdict(list)
    lengths: dict[str, float] = defaultdict(float)
    matched_objects = 0
    object_type_counts: dict[str, int] = defaultdict(int)
    for layer_name, path in sorted(gerber_paths.items()):
        if layer_name not in {"F.Cu", "B.Cu"}:
            continue
        try:
            gerber = GerberFile.open(path)  # pyright: ignore[reportUnknownMemberType]
            objects = cast("list[object]", gerber.objects)  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:
            raise FabOutputError(
                f"{path.name}: Gerber width measurement parse failed: {exc}"
            ) from exc
        for obj in objects:
            object_type = type(obj).__name__
            object_type_counts[object_type] += 1
            if isinstance(obj, (Region, Flash)):
                continue
            if not isinstance(obj, Line):
                raise FabOutputError(
                    f"{path.name}: unexpected conductor object type "
                    f"{object_type} (fail-closed)"
                )
            aperture = obj.aperture
            if not isinstance(aperture, CircleAperture):
                raise FabOutputError(
                    f"{path.name}: unsupported conductor aperture "
                    f"{type(aperture).__name__}; width is unknown"
                )
            start = _gerber_to_board_point(
                float(obj.x1),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                float(obj.y1),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            )
            end = _gerber_to_board_point(
                float(obj.x2),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                float(obj.y2),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            )
            candidates = [
                segment
                for segment in segments
                if segment.layer == layer_name
                and (
                    (
                        math.dist(start, segment.start) <= tolerance_mm
                        and math.dist(end, segment.end) <= tolerance_mm
                    )
                    or (
                        math.dist(start, segment.end) <= tolerance_mm
                        and math.dist(end, segment.start) <= tolerance_mm
                    )
                )
            ]
            if len(candidates) != 1:
                raise FabOutputError(
                    f"{path.name}: conductor line cannot be uniquely matched "
                    f"to saved-board net segment at {start}->{end}"
                )
            segment = candidates[0]
            width_mm = float(aperture.diameter)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            matched[segment.net].append(width_mm)
            lengths[segment.net] += math.dist(segment.start, segment.end)
            matched_objects += 1
    if matched_objects == 0:
        raise FabOutputError("no routed Gerber conductor lines were measured (fail-closed)")
    by_net = {requirement.net_name: requirement for requirement in requirements}
    if set(matched) - set(by_net):
        raise FabOutputError(
            f"Gerber conductor attributed to undeclared net(s): "
            f"{sorted(set(matched) - set(by_net))}"
        )
    evidence: dict[str, object] = {
        "matching_method": (
            "post-refill Gerber Line endpoints to saved-board segment endpoints; "
            "Gerber Y-up converted to board Y-down"
        ),
        "tolerance_mm": tolerance_mm,
        "matched_object_count": matched_objects,
        "recognized_object_count": sum(object_type_counts.values()),
        "object_type_counts": dict(sorted(object_type_counts.items())),
        "nets": {},
    }
    net_evidence: dict[str, object] = {}
    for requirement in requirements:
        widths = matched.get(requirement.net_name)
        if not widths:
            raise FabOutputError(
                f"net {requirement.net_name}: no matched Gerber conductor width"
            )
        measured = min(widths)
        passed = measured + tolerance_mm >= requirement.adopted_width_mm
        net_evidence[requirement.net_name] = {
            **requirement.evidence(),
            "measured_minimum_mm": measured,
            "sample_count": len(widths),
            "matched_object_count": len(widths),
            "pass": passed,
            "total_conductor_length_mm": lengths[requirement.net_name],
        }
        if not passed:
            raise FabOutputError(
                f"net {requirement.net_name}: measured width {measured:.6f} mm "
                f"is below adopted width {requirement.adopted_width_mm:.6f} mm"
            )
    evidence["nets"] = net_evidence
    return evidence


def measure_net_path_resistance(
    measurement: BoardMeasurement,
    requirements: Sequence[NetWidthRequirement],
    routed_vias: Sequence[RoutedVia],
    copper_thickness_mm: float,
    tolerance_mm: float = 1e-4,
) -> dict[str, object]:
    """Measure shortest pad-to-pad resistance through saved routed geometry."""
    if not math.isfinite(copper_thickness_mm) or copper_thickness_mm <= 0:
        raise FabOutputError("copper thickness is invalid (fail-closed)")
    if not math.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise FabOutputError("path matching tolerance is invalid (fail-closed)")
    rho_ohm_mm = 1.724e-5
    by_net: dict[str, list[SegmentMeasurement]] = defaultdict(list)
    for segment in measurement.segments:
        by_net[segment.net].append(segment)
    result: dict[str, object] = {}
    for requirement in requirements:
        segments = by_net.get(requirement.net_name, [])
        pads = [pad for pad in measurement.pads if pad.net == requirement.net_name]
        nodes: set[tuple[str, float, float]] = set()
        edges: dict[
            tuple[str, float, float],
            list[tuple[tuple[str, float, float], float]],
        ] = defaultdict(list)

        def node_for(
            layer: str,
            point: tuple[float, float],
            nodes_ref: set[tuple[str, float, float]] = nodes,
        ) -> tuple[str, float, float]:
            for existing in nodes_ref:
                if existing[0] == layer and math.dist(existing[1:], point) <= tolerance_mm:
                    return existing
            node = (layer, round(point[0], 6), round(point[1], 6))
            nodes_ref.add(node)
            return node

        for segment in segments:
            start = node_for(segment.layer, segment.start)
            end = node_for(segment.layer, segment.end)
            length_mm = math.dist(segment.start, segment.end)
            resistance = (
                rho_ohm_mm * length_mm
                / (segment.width_mm * copper_thickness_mm)
            )
            edges[start].append((end, resistance))
            edges[end].append((start, resistance))
        for via in routed_vias:
            if via.net != requirement.net_name:
                continue
            front = node_for("F.Cu", (via.x_mm, via.y_mm))
            back = node_for("B.Cu", (via.x_mm, via.y_mm))
            edges[front].append((back, 0.0))
            edges[back].append((front, 0.0))

        pad_nodes: list[tuple[str, tuple[str, float, float]]] = []
        for pad in pads:
            candidates = [
                node
                for node in nodes
                if math.dist(node[1:], (pad.x_mm, pad.y_mm)) <= tolerance_mm
            ]
            if len(candidates) != 1:
                continue
            label = f"{pad.refdes}-{pad.number or '?'}"
            pad_nodes.append((label, candidates[0]))

        def shortest_path(
            source: tuple[str, float, float],
            target: tuple[str, float, float],
            edges_ref: dict[
                tuple[str, float, float],
                list[tuple[tuple[str, float, float], float]],
            ] = edges,
        ) -> float | None:
            distances: dict[tuple[str, float, float], float] = {source: 0.0}
            pending: list[tuple[float, tuple[str, float, float]]] = [(0.0, source)]
            while pending:
                pending.sort(key=lambda pending_item: pending_item[0], reverse=True)
                distance, current = pending.pop()
                if current == target:
                    return distance
                if distance > distances.get(current, math.inf):
                    continue
                for neighbor, weight in edges_ref.get(current, []):
                    candidate = distance + weight
                    if candidate < distances.get(neighbor, math.inf):
                        distances[neighbor] = candidate
                        pending.append((candidate, neighbor))
            return None

        path_candidates: list[tuple[float, str, str]] = []
        for index, (source_label, source_node) in enumerate(pad_nodes):
            for target_label, target_node in pad_nodes[index + 1 :]:
                resistance = shortest_path(source_node, target_node)
                if resistance is not None:
                    path_candidates.append((resistance, source_label, target_label))
        total_length = sum(
            math.dist(segment.start, segment.end) for segment in segments
        )
        total_resistance = (
            rho_ohm_mm
            * total_length
            / (requirement.adopted_width_mm * copper_thickness_mm)
        )
        current = requirement.current_max_a
        upper_bound_basis = (
            "Total routed conductor length is treated as one series path; "
            "parallel branches are ignored. For GND, the filled-plane return path "
            "is omitted, so this is a pessimistic routed-conductor upper bound."
        )
        item: dict[str, object] = {
            "total_conductor_length_mm": total_length,
            "series_resistance_upper_bound_ohm": total_resistance,
            "ir_drop_upper_bound_v": (
                total_resistance * current if current is not None else None
            ),
            "upper_bound_basis": upper_bound_basis,
            "path_resistance_basis": (
                "Shortest resistance path between measured pads over saved-board "
                "segment endpoints and routed via endpoints; GND plane return is "
                "not represented."
            ),
            "via_resistance_model": (
                "Routed via endpoint connections are modeled as ideal zero-ohm "
                "connections because barrel plating resistance is not measured."
            ),
            "path_measurement_status": "measured" if path_candidates else "unknown",
        }
        if path_candidates:
            resistance, source_label, target_label = max(path_candidates)
            item.update(
                {
                    "farthest_pad_pair": [source_label, target_label],
                    "farthest_pad_path_resistance_ohm": resistance,
                    "farthest_pad_path_ir_drop_v": (
                        resistance * current if current is not None else None
                    ),
                }
            )
        result[requirement.net_name] = item
    return result


def read_drill_measurement(path: Path) -> tuple[tuple[float, ...], int]:
    try:
        drill = ExcellonFile.open(path)  # pyright: ignore[reportUnknownMemberType]
        objects = cast("list[object]", drill.objects)  # pyright: ignore[reportUnknownMemberType]
    except Exception as exc:  # pragma: no cover
        raise FabOutputError(f"{path.name}: gerbonara parse failed: {exc}") from exc
    tools: set[float] = set()
    for obj in objects:
        aperture = getattr(obj, "aperture", None)
        diameter = getattr(aperture, "diameter", None)
        if diameter is not None:
            tools.add(float(cast(float, diameter)))
    return tuple(sorted(tools)), len(objects)


def _cap(profile: FabProfile, key: str) -> float:
    value = profile.data["capabilities"].get(key)
    if value is None:
        raise FabOutputError(f"profile capability {key!r} is missing")
    return float(value["value"])


def _cap_pair(profile: FabProfile, key: str) -> tuple[float, float]:
    value = profile.data["capabilities"].get(key)
    if value is None or not isinstance(value["value"], list) or len(value["value"]) != 2:
        raise FabOutputError(f"profile capability {key!r} must be a pair")
    return float(value["value"][0]), float(value["value"][1])


def _pref(profile: FabProfile, rule_id: str) -> tuple[float, str, str]:
    for item in profile.data["preferences"]:
        if item["rule_id"] == rule_id:
            threshold = item.get("threshold")
            if not isinstance(threshold, dict):
                raise FabOutputError(f"profile preference {rule_id!r} threshold is missing")
            raw_threshold = cast(dict[str, object], threshold)
            value = raw_threshold.get("value")
            unit = raw_threshold.get("unit")
            comparison = raw_threshold.get("comparison")
            if (
                not isinstance(value, (float, int))
                or not isinstance(unit, str)
                or not isinstance(comparison, str)
            ):
                raise FabOutputError(f"profile preference {rule_id!r} threshold is malformed")
            return (float(value), unit, comparison)
    raise FabOutputError(f"profile preference {rule_id!r} is missing")


def _below(value: float, threshold: tuple[float, str, str]) -> bool:
    return value < threshold[0]


def _equal(value: float, threshold: tuple[float, str, str]) -> bool:
    return math.isclose(value, threshold[0], rel_tol=0.0, abs_tol=1e-9)


def _allowance_map(
    allowances: Iterable[ProcessAllowanceView], profile: FabProfile
) -> dict[str, ProcessAllowanceView]:
    values = tuple(allowances)
    validate_allowances_against_profile(values, profile)
    return {item.rule_id: item for item in values}


def _finding(
    rule_id: str,
    classification: str,
    measured: object,
    threshold: object,
    unit: str,
    locations: Sequence[Mapping[str, object]],
    allowance: ProcessAllowanceView | None,
) -> dict[str, object]:
    is_capability = classification == "capability_violation"
    effective_allowance = None if is_capability else allowance
    return {
        "rule_id": rule_id,
        "classification": classification,
        "measured_value": measured,
        "threshold": threshold,
        "unit": unit,
        "locations": [dict(location) for location in locations],
        "allowance": None
        if effective_allowance is None
        else {
            "node_id": effective_allowance.node_id,
            "reason": effective_allowance.reason,
            "requirement": effective_allowance.requirement,
        },
        "status": "allowed" if effective_allowance is not None else "fail",
    }


def run_dfm(
    measurement: BoardMeasurement,
    profile: FabProfile,
    revision: str,
    allowances: tuple[ProcessAllowanceView, ...],
    lane: ElectricalLane | None = None,
    intent: FabOrderIntentView | None = None,
    edge_clearance_mm: float | None = None,
    edge_overhang_declarations: Mapping[str, float] | None = None,
    cpl_unknowns: Mapping[str, Sequence[str]] | None = None,
    silkscreen_evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if edge_clearance_mm is None:
        raise FabOutputError(
            "board edge copper clearance is required from the electrical graph"
        )
    allowed = _allowance_map(allowances, profile)
    thresholds = {
        rule: _pref(profile, rule)
        for rule in (
            "via-hole-prefer-020",
            "via-hole-015-cost",
            "via-hole-small-diameter-cost",
            "via-diameter-margin-quality",
            "pth-hole-prefer-050",
            "pth-annular-ring-prefer-025",
            "track-width-quality-margin",
            "optimal-layer-balance",
        )
    }
    findings: list[dict[str, object]] = []

    def add(
        rule: str,
        classification: str,
        measured: object,
        threshold: object,
        unit: str,
        locations: Sequence[Mapping[str, object]],
    ) -> None:
        findings.append(
            _finding(rule, classification, measured, threshold, unit, locations, allowed.get(rule))
        )

    for via in measurement.vias:
        loc = [{"x_mm": via.x_mm, "y_mm": via.y_mm}]
        if via.hole_mm < _cap(profile, "min_via_hole"):
            add(
                "via-hole-capability",
                "capability_violation",
                via.hole_mm,
                _cap(profile, "min_via_hole"),
                "mm",
                loc,
            )
        if via.diameter_mm < _cap(profile, "min_via_diameter"):
            add(
                "via-diameter-capability",
                "capability_violation",
                via.diameter_mm,
                _cap(profile, "min_via_diameter"),
                "mm",
                loc,
            )
        if via.diameter_mm - via.hole_mm < _cap(profile, "via_diameter_margin"):
            add(
                "via-margin-capability",
                "capability_violation",
                via.diameter_mm - via.hole_mm,
                _cap(profile, "via_diameter_margin"),
                "mm",
                loc,
            )
        if _equal(via.hole_mm, thresholds["via-hole-015-cost"]):
            add(
                "via-hole-015-cost",
                "cost_or_lead_time_adder",
                via.hole_mm,
                thresholds["via-hole-015-cost"][0],
                "mm",
                loc,
            )
        if via.hole_mm <= _cap(profile, "min_via_diameter") and _below(
            via.diameter_mm, thresholds["via-hole-small-diameter-cost"]
        ):
            add(
                "via-hole-small-diameter-cost",
                "cost_or_lead_time_adder",
                via.diameter_mm,
                thresholds["via-hole-small-diameter-cost"][0],
                "mm",
                loc,
            )
        if _below(via.hole_mm, thresholds["via-hole-prefer-020"]):
            add(
                "via-hole-prefer-020",
                "cost_or_lead_time_adder",
                via.hole_mm,
                thresholds["via-hole-prefer-020"][0],
                "mm",
                loc,
            )
        if _below(via.diameter_mm - via.hole_mm, thresholds["via-diameter-margin-quality"]):
            add(
                "via-diameter-margin-quality",
                "quality_risk",
                via.diameter_mm - via.hole_mm,
                thresholds["via-diameter-margin-quality"][0],
                "mm",
                loc,
            )
        if set(via.layers) != {"F.Cu", "B.Cu"}:
            add(
                "blind-buried-via-unsupported",
                "capability_violation",
                via.layers,
                "F.Cu/B.Cu",
                "layers",
                loc,
            )
    for pad in measurement.pads:
        loc = [{"refdes": pad.refdes, "x_mm": pad.x_mm, "y_mm": pad.y_mm}]
        if pad.kind == "npth" and (pad.drill_mm or 0) < _cap(profile, "min_npth"):
            add(
                "npth-drill-capability",
                "capability_violation",
                pad.drill_mm,
                _cap(profile, "min_npth"),
                "mm",
                loc,
            )
        pad_half_x = pad.size_x_mm / 2.0
        pad_half_y = pad.size_y_mm / 2.0
        outline = measurement.outline_bbox_mm
        if outline is not None and (
            pad.x_mm - pad_half_x < edge_clearance_mm - 1e-6
            or pad.y_mm - pad_half_y < edge_clearance_mm - 1e-6
            or pad.x_mm + pad_half_x
            > outline[2]
            - edge_clearance_mm
            + 1e-6
            or pad.y_mm + pad_half_y
            > outline[3]
            - edge_clearance_mm
            + 1e-6
        ):
            add(
                "pad-to-board-edge-clearance",
                "capability_violation",
                {"refdes": pad.refdes, "x_mm": pad.x_mm, "y_mm": pad.y_mm},
                edge_clearance_mm,
                "mm",
                loc,
            )
        if pad.kind == "through-hole" and pad.annular_ring_mm is not None:
            if pad.annular_ring_mm < _cap(profile, "min_pth_annular_ring_2l_1oz"):
                add(
                    "pth-annular-ring-capability",
                    "capability_violation",
                    pad.annular_ring_mm,
                    _cap(profile, "min_pth_annular_ring_2l_1oz"),
                    "mm",
                    loc,
                )
            if _below(pad.annular_ring_mm, thresholds["pth-annular-ring-prefer-025"]):
                add(
                    "pth-annular-ring-prefer-025",
                    "quality_risk",
                    pad.annular_ring_mm,
                    thresholds["pth-annular-ring-prefer-025"][0],
                    "mm",
                    loc,
                )
            if pad.drill_mm is not None and _below(pad.drill_mm, thresholds["pth-hole-prefer-050"]):
                add(
                    "pth-hole-prefer-050",
                    "quality_risk",
                    pad.drill_mm,
                    thresholds["pth-hole-prefer-050"][0],
                    "mm",
                    loc,
                )
        smd_min = _cap_pair(profile, "min_smd_pad")
        if pad.kind == "smd" and (pad.size_x_mm < smd_min[0] or pad.size_y_mm < smd_min[1]):
            add(
                "smd-pad-capability",
                "capability_violation",
                [pad.size_x_mm, pad.size_y_mm],
                list(smd_min),
                "mm",
                loc,
            )
    if measurement.outline_bbox_mm is None and measurement.pads:
        add(
            "board-outline-geometry-missing",
            "capability_violation",
            None,
            "board outline required",
            "geometry",
            [],
        )
    missing_body_refdes: list[str] = []
    declarations = edge_overhang_declarations or {}
    for fp in measurement.footprints:
        bbox = fp.body_bbox_mm
        if bbox is None or measurement.outline_bbox_mm is None:
            if bbox is None:
                missing_body_refdes.append(fp.refdes)
            continue
        ox1, oy1, ox2, oy2 = measurement.outline_bbox_mm
        overhang = max(ox1 - bbox[0], oy1 - bbox[1], bbox[2] - ox2, bbox[3] - oy2, 0.0)
        if overhang > 1e-9:
            declared_allowed = declarations.get(fp.refdes)
            if declared_allowed is None or overhang > declared_allowed + 1e-6:
                add(
                    "undeclared-board-edge-overhang",
                    "capability_violation",
                    overhang,
                    declared_allowed if declared_allowed is not None else "declaration required",
                    "mm",
                    [{"refdes": fp.refdes, "x_mm": fp.x_mm, "y_mm": fp.y_mm}],
                )
    for via in measurement.vias:
        for pad in measurement.pads:
            if pad.kind != "smd":
                continue
            local_x, local_y = _inverse_rotate(
                via.x_mm - pad.x_mm, via.y_mm - pad.y_mm, pad.rotation_deg
            )
            # DRC owns unrelated-net copper clearance; DFM only checks a drill
            # circle intersecting a soldered SMD pad, which requires filled plating.
            radius = via.hole_mm / 2
            nearest_x = min(max(local_x, -pad.size_x_mm / 2), pad.size_x_mm / 2)
            nearest_y = min(max(local_y, -pad.size_y_mm / 2), pad.size_y_mm / 2)
            if math.hypot(local_x - nearest_x, local_y - nearest_y) <= radius:
                add(
                    "via-in-pad-process",
                    "cost_or_lead_time_adder",
                    {"via_x_mm": via.x_mm, "via_y_mm": via.y_mm},
                    {"refdes": pad.refdes},
                    "overlap",
                    [{"refdes": pad.refdes, "x_mm": via.x_mm, "y_mm": via.y_mm}],
                )
    if measurement.min_track_width_mm is not None:
        if measurement.min_track_width_mm < _cap(profile, "min_track_width"):
            add(
                "track-width-capability",
                "capability_violation",
                measurement.min_track_width_mm,
                _cap(profile, "min_track_width"),
                "mm",
                [],
            )
        if _below(measurement.min_track_width_mm, thresholds["track-width-quality-margin"]):
            add(
                "track-width-quality-margin",
                "quality_risk",
                measurement.min_track_width_mm,
                thresholds["track-width-quality-margin"][0],
                "mm",
                [],
            )
    if measurement.silk_min_height_mm is not None and measurement.silk_min_height_mm < _cap(
        profile, "min_silk_height"
    ):
        add(
            "silk-height-capability",
            "capability_violation",
            measurement.silk_min_height_mm,
            _cap(profile, "min_silk_height"),
            "mm",
            [],
        )
    if measurement.silk_min_width_mm is not None and measurement.silk_min_width_mm < _cap(
        profile, "min_silk_width"
    ):
        add(
            "silk-width-capability",
            "capability_violation",
            measurement.silk_min_width_mm,
            _cap(profile, "min_silk_width"),
            "mm",
            [],
        )
    if lane is not None and intent is not None:
        economic = profile.data["assembly_classes"]["economic"]
        combination = any(
            lane.board.layers == item["layers"]
            and lane.board.thickness_mm == item["thickness_mm"]
            and intent.soldermask_color in item["colors"]
            and intent.surface_finish in item["surface_finishes"]
            and item["quantity_pcs"][0] <= intent.quantity_pcs <= item["quantity_pcs"][1]
            and intent.assembly_sides in economic["assembly_sides"]
            for item in economic["combinations"]
        )
        in_economic = intent.pcba_class_target == "economic" and (
            intent.assembly_sides == "top"
            and combination
            and economic["board_size_mm"]["min"][0]
            <= lane.board.width_mm
            <= economic["board_size_mm"]["max"][0]
            and economic["board_size_mm"]["min"][1]
            <= lane.board.height_mm
            <= economic["board_size_mm"]["max"][1]
        )
        if intent.pcba_class_target == "standard" or not in_economic:
            add(
                "economic-pcba-envelope",
                "cost_or_lead_time_adder",
                {
                    "layers": lane.board.layers,
                    "thickness_mm": lane.board.thickness_mm,
                    "soldermask_color": intent.soldermask_color,
                    "surface_finish": intent.surface_finish,
                    "assembly_sides": intent.assembly_sides,
                    "pcba_class_target": intent.pcba_class_target,
                },
                "economic combination; standard requires edge rails/fiducials and build >= 4 days",
                "combination",
                [],
            )
        if lane.board.layers > thresholds["optimal-layer-balance"][0]:
            add(
                "optimal-layer-balance",
                "quality_risk",
                lane.board.layers,
                thresholds["optimal-layer-balance"][0],
                "layers",
                [],
            )
    checks = [
        {
            "rule_id": "component_body_geometry",
            "reason": (
                "F.Fab body geometry is unavailable for "
                + ", ".join(missing_body_refdes)
                + "; physical overhang was not independently measured for these references."
            ),
        }
        if missing_body_refdes
        else None,
        {
            "rule_id": "pth-to-track-prefer-035",
            "reason": (
                "DFM v1 does not yet independently measure pad-to-track distances; "
                "KiCad DRC clearance is not a substitute."
            ),
        },
        {
            "rule_id": "via_hole_to_hole",
            "reason": "KiCad custom rules do not provide an independently verified "
            "hole-to-hole constraint in this KiCad 10 environment.",
        },
        {
            "rule_id": "routed_edge_copper_clearance",
            "reason": "The KiCad custom-rule edge-clearance constraint was not accepted "
            "as semantically equivalent; independent edge geometry is not implemented.",
        },
        {
            "rule_id": "connector_mating_face_edge_alignment",
            "reason": (
                "Connector mating-face alignment requires a footprint semantic marker not emitted "
                "by the independent board parser."
            ),
        },
        {
            "rule_id": "pad_to_silk",
            "reason": "Silkscreen clearance is not independently measured; DRC is not "
            "treated as an equivalent DFM measurement.",
        }
        if silkscreen_evidence is None
        else None,
        {
            "rule_id": "min_via_diameter",
            "reason": "KiCad custom rules cannot be used as a verified via outer-diameter "
            "measurement; the independent DFM measurement remains authoritative.",
        },
        {
            "rule_id": "min_plated_slot_width",
            "reason": "Drill parsing records tool diameters but does not independently "
            "classify plated slot width.",
        },
        {
            "rule_id": "min_nonplated_slot_width",
            "reason": "Drill parsing records tool diameters but does not independently "
            "classify non-plated slot width.",
        },
        {
            "rule_id": "slot_length_width_ratio",
            "reason": "Slot length-to-width ratio is not independently measured.",
        },
        {
            "rule_id": "soldermask_bridge",
            "reason": "Soldermask bridge geometry is not independently measured.",
        },
        {
            "rule_id": "pad_to_track_clearance",
            "reason": "Pad-to-track and PTH-to-track geometry is not independently measured.",
        },
        {
            "rule_id": "min_package",
            "reason": "Graph component data does not include package dimensions.",
        },
        {
            "rule_id": "min_ic_pitch",
            "reason": "Graph component data does not include IC pin pitch.",
        },
        {
            "rule_id": "min_bga_pitch",
            "reason": "Graph component data does not include BGA pitch.",
        },
    ]
    checks = [item for item in checks if item is not None]
    if measurement.silk_min_height_mm is None:
        checks.append(
            {
                "rule_id": "min_silk_height",
                "reason": "No independent silkscreen text geometry was emitted by this board; "
                "the minimum character-height check is not treated as passed.",
            }
        )
    if measurement.silk_min_width_mm is None:
        checks.append(
            {
                "rule_id": "min_silk_width",
                "reason": "No independent silkscreen stroke geometry was emitted by this board; "
                "the minimum line-width check is not treated as passed.",
            }
        )
    unused = [
        item.rule_id
        for item in allowances
        if not any(f["rule_id"] == item.rule_id for f in findings)
    ]
    for rule_id in unused:
        findings.append(
            _finding(
                "unused_allowance",
                "unused_allowance",
                rule_id,
                "finding required",
                "rule_id",
                [],
                None,
            )
        )
    status = "pass" if all(item["status"] == "allowed" for item in findings) else "fail"
    unknowns: dict[str, object] = {
        "cpl_rotation_basis_fab_lcsc": (
            "unknown: KiCad rotation was emitted without independent fab/LCSC "
            "component-orientation preview comparison"
        )
    }
    if cpl_unknowns is not None:
        for key, refs in cpl_unknowns.items():
            unknowns[key] = {
                "status": "unknown",
                "designators": list(refs),
                "reason": "実装基準はfab側プレビューでの目視確認が必要",
            }
    report = {
        "schema_version": "0.1",
        "target_revision": revision,
        "profile_id": profile.profile_id,
        "status": status,
        "findings": findings,
        "checks_not_implemented": checks,
        "measurements": {
            "via_count": len(measurement.vias),
            "vias": [
                {
                    "x_mm": via.x_mm,
                    "y_mm": via.y_mm,
                    "outer_diameter_mm": via.diameter_mm,
                    "hole_diameter_mm": via.hole_mm,
                    "layers": list(via.layers),
                }
                for via in measurement.vias
            ],
            "pad_count": len(measurement.pads),
            "min_track_width_mm": measurement.min_track_width_mm,
            "silk_min_height_mm": measurement.silk_min_height_mm,
            "silk_min_width_mm": measurement.silk_min_width_mm,
            "outline_bbox_mm": measurement.outline_bbox_mm,
            "drill_tool_diameters_mm": measurement.drill_tool_diameters_mm,
            "drill_object_count": measurement.drill_object_count,
        },
        "unknowns": unknowns,
    }
    if silkscreen_evidence is not None:
        report["silkscreen"] = dict(silkscreen_evidence)
    return cast(dict[str, object], report)


def parse_pos_csv(path: Path) -> tuple[dict[str, str], ...]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = tuple(csv.DictReader(stream))
    required = {"Ref", "PosX", "PosY", "Rot", "Side"}
    if not rows or not required <= set(rows[0]):
        raise FabOutputError(f"{path.name}: KiCad position CSV missing required columns")
    return rows


def jlcpcb_cpl_csv(rows: Iterable[dict[str, str]], fitted: set[str]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("Designator", "Mid X", "Mid Y", "Rotation", "Layer"))
    seen: set[str] = set()
    for row in sorted(rows, key=lambda item: item["Ref"]):
        ref = row["Ref"]
        if ref not in fitted:
            continue
        seen.add(ref)
        side = row["Side"].strip().lower()
        if side not in {"top", "bottom"}:
            raise FabOutputError(f"{ref}: unknown placement side {row['Side']!r}")
        writer.writerow((ref, row["PosX"], row["PosY"], row["Rot"], side.title()))
    if seen != fitted:
        raise FabOutputError(f"CPL fitted designator mismatch: missing={sorted(fitted - seen)}")
    return output.getvalue()


def _bbox_center(
    bbox: tuple[float, float, float, float] | None,
) -> tuple[float, float] | None:
    if bbox is None:
        return None
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _pad_bbox_center(fp: FootprintMeasurement) -> tuple[float, float] | None:
    if not fp.pads:
        return None
    xs = [pad.x_mm for pad in fp.pads]
    ys = [pad.y_mm for pad in fp.pads]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def _cpl_position(
    fp: FootprintMeasurement, basis: str
) -> tuple[float, float] | None:
    if basis == "footprint_origin":
        return (fp.x_mm, fp.y_mm)
    if basis == "body_bbox_center":
        return _bbox_center(fp.body_bbox_mm)
    if basis == "pad_bbox_center":
        return _pad_bbox_center(fp)
    raise FabOutputError(f"{fp.refdes}: unsupported CPL position basis {basis!r}")


def _geometry_centers(fp: FootprintMeasurement) -> dict[str, tuple[float, float] | None]:
    return {
        "footprint_origin": (fp.x_mm, fp.y_mm),
        "body_bbox_center": _bbox_center(fp.body_bbox_mm),
        "pad_bbox_center": _pad_bbox_center(fp),
    }


def _centers_disagree(
    centers: Mapping[str, tuple[float, float] | None], tolerance_mm: float
) -> bool:
    present = [center for center in centers.values() if center is not None]
    return any(
        math.dist(first, second) > tolerance_mm
        for index, first in enumerate(present)
        for second in present[index + 1 :]
    )


def apply_cpl_contract(
    position_rows: tuple[dict[str, str], ...],
    board: BoardMeasurement,
    lane: ElectricalLane,
    profile: FabProfile,
    fitted: set[str],
    tolerance_mm: float = 0.001,
) -> tuple[tuple[dict[str, str], ...], dict[str, object]]:
    """Resolve and independently validate the declared CPL basis."""
    contract = cast(dict[str, object], profile.data["cpl_contract"])
    default_position_basis = str(contract["position_basis"])
    default_rotation_basis = str(contract["rotation_basis"])
    components = {component.refdes: component for component in lane.components}
    footprints = {fp.refdes: fp for fp in board.footprints}
    unknown_position: list[str] = []
    unknown_rotation: list[str] = []
    errors: list[str] = []
    resolved: list[dict[str, str]] = []
    resolved_bases: dict[str, str] = {}
    rotation_offsets: dict[str, float] = {}

    for source in sorted(position_rows, key=lambda row: refdes_key(row["Ref"])):
        ref = source["Ref"]
        if ref not in fitted:
            continue
        component = components.get(ref)
        fp = footprints.get(ref)
        if component is None or fp is None:
            errors.append(f"{ref}: CPL basis source is absent from independent sources")
            continue
        centers = _geometry_centers(fp)
        position_basis = default_position_basis
        if _centers_disagree(centers, tolerance_mm):
            position_basis = component.cpl_position_basis or ""
            if not position_basis:
                unknown_position.append(ref)
                errors.append(
                    f"{ref}: CPL position basis is unknown; "
                    "component declaration and provenance are required"
                )
            elif (
                component.cpl_position_source_url is None
                or component.cpl_position_evidence_at is None
            ):
                unknown_position.append(ref)
                errors.append(
                    f"{ref}: CPL position basis {position_basis!r} has no source URL "
                    "and confirmation date"
                )
            elif component.cpl_position_evidence_basis not in {"estimated", "confirmed"}:
                errors.append(
                    f"{ref}: CPL position evidence basis must be 'estimated' or 'confirmed'"
                )
            elif component.cpl_position_evidence_basis == "confirmed" and (
                component.cpl_position_evidence_method is None
                or component.cpl_position_evidence_revision is None
                or component.cpl_position_evidence_note is None
            ):
                errors.append(
                    f"{ref}: confirmed CPL position evidence requires method, date, "
                    "revision, and note"
                )
            elif component.cpl_position_evidence_basis == "estimated":
                unknown_position.append(ref)
        if position_basis:
            resolved_bases[ref] = position_basis
            try:
                position = _cpl_position(fp, position_basis)
            except FabOutputError as exc:
                errors.append(str(exc))
                position = None
            if position is None:
                errors.append(f"{ref}: CPL position basis {position_basis!r} is unmeasurable")
            else:
                output = dict(source)
                output["PosX"] = f"{position[0]:.6f}"
                output["PosY"] = f"{-position[1]:.6f}"
                rotation = float(source["Rot"])
                if default_rotation_basis == "component_part_number":
                    if (
                        component.cpl_rotation_basis != "component_part_number"
                        or component.cpl_rotation_source_url is None
                        or component.cpl_rotation_offset_deg is None
                        or component.cpl_rotation_evidence_at is None
                        or component.cpl_rotation_evidence_basis != "confirmed"
                        or component.cpl_rotation_evidence_method is None
                        or component.cpl_rotation_evidence_revision is None
                        or component.cpl_rotation_evidence_note is None
                    ):
                        unknown_rotation.append(ref)
                        rotation_offsets[ref] = 0.0
                    else:
                        rotation += component.cpl_rotation_offset_deg
                        rotation_offsets[ref] = component.cpl_rotation_offset_deg
                elif default_rotation_basis != "kicad_footprint":
                    errors.append(
                        f"{ref}: unsupported CPL rotation basis {default_rotation_basis!r}"
                    )
                output["Rot"] = f"{rotation % 360.0:.6f}"
                resolved.append(output)

    report: dict[str, object] = {
        "schema_version": "0.1",
        "status": "fail" if errors or unknown_position or unknown_rotation else "pass",
        "position_basis": default_position_basis,
        "rotation_basis": default_rotation_basis,
        "unknowns": {
            "cpl_position_basis": sorted(set(unknown_position), key=refdes_key),
            "cpl_rotation_basis_fab_lcsc": sorted(set(unknown_rotation), key=refdes_key),
        },
        "position_bases": resolved_bases,
        "rotation_offsets": rotation_offsets,
        "errors": errors,
    }
    if errors:
        raise CplBasisError(
            "CPL basis gate failed: " + "; ".join(errors),
            report,
        )
    return tuple(resolved), report


def jlcpcb_bom_csv(lane: ElectricalLane) -> str:
    fitted = tuple(comp for comp in lane.components if comp.assembly == "fitted")
    if any(not comp.lcsc for comp in fitted):
        raise FabOutputError("fitted component without LCSC part number (fail-closed)")
    grouped: dict[tuple[str, str, str], list[ComponentView]] = {}
    for comp in fitted:
        key = (comp.lcsc, comp.mpn, comp.library.footprint)
        grouped.setdefault(key, []).append(comp)
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("Comment", "Designator", "Footprint", "LCSC Part #"))
    for (lcsc, mpn, footprint), components in sorted(
        grouped.items(),
        key=lambda item: min(refdes_key(c.refdes) for c in item[1]),
    ):
        values = {comp.value for comp in components}
        comment = next(iter(values)) if len(values) == 1 else mpn
        refs = sorted((comp.refdes for comp in components), key=refdes_key)
        writer.writerow((comment, ",".join(refs), footprint, lcsc))
    return output.getvalue()


def cross_validate_bom(
    bom_path: Path,
    lane: ElectricalLane,
    fitted: set[str],
) -> None:
    with bom_path.open(newline="", encoding="utf-8-sig") as stream:
        rows = tuple(csv.DictReader(stream))
    required = {"Comment", "Designator", "Footprint", "LCSC Part #"}
    if not rows or not required <= set(rows[0]):
        raise FabOutputError(f"{bom_path.name}: BOM missing required columns")
    components = {
        comp.refdes: comp for comp in lane.components if comp.assembly == "fitted"
    }
    seen: set[str] = set()
    for row in rows:
        refs = tuple(ref.strip() for ref in row["Designator"].split(",") if ref.strip())
        if not refs:
            raise FabOutputError(f"{bom_path.name}: BOM row has no designator")
        overlap = seen.intersection(refs)
        if overlap:
            raise FabOutputError(
                f"{bom_path.name}: duplicate designators {sorted(overlap, key=refdes_key)}"
            )
        seen.update(refs)
        lcsc = row["LCSC Part #"].strip()
        footprint = row["Footprint"].strip()
        if not lcsc:
            raise FabOutputError(f"{bom_path.name}: BOM row has empty LCSC part number")
        for ref in refs:
            comp = components.get(ref)
            if comp is None:
                raise FabOutputError(f"{bom_path.name}: unknown fitted designator {ref!r}")
            if comp.lcsc != lcsc:
                raise FabOutputError(f"{ref}: BOM LCSC differs from graph")
            if comp.library.footprint != footprint:
                raise FabOutputError(f"{ref}: BOM footprint differs from graph")
    if seen != fitted:
        raise FabOutputError(
            f"BOM fitted designator mismatch: missing={sorted(fitted - seen, key=refdes_key)}, "
            f"extra={sorted(seen - fitted, key=refdes_key)}"
        )


def cross_validate_cpl(
    cpl_path: Path,
    position_rows: tuple[dict[str, str], ...],
    board: BoardMeasurement,
    fitted: set[str],
    position_bases: Mapping[str, str] | None = None,
    rotation_offsets: Mapping[str, float] | None = None,
    tolerance_mm: float = 0.001,
    tolerance_deg: float = 0.01,
) -> None:
    with cpl_path.open(newline="", encoding="utf-8-sig") as stream:
        cpl_rows = tuple(csv.DictReader(stream))
    if {row["Designator"] for row in cpl_rows} != fitted:
        raise FabOutputError("CPL designator set differs from fitted graph components")
    source = {row["Ref"]: row for row in position_rows}
    footprints = {fp.refdes: fp for fp in board.footprints}
    for row in cpl_rows:
        ref = row["Designator"]
        if ref not in source or ref not in footprints:
            raise FabOutputError(f"CPL refdes {ref!r} is absent from independent sources")
        expected = source[ref]
        actual = footprints[ref]
        if abs(float(expected["PosX"]) - actual.x_mm) > tolerance_mm:
            raise FabOutputError(f"{ref}: position source X differs from routed board origin")
        if abs(-float(expected["PosY"]) - actual.y_mm) > tolerance_mm:
            raise FabOutputError(f"{ref}: position source Y differs from routed board origin")
        basis = (position_bases or {}).get(ref, "footprint_origin")
        selected = _cpl_position(actual, basis)
        if selected is None:
            raise FabOutputError(f"{ref}: selected CPL basis {basis!r} is unmeasurable")
        if abs(float(row["Mid X"]) - selected[0]) > tolerance_mm:
            raise FabOutputError(f"{ref}: CPL X differs from selected independent basis")
        if abs(-float(row["Mid Y"]) - selected[1]) > tolerance_mm:
            raise FabOutputError(f"{ref}: CPL Y differs from selected independent basis")
        expected_rotation = (
            actual.rotation_deg + (rotation_offsets or {}).get(ref, 0.0)
        ) % 360.0
        if abs(float(row["Rotation"]) - expected_rotation) > tolerance_deg:
            raise FabOutputError(f"{ref}: CPL rotation differs from declared basis")
        if row["Layer"].lower() != expected["Side"].lower():
            raise FabOutputError(f"{ref}: CPL layer differs from position CSV")


def deterministic_zip(output: Path, members: Iterable[Path], root: Path) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(members, key=lambda item: item.relative_to(root).as_posix()):
            info = zipfile.ZipInfo(
                path.relative_to(root).as_posix(), date_time=(1980, 1, 1, 0, 0, 0)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    with zipfile.ZipFile(output) as archive:
        for name in archive.namelist():
            if archive.read(name) != (root / name).read_bytes():
                raise FabOutputError(f"zip member verification failed: {name}")


def zip_content_hash(path: Path) -> str:
    entries: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            data = b"\n".join(
                line
                for line in archive.read(name).splitlines()
                if not line.lstrip().startswith((b"G04", b";"))
            ) + b"\n"
            entries.append(f"{name}:sha256:{hashlib.sha256(data).hexdigest()}")
    return "sha256:" + hashlib.sha256("\n".join(entries).encode()).hexdigest()
