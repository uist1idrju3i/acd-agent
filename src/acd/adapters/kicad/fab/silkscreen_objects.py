"""Silkscreen Gerber objects and the geometry primitives measured against them."""
# pyright: reportUnknownVariableType=false,reportUnknownMemberType=false

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from gerbonara.apertures import (  # pyright: ignore[reportMissingTypeStubs]
    CircleAperture,
    ObroundAperture,
    RectangleAperture,
)
from gerbonara.graphic_objects import (  # pyright: ignore[reportMissingTypeStubs]
    Arc,
    Flash,
    Line,
    Region,
)
from gerbonara.rs274x import GerberFile  # pyright: ignore[reportMissingTypeStubs]

from acd.core.silkscreen import SilkTextView

from .common import FabOutputError
from .geometry import _bbox_overlap_area, _gerber_to_board_point


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


class SilkscreenGateError(FabOutputError):
    """Raised when silkscreen geometry fails, with measured context."""

    def __init__(self, message: str, context: dict[str, object]) -> None:
        super().__init__(message)
        self.context = context

    def __reduce__(self) -> tuple[type[SilkscreenGateError], tuple[str, dict[str, object]]]:
        return (type(self), (str(self), self.context))


def _silk_side(layer: str) -> str:
    return "F.Cu" if layer.startswith("F.") else "B.Cu"


def _mask_layer_for_silk(layer: str) -> str:
    if layer == "F.SilkS":
        return "F.Mask"
    if layer == "B.SilkS":
        return "B.Mask"
    raise ValueError(f"unsupported silkscreen layer {layer!r}")


def _same_side(silk_layer: str, copper_layers: tuple[str, ...]) -> bool:
    return _silk_side(silk_layer) in copper_layers


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


# KiCad stroke-font measurements showed an uppercase advance of about 0.868
# times the declared height; 0.95 is an attribution upper bound with margin.
SILK_TEXT_ADVANCE_RATIO = 0.95
SILK_TEXT_ATTRIBUTION_MARGIN_STROKE_WIDTHS = 1.0
SILK_TEXT_DESCENDER_CHARS = frozenset("gjpqy")
# KiCad stroke-font measurements showed 1.483 mm of orthogonal ink at height
# 1.0 mm (1.333 times height without stroke); 1.45 is an upper bound for
# descenders in g/j/p/q/y with about 8% margin.
SILK_TEXT_DESCENDER_HEIGHT_RATIO = 1.45


def _text_model_size(
    text: str,
    height_mm: float,
    stroke_width_mm: float,
    rotation_deg: float = 0.0,
) -> tuple[float, float]:
    advance_width = max(height_mm * SILK_TEXT_ADVANCE_RATIO * len(text), height_mm)
    glyph_height = height_mm * (
        SILK_TEXT_DESCENDER_HEIGHT_RATIO if SILK_TEXT_DESCENDER_CHARS.intersection(text) else 1.0
    )
    margin = stroke_width_mm * SILK_TEXT_ATTRIBUTION_MARGIN_STROKE_WIDTHS
    width = advance_width + 2.0 * margin
    height = glyph_height + margin
    if int(rotation_deg) % 180:
        width, height = height, width
    return width, height


def _declared_bbox(
    x_mm: float,
    y_mm: float,
    text: str,
    height_mm: float,
    stroke_width_mm: float,
    rotation_deg: float = 0.0,
) -> tuple[float, float, float, float]:
    estimated_width, estimated_height = _text_model_size(
        text, height_mm, stroke_width_mm, rotation_deg
    )
    return (
        x_mm - estimated_width / 2.0,
        y_mm - estimated_height / 2.0,
        x_mm + estimated_width / 2.0,
        y_mm + estimated_height / 2.0,
    )


def _text_attribution_overflow(
    text: SilkTextView,
    measured_length_mm: float,
    measured_height_mm: float,
) -> tuple[dict[str, object], ...]:
    estimated_width, estimated_height = _text_model_size(
        text.text, text.height_mm, text.stroke_width_mm
    )
    overflows: list[dict[str, object]] = []
    if measured_length_mm > estimated_width + text.stroke_width_mm:
        overflows.append(
            {
                "dimension": "length",
                "measured_mm": measured_length_mm,
                "upper_bound_mm": estimated_width,
                "tolerance_mm": text.stroke_width_mm,
            }
        )
    if measured_height_mm > estimated_height + text.stroke_width_mm:
        overflows.append(
            {
                "dimension": "height",
                "measured_mm": measured_height_mm,
                "upper_bound_mm": estimated_height,
                "tolerance_mm": text.stroke_width_mm,
            }
        )
    return tuple(overflows)


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


__all__ = [
    "SILK_TEXT_ADVANCE_RATIO",
    "SILK_TEXT_ATTRIBUTION_MARGIN_STROKE_WIDTHS",
    "SILK_TEXT_DESCENDER_CHARS",
    "SILK_TEXT_DESCENDER_HEIGHT_RATIO",
    "SilkscreenGateError",
    "_SilkObject",
    "_declared_bbox",
    "_gerber_silk_objects",
    "_local_silk_bounds",
    "_mask_layer_for_silk",
    "_point_rect_distance",
    "_same_side",
    "_segment_distance_to_rect",
    "_silk_aperture_width",
    "_silk_object",
    "_silk_objects_overlap",
    "_silk_overlaps_rect",
    "_silk_rect_distance",
    "_silk_side",
    "_text_attribution_overflow",
    "_text_model_size",
    "_union_bbox",
]
