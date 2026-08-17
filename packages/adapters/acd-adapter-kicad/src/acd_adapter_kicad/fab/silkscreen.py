"""Independent manufacturing measurements, DFM checks, and JLCPCB exports."""
# pyright: reportUnusedImport=false
# ruff: noqa

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


from .common import *  # noqa: F401,F403
from .geometry import *  # noqa: F401,F403
from .sexpr_query import *  # noqa: F401,F403


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
    points_mm: tuple[tuple[float, float], ...] = ()


def _silk_aperture_width(aperture: Any) -> float:
    raw = aperture
    if isinstance(aperture, CircleAperture):
        return float(raw.diameter)
    if isinstance(aperture, RectangleAperture):
        return max(float(raw.w), float(raw.h))
    if isinstance(aperture, ObroundAperture):
        return max(float(raw.w), float(raw.h))
    raise FabOutputError(f"unsupported silkscreen aperture {type(aperture).__name__} (fail-closed)")


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
                points[index][0] * points[index + 1][1] - points[index + 1][0] * points[index][1]
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
            points_mm=tuple(points),
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
    raise FabOutputError(f"unsupported silkscreen object {type(obj).__name__} (fail-closed)")


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


def _local_silk_bounds(
    objects: Sequence[_SilkObject],
    anchor_mm: tuple[float, float],
    rotation_deg: float,
) -> tuple[float, float, float, float]:
    """Measure silk geometry in the declared text coordinate system."""
    angle = math.radians(rotation_deg)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    local_points: list[tuple[float, float]] = []
    for item in objects:
        if item.kind == "Line" and item.start_mm is not None and item.end_mm is not None:
            x1, y1 = item.start_mm
            x2, y2 = item.end_mm
            dx = x2 - x1
            dy = y2 - y1
            length = math.hypot(dx, dy)
            half_width = (item.stroke_width_mm or 0.0) / 2.0
            if length > 0:
                normal = (-dy / length * half_width, dx / length * half_width)
            else:
                normal = (half_width, 0.0)
            points = (
                (x1 + normal[0], y1 + normal[1]),
                (x1 - normal[0], y1 - normal[1]),
                (x2 + normal[0], y2 + normal[1]),
                (x2 - normal[0], y2 - normal[1]),
            )
        elif item.points_mm:
            points = item.points_mm
        elif item.kind == "Flash" and item.center_mm is not None and item.radius_mm is not None:
            x, y = item.center_mm
            radius = item.radius_mm
            points = (
                (x - radius, y - radius),
                (x - radius, y + radius),
                (x + radius, y - radius),
                (x + radius, y + radius),
            )
        else:
            points = (
                (item.bbox_mm[0], item.bbox_mm[1]),
                (item.bbox_mm[0], item.bbox_mm[3]),
                (item.bbox_mm[2], item.bbox_mm[1]),
                (item.bbox_mm[2], item.bbox_mm[3]),
            )
        for x, y in points:
            dx = x - anchor_mm[0]
            dy = y - anchor_mm[1]
            local_points.append((cosine * dx + sine * dy, -sine * dx + cosine * dy))
    if not local_points:
        raise FabOutputError("silkscreen declaration has no measurable geometry (fail-closed)")
    xs, ys = zip(*local_points, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


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
        return (
            _segment_distance_to_rect(item.start_mm, item.end_mm, rect)
            <= (item.stroke_width_mm or 0.0) / 2.0
        )
    return _bbox_overlap_area(item.bbox_mm, rect) > 1e-6


def _silk_rect_distance(item: _SilkObject, rect: tuple[float, float, float, float]) -> float:
    if _silk_overlaps_rect(item, rect):
        return 0.0
    return math.hypot(
        max(rect[0] - item.bbox_mm[2], 0.0, item.bbox_mm[0] - rect[2]),
        max(rect[1] - item.bbox_mm[3], 0.0, item.bbox_mm[1] - rect[3]),
    )


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
        return (
            _segment_distance_to_rect(
                first.start_mm,
                first.end_mm,
                (
                    second.center_mm[0] - second.radius_mm,
                    second.center_mm[1] - second.radius_mm,
                    second.center_mm[0] + second.radius_mm,
                    second.center_mm[1] + second.radius_mm,
                ),
            )
            <= stroke_width / 2
        )
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
    declared_groups: list[tuple[dict[str, object], tuple[_SilkObject, ...]]] = []
    for text in declarations.texts:
        target = _declared_bbox(text.x_mm, text.y_mm, text.text, text.height_mm, text.rotation_deg)
        target_half_width = (target[2] - target[0]) / 2.0
        target_half_height = (target[3] - target[1]) / 2.0
        nearby = [
            item
            for item in all_silk
            if item.layer == text.layer
            and (
                item.stroke_width_mm is None or item.stroke_width_mm + 1e-6 >= text.stroke_width_mm
            )
            and _bbox_overlap_area(item.bbox_mm, target) > 0
            and abs((item.bbox_mm[0] + item.bbox_mm[2]) / 2.0 - text.x_mm) <= target_half_width
            and abs((item.bbox_mm[1] + item.bbox_mm[3]) / 2.0 - text.y_mm) <= target_half_height
        ]
        bbox = _union_bbox(nearby)
        declared_objects.extend(nearby)
        measured_widths = [
            item.stroke_width_mm for item in nearby if item.stroke_width_mm is not None
        ]
        measured_width = min(measured_widths) if measured_widths else None
        area = sum(item.area_mm2 for item in nearby)
        local_bbox = _local_silk_bounds(nearby, (text.x_mm, text.y_mm), text.rotation_deg)
        height = local_bbox[3] - local_bbox[1]
        text_length = local_bbox[2] - local_bbox[0]
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
        entry: dict[str, object] = {
            "node_id": text.node_id,
            "role": text.role,
            "text": text.text,
            "layer": text.layer,
            "declared_position_mm": [text.x_mm, text.y_mm],
            "declared_height_mm": text.height_mm,
            "declared_stroke_width_mm": text.stroke_width_mm,
            "declared_rotation_deg": text.rotation_deg,
            "measured_bbox_mm": list(bbox),
            "measured_ink_area_mm2": area,
            "measured_height_mm": height,
            "measured_text_length_mm": text_length,
            "measured_minimum_stroke_width_mm": measured_width,
            "measurement_coordinate_system": (
                "text-local coordinates after inverse declared rotation"
            ),
            "placement_basis": text.placement_basis,
            "placement_search_order": text.placement_search_order,
            "placement_reference": text.placement_reference,
            "placement_offset_step_mm": text.placement_offset_step_mm,
            "placement_search_limit_mm": text.placement_search_limit_mm,
            "board_edge_margin_mm": text.board_edge_margin_mm,
        }
        declared.append(entry)
        declared_groups.append((entry, tuple(nearby)))
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
            and abs((item.bbox_mm[0] + item.bbox_mm[2]) / 2.0 - (min(xs) + max(xs)) / 2.0)
            <= target_half_width
            and abs((item.bbox_mm[1] + item.bbox_mm[3]) / 2.0 - (min(ys) + max(ys)) / 2.0)
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
        entry: dict[str, object] = {
            "node_id": graphic.node_id,
            "role": graphic.role,
            "layer": graphic.layer,
            "declared_polygon_points": [list(point) for point in graphic.polygon_points],
            "measured_bbox_mm": list(bbox),
            "measured_ink_area_mm2": area,
            "measured_minimum_stroke_width_mm": measured_width,
            "placement_basis": graphic.placement_basis,
            "placement_search_order": graphic.placement_search_order,
            "board_edge_margin_mm": graphic.board_edge_margin_mm,
        }
        declared.append(entry)
        declared_groups.append((entry, tuple(nearby)))
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
    body_rects = [
        (fp.refdes, fp.body_bbox_mm) for fp in measurement.footprints if fp.body_bbox_mm is not None
    ]
    courtyard_rects = [
        (fp.refdes, fp.courtyard_bbox_mm)
        for fp in measurement.footprints
        if fp.courtyard_bbox_mm is not None
    ]
    declared_ids = {id(item) for item in declared_objects}
    non_declared_silk = [item for item in all_silk if id(item) not in declared_ids]
    body_overlaps: list[dict[str, object]] = []
    courtyard_overlaps: list[dict[str, object]] = []
    existing_silk_overlaps: list[dict[str, object]] = []
    edge_margin_violations: list[dict[str, object]] = []
    nearest_component_mismatches: list[dict[str, object]] = []
    for entry, objects in declared_groups:
        node_id = str(entry["node_id"])
        body_hits: list[dict[str, object]] = [
            {
                "node_id": node_id,
                "refdes": refdes,
                "silk_bbox_mm": list(item.bbox_mm),
                "body_bbox_mm": list(rect),
                "overlap_area_mm2": _bbox_overlap_area(item.bbox_mm, rect),
            }
            for item in objects
            for refdes, rect in body_rects
            if _silk_overlaps_rect(item, rect)
        ]
        courtyard_hits: list[dict[str, object]] = [
            {
                "node_id": node_id,
                "refdes": refdes,
                "silk_bbox_mm": list(item.bbox_mm),
                "courtyard_bbox_mm": list(rect),
                "overlap_area_mm2": _bbox_overlap_area(item.bbox_mm, rect),
            }
            for item in objects
            for refdes, rect in courtyard_rects
            if _silk_overlaps_rect(item, rect)
        ]
        other_hits: list[dict[str, object]] = [
            {
                "node_id": node_id,
                "silk_bbox_mm": list(item.bbox_mm),
                "existing_silk_bbox_mm": list(other.bbox_mm),
                "layer": item.layer,
                "existing_silk_kind": other.kind,
                "overlap_area_mm2": _bbox_overlap_area(item.bbox_mm, other.bbox_mm),
            }
            for item in objects
            for other in non_declared_silk
            if item.layer == other.layer and _silk_objects_overlap(item, other)
        ]
        body_overlaps.extend(body_hits)
        courtyard_overlaps.extend(courtyard_hits)
        existing_silk_overlaps.extend(other_hits)
        entry["body_overlap_count"] = len(body_hits)
        entry["courtyard_overlap_count"] = len(courtyard_hits)
        entry["existing_footprint_silk_overlap_count"] = len(other_hits)
        body_distances = [
            (_silk_rect_distance(item, rect), refdes)
            for item in objects
            for refdes, rect in body_rects
        ]
        courtyard_distances = [
            (_silk_rect_distance(item, rect), refdes)
            for item in objects
            for refdes, rect in courtyard_rects
        ]
        entry["nearest_body_distance_mm"] = min(body_distances)[0] if body_distances else None
        entry["nearest_body_refdes"] = min(body_distances)[1] if body_distances else None
        entry["nearest_courtyard_distance_mm"] = (
            min(courtyard_distances)[0] if courtyard_distances else None
        )
        entry["nearest_courtyard_refdes"] = (
            min(courtyard_distances)[1] if courtyard_distances else None
        )
        edge_distances = [
            min(
                item.bbox_mm[0] - outline[0],
                outline[2] - item.bbox_mm[2],
                item.bbox_mm[1] - outline[1],
                outline[3] - item.bbox_mm[3],
            )
            for item in objects
        ]
        entry["board_edge_minimum_distance_mm"] = min(edge_distances) if edge_distances else None
        margin = float(cast(float, entry["board_edge_margin_mm"]))
        for item in objects:
            distance = min(
                item.bbox_mm[0] - outline[0],
                outline[2] - item.bbox_mm[2],
                item.bbox_mm[1] - outline[1],
                outline[3] - item.bbox_mm[3],
            )
            if distance < margin:
                edge_margin_violations.append(
                    {
                        "node_id": node_id,
                        "silk_bbox_mm": list(item.bbox_mm),
                        "minimum_distance_mm": distance,
                        "declared_margin_mm": margin,
                    }
                )
        reference_value = entry.get("placement_reference")
        reference = str(reference_value) if isinstance(reference_value, str) else None
        component_distances: list[tuple[float, str]] = []
        for refdes in sorted({ref for ref, _ in body_rects + courtyard_rects}):
            distances = [
                _silk_rect_distance(item, rect)
                for item in objects
                for candidate_ref, rect in body_rects + courtyard_rects
                if candidate_ref == refdes
            ]
            if distances:
                component_distances.append((min(distances), refdes))
        if component_distances:
            nearest_distance, nearest_refdes = min(component_distances)
            entry["nearest_component_distance_mm"] = nearest_distance
            entry["nearest_component_refdes"] = nearest_refdes
            if reference is not None:
                reference_distance = next(
                    (distance for distance, refdes in component_distances if refdes == reference),
                    None,
                )
                entry["reference_component_distance_mm"] = reference_distance
                entry["reference_is_nearest_component"] = (
                    reference_distance is not None
                    and reference_distance <= nearest_distance + 1e-9
                    and nearest_refdes == reference
                )
                if not entry["reference_is_nearest_component"]:
                    nearest_component_mismatches.append(
                        {
                            "node_id": node_id,
                            "reference": reference,
                            "reference_distance_mm": reference_distance,
                            "nearest_refdes": nearest_refdes,
                            "nearest_distance_mm": nearest_distance,
                        }
                    )
    if (
        pad_overlaps
        or mask_overlaps
        or outside
        or edge_margin_violations
        or body_overlaps
        or existing_silk_overlaps
        or nearest_component_mismatches
    ):
        raise FabOutputError(
            "silkscreen clearance or board-edge overlap detected (fail-closed): "
            f"pad={len(pad_overlaps)}, mask={len(mask_overlaps)}, edge={len(outside)}, "
            f"edge_margin={len(edge_margin_violations)}, "
            f"body={len(body_overlaps)}, courtyard={len(courtyard_overlaps)}, "
            f"existing_silk={len(existing_silk_overlaps)}, "
            f"nearest_component={len(nearest_component_mismatches)}; "
            f"pad_examples={pad_overlaps[:3]}, mask_examples={mask_overlaps[:3]}, "
            f"edge_examples={outside[:3]}, body_examples={body_overlaps[:3]}, "
            f"edge_margin_examples={edge_margin_violations[:3]}, "
            f"nearest_component_examples={nearest_component_mismatches[:3]}"
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
        "board_edge_margin_violation_count": len(edge_margin_violations),
        "body_overlap_count": len(body_overlaps),
        "courtyard_overlap_count": len(courtyard_overlaps),
        "existing_footprint_silk_overlap_count": len(existing_silk_overlaps),
        "nearest_component_mismatch_count": len(nearest_component_mismatches),
        "pad_to_silk_overlaps": pad_overlaps,
        "mask_to_silk_overlaps": mask_overlaps,
        "board_edge_overflows": outside,
        "board_edge_margin_violations": edge_margin_violations,
        "body_overlaps": body_overlaps,
        "courtyard_overlaps": courtyard_overlaps,
        "existing_footprint_silk_overlaps": existing_silk_overlaps,
        "nearest_component_mismatches": nearest_component_mismatches,
        "status": "measured_pass",
    }
