# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@25d07aa0869c1469628468b485ae9157855860f6",
# ]
# ///
"""Accept vision-derived routing proposals as search input (skill asset).

A vision response is an observation, never a verdict and never Evidence. This
script turns the numeric part of such a response into routing candidates: it
validates the declared provenance, pins every connection to the pads it names,
snaps the intermediate waypoints onto the profile grid, and rewrites every
segment into the routing freedom the versioned relaxation profile permits. Arc
tracks and off-grid angles stay rejected until measured Evidence exists, so the
default candidate is octilinear.

A proposal may declare one connection per pad pair, so a net with more than two
pads is expressed as several connections, and it may change layer through
declared via positions. Via geometry is never read from the vision response: the
drill and diameter come from the graph declaration and are checked against the
fab profile. A net that is proposed but left electrically incomplete is a stop
condition, because an unconnected net would only surface as a DRC failure later.

The free-text part of a vision response is never interpreted here. Only
coordinates, layers, net names, pad references, and provenance cross this
boundary, so text rendered inside an image cannot become a command. The
candidates and their surrogate metrics stay non-authoritative: acceptance is
decided by the ACD projections and the deterministic gates (DRC, independent
Gerber reload) after the candidates have been written into the design input
files.
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
class ProposedSegment:
    """One proposed polyline on a single copper layer."""

    layer: str
    waypoints: tuple[Point, ...]


@dataclass(frozen=True)
class ProposedRoute:
    """One proposed connection between two pads of the same net.

    ``transitions`` holds the layer change positions between consecutive
    segments, so a route with n segments declares n-1 of them. The pad
    references may be omitted only for a net with exactly two pads.
    """

    net: str
    segments: tuple[ProposedSegment, ...]
    transitions: tuple[Point, ...] = ()
    from_pad: str | None = None
    to_pad: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.net, self.from_pad or "", self.to_pad or "")


def single_layer_route(
    net: str,
    layer: str,
    waypoints: tuple[Point, ...],
    from_pad: str | None = None,
    to_pad: str | None = None,
) -> ProposedRoute:
    """One-segment route, the shape a same-layer proposal reduces to."""
    return ProposedRoute(
        net=net,
        segments=(ProposedSegment(layer=layer, waypoints=waypoints),),
        from_pad=from_pad,
        to_pad=to_pad,
    )


@dataclass(frozen=True)
class VisionRouteProposal:
    observation: VisionObservationRef
    routes: tuple[ProposedRoute, ...]


@dataclass(frozen=True)
class FabMinimums:
    """Manufacturing minimums a candidate may never fall below."""

    track_width_mm: float
    via_hole_mm: float
    via_diameter_mm: float
    via_diameter_margin_mm: float


@dataclass(frozen=True)
class PadSite:
    """One resolvable pad: its net, its position, and the layers it reaches."""

    pad_id: str
    net: str
    point: Point
    layers: tuple[str, ...]


@dataclass(frozen=True)
class RouteContext:
    """Geometry the route legalizer needs, derived from a placement candidate."""

    region: Rect
    clearance_mm: float
    pads: dict[str, PadSite]
    net_pads: dict[str, tuple[str, ...]]
    widths_mm: dict[str, float]
    obstacles: dict[tuple[str, str], tuple[Rect, ...]]
    via_drill_mm: float
    via_diameter_mm: float
    fab: FabMinimums


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
class RouteVia:
    """One legalized layer change; drill and diameter come from declarations."""

    net: str
    point: Point
    drill_mm: float
    diameter_mm: float


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


@dataclass(frozen=True)
class LegalizedRoute:
    """One legalized connection: its wires per layer and its vias."""

    net: str
    from_pad: str
    to_pad: str
    wires: tuple[RouteCandidate, ...]
    vias: tuple[RouteVia, ...]

    @property
    def label(self) -> str:
        return f"{self.net}:{self.from_pad}->{self.to_pad}"


@dataclass(frozen=True)
class ConnectionMetrics:
    """Surrogate metrics of one connection, aggregated over its wires."""

    total_length_mm: float
    segment_count: int
    direction_changes: int
    repaired_hops: int
    via_count: int
    min_clearance_mm: float

    @property
    def rank_key(self) -> tuple[float, int, int, int]:
        return (
            round(self.total_length_mm, 6),
            self.via_count,
            self.segment_count,
            self.direction_changes,
        )


@dataclass(frozen=True)
class RoutePlan:
    """One legalized connection with the metrics of its wires."""

    route: LegalizedRoute
    wire_metrics: tuple[RouteMetrics, ...]
    metrics: ConnectionMetrics


def _point(payload: dict[str, object]) -> Point:
    return (float_field(payload, "x_mm"), float_field(payload, "y_mm"))


def _waypoints(route: dict[str, object], net: str, source: dict[str, object]) -> tuple[Point, ...]:
    raw_points = source.get("waypoints")
    if not isinstance(raw_points, list) or not raw_points:
        raise VisionProposalError(f"net {net!r}: waypoints must be a non-empty array")
    for key in ("arc", "arcs", "radius_mm"):
        if key in route or key in source:
            raise VisionProposalError(
                f"net {net!r}: arc geometry is not accepted without measured Evidence"
            )
    points: list[Point] = []
    for item in cast(list[object], raw_points):
        if not isinstance(item, dict):
            raise VisionProposalError(f"net {net!r}: each waypoint must be an object")
        points.append(_point(cast(dict[str, object], item)))
    return tuple(points)


def _layer(payload: dict[str, object], net: str) -> str:
    layer = string_field(payload, "layer")
    if layer not in COPPER_LAYERS:
        raise VisionProposalError(f"unsupported copper layer {layer!r} (fail-closed)")
    return layer


def _pad_reference(route: dict[str, object], key: str, net: str) -> str | None:
    if key not in route:
        return None
    value = route[key]
    if not isinstance(value, str) or not value:
        raise VisionProposalError(f"net {net!r}: {key!r} must be a non-empty string (fail-closed)")
    return value


def _transitions(route: dict[str, object], net: str, segments: int) -> tuple[Point, ...]:
    """Declared layer change positions; one fewer than the segment count."""
    raw_vias = route.get("vias", [])
    if not isinstance(raw_vias, list):
        raise VisionProposalError(f"net {net!r}: vias must be an array (fail-closed)")
    positions: list[Point] = []
    for item in cast(list[object], raw_vias):
        if not isinstance(item, dict):
            raise VisionProposalError(f"net {net!r}: each via must be an object (fail-closed)")
        positions.append(_point(cast(dict[str, object], item)))
    if len(positions) != segments - 1:
        raise VisionProposalError(
            f"net {net!r}: {segments} segments require {segments - 1} declared vias (fail-closed)"
        )
    return tuple(positions)


def _parse_route(route: dict[str, object]) -> ProposedRoute:
    """One proposal entry: a same-layer polyline or a multi-layer connection."""
    net = string_field(route, "net")
    from_pad = _pad_reference(route, "from_pad", net)
    to_pad = _pad_reference(route, "to_pad", net)
    if (from_pad is None) != (to_pad is None):
        raise VisionProposalError(
            f"net {net!r}: from_pad and to_pad must be declared together (fail-closed)"
        )
    if from_pad is not None and from_pad == to_pad:
        raise VisionProposalError(f"net {net!r}: a connection needs two distinct pads")
    raw_segments = route.get("segments")
    if raw_segments is None:
        return ProposedRoute(
            net=net,
            segments=(
                ProposedSegment(
                    layer=_layer(route, net), waypoints=_waypoints(route, net, route)
                ),
            ),
            transitions=_transitions(route, net, 1),
            from_pad=from_pad,
            to_pad=to_pad,
        )
    if "layer" in route or "waypoints" in route:
        raise VisionProposalError(
            f"net {net!r}: declare either segments or a single layer polyline (fail-closed)"
        )
    if not isinstance(raw_segments, list) or not raw_segments:
        raise VisionProposalError(f"net {net!r}: segments must be a non-empty array (fail-closed)")
    parsed: list[ProposedSegment] = []
    for entry in cast(list[object], raw_segments):
        if not isinstance(entry, dict):
            raise VisionProposalError(f"net {net!r}: each segment must be an object (fail-closed)")
        segment = cast(dict[str, object], entry)
        parsed.append(
            ProposedSegment(
                layer=_layer(segment, net), waypoints=_waypoints(route, net, segment)
            )
        )
    for first, second in itertools.pairwise(parsed):
        if first.layer == second.layer:
            raise VisionProposalError(
                f"net {net!r}: consecutive segments must change layer (fail-closed)"
            )
    return ProposedRoute(
        net=net,
        segments=tuple(parsed),
        transitions=_transitions(route, net, len(parsed)),
        from_pad=from_pad,
        to_pad=to_pad,
    )


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
    seen: set[tuple[str, str, str]] = set()
    for entry in cast(list[object], raw_routes):
        if not isinstance(entry, dict):
            raise VisionProposalError("each proposal must be an object (fail-closed)")
        route = _parse_route(cast(dict[str, object], entry))
        if route.key in seen:
            raise VisionProposalError(f"duplicate proposal for {route.key} (fail-closed)")
        seen.add(route.key)
        routes.append(route)
    return VisionRouteProposal(
        observation=reference,
        routes=tuple(sorted(routes, key=lambda proposed: proposed.key)),
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


def _pad_sites(
    electrical: ElectricalContext, placements: dict[str, ProposedItem]
) -> tuple[dict[str, PadSite], dict[str, tuple[str, ...]]]:
    """Resolvable pads per net, plus the full pad membership of every net.

    A pad number that repeats inside its footprint has no single position, so it
    stays out of the resolvable sites: naming it in a proposal is a stop
    condition rather than a guess between the matching pads.
    """
    lane = electrical.lane
    sites: dict[str, PadSite] = {}
    membership: dict[str, tuple[str, ...]] = {}
    for net in lane.nets:
        pad_ids: list[str] = []
        for refdes, pad_number in lane.pads_of_net(net.node_id):
            pad_id = f"{refdes}-{pad_number}"
            pad_ids.append(pad_id)
            placement = placements[refdes]
            footprint = electrical.footprints[refdes]
            matching = [pad for pad in footprint.pads if pad.number == pad_number]
            if len(matching) != 1:
                continue
            pad = matching[0]
            layers = tuple(
                layer
                for layer, present in (("B.Cu", pad.on_back), ("F.Cu", pad.on_front))
                if present
            )
            sites[pad_id] = PadSite(
                pad_id=pad_id,
                net=net.name,
                point=pad_position(
                    footprint,
                    (placement.x_mm, placement.y_mm),
                    placement.rotation_deg,
                    pad_number,
                ),
                layers=layers,
            )
        membership[net.name] = tuple(pad_ids)
    return sites, membership


def route_context(
    electrical: ElectricalContext,
    placements: tuple[ProposedItem, ...],
    fab: FabMinimums,
) -> RouteContext:
    """Board region, net widths, pad obstacles and pad sites of one placement."""
    by_refdes = {item.item_id: item for item in placements}
    board = electrical.lane.board
    widths = {
        requirement.net_name: requirement.adopted_width_mm
        for requirement in derive_net_widths(electrical.lane, fab.track_width_mm)
    }
    sites, membership = _pad_sites(electrical, by_refdes)
    return RouteContext(
        region=electrical.context.region,
        clearance_mm=board.min_clearance_mm,
        pads=sites,
        net_pads=membership,
        widths_mm=widths,
        obstacles=_pad_rects(electrical, by_refdes),
        via_drill_mm=board.via_drill_mm,
        via_diameter_mm=board.via_diameter_mm,
        fab=fab,
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
    vias: tuple[RouteVia, ...] = (),
) -> tuple[Blockage, ...]:
    """Foreign pads, already legalized wires of the same layer, and foreign vias."""
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
    items.extend(
        Blockage(
            label=f"via of net {via.net!r}",
            limit_mm=context.clearance_mm + (width_mm + via.diameter_mm) / 2.0,
            rects=(Rect(via.point[0], via.point[1], via.point[0], via.point[1]),),
        )
        for via in vias
        if via.net != net
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


def resolve_endpoints(route: ProposedRoute, context: RouteContext) -> tuple[PadSite, PadSite]:
    """The two pads a proposed connection joins; a guess is never made.

    Pad references are required as soon as the net has more than two pads,
    because picking two of them would be a design decision the vision response
    is not allowed to make implicitly.
    """
    pad_ids = context.net_pads.get(route.net)
    if pad_ids is None:
        raise VisionProposalError(f"unknown net {route.net!r} (fail-closed)")
    if route.from_pad is None or route.to_pad is None:
        if len(pad_ids) != 2:
            raise VisionProposalError(
                f"net {route.net!r} has {len(pad_ids)} pads; from_pad and to_pad "
                "must be declared (fail-closed)"
            )
        first, second = sorted(pad_ids)
    else:
        first, second = route.from_pad, route.to_pad
    sites: list[PadSite] = []
    for pad_id in (first, second):
        if pad_id not in pad_ids:
            raise VisionProposalError(
                f"pad {pad_id!r} is not a pad of net {route.net!r} (fail-closed)"
            )
        site = context.pads.get(pad_id)
        if site is None:
            raise VisionProposalError(f"pad {pad_id!r} is not a unique pad (fail-closed)")
        sites.append(site)
    entry, exit_ = sites
    if route.segments[0].layer not in entry.layers:
        raise VisionProposalError(
            f"pad {entry.pad_id!r} is not on {route.segments[0].layer} (fail-closed)"
        )
    if route.segments[-1].layer not in exit_.layers:
        raise VisionProposalError(
            f"pad {exit_.pad_id!r} is not on {route.segments[-1].layer} (fail-closed)"
        )
    return entry, exit_


def check_via_geometry(context: RouteContext) -> None:
    """Declared via geometry against the fab profile; a shortfall stops the run."""
    fab = context.fab
    if context.via_drill_mm < fab.via_hole_mm - _TOLERANCE:
        raise VisionProposalError(
            f"declared via drill {context.via_drill_mm} mm is below the fab minimum "
            f"{fab.via_hole_mm} mm (fail-closed)"
        )
    if context.via_diameter_mm < fab.via_diameter_mm - _TOLERANCE:
        raise VisionProposalError(
            f"declared via diameter {context.via_diameter_mm} mm is below the fab minimum "
            f"{fab.via_diameter_mm} mm (fail-closed)"
        )
    annulus = context.via_diameter_mm - context.via_drill_mm
    if annulus < fab.via_diameter_margin_mm - _TOLERANCE:
        raise VisionProposalError(
            f"declared via annulus {round(annulus, _ROUND_DIGITS)} mm is below the fab "
            f"minimum {fab.via_diameter_margin_mm} mm (fail-closed)"
        )


def _legalize_via(
    point: Point,
    net: str,
    layers: tuple[str, str],
    context: RouteContext,
    profile: RelaxationProfile,
    routed: tuple[RouteCandidate, ...],
    vias: tuple[RouteVia, ...],
) -> RouteVia:
    """Snap one declared layer change onto a legal grid node on both layers."""
    diameter = context.via_diameter_mm
    region = _inset_region(context.region, diameter / 2.0)
    items = tuple(
        item
        for layer in layers
        for item in blockages(net, layer, diameter, context, routed, vias)
    )
    snapped = (
        _clamp(_snap(point[0], profile.grid_step_mm), region.x1, region.x2),
        _clamp(_snap(point[1], profile.grid_step_mm), region.y1, region.y2),
    )
    return RouteVia(
        net=net,
        point=_nudge(snapped, region, items, profile),
        drill_mm=round(context.via_drill_mm, _ROUND_DIGITS),
        diameter_mm=round(diameter, _ROUND_DIGITS),
    )


def _legalize_wire(
    net: str,
    layer: str,
    width_mm: float,
    entry: Point,
    exit_: Point,
    waypoints: tuple[Point, ...],
    context: RouteContext,
    profile: RelaxationProfile,
    items: tuple[Blockage, ...],
) -> RouteCandidate:
    """Pin one polyline between two fixed points and legalize every hop."""
    region = _inset_region(context.region, width_mm / 2.0)
    snapped: list[Point] = []
    for x_mm, y_mm in waypoints:
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

    points: list[Point] = [entry]
    repaired = 0
    for target in [*snapped, exit_]:
        if math.dist(points[-1], target) <= _TOLERANCE:
            continue
        hop = _hop(points[-1], target, region, items, profile)
        if len(hop) > 3:
            repaired += 1
        points.extend(hop[1:])
    collapsed = _collapse(tuple(points))
    if len(collapsed) < 2:
        raise VisionProposalError(f"net {net!r}: candidate has no length (fail-closed)")
    return RouteCandidate(
        net=net,
        layer=layer,
        width_mm=round(width_mm, _ROUND_DIGITS),
        points=tuple(collapsed),
        repaired_hops=repaired,
    )


def legalize_route(
    route: ProposedRoute,
    context: RouteContext,
    profile: RelaxationProfile,
    routed: tuple[RouteCandidate, ...] = (),
    vias: tuple[RouteVia, ...] = (),
) -> LegalizedRoute:
    """Pin the pads, place the declared vias, and legalize every segment."""
    entry, exit_ = resolve_endpoints(route, context)
    width = context.widths_mm.get(route.net)
    if width is None:
        raise VisionProposalError(f"net {route.net!r} has no declared width (fail-closed)")
    placed: list[RouteVia] = []
    if route.transitions:
        check_via_geometry(context)
        for index, transition in enumerate(route.transitions):
            placed.append(
                _legalize_via(
                    transition,
                    route.net,
                    (route.segments[index].layer, route.segments[index + 1].layer),
                    context,
                    profile,
                    routed,
                    vias,
                )
            )
    wires: list[RouteCandidate] = []
    for index, segment in enumerate(route.segments):
        start = entry.point if index == 0 else placed[index - 1].point
        end = exit_.point if index == len(route.segments) - 1 else placed[index].point
        items = blockages(route.net, segment.layer, width, context, routed, vias)
        wires.append(
            _legalize_wire(
                route.net,
                segment.layer,
                width,
                start,
                end,
                segment.waypoints,
                context,
                profile,
                items,
            )
        )
    return LegalizedRoute(
        net=route.net,
        from_pad=entry.pad_id,
        to_pad=exit_.pad_id,
        wires=tuple(wires),
        vias=tuple(placed),
    )


def check_route(
    candidate: RouteCandidate,
    context: RouteContext,
    routed: tuple[RouteCandidate, ...] = (),
    vias: tuple[RouteVia, ...] = (),
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
    items = blockages(
        candidate.net, candidate.layer, candidate.width_mm, context, routed, vias
    )
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
    vias: tuple[RouteVia, ...] = (),
) -> RouteMetrics:
    """Surrogate metrics of one candidate; not acceptance evidence."""
    clearance = check_route(candidate, context, routed, vias)
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


def connection_metrics(
    route: LegalizedRoute, wire_metrics: tuple[RouteMetrics, ...]
) -> ConnectionMetrics:
    """Aggregate the wire metrics of one connection; still non-authoritative."""
    return ConnectionMetrics(
        total_length_mm=round(sum(item.total_length_mm for item in wire_metrics), 6),
        segment_count=sum(item.segment_count for item in wire_metrics),
        direction_changes=sum(item.direction_changes for item in wire_metrics),
        repaired_hops=sum(item.repaired_hops for item in wire_metrics),
        via_count=len(route.vias),
        min_clearance_mm=round(min(item.min_clearance_mm for item in wire_metrics), 6),
    )


def _root(parent: dict[str, str], pad_id: str) -> str:
    while parent[pad_id] != pad_id:
        pad_id = parent[pad_id]
    return pad_id


def _check_connectivity(plans: tuple[RoutePlan, ...], context: RouteContext) -> None:
    """Every proposed net must end up electrically complete.

    A partially connected net would only surface as an unconnected DRC item much
    later, so an incomplete set of proposed connections stops the run here.
    """
    joined: dict[str, dict[str, str]] = {}
    for plan in plans:
        parent = joined.setdefault(plan.route.net, {})
        for pad_id in (plan.route.from_pad, plan.route.to_pad):
            parent.setdefault(pad_id, pad_id)
        parent[_root(parent, plan.route.from_pad)] = _root(parent, plan.route.to_pad)
    for net, parent in sorted(joined.items()):
        roots: set[str] = set()
        for pad_id in context.net_pads[net]:
            if pad_id not in parent:
                raise VisionProposalError(
                    f"net {net!r}: pad {pad_id!r} is left unconnected by the proposal "
                    "(fail-closed)"
                )
            roots.add(_root(parent, pad_id))
        if len(roots) > 1:
            raise VisionProposalError(
                f"net {net!r}: the proposed connections do not join all pads (fail-closed)"
            )


def legalize_proposal(
    proposal: VisionRouteProposal, context: RouteContext, profile: RelaxationProfile
) -> tuple[RoutePlan, ...]:
    """Legalize every proposed connection in a deterministic order."""
    if profile.arc_tracks:
        raise VisionProposalError(
            "arc tracks are not implemented by this candidate generator (fail-closed)"
        )
    plans: list[RoutePlan] = []
    for route in proposal.routes:
        routed = tuple(wire for plan in plans for wire in plan.route.wires)
        vias = tuple(via for plan in plans for via in plan.route.vias)
        legalized = legalize_route(route, context, profile, routed, vias)
        metrics = tuple(
            route_metrics(wire, context, routed, vias) for wire in legalized.wires
        )
        plans.append(
            RoutePlan(
                route=legalized,
                wire_metrics=metrics,
                metrics=connection_metrics(legalized, metrics),
            )
        )
    _check_connectivity(tuple(plans), context)
    return tuple(plans)


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


def fab_minimums(path: Path) -> FabMinimums:
    """Track and via minimums of the declared fab profile."""
    document = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(document, dict):
        raise VisionProposalError("fab profile must be a JSON object (fail-closed)")
    capabilities = mapping_field(cast(dict[str, object], document), "capabilities")

    def value(key: str) -> float:
        return float_field(mapping_field(capabilities, key), "value")

    return FabMinimums(
        track_width_mm=value("min_track_width"),
        via_hole_mm=value("min_via_hole"),
        via_diameter_mm=value("min_via_diameter"),
        via_diameter_margin_mm=value("via_diameter_margin"),
    )


def _wires_payload(plans: tuple[RoutePlan, ...]) -> list[dict[str, object]]:
    return [
        {
            "net": wire.net,
            "layer": wire.layer,
            "from_pad": plan.route.from_pad,
            "to_pad": plan.route.to_pad,
            "width_mm": wire.width_mm,
            "points": [[point[0], point[1]] for point in wire.points],
            "surrogate_metrics": {
                "total_length_mm": metrics.total_length_mm,
                "segment_count": metrics.segment_count,
                "direction_changes": metrics.direction_changes,
                "repaired_hops": metrics.repaired_hops,
                "min_clearance_mm": metrics.min_clearance_mm,
            },
        }
        for plan in plans
        for wire, metrics in zip(plan.route.wires, plan.wire_metrics, strict=True)
    ]


def _vias_payload(plans: tuple[RoutePlan, ...]) -> list[dict[str, object]]:
    return [
        {
            "net": via.net,
            "x_mm": via.point[0],
            "y_mm": via.point[1],
            "drill_mm": via.drill_mm,
            "diameter_mm": via.diameter_mm,
        }
        for plan in plans
        for via in plan.route.vias
    ]


def _connections_payload(plans: tuple[RoutePlan, ...]) -> list[dict[str, object]]:
    return [
        {
            "net": plan.route.net,
            "from_pad": plan.route.from_pad,
            "to_pad": plan.route.to_pad,
            "wire_count": len(plan.route.wires),
            "via_count": plan.metrics.via_count,
            "surrogate_metrics": {
                "total_length_mm": plan.metrics.total_length_mm,
                "segment_count": plan.metrics.segment_count,
                "direction_changes": plan.metrics.direction_changes,
                "repaired_hops": plan.metrics.repaired_hops,
                "min_clearance_mm": plan.metrics.min_clearance_mm,
            },
        }
        for plan in plans
    ]


def build_candidate_report(
    *,
    plans: tuple[RoutePlan, ...],
    lane: ElectricalLane,
    provenance: dict[str, object],
) -> dict[str, object]:
    """Assemble the non-authoritative routing candidate report."""
    ranked = sorted(plans, key=lambda plan: (plan.metrics.rank_key, plan.route.label))
    return {
        "artifact_kind": CANDIDATE_ARTIFACT_KIND,
        "pass_evidence": False,
        "lane": "electrical",
        "proposed_nets": sorted({plan.route.net for plan in plans}),
        "candidates": {"vision": _wires_payload(plans), "vias": _vias_payload(plans)},
        "connections": _connections_payload(plans),
        "ranking": [plan.route.label for plan in ranked],
        "board": {
            "min_clearance_mm": lane.board.min_clearance_mm,
            "min_track_mm": lane.board.min_track_mm,
            "via_drill_mm": lane.board.via_drill_mm,
            "via_diameter_mm": lane.board.via_diameter_mm,
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
    context = route_context(electrical, placements, fab_minimums(args.fab_profile))
    plans = legalize_proposal(proposal, context, relaxation_profile)

    report = build_candidate_report(
        plans=plans,
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
