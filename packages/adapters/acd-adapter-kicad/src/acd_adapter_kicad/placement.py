"""Placement geometry used by the board projection.

Only the geometry needed to project and check placements lives here: rectangle
arithmetic, pad transforms and the placement record itself. The placement search
that produces coordinates is not part of the ACD core; it is provided as the
``acd-placement-search`` skill under ``plugins/acd/skills/``.
"""

from __future__ import annotations

from dataclasses import dataclass

from acd_core.board_model import FootprintShape

MARGIN_MM = 0.0


class PlacementError(ValueError):
    """Raised when a placement is geometrically invalid or unsupported."""


@dataclass(frozen=True)
class Rect:
    x1: float
    y1: float
    x2: float
    y2: float

    def overlaps(self, other: Rect) -> bool:
        return not (
            self.x2 <= other.x1
            or other.x2 <= self.x1
            or self.y2 <= other.y1
            or other.y2 <= self.y1
        )


@dataclass(frozen=True)
class Placement:
    refdes: str
    x_mm: float
    y_mm: float
    rotation_deg: float


def pad_bbox(footprint: FootprintShape, margin: float) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for pad in footprint.pads:
        rot = pad.rotation_deg % 180.0
        if rot == 90.0:
            half_x = pad.size_y_mm / 2.0
            half_y = pad.size_x_mm / 2.0
        else:
            half = max(pad.size_x_mm, pad.size_y_mm) / 2.0 if rot else 0.0
            half_x = pad.size_x_mm / 2.0 if rot == 0.0 else half
            half_y = pad.size_y_mm / 2.0 if rot == 0.0 else half
        xs.extend((pad.x_mm - half_x, pad.x_mm + half_x))
        ys.extend((pad.y_mm - half_y, pad.y_mm + half_y))
    if footprint.courtyard_bbox_mm is not None:
        cx1, cy1, cx2, cy2 = footprint.courtyard_bbox_mm
        xs.extend((cx1, cx2))
        ys.extend((cy1, cy2))
    if not xs:
        xs = [-1.0, 1.0]
        ys = [-1.0, 1.0]
    return min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin


def placed_rect(footprint: FootprintShape, x: float, y: float, rotation: float) -> Rect:
    x1, y1, x2, y2 = pad_bbox(footprint, MARGIN_MM)
    rot = rotation % 360
    if rot == 90.0:
        x1, y1, x2, y2 = y1, -x2, y2, -x1
    elif rot == 180.0:
        x1, y1, x2, y2 = -x2, -y2, -x1, -y1
    elif rot == 270.0:
        x1, y1, x2, y2 = -y2, x1, -y1, x2
    elif rot != 0.0:
        raise PlacementError(f"unsupported rotation {rotation} (fail-closed)")
    return Rect(x + x1, y + y1, x + x2, y + y2)


def pad_position(
    footprint: FootprintShape,
    placement: tuple[float, float],
    rotation: float,
    pad_number: str,
) -> tuple[float, float]:
    pads = [pad for pad in footprint.pads if pad.number == pad_number]
    if len(pads) != 1:
        raise PlacementError(f"pad target is not unique: {footprint.library_ref}-{pad_number}")
    pad = pads[0]
    x, y = rotate_point(pad.x_mm, pad.y_mm, rotation)
    return placement[0] + x, placement[1] + y


def rotate_point(x: float, y: float, rotation: float) -> tuple[float, float]:
    rot = rotation % 360.0
    if rot == 0.0:
        return x, y
    if rot == 90.0:
        return y, -x
    if rot == 180.0:
        return -x, -y
    if rot == 270.0:
        return -y, x
    raise PlacementError(f"unsupported rotation {rotation} (fail-closed)")
