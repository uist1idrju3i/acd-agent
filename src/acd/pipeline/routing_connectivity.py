"""Deterministic routing connectivity observations.

This module reports route-to-pad connectivity only.  It is intentionally not
used by an authoritative gate: router convergence and KiCad DRC retain their
existing pass/fail authority.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations, pairwise

from acd.adapters.kicad.placement import rotate_point
from acd.core.board_model import BoardModel, BoardNet, ComponentPlacement, RoutedDesign

# FreeRouting and KiCad coordinates are decimal millimetres.  This tolerance
# absorbs serialization round-off while remaining far below pad clearances.
COORDINATE_TOLERANCE_MM = 1e-6
COORDINATE_DECIMAL_PLACES = 6


@dataclass
class _UnionFind:
    parents: list[int]

    @classmethod
    def create(cls, count: int) -> _UnionFind:
        return cls(list(range(count)))

    def find(self, item: int) -> int:
        parent = self.parents[item]
        if parent != item:
            self.parents[item] = self.find(parent)
        return self.parents[item]

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parents[max(left_root, right_root)] = min(left_root, right_root)


def _near(left: tuple[float, float], right: tuple[float, float]) -> bool:
    return math.dist(left, right) <= COORDINATE_TOLERANCE_MM


def _placement_map(board: BoardModel) -> dict[str, ComponentPlacement]:
    result = {placement.refdes: placement for placement in board.placements}
    if len(result) != len(board.placements):
        raise ValueError("board placements contain duplicate refdes")
    return result


def _pad_bbox(
    placement: ComponentPlacement,
    pad_number: str,
) -> tuple[tuple[float, float], tuple[float, float]]:
    pads = [pad for pad in placement.footprint.pads if pad.number == pad_number]
    if len(pads) != 1:
        raise ValueError(f"{placement.refdes}: pad {pad_number} is not unique")
    pad = pads[0]
    center_offset = rotate_point(pad.x_mm, pad.y_mm, placement.rotation_deg)
    center = (placement.x_mm + center_offset[0], placement.y_mm + center_offset[1])
    angle = math.radians(pad.rotation_deg + placement.rotation_deg)
    cosine = abs(math.cos(angle))
    sine = abs(math.sin(angle))
    half_x = (cosine * pad.size_x_mm + sine * pad.size_y_mm) / 2.0
    half_y = (sine * pad.size_x_mm + cosine * pad.size_y_mm) / 2.0
    return center, (half_x, half_y)


def _pad_entries(
    board: BoardModel,
    net: BoardNet,
) -> tuple[tuple[tuple[str, str], tuple[float, float], tuple[float, float]], ...]:
    placements = _placement_map(board)
    entries: list[tuple[tuple[str, str], tuple[float, float], tuple[float, float]]] = []
    for refdes, pad_number in sorted(net.pads):
        placement = placements.get(refdes)
        if placement is None:
            raise ValueError(f"{refdes}: placement is missing")
        center, half_size = _pad_bbox(placement, pad_number)
        entries.append(((refdes, pad_number), center, half_size))
    return tuple(entries)


def _connectivity_for_net(
    board: BoardModel,
    routes: RoutedDesign,
    net: BoardNet,
) -> dict[str, object]:
    wires = tuple(
        sorted(
            (wire for wire in routes.wires if wire.net == net.name),
            key=lambda wire: (wire.layer, wire.width_mm, wire.points),
        )
    )
    vias = tuple(
        sorted(
            (via for via in routes.vias if via.net == net.name),
            key=lambda via: (via.x_mm, via.y_mm),
        )
    )
    points: list[tuple[float, float]] = []
    wire_indexes: list[tuple[int, ...]] = []
    for wire in wires:
        indexes = tuple(range(len(points), len(points) + len(wire.points)))
        points.extend(wire.points)
        wire_indexes.append(indexes)
    via_indexes: list[int] = []
    for via in vias:
        via_indexes.append(len(points))
        points.append((via.x_mm, via.y_mm))
    union_find = _UnionFind.create(len(points))
    for indexes in wire_indexes:
        for left, right in pairwise(indexes):
            union_find.union(left, right)
    for left, right in combinations(range(len(points)), 2):
        if _near(points[left], points[right]):
            union_find.union(left, right)

    entries = _pad_entries(board, net)
    pad_components: dict[tuple[str, str], int | None] = {}
    for pad, center, half_size in entries:
        connected_indexes = [
            index
            for indexes in wire_indexes
            for index in indexes
            if (
                abs(points[index][0] - center[0]) <= half_size[0] + COORDINATE_TOLERANCE_MM
                and abs(points[index][1] - center[1]) <= half_size[1] + COORDINATE_TOLERANCE_MM
            )
        ]
        pad_components[pad] = (
            min(union_find.find(index) for index in connected_indexes)
            if connected_indexes
            else None
        )

    ordered_pads = tuple(sorted(pad_components))
    unconnected_pairs = [
        [list(left), list(right)]
        for left, right in combinations(ordered_pads, 2)
        if (
            pad_components[left] != pad_components[right]
            or pad_components[left] is None
            or pad_components[right] is None
        )
    ]
    unattached = [list(pad) for pad in ordered_pads if pad_components[pad] is None]
    component_values = sorted(
        {
            union_find.find(component)
            for component in pad_components.values()
            if component is not None
        }
    )
    return {
        "net": net.name,
        "pad_count": len(ordered_pads),
        "wire_count": len(wires),
        "via_count": len(via_indexes),
        "component_count": len(component_values),
        "unconnected_pad_pairs": unconnected_pairs,
        "unattached_pads": unattached,
        "status": "fail" if unconnected_pairs or unattached else "pass",
    }


def measure_routing_connectivity(
    board: BoardModel,
    routes: RoutedDesign,
) -> dict[str, object]:
    """Return sorted, rounded net-level route connectivity observations."""
    nets = tuple(sorted(board.nets, key=lambda net: net.name))
    measured = [_connectivity_for_net(board, routes, net) for net in nets]
    return {
        "coordinate_tolerance_mm": COORDINATE_TOLERANCE_MM,
        "coordinate_decimal_places": COORDINATE_DECIMAL_PLACES,
        "net_count": len(measured),
        "nets": measured,
        "status": "fail" if any(item["status"] == "fail" for item in measured) else "pass",
    }


measure_net_connectivity = measure_routing_connectivity


__all__ = [
    "COORDINATE_DECIMAL_PLACES",
    "COORDINATE_TOLERANCE_MM",
    "measure_net_connectivity",
    "measure_routing_connectivity",
]
