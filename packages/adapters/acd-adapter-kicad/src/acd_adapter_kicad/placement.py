"""Deterministic component placement.

Fixed anchors (RF module at the top edge with the antenna overhanging, USB
connector at the bottom edge, mounting holes in the corners) plus a greedy
first-fit grid scan for the remaining components. The scan order is fully
deterministic: components sorted by refdes, candidate positions row-major on a
0.5 mm grid. Placement fails closed if any component cannot be placed.
"""

from __future__ import annotations

from dataclasses import dataclass

from acd_core.board_model import FootprintShape
from acd_core.electrical import BoardView, ComponentView


class PlacementError(ValueError):
    """Raised when deterministic placement cannot fit all components."""


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


_MARGIN_MM = 0.0
_GRID_MM = 0.25
# Preferred spacing between neighbouring components leaves a routing channel
# (track width + clearance on both sides); tighter fallbacks keep dense boards
# placeable while still fully deterministic.
_SPACING_STEPS_MM = (0.45, 0.15, 0.0)
_COMPACTNESS_WEIGHT = 0.05

# Anchored placements for the golden design profile: the antenna module hangs
# over the top edge, the USB receptacle sits on the bottom edge.
ANTENNA_MODULE_Y_MM = 6.4
USB_CONNECTOR_Y_MM = 22.0
MOUNTING_HOLE_INSET_MM = 3.0


def _pad_bbox(footprint: FootprintShape, margin: float) -> tuple[float, float, float, float]:
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


def _placed_rect(footprint: FootprintShape, x: float, y: float, rotation: float) -> Rect:
    x1, y1, x2, y2 = _pad_bbox(footprint, _MARGIN_MM)
    rot = rotation % 360
    if rot == 90.0:
        x1, y1, x2, y2 = -y2, x1, -y1, x2
    elif rot == 180.0:
        x1, y1, x2, y2 = -x2, -y2, -x1, -y1
    elif rot == 270.0:
        x1, y1, x2, y2 = y1, -x2, y2, -x1
    elif rot != 0.0:
        raise PlacementError(f"unsupported rotation {rotation} (fail-closed)")
    return Rect(x + x1, y + y1, x + x2, y + y2)


def _classify(comp: ComponentView) -> str:
    library_ref = comp.library.footprint
    if library_ref.startswith("Espressif:"):
        return "rf_module"
    if "USB_C_Receptacle" in library_ref:
        return "usb_connector"
    if library_ref.startswith("MountingHole:"):
        return "mounting_hole"
    return "generic"


def compute_placements(
    board: BoardView,
    components: tuple[ComponentView, ...],
    footprints: dict[str, FootprintShape],
    keepouts: tuple[Rect, ...],
    net_refdes: tuple[tuple[str, ...], ...] = (),
) -> tuple[Placement, ...]:
    placements: list[Placement] = []
    occupied: list[Rect] = list(keepouts)
    center_x = board.width_mm / 2.0

    ordered = sorted(components, key=lambda c: c.refdes)
    holes = [c for c in ordered if _classify(c) == "mounting_hole"]
    hole_positions = [
        (MOUNTING_HOLE_INSET_MM, MOUNTING_HOLE_INSET_MM),
        (board.width_mm - MOUNTING_HOLE_INSET_MM, MOUNTING_HOLE_INSET_MM),
        (MOUNTING_HOLE_INSET_MM, board.height_mm - MOUNTING_HOLE_INSET_MM),
        (board.width_mm - MOUNTING_HOLE_INSET_MM, board.height_mm - MOUNTING_HOLE_INSET_MM),
    ]
    if len(holes) > len(hole_positions):
        raise PlacementError(f"too many mounting holes: {len(holes)}")

    for comp in ordered:
        kind = _classify(comp)
        footprint = footprints[comp.refdes]
        if kind == "rf_module":
            x, y, rot = center_x, ANTENNA_MODULE_Y_MM, 0.0
        elif kind == "usb_connector":
            x, y, rot = center_x, USB_CONNECTOR_Y_MM, 0.0
        elif kind == "mounting_hole":
            x, y = hole_positions[holes.index(comp)]
            rot = 0.0
        else:
            continue
        placements.append(Placement(comp.refdes, x, y, rot))
        occupied.append(_placed_rect(footprint, x, y, rot))

    def bbox_area(comp: ComponentView) -> float:
        x1, y1, x2, y2 = _pad_bbox(footprints[comp.refdes], _MARGIN_MM)
        return (x2 - x1) * (y2 - y1)

    # High-fanout nets (ground/power planes) would pull everything to one
    # centroid, so only small signal nets contribute placement attraction.
    neighbours: dict[str, set[str]] = {}
    for refs in net_refdes:
        if len(set(refs)) > 4:
            continue
        for ref in refs:
            neighbours.setdefault(ref, set()).update(r for r in refs if r != ref)

    generic = [c for c in ordered if _classify(c) == "generic"]
    generic.sort(key=lambda c: (-bbox_area(c), c.refdes))
    placed_at: dict[str, tuple[float, float]] = {p.refdes: (p.x_mm, p.y_mm) for p in placements}
    for comp in generic:
        footprint = footprints[comp.refdes]
        anchors = tuple(
            placed_at[ref] for ref in sorted(neighbours.get(comp.refdes, ())) if ref in placed_at
        )
        spot = None
        for spacing in _SPACING_STEPS_MM:
            spot = _best_fit(board, footprint, occupied, spacing, anchors)
            if spot is not None:
                break
        if spot is None:
            raise PlacementError(f"no placement found for {comp.refdes} (fail-closed)")
        x, y, rot = spot
        placements.append(Placement(comp.refdes, x, y, rot))
        occupied.append(_placed_rect(footprint, x, y, rot))
        placed_at[comp.refdes] = (x, y)

    return tuple(sorted(placements, key=lambda p: p.refdes))


def _best_fit(
    board: BoardView,
    footprint: FootprintShape,
    occupied: list[Rect],
    spacing: float,
    anchors: tuple[tuple[float, float], ...],
) -> tuple[float, float, float] | None:
    """Deterministic candidate scan; among all fitting spots pick the one that
    minimises the summed distance to connected, already-placed components so
    nets stay short and routable. Ties resolve row-major with rotation 0 first."""
    edge = board.edge_copper_clearance_mm
    bx1, by1, bx2, by2 = _pad_bbox(footprint, _MARGIN_MM)
    best: tuple[float, float, float, float] | None = None
    for rot_index, rotation in enumerate((0.0, 90.0)):
        if rotation == 90.0:
            x1, y1, x2, y2 = -by2, bx1, -by1, bx2
        else:
            x1, y1, x2, y2 = bx1, by1, bx2, by2
        y = edge - y1
        while y + y2 <= board.height_mm - edge:
            x = edge - x1
            while x + x2 <= board.width_mm - edge:
                candidate = Rect(
                    x + x1 - spacing, y + y1 - spacing, x + x2 + spacing, y + y2 + spacing
                )
                if not any(candidate.overlaps(rect) for rect in occupied):
                    cost = sum(abs(x - ax) + abs(y - ay) for ax, ay in anchors)
                    # Small centre bias fights fragmentation and keeps parts
                    # away from corners where mounting holes block escapes.
                    cost += _COMPACTNESS_WEIGHT * (
                        abs(x - board.width_mm / 2.0) + abs(y - board.height_mm / 2.0)
                    )
                    key = (cost, y, x, float(rot_index))
                    if best is None or key < (best[0], best[2], best[1], best[3]):
                        best = (cost, x, y, float(rot_index))
                x += _GRID_MM
            y += _GRID_MM
    if best is None:
        return None
    return round(best[1], 4), round(best[2], 4), (0.0, 90.0)[int(best[3])]
