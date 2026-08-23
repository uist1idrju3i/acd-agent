# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@4cca489171ac53e6e55639b791c8571482167bd2",
# ]
# ///
"""Accept vision-derived routing proposals as search input (skill asset).

A vision response is an observation, never a verdict and never Evidence. This
script turns the numeric part of such a response into a routing candidate: it
validates the declared provenance, pins the polyline endpoints to the pads of
the declared net, snaps the intermediate waypoints onto the profile grid, and
rewrites every segment into the routing freedom the versioned relaxation
profile permits. Arc tracks and off-grid angles stay rejected until measured
Evidence exists, so the default candidate is octilinear.

The free-text part of a vision response is never interpreted here. Only
coordinates, layers, net names, and provenance cross this boundary, so text
rendered inside an image cannot become a command. The candidate and its
surrogate metrics stay non-authoritative: acceptance is decided by the ACD
projections and the deterministic gates (DRC, independent Gerber reload) after
the candidate has been written into the design input files.
"""

from __future__ import annotations

import argparse
import heapq
import itertools
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from acd.adapters.kicad.placement import Rect, pad_position, rotate_point
from acd.core.electrical import ElectricalLane
from acd.core.routing_width import derive_net_widths
from acd.schema.design_graph import DesignGraph
from vision_proposal import (
    SKILL_NAME,
    VISION_TOOL_NAME,
    ElectricalContext,
    ProposedItem,
    RelaxationProfile,
    VisionObservationRef,
    VisionProposalError,
    deterministic_placements,
    electrical_context,
    float_field,
    load_relaxation_profile,
    mapping_field,
    sha256_field,
    sha256_of_bytes,
    sha256_of_file,
    string_field,
)

PROPOSAL_ARTIFACT_KIND = "vision_route_proposal"
CANDIDATE_ARTIFACT_KIND = "vision_route_candidates"
COPPER_LAYERS = ("B.Cu", "F.Cu")
_TOLERANCE = 1e-9
_ROUND_DIGITS = 4
_DETOUR_NODE_BUDGET = 200000

Point = tuple[float, float]


@dataclass(frozen=True)
class ProposedRoute:
    """One numeric routing proposal: a net, a copper layer, and waypoints."""

    net: str
    layer: str
    waypoints: tuple[Point, ...]


@dataclass(frozen=True)
class VisionRouteProposal:
    observation: VisionObservationRef
    routes: tuple[ProposedRoute, ...]


@dataclass(frozen=True)
class RouteContext:
    """Geometry the route legalizer needs, derived from a placement candidate."""

    region: Rect
    clearance_mm: float
    endpoints: dict[tuple[str, str], tuple[Point, Point]]
    widths_mm: dict[str, float]
    obstacles: dict[tuple[str, str], tuple[Rect, ...]]


@dataclass(frozen=True)
class RouteCandidate:
    """One legalized wire; still a candidate, never a verdict."""

    net: str
    layer: str
    width_mm: float
    points: tuple[Point, ...]
    repaired_hops: int = 0

    @property
    def length_mm(self) -> float:
        return sum(
            math.dist(start, end)
            for start, end in itertools.pairwise(self.points)
        )


@dataclass(frozen=True)
class RouteMetrics:
    """Surrogate metrics of one routing candidate; never a pass verdict."""

    total_length_mm: float
    segment_count: int
    direction_changes: int
    repaired_hops: int
    min_clearance_mm: float

    @property
    def rank_key(self) -> tuple[float, int, int]:
        """Deterministic sort key; lower is better."""
        return (round(self.total_length_mm, 6), self.segment_count, self.direction_changes)


def parse_route_proposal(payload: dict[str, object]) -> VisionRouteProposal:
    """Validate the proposal contract; every deviation is a stop condition."""
    if payload.get("artifact_kind") != PROPOSAL_ARTIFACT_KIND:
        raise VisionProposalError(f"artifact_kind must be {PROPOSAL_ARTIFACT_KIND!r} (fail-closed)")
    if payload.get("pass_evidence") is not False:
        raise VisionProposalError("vision proposals must declare pass_evidence=false")

    observation = mapping_field(payload, "observation")
    if observation.get("tool_name") != VISION_TOOL_NAME:
        raise VisionProposalError(f"observation tool_name must be {VISION_TOOL_NAME!r}")
    response = string_field(observation, "response")
    reference = VisionObservationRef(
        tool_name=VISION_TOOL_NAME,
        profile_name=string_field(observation, "profile_name"),
        model=string_field(observation, "model"),
        projection_id=string_field(observation, "projection_id"),
        image_hash=sha256_field(observation, "image_hash"),
        response_sha256=sha256_of_bytes(response.encode("utf-8")),
    )

    raw_routes = payload.get("proposals")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise VisionProposalError("proposals must be a non-empty array (fail-closed)")
    routes: list[ProposedRoute] = []
    seen: set[str] = set()
    for entry in cast(list[object], raw_routes):
        if not isinstance(entry, dict):
            raise VisionProposalError("each proposal must be an object (fail-closed)")
        route = cast(dict[str, object], entry)
        net = string_field(route, "net")
        if net in seen:
            raise VisionProposalError(f"duplicate proposal for net {net!r} (fail-closed)")
        seen.add(net)
        layer = string_field(route, "layer")
        if layer not in COPPER_LAYERS:
            raise VisionProposalError(f"unsupported copper layer {layer!r} (fail-closed)")
        for key in ("arc", "arcs", "radius_mm"):
            if key in route:
                raise VisionProposalError(
                    f"net {net!r}: arc geometry is not accepted without measured Evidence"
                )
        raw_points = route.get("waypoints")
        if not isinstance(raw_points, list) or not raw_points:
            raise VisionProposalError(f"net {net!r}: waypoints must be a non-empty array")
        waypoints: list[Point] = []
        for item in cast(list[object], raw_points):
            if not isinstance(item, dict):
                raise VisionProposalError(f"net {net!r}: each waypoint must be an object")
            point = cast(dict[str, object], item)
            waypoints.append((float_field(point, "x_mm"), float_field(point, "y_mm")))
        routes.append(ProposedRoute(net=net, layer=layer, waypoints=tuple(waypoints)))
    return VisionRouteProposal(
        observation=reference,
        routes=tuple(sorted(routes, key=lambda proposed: proposed.net)),
    )


def _pad_rects(
    electrical: ElectricalContext, placements: dict[str, ProposedItem]
) -> dict[tuple[str, str], tuple[Rect, ...]]:
    """Pad bounding boxes per copper layer and net, from the placement candidate.

    A pad number may repeat inside a footprint (thermal pads, split pads), so
    every matching pad becomes an obstacle rather than one unique pad. A pad
    only obstructs the layers it actually appears on.
    """
    lane = electrical.lane
    rects: dict[tuple[str, str], list[Rect]] = {
        (layer, net.name): [] for layer in COPPER_LAYERS for net in lane.nets
    }
    for net in lane.nets:
        for refdes, pad_number in lane.pads_of_net(net.node_id):
            placement = placements.get(refdes)
            footprint = electrical.footprints.get(refdes)
            if placement is None or footprint is None:
                raise VisionProposalError(f"{refdes} has no placement or footprint (fail-closed)")
            pads = [pad for pad in footprint.pads if pad.number == pad_number]
            if not pads:
                raise VisionProposalError(f"{refdes}-{pad_number} has no pad (fail-closed)")
            for pad in pads:
                offset_x, offset_y = rotate_point(pad.x_mm, pad.y_mm, placement.rotation_deg)
                x = placement.x_mm + offset_x
                y = placement.y_mm + offset_y
                half_width, half_height = pad.size_x_mm / 2.0, pad.size_y_mm / 2.0
                if placement.rotation_deg in (90.0, 270.0):
                    half_width, half_height = half_height, half_width
                rect = Rect(x - half_width, y - half_height, x + half_width, y + half_height)
                if pad.on_front:
                    rects[("F.Cu", net.name)].append(rect)
                if pad.on_back:
                    rects[("B.Cu", net.name)].append(rect)
    return {key: tuple(items) for key, items in rects.items()}


def _net_endpoints(
    electrical: ElectricalContext, placements: dict[str, ProposedItem]
) -> dict[tuple[str, str], tuple[Point, Point]]:
    """Pad endpoints per copper layer for the two-pad nets a proposal may route.

    Nets with more than two pads, or with a pad number that is not unique in
    its footprint, stay out: those need the router, not a two-point candidate.
    A net is only routable on a layer where both of its pads exist, because this
    generator does not create vias.
    """
    lane = electrical.lane
    endpoints: dict[tuple[str, str], tuple[Point, Point]] = {}
    for net in lane.nets:
        pads = lane.pads_of_net(net.node_id)
        if len(pads) != 2:
            continue
        positions: list[Point] = []
        layers = set(COPPER_LAYERS)
        for refdes, pad_number in pads:
            placement = placements[refdes]
            footprint = electrical.footprints[refdes]
            matching = [pad for pad in footprint.pads if pad.number == pad_number]
            if len(matching) != 1:
                break
            pad = matching[0]
            if not pad.on_front:
                layers.discard("F.Cu")
            if not pad.on_back:
                layers.discard("B.Cu")
            positions.append(
                pad_position(
                    footprint,
                    (placement.x_mm, placement.y_mm),
                    placement.rotation_deg,
                    pad_number,
                )
            )
        if len(positions) != 2:
            continue
        ordered = sorted(positions)
        for layer in sorted(layers):
            endpoints[(layer, net.name)] = (ordered[0], ordered[1])
    return endpoints


def route_context(
    electrical: ElectricalContext,
    placements: tuple[ProposedItem, ...],
    fab_profile_minimum_mm: float,
) -> RouteContext:
    """Board region, net widths, pad obstacles and endpoints of one placement."""
    by_refdes = {item.item_id: item for item in placements}
    board = electrical.lane.board
    widths = {
        requirement.net_name: requirement.adopted_width_mm
        for requirement in derive_net_widths(electrical.lane, fab_profile_minimum_mm)
    }
    return RouteContext(
        region=electrical.context.region,
        clearance_mm=board.min_clearance_mm,
        endpoints=_net_endpoints(electrical, by_refdes),
        widths_mm=widths,
        obstacles=_pad_rects(electrical, by_refdes),
    )


def _snap(value: float, grid_step_mm: float) -> float:
    return round(round(value / grid_step_mm) * grid_step_mm, _ROUND_DIGITS)


def _clamp(value: float, low: float, high: float) -> float:
    if low > high:
        raise VisionProposalError("routable region is empty (fail-closed)")
    return min(max(value, low), high)


def octilinearize(start: Point, end: Point) -> tuple[Point, ...]:
    """Rewrite one segment into 45/90 degree segments (no arcs, no free angles)."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if abs(dx) <= _TOLERANCE or abs(dy) <= _TOLERANCE or abs(abs(dx) - abs(dy)) <= _TOLERANCE:
        return (start, end)
    diagonal = min(abs(dx), abs(dy))
    corner = (
        round(start[0] + math.copysign(diagonal, dx), _ROUND_DIGITS),
        round(start[1] + math.copysign(diagonal, dy), _ROUND_DIGITS),
    )
    return (start, corner, end)


def _point_rect_distance(point: Point, rect: Rect) -> float:
    dx = max(rect.x1 - point[0], point[0] - rect.x2, 0.0)
    dy = max(rect.y1 - point[1], point[1] - rect.y2, 0.0)
    return math.hypot(dx, dy)


def _point_segment_distance(point: Point, segment: tuple[Point, Point]) -> float:
    (x1, y1), (x2, y2) = segment
    dx, dy = x2 - x1, y2 - y1
    length2 = dx * dx + dy * dy
    if length2 <= _TOLERANCE:
        return math.dist(point, segment[0])
    ratio = ((point[0] - x1) * dx + (point[1] - y1) * dy) / length2
    ratio = min(max(ratio, 0.0), 1.0)
    return math.dist(point, (x1 + dx * ratio, y1 + dy * ratio))


def _crosses(first: tuple[Point, Point], second: tuple[Point, Point]) -> bool:
    def orientation(a: Point, b: Point, c: Point) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1 = orientation(second[0], second[1], first[0])
    d2 = orientation(second[0], second[1], first[1])
    d3 = orientation(first[0], first[1], second[0])
    d4 = orientation(first[0], first[1], second[1])
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _rect_edges(rect: Rect) -> tuple[tuple[Point, Point], ...]:
    corners = (
        (rect.x1, rect.y1),
        (rect.x2, rect.y1),
        (rect.x2, rect.y2),
        (rect.x1, rect.y2),
    )
    return tuple(
        (corners[index], corners[(index + 1) % 4]) for index in range(4)
    )


def _segment_rect_distance(segment: tuple[Point, Point], rect: Rect) -> float:
    """Exact distance between a segment and an axis-aligned rectangle."""
    for point in segment:
        if rect.x1 <= point[0] <= rect.x2 and rect.y1 <= point[1] <= rect.y2:
            return 0.0
    if any(_crosses(segment, edge) for edge in _rect_edges(rect)):
        return 0.0
    distances = [_point_rect_distance(point, rect) for point in segment]
    distances.extend(
        _point_segment_distance(corner, segment)
        for edge in _rect_edges(rect)
        for corner in edge
    )
    return min(distances)


def _segment_gap(first: tuple[Point, Point], second: tuple[Point, Point]) -> float:
    """Exact distance between two segments."""
    if _crosses(first, second):
        return 0.0
    return min(
        _point_segment_distance(first[0], second),
        _point_segment_distance(first[1], second),
        _point_segment_distance(second[0], first),
        _point_segment_distance(second[1], first),
    )


def _segments(points: tuple[Point, ...]) -> tuple[tuple[Point, Point], ...]:
    return tuple(itertools.pairwise(points))


@dataclass(frozen=True)
class Blockage:
    """Foreign copper a candidate must keep its declared clearance from."""

    label: str
    limit_mm: float
    rects: tuple[Rect, ...] = ()
    wires: tuple[tuple[Point, Point], ...] = ()

    def distance(self, segment: tuple[Point, Point]) -> float:
        distances = [_segment_rect_distance(segment, rect) for rect in self.rects]
        distances.extend(_segment_gap(segment, wire) for wire in self.wires)
        return min(distances) if distances else math.inf


def blockages(
    net: str,
    layer: str,
    width_mm: float,
    context: RouteContext,
    routed: tuple[RouteCandidate, ...],
) -> tuple[Blockage, ...]:
    """Foreign pads plus already legalized wires of the same layer."""
    items = [
        Blockage(
            label=f"net {key[1]!r} pads",
            limit_mm=context.clearance_mm + width_mm / 2.0,
            rects=rects,
        )
        for key, rects in sorted(context.obstacles.items())
        if key[0] == layer and key[1] != net and rects
    ]
    items.extend(
        Blockage(
            label=f"routed net {other.net!r}",
            limit_mm=context.clearance_mm + (width_mm + other.width_mm) / 2.0,
            wires=_segments(other.points),
        )
        for other in routed
        if other.net != net and other.layer == layer
    )
    return tuple(items)


def _violation(segment: tuple[Point, Point], items: tuple[Blockage, ...]) -> str | None:
    for item in items:
        if item.distance(segment) < item.limit_mm - _TOLERANCE:
            return item.label
    return None


def _clearance(segments: tuple[tuple[Point, Point], ...], items: tuple[Blockage, ...]) -> float:
    worst = math.inf
    for segment in segments:
        for item in items:
            worst = min(worst, item.distance(segment))
    return worst


def _inset_region(region: Rect, inset: float) -> Rect:
    return Rect(region.x1 + inset, region.y1 + inset, region.x2 - inset, region.y2 - inset)


def _detour(
    start: Point,
    end: Point,
    region: Rect,
    items: tuple[Blockage, ...],
    grid_step_mm: float,
) -> tuple[Point, ...]:
    """Deterministic octilinear grid search between two pinned points.

    The vision proposal only states the intent of a connection; where that
    intent collides with foreign copper, this search repairs it on the profile
    grid. An exhausted region or node budget is a stop condition.
    """

    def on_grid(point: Point) -> Point:
        return (
            _clamp(_snap(point[0], grid_step_mm), region.x1, region.x2),
            _clamp(_snap(point[1], grid_step_mm), region.y1, region.y2),
        )

    entry, goal = on_grid(start), on_grid(end)
    steps = (
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    )
    queue: list[tuple[float, Point]] = [(math.dist(entry, goal), entry)]
    came: dict[Point, Point | None] = {entry: None}
    cost: dict[Point, float] = {entry: 0.0}
    visited = 0
    while queue:
        _, current = heapq.heappop(queue)
        if current == goal:
            break
        visited += 1
        if visited > _DETOUR_NODE_BUDGET:
            raise VisionProposalError("detour search exceeded its node budget (fail-closed)")
        for step_x, step_y in steps:
            neighbour = (
                round(current[0] + step_x * grid_step_mm, _ROUND_DIGITS),
                round(current[1] + step_y * grid_step_mm, _ROUND_DIGITS),
            )
            if not (
                region.x1 - _TOLERANCE <= neighbour[0] <= region.x2 + _TOLERANCE
                and region.y1 - _TOLERANCE <= neighbour[1] <= region.y2 + _TOLERANCE
            ):
                continue
            spent = cost[current] + math.dist(current, neighbour)
            if spent >= cost.get(neighbour, math.inf) - _TOLERANCE:
                continue
            if _violation((current, neighbour), items) is not None:
                continue
            cost[neighbour] = spent
            came[neighbour] = current
            heapq.heappush(queue, (spent + math.dist(neighbour, goal), neighbour))
    if goal not in came:
        raise VisionProposalError("no legal detour exists on the board (fail-closed)")

    path: list[Point] = []
    cursor: Point | None = goal
    while cursor is not None:
        path.append(cursor)
        cursor = came[cursor]
    path.reverse()
    for approach in ((start, path[0]), (path[-1], end)):
        if math.dist(*approach) > _TOLERANCE and _violation(approach, items) is not None:
            raise VisionProposalError("detour cannot reach its pinned endpoint (fail-closed)")
    return tuple(_collapse((start, *path, end)))


def _collapse(points: tuple[Point, ...]) -> list[Point]:
    """Drop repeated and collinear intermediate points."""
    kept: list[Point] = []
    for point in points:
        if kept and math.dist(kept[-1], point) <= _TOLERANCE:
            continue
        if len(kept) >= 2:
            previous, last = kept[-2], kept[-1]
            cross = (last[0] - previous[0]) * (point[1] - last[1]) - (last[1] - previous[1]) * (
                point[0] - last[0]
            )
            if abs(cross) <= _TOLERANCE:
                kept[-1] = point
                continue
        kept.append(point)
    return kept


def _nudge(
    point: Point,
    region: Rect,
    items: tuple[Blockage, ...],
    profile: RelaxationProfile,
) -> Point:
    """Move a waypoint that sits on foreign copper onto the nearest legal node.

    A vision estimate is coarse, so a waypoint may land on a pad. The shift is
    bounded by the same declared maximum as placement legalization; exceeding it
    is a stop condition.
    """
    if _violation((point, point), items) is None:
        return point
    step = profile.grid_step_mm
    rings = int(profile.max_shift_mm / step)
    for ring in range(1, rings + 1):
        offsets = sorted(
            {
                (offset_x, offset_y)
                for offset_x in range(-ring, ring + 1)
                for offset_y in range(-ring, ring + 1)
                if max(abs(offset_x), abs(offset_y)) == ring
            },
            key=lambda offset: (math.hypot(*offset), offset),
        )
        for offset_x, offset_y in offsets:
            moved = (
                round(point[0] + offset_x * step, _ROUND_DIGITS),
                round(point[1] + offset_y * step, _ROUND_DIGITS),
            )
            if not (
                region.x1 - _TOLERANCE <= moved[0] <= region.x2 + _TOLERANCE
                and region.y1 - _TOLERANCE <= moved[1] <= region.y2 + _TOLERANCE
            ):
                continue
            if _violation((moved, moved), items) is None:
                return moved
    raise VisionProposalError(
        "a proposed waypoint cannot be legalized within the declared shift (fail-closed)"
    )


def _hop(
    start: Point,
    end: Point,
    region: Rect,
    items: tuple[Blockage, ...],
    profile: RelaxationProfile,
) -> tuple[Point, ...]:
    """One proposed hop, rewritten into legal geometry."""
    direct = (
        (start, end) if profile.off_grid_angles else octilinearize(start, end)
    )
    if all(_violation(segment, items) is None for segment in _segments(direct)):
        return direct
    if profile.off_grid_angles:
        raise VisionProposalError(
            "off-grid hops are not repaired by the detour search (fail-closed)"
        )
    return _detour(start, end, region, items, profile.grid_step_mm)


def legalize_route(
    route: ProposedRoute,
    context: RouteContext,
    profile: RelaxationProfile,
    routed: tuple[RouteCandidate, ...] = (),
) -> RouteCandidate:
    """Pin the endpoints, snap the waypoints, and legalize every hop."""
    endpoints = context.endpoints.get((route.layer, route.net))
    if endpoints is None:
        raise VisionProposalError(
            f"net {route.net!r} is not a two-pad net reachable on {route.layer} "
            "without vias (fail-closed)"
        )
    width = context.widths_mm.get(route.net)
    if width is None:
        raise VisionProposalError(f"net {route.net!r} has no declared width (fail-closed)")
    items = blockages(route.net, route.layer, width, context, routed)
    region = _inset_region(context.region, width / 2.0)
    snapped: list[Point] = []
    for x_mm, y_mm in route.waypoints:
        point = _nudge(
            (
                _clamp(_snap(x_mm, profile.grid_step_mm), region.x1, region.x2),
                _clamp(_snap(y_mm, profile.grid_step_mm), region.y1, region.y2),
            ),
            region,
            items,
            profile,
        )
        if not snapped or math.dist(snapped[-1], point) > _TOLERANCE:
            snapped.append(point)

    points: list[Point] = [endpoints[0]]
    repaired = 0
    for target in [*snapped, endpoints[1]]:
        if math.dist(points[-1], target) <= _TOLERANCE:
            continue
        hop = _hop(points[-1], target, region, items, profile)
        if len(hop) > 3:
            repaired += 1
        points.extend(hop[1:])
    collapsed = _collapse(tuple(points))
    if len(collapsed) < 2:
        raise VisionProposalError(f"net {route.net!r}: candidate has no length (fail-closed)")
    return RouteCandidate(
        net=route.net,
        layer=route.layer,
        width_mm=round(width, _ROUND_DIGITS),
        points=tuple(collapsed),
        repaired_hops=repaired,
    )


def check_route(
    candidate: RouteCandidate,
    context: RouteContext,
    routed: tuple[RouteCandidate, ...] = (),
) -> float:
    """Fail closed unless the candidate keeps clearance to foreign copper."""
    region = _inset_region(context.region, candidate.width_mm / 2.0)
    for x_mm, y_mm in candidate.points:
        if not (
            region.x1 - _TOLERANCE <= x_mm <= region.x2 + _TOLERANCE
            and region.y1 - _TOLERANCE <= y_mm <= region.y2 + _TOLERANCE
        ):
            raise VisionProposalError(
                f"net {candidate.net!r}: candidate leaves the routable region (fail-closed)"
            )
    items = blockages(candidate.net, candidate.layer, candidate.width_mm, context, routed)
    segments = _segments(candidate.points)
    for segment in segments:
        label = _violation(segment, items)
        if label is not None:
            raise VisionProposalError(
                f"net {candidate.net!r}: candidate violates clearance to {label} (fail-closed)"
            )
    worst = _clearance(segments, items)
    return worst if math.isfinite(worst) else 0.0


def route_metrics(
    candidate: RouteCandidate,
    context: RouteContext,
    routed: tuple[RouteCandidate, ...] = (),
) -> RouteMetrics:
    """Surrogate metrics of one candidate; not acceptance evidence."""
    clearance = check_route(candidate, context, routed)
    segments = _segments(candidate.points)
    directions = [
        round(math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])), 6)
        for start, end in segments
    ]
    changes = sum(
        1
        for first, second in itertools.pairwise(directions)
        if abs(first - second) > _TOLERANCE
    )
    return RouteMetrics(
        total_length_mm=round(candidate.length_mm, 6),
        segment_count=len(segments),
        direction_changes=changes,
        repaired_hops=candidate.repaired_hops,
        min_clearance_mm=round(clearance, 6),
    )


def legalize_proposal(
    proposal: VisionRouteProposal, context: RouteContext, profile: RelaxationProfile
) -> tuple[tuple[RouteCandidate, RouteMetrics], ...]:
    """Legalize every proposed net in a deterministic order."""
    if profile.arc_tracks:
        raise VisionProposalError(
            "arc tracks are not implemented by this candidate generator (fail-closed)"
        )
    accepted: list[tuple[RouteCandidate, RouteMetrics]] = []
    for route in proposal.routes:
        routed = tuple(item for item, _ in accepted)
        candidate = legalize_route(route, context, profile, routed)
        metrics = route_metrics(candidate, context, routed)
        accepted.append((candidate, metrics))
    return tuple(accepted)


def load_placements(
    electrical: ElectricalContext, path: Path | None
) -> tuple[tuple[ProposedItem, ...], str]:
    """Placement the routing candidate is pinned to, plus its provenance hash."""
    if path is None:
        return deterministic_placements(electrical), "deterministic-search"
    document = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(document, dict):
        raise VisionProposalError("placement report must be a JSON object (fail-closed)")
    payload = cast(dict[str, object], document)
    candidates = mapping_field(payload, "candidates")
    raw_items = candidates.get("vision")
    if not isinstance(raw_items, list) or not raw_items:
        raise VisionProposalError("placement report has no vision candidate (fail-closed)")
    items: list[ProposedItem] = []
    for entry in cast(list[object], raw_items):
        if not isinstance(entry, dict):
            raise VisionProposalError("each placement must be an object (fail-closed)")
        item = cast(dict[str, object], entry)
        items.append(
            ProposedItem(
                item_id=string_field(item, "item_id"),
                x_mm=float_field(item, "x_mm"),
                y_mm=float_field(item, "y_mm"),
                rotation_deg=float_field(item, "rotation_deg"),
            )
        )
    return tuple(items), sha256_of_file(path)


def _fab_profile_minimum(path: Path) -> float:
    document = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(document, dict):
        raise VisionProposalError("fab profile must be a JSON object (fail-closed)")
    capabilities = mapping_field(cast(dict[str, object], document), "capabilities")
    return float_field(mapping_field(capabilities, "min_track_width"), "value")


def _wires_payload(
    accepted: tuple[tuple[RouteCandidate, RouteMetrics], ...],
) -> list[dict[str, object]]:
    return [
        {
            "net": candidate.net,
            "layer": candidate.layer,
            "width_mm": candidate.width_mm,
            "points": [[point[0], point[1]] for point in candidate.points],
            "surrogate_metrics": {
                "total_length_mm": metrics.total_length_mm,
                "segment_count": metrics.segment_count,
                "direction_changes": metrics.direction_changes,
                "repaired_hops": metrics.repaired_hops,
                "min_clearance_mm": metrics.min_clearance_mm,
            },
        }
        for candidate, metrics in accepted
    ]


def build_candidate_report(
    *,
    proposal: VisionRouteProposal,
    accepted: tuple[tuple[RouteCandidate, RouteMetrics], ...],
    lane: ElectricalLane,
    provenance: dict[str, object],
) -> dict[str, object]:
    """Assemble the non-authoritative routing candidate report."""
    ranked = sorted(accepted, key=lambda entry: (entry[1].rank_key, entry[0].net))
    return {
        "artifact_kind": CANDIDATE_ARTIFACT_KIND,
        "pass_evidence": False,
        "lane": "electrical",
        "proposed_nets": [route.net for route in proposal.routes],
        "candidates": {"vision": _wires_payload(accepted), "vias": []},
        "ranking": [candidate.net for candidate, _ in ranked],
        "board": {
            "min_clearance_mm": lane.board.min_clearance_mm,
            "min_track_mm": lane.board.min_track_mm,
        },
        "provenance": provenance,
    }


def _provenance(
    *,
    proposal: VisionRouteProposal,
    proposal_path: Path,
    relaxation_profile_path: Path,
    relaxation_profile: RelaxationProfile,
    placements_sha256: str,
    graph_revision: str,
) -> dict[str, object]:
    script = Path(__file__).resolve()
    return {
        "skill_name": SKILL_NAME,
        "script_name": script.name,
        "script_sha256": sha256_of_file(script),
        "proposal_sha256": sha256_of_file(proposal_path),
        "placements_sha256": placements_sha256,
        "relaxation_profile_id": relaxation_profile.profile_id,
        "relaxation_profile_sha256": sha256_of_file(relaxation_profile_path),
        "graph_revision": graph_revision,
        "observation": {
            "tool_name": proposal.observation.tool_name,
            "profile_name": proposal.observation.profile_name,
            "model": proposal.observation.model,
            "projection_id": proposal.observation.projection_id,
            "image_hash": proposal.observation.image_hash,
            "response_sha256": proposal.observation.response_sha256,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--relaxation-profile", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--fab-profile", type=Path, required=True)
    parser.add_argument("--placements", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    document = cast(object, json.loads(args.proposal.read_text(encoding="utf-8")))
    if not isinstance(document, dict):
        raise VisionProposalError("proposal must be a JSON object (fail-closed)")
    proposal = parse_route_proposal(cast(dict[str, object], document))
    relaxation_profile = load_relaxation_profile(args.relaxation_profile)
    graph = DesignGraph.model_validate(
        cast(object, json.loads(args.input.read_text(encoding="utf-8")))
    )

    electrical = electrical_context(graph, args.fixture_dir, args.fab_profile)
    placements, placements_sha256 = load_placements(electrical, args.placements)
    context = route_context(electrical, placements, _fab_profile_minimum(args.fab_profile))
    accepted = legalize_proposal(proposal, context, relaxation_profile)

    report = build_candidate_report(
        proposal=proposal,
        accepted=accepted,
        lane=electrical.lane,
        provenance=_provenance(
            proposal=proposal,
            proposal_path=args.proposal,
            relaxation_profile_path=args.relaxation_profile,
            relaxation_profile=relaxation_profile,
            placements_sha256=placements_sha256,
            graph_revision=graph.revision,
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
