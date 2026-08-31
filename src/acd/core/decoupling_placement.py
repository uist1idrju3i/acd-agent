"""Deterministic decoupling-aware placement normalization.

Fixture generation places declared decoupling capacitors close enough to their
declared bypass targets to satisfy the pinned distance limits of the
``power_decoupling`` predicate. The solver only moves capacitors that violate
the limit, so a design input that already satisfies the limits keeps its
declared placement and its normalized graph hash. A capacitor that cannot be
placed inside the limit is reported as a deficiency; this module never relaxes a
limit and never turns an unsatisfied placement into a pass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from acd.adapters.kicad.library import FootprintLibrary
from acd.adapters.kicad.placement import rotate_point
from acd.core.design_predicates import (
    component_net_pad_positions,
    decoupling_distance_limit,
    parse_capacitance_uf,
    resolve_decoupling_pair,
    resolve_fixture_path,
)
from acd.core.electrical import ComponentView, ElectricalLane, extract_electrical_lane
from acd.schema import DesignGraph
from acd.schema.design_graph import GraphNode

# Placement source recorded for solver-adjusted capacitors. The value is
# classified as rationale-exempt provenance metadata.
PLACEMENT_SOURCE: Final = "acd.core.decoupling_placement"

# Search geometry. Candidate origins are generated on compass directions around
# each target pad at a fraction of the limit, so the accepted placement keeps
# margin against the limit instead of sitting exactly on it.
_RADIUS_FRACTIONS: Final[tuple[float, ...]] = (0.4, 0.6, 0.8)
_DIRECTIONS: Final[tuple[tuple[float, float], ...]] = (
    (1.0, 0.0),
    (0.0, 1.0),
    (-1.0, 0.0),
    (0.0, -1.0),
    (1.0, 1.0),
    (1.0, -1.0),
    (-1.0, 1.0),
    (-1.0, -1.0),
)

# Minimum gap kept between the moved capacitor courtyard and every other
# component courtyard. The board pipeline owns the authoritative clearance
# checks; this value only keeps generated candidates physically plausible.
COURTYARD_CLEARANCE_MM: Final = 0.2

# Rounding applied to generated coordinates so that repeated runs of the solver
# emit byte-identical graphs.
_COORDINATE_DIGITS: Final = 3


class DecouplingPlacementError(ValueError):
    """Raised when decoupling placement inputs cannot be resolved."""


@dataclass(frozen=True)
class DecouplingPlacement:
    """One deterministic placement decision for a declared decoupling pair."""

    node_id: str
    refdes: str
    target_refdes: str
    net_id: str
    limit_mm: float
    distance_mm: float
    placement_x_mm: float
    placement_y_mm: float
    changed: bool


@dataclass(frozen=True)
class DecouplingPlacementDeficiency:
    """One declared decoupling pair that placement could not satisfy."""

    refdes: str
    target_refdes: str | None
    net_id: str | None
    limit_mm: float | None
    distance_mm: float | None
    reason: str


@dataclass(frozen=True)
class DecouplingPlacementReport:
    """Non-authoritative result of deterministic decoupling placement."""

    status: Literal["satisfied", "adjusted", "deficient"]
    placements: tuple[DecouplingPlacement, ...]
    deficiencies: tuple[DecouplingPlacementDeficiency, ...]

    def as_payload(self) -> dict[str, object]:
        """Return the machine-readable L3 report payload."""
        return {
            "artifact_kind": "decoupling_placement_report",
            "pass_evidence": False,
            "record_class": "L3",
            "status": self.status,
            "placements": [
                {
                    "node_id": item.node_id,
                    "refdes": item.refdes,
                    "target_refdes": item.target_refdes,
                    "net_id": item.net_id,
                    "limit_mm": item.limit_mm,
                    "distance_mm": item.distance_mm,
                    "placement_x_mm": item.placement_x_mm,
                    "placement_y_mm": item.placement_y_mm,
                    "changed": item.changed,
                }
                for item in self.placements
            ],
            "deficiencies": [
                {
                    "refdes": item.refdes,
                    "target_refdes": item.target_refdes,
                    "net_id": item.net_id,
                    "limit_mm": item.limit_mm,
                    "distance_mm": item.distance_mm,
                    "reason": item.reason,
                }
                for item in self.deficiencies
            ],
        }


def _placement(graph: DesignGraph, node_id: str) -> tuple[float, float, float]:
    node = graph.node_by_id(node_id)
    values: list[float] = []
    for attr in ("placement_x_mm", "placement_y_mm", "placement_rotation_deg"):
        value = node.attrs.get(attr)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DecouplingPlacementError(f"{node_id}: {attr} is missing")
        values.append(float(value))
    return values[0], values[1], values[2]


def _courtyard_corners(
    box: tuple[float, float, float, float],
    x_mm: float,
    y_mm: float,
    rotation_deg: float,
) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = box
    corners = [
        rotate_point(x, y, rotation_deg)
        for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
    ]
    xs = [x_mm + corner[0] for corner in corners]
    ys = [y_mm + corner[1] for corner in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _component_box(
    graph: DesignGraph,
    component: ComponentView,
    fixture_dir: Path,
    library: FootprintLibrary,
    *,
    x_mm: float | None = None,
    y_mm: float | None = None,
) -> tuple[float, float, float, float] | None:
    shape = library.load(
        component.library.footprint,
        resolve_fixture_path(component.library.footprint_file, fixture_dir),
        component.library.footprint_sha256,
    )
    box = shape.courtyard_bbox_mm or shape.body_bbox_mm
    if box is None:
        return None
    placed_x, placed_y, rotation = _placement(graph, component.node_id)
    return _courtyard_corners(
        box,
        placed_x if x_mm is None else x_mm,
        placed_y if y_mm is None else y_mm,
        rotation,
    )


def _boxes_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    clearance_mm: float,
) -> bool:
    return (
        first[0] - clearance_mm <= second[2]
        and second[0] - clearance_mm <= first[2]
        and first[1] - clearance_mm <= second[3]
        and second[1] - clearance_mm <= first[3]
    )


def _minimum_distance(
    capacitor_offsets: tuple[tuple[str, tuple[float, float]], ...],
    target_positions: tuple[tuple[str, tuple[float, float]], ...],
    origin: tuple[float, float],
) -> float:
    return min(
        math.dist(
            (origin[0] + offset[0], origin[1] + offset[1]),
            target_position,
        )
        for _, offset in capacitor_offsets
        for _, target_position in target_positions
    )


def _round(value: float) -> float:
    return round(value, _COORDINATE_DIGITS)


def _candidate_origins(
    target_positions: tuple[tuple[str, tuple[float, float]], ...],
    capacitor_offsets: tuple[tuple[str, tuple[float, float]], ...],
    limit_mm: float,
) -> tuple[tuple[float, float], ...]:
    origins: list[tuple[float, float]] = []
    for fraction in _RADIUS_FRACTIONS:
        radius = limit_mm * fraction
        for _, target_position in target_positions:
            for direction_x, direction_y in _DIRECTIONS:
                norm = math.hypot(direction_x, direction_y)
                offset_x = radius * direction_x / norm
                offset_y = radius * direction_y / norm
                for _, pad_offset in capacitor_offsets:
                    origins.append(
                        (
                            _round(target_position[0] + offset_x - pad_offset[0]),
                            _round(target_position[1] + offset_y - pad_offset[1]),
                        )
                    )
    seen: set[tuple[float, float]] = set()
    unique: list[tuple[float, float]] = []
    for origin in origins:
        if origin in seen:
            continue
        seen.add(origin)
        unique.append(origin)
    return tuple(unique)


def _pad_offsets(
    graph: DesignGraph,
    lane: ElectricalLane,
    component: ComponentView,
    net_id: str,
    fixture_dir: Path,
    library: FootprintLibrary,
) -> tuple[tuple[str, tuple[float, float]], ...]:
    positions = component_net_pad_positions(
        graph, lane, component, net_id, fixture_dir, library
    )
    origin_x, origin_y, _ = _placement(graph, component.node_id)
    return tuple(
        (pad, (position[0] - origin_x, position[1] - origin_y))
        for pad, position in positions
    )


def solve_decoupling_placements(
    graph: DesignGraph, fixture_dir: Path
) -> DecouplingPlacementReport:
    """Return placements that satisfy the declared decoupling distance limits."""
    lane = extract_electrical_lane(graph)
    library = FootprintLibrary()
    placements: list[DecouplingPlacement] = []
    deficiencies: list[DecouplingPlacementDeficiency] = []
    occupied: list[tuple[str, tuple[float, float, float, float]]] = []
    for component in sorted(lane.components, key=lambda item: item.refdes):
        box = _component_box(graph, component, fixture_dir, library)
        if box is not None:
            occupied.append((component.refdes, box))
    for capacitor in sorted(lane.components, key=lambda item: item.refdes):
        if capacitor.decoupling_target is None:
            continue
        pair = resolve_decoupling_pair(graph, lane, capacitor)
        if pair is None:
            deficiencies.append(
                DecouplingPlacementDeficiency(
                    refdes=capacitor.refdes,
                    target_refdes=capacitor.decoupling_target,
                    net_id=None,
                    limit_mm=None,
                    distance_mm=None,
                    reason="declared decoupling target or shared power net is unresolved",
                )
            )
            continue
        target, net_id = pair
        capacitance = parse_capacitance_uf(capacitor.value)
        if capacitance is None:
            deficiencies.append(
                DecouplingPlacementDeficiency(
                    refdes=capacitor.refdes,
                    target_refdes=target.refdes,
                    net_id=net_id,
                    limit_mm=None,
                    distance_mm=None,
                    reason="declared capacitance is unparseable",
                )
            )
            continue
        limit = decoupling_distance_limit(capacitance)
        try:
            target_positions = component_net_pad_positions(
                graph, lane, target, net_id, fixture_dir, library
            )
            capacitor_offsets = _pad_offsets(
                graph, lane, capacitor, net_id, fixture_dir, library
            )
        except (DecouplingPlacementError, OSError, StopIteration, ValueError) as exc:
            deficiencies.append(
                DecouplingPlacementDeficiency(
                    refdes=capacitor.refdes,
                    target_refdes=target.refdes,
                    net_id=net_id,
                    limit_mm=limit,
                    distance_mm=None,
                    reason=f"pad geometry is unresolved: {exc}",
                )
            )
            continue
        current_x, current_y, _ = _placement(graph, capacitor.node_id)
        current = _minimum_distance(
            capacitor_offsets, target_positions, (current_x, current_y)
        )
        if current <= limit:
            placements.append(
                DecouplingPlacement(
                    node_id=capacitor.node_id,
                    refdes=capacitor.refdes,
                    target_refdes=target.refdes,
                    net_id=net_id,
                    limit_mm=limit,
                    distance_mm=current,
                    placement_x_mm=current_x,
                    placement_y_mm=current_y,
                    changed=False,
                )
            )
            continue
        accepted: DecouplingPlacement | None = None
        for origin in _candidate_origins(target_positions, capacitor_offsets, limit):
            distance = _minimum_distance(capacitor_offsets, target_positions, origin)
            if distance > limit:
                continue
            candidate_box = _component_box(
                graph,
                capacitor,
                fixture_dir,
                library,
                x_mm=origin[0],
                y_mm=origin[1],
            )
            if candidate_box is not None and any(
                _boxes_overlap(candidate_box, other, COURTYARD_CLEARANCE_MM)
                for refdes, other in occupied
                if refdes != capacitor.refdes
            ):
                continue
            accepted = DecouplingPlacement(
                node_id=capacitor.node_id,
                refdes=capacitor.refdes,
                target_refdes=target.refdes,
                net_id=net_id,
                limit_mm=limit,
                distance_mm=distance,
                placement_x_mm=origin[0],
                placement_y_mm=origin[1],
                changed=True,
            )
            break
        if accepted is None:
            deficiencies.append(
                DecouplingPlacementDeficiency(
                    refdes=capacitor.refdes,
                    target_refdes=target.refdes,
                    net_id=net_id,
                    limit_mm=limit,
                    distance_mm=current,
                    reason=(
                        "no candidate placement satisfies the declared decoupling "
                        "distance limit without overlapping another courtyard"
                    ),
                )
            )
            continue
        placements.append(accepted)
        occupied = [item for item in occupied if item[0] != capacitor.refdes]
        moved_box = _component_box(
            graph,
            capacitor,
            fixture_dir,
            library,
            x_mm=accepted.placement_x_mm,
            y_mm=accepted.placement_y_mm,
        )
        if moved_box is not None:
            occupied.append((capacitor.refdes, moved_box))
    status: Literal["satisfied", "adjusted", "deficient"]
    if deficiencies:
        status = "deficient"
    elif any(item.changed for item in placements):
        status = "adjusted"
    else:
        status = "satisfied"
    return DecouplingPlacementReport(
        status=status,
        placements=tuple(placements),
        deficiencies=tuple(deficiencies),
    )


def apply_decoupling_placements(
    graph: DesignGraph, report: DecouplingPlacementReport
) -> DesignGraph:
    """Return a graph with the solver's changed placements applied."""
    changed = {item.node_id: item for item in report.placements if item.changed}
    if not changed:
        return graph
    nodes: list[GraphNode] = []
    for node in graph.nodes:
        placement = changed.get(node.id)
        if placement is None:
            nodes.append(node)
            continue
        nodes.append(
            node.model_copy(
                update={
                    "attrs": {
                        **node.attrs,
                        "placement_x_mm": placement.placement_x_mm,
                        "placement_y_mm": placement.placement_y_mm,
                        "placement_source": PLACEMENT_SOURCE,
                        "placement_source_ref": (
                            f"decoupling_target={placement.target_refdes};"
                            f"limit_mm={placement.limit_mm}"
                        ),
                    }
                }
            )
        )
    return graph.model_copy(update={"nodes": nodes})


__all__ = [
    "COURTYARD_CLEARANCE_MM",
    "PLACEMENT_SOURCE",
    "DecouplingPlacement",
    "DecouplingPlacementDeficiency",
    "DecouplingPlacementError",
    "DecouplingPlacementReport",
    "apply_decoupling_placements",
    "solve_decoupling_placements",
]
