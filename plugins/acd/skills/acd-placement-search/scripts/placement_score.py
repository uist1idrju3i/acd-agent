# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@8bdcc7d276a07899539101721258b643bb7f4cde",
# ]
# ///
"""Surrogate placement metrics for ranking candidates (skill asset).

The metrics here are cheap approximations of routability and manufacturability.
They exist to order candidates before the expensive deterministic steps. They
are never a pass verdict: only the ACD projections and gates (ERC/DRC and the
independent Gerber reload) decide whether a placement is acceptable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from acd.adapters.kicad.placement import MARGIN_MM, Placement, pad_bbox, placed_rect
from acd.core.board_model import FootprintShape
from acd.core.electrical import BoardView, ElectricalLane


class PlacementScoreError(ValueError):
    """Raised when a candidate cannot be scored (missing geometry, unknown refdes)."""


@dataclass(frozen=True)
class PlacementScore:
    """Surrogate metrics of one placement candidate.

    ``hpwl_mm`` is the summed half-perimeter wirelength over all nets with at
    least two pads. ``min_component_gap_mm`` is the smallest gap between any two
    component pad bounding boxes, ``min_edge_gap_mm`` the smallest gap to the
    board outline. Larger gaps and smaller wirelength rank better.
    """

    hpwl_mm: float
    min_component_gap_mm: float
    min_edge_gap_mm: float

    @property
    def rank_key(self) -> tuple[float, float, float]:
        """Deterministic sort key; lower is better."""
        return (
            round(self.hpwl_mm, 6),
            -round(self.min_component_gap_mm, 6),
            -round(self.min_edge_gap_mm, 6),
        )


def _placement_map(placements: tuple[Placement, ...]) -> dict[str, Placement]:
    by_refdes: dict[str, Placement] = {}
    for placement in placements:
        if placement.refdes in by_refdes:
            raise PlacementScoreError(f"duplicate placement for {placement.refdes}")
        by_refdes[placement.refdes] = placement
    return by_refdes


def hpwl_mm(
    lane: ElectricalLane,
    placements: tuple[Placement, ...],
    footprints: dict[str, FootprintShape],
) -> float:
    """Half-perimeter wirelength over component centres of each net."""
    by_refdes = _placement_map(placements)
    total = 0.0
    for net in sorted(lane.nets, key=lambda n: n.name):
        points: list[tuple[float, float]] = []
        for refdes, _pad in lane.pads_of_net(net.node_id):
            placement = by_refdes.get(refdes)
            if placement is None:
                raise PlacementScoreError(f"net {net.name}: {refdes} is not placed")
            if refdes not in footprints:
                raise PlacementScoreError(f"footprint geometry missing for {refdes}")
            points.append((placement.x_mm, placement.y_mm))
        if len(points) < 2:
            continue
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        total += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return total


def min_component_gap_mm(
    placements: tuple[Placement, ...],
    footprints: dict[str, FootprintShape],
) -> float:
    """Smallest gap between component pad bounding boxes; 0.0 when they touch."""
    rects = [
        (
            placement.refdes,
            placed_rect(
                footprints[placement.refdes], placement.x_mm, placement.y_mm, placement.rotation_deg
            ),
        )
        for placement in sorted(placements, key=lambda p: p.refdes)
        if placement.refdes in footprints
    ]
    if len(rects) != len(placements):
        raise PlacementScoreError("footprint geometry missing for a placed component")
    gaps: list[float] = []
    for index, (_, first) in enumerate(rects):
        for _, second in rects[index + 1 :]:
            dx = max(first.x1 - second.x2, second.x1 - first.x2, 0.0)
            dy = max(first.y1 - second.y2, second.y1 - first.y2, 0.0)
            gaps.append(math.hypot(dx, dy))
    return min(gaps) if gaps else 0.0


def min_edge_gap_mm(
    board: BoardView,
    placements: tuple[Placement, ...],
    footprints: dict[str, FootprintShape],
) -> float:
    """Smallest gap between any component pad bbox and the board outline."""
    gaps: list[float] = []
    for placement in placements:
        footprint = footprints.get(placement.refdes)
        if footprint is None:
            raise PlacementScoreError(f"footprint geometry missing for {placement.refdes}")
        pad_only = FootprintShape(footprint.library_ref, footprint.pads)
        rect = placed_rect(pad_only, placement.x_mm, placement.y_mm, placement.rotation_deg)
        gaps.extend(
            (
                rect.x1,
                rect.y1,
                board.width_mm - rect.x2,
                board.height_mm - rect.y2,
            )
        )
    return min(gaps) if gaps else 0.0


def score_placement(
    lane: ElectricalLane,
    placements: tuple[Placement, ...],
    footprints: dict[str, FootprintShape],
) -> PlacementScore:
    return PlacementScore(
        hpwl_mm=hpwl_mm(lane, placements, footprints),
        min_component_gap_mm=min_component_gap_mm(placements, footprints),
        min_edge_gap_mm=min_edge_gap_mm(lane.board, placements, footprints),
    )


def rank_candidates(
    lane: ElectricalLane,
    candidates: dict[str, tuple[Placement, ...]],
    footprints: dict[str, FootprintShape],
) -> tuple[tuple[str, PlacementScore], ...]:
    """Rank named candidates best-first. Ranking is not a pass verdict."""
    scored = [
        (name, score_placement(lane, candidates[name], footprints))
        for name in sorted(candidates)
    ]
    return tuple(sorted(scored, key=lambda item: (item[1].rank_key, item[0])))


def component_area_mm2(footprint: FootprintShape) -> float:
    """Pad bounding-box area, used for coarse density estimates."""
    x1, y1, x2, y2 = pad_bbox(footprint, MARGIN_MM)
    return (x2 - x1) * (y2 - y1)
