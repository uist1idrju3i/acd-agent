"""Shared fabrication geometry helpers."""
# ruff: noqa

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import cast

from .sexpr_query import *  # noqa: F401,F403


def _bbox_overlap_area(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    width = min(first[2], second[2]) - max(first[0], second[0])
    height = min(first[3], second[3]) - max(first[1], second[1])
    return max(0.0, width) * max(0.0, height)


def _point_in_polygon(x: float, y: float, polygon: Sequence[tuple[float, float]]) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, (*polygon[1:], polygon[0]), strict=True):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


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


def rotate(x: float, y: float, angle: float) -> tuple[float, float]:
    radians = math.radians(angle)
    return (
        x * math.cos(radians) + y * math.sin(radians),
        -x * math.sin(radians) + y * math.cos(radians),
    )


def _gerber_to_board_point(x_mm: float, y_mm: float) -> tuple[float, float]:
    """Convert Gerber's Y-up coordinates to the board's Y-down frame."""
    return x_mm, -y_mm


def _inverse_rotate(x: float, y: float, angle: float) -> tuple[float, float]:
    return rotate(x, y, -angle)


__all__ = [
    "_bbox_overlap_area",
    "_footprint_bbox",
    "_gerber_to_board_point",
    "_inverse_rotate",
    "_point_in_polygon",
    "rotate",
]
