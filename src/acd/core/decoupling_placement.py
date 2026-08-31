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
from dataclasses import dataclass, replace
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
    placement_rotation_deg: float
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
    best_distance_mm: float | None = None
    best_placement_x_mm: float | None = None
    best_placement_y_mm: float | None = None
    best_rotation_deg: float | None = None
    distance_deficit_mm: float | None = None
    clearance_deficit_mm: float | None = None
    blocking_refdes: tuple[str, ...] = ()
    explored_dimensions: tuple[dict[str, object], ...] = ()
    changeable_dimensions: tuple[dict[str, object], ...] = ()


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
                    "placement_rotation_deg": item.placement_rotation_deg,
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
                    "best_distance_mm": item.best_distance_mm,
                    "best_placement_x_mm": item.best_placement_x_mm,
                    "best_placement_y_mm": item.best_placement_y_mm,
                    "best_rotation_deg": item.best_rotation_deg,
                    "distance_deficit_mm": item.distance_deficit_mm,
                    "clearance_deficit_mm": item.clearance_deficit_mm,
                    "blocking_refdes": item.blocking_refdes,
                    "explored_dimensions": item.explored_dimensions,
                    "changeable_dimensions": item.changeable_dimensions,
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
    rotation_deg: float | None = None,
) -> tuple[float, float, float, float] | None:
    shape = library.load(
        component.library.footprint,
        resolve_fixture_path(component.library.footprint_file, fixture_dir),
        component.library.footprint_sha256,
    )
    box = shape.courtyard_bbox_mm or shape.body_bbox_mm
    if box is None:
        return None
    placed_x, placed_y, declared_rotation = _placement(graph, component.node_id)
    return _courtyard_corners(
        box,
        placed_x if x_mm is None else x_mm,
        placed_y if y_mm is None else y_mm,
        declared_rotation if rotation_deg is None else rotation_deg,
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


def _clearance_deficit(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    clearance_mm: float,
) -> float:
    """Return the missing clearance depth, or zero when boxes are separated."""
    if not _boxes_overlap(first, second, clearance_mm):
        return 0.0
    x_overlap = min(first[2], second[2]) - max(first[0], second[0])
    y_overlap = min(first[3], second[3]) - max(first[1], second[1])
    return max(0.0, min(x_overlap, y_overlap) + clearance_mm)


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
    *,
    rotation_deg: float | None = None,
) -> tuple[tuple[str, tuple[float, float]], ...]:
    positions = component_net_pad_positions(
        graph, lane, component, net_id, fixture_dir, library
    )
    origin_x, origin_y, declared_rotation = _placement(graph, component.node_id)
    rotation_delta = (
        0.0 if rotation_deg is None else rotation_deg - declared_rotation
    )
    return tuple(
        (
            pad,
            rotate_point(
                position[0] - origin_x,
                position[1] - origin_y,
                rotation_delta,
            ),
        )
        for pad, position in positions
    )


@dataclass
class _CandidateMetrics:
    best_distance_mm: float = math.inf
    best_placement_x_mm: float | None = None
    best_placement_y_mm: float | None = None
    best_rotation_deg: float | None = None
    distance_candidate_count: int = 0
    clearance_deficit_mm: float | None = None
    blocking_refdes: tuple[str, ...] = ()
    origin_candidates_evaluated: int = 0


@dataclass(frozen=True)
class _PassResult:
    placements: tuple[DecouplingPlacement, ...]
    deficiencies: tuple[DecouplingPlacementDeficiency, ...]


def _rotation_unavailable(graph: DesignGraph, component: ComponentView) -> bool:
    attrs = graph.node_by_id(component.node_id).attrs
    if attrs.get("cpl_rotation_polarized") is True:
        return True
    return any(
        key.startswith("cpl_rotation_")
        and key != "cpl_rotation_polarized"
        and value not in (None, "", [], {})
        for key, value in attrs.items()
    )


def _explored_dimensions(
    *,
    origin_candidates: int,
    rotation_available: bool,
    rotation_candidates: int,
    placement_passes: int,
) -> tuple[dict[str, object], ...]:
    return (
        {
            "dimension": "origin_radius",
            "status": "exhausted",
            "reason": "all declared radius fractions and compass directions were evaluated",
            "candidates_evaluated": origin_candidates,
        },
        {
            "dimension": "rotation",
            "status": "exhausted" if rotation_available else "unavailable",
            "reason": (
                "declared rotation evidence fixes this component orientation"
                if not rotation_available
                else "all allowed alternate rotations were evaluated"
            ),
            "candidates_evaluated": rotation_candidates,
        },
        {
            "dimension": "placement_order",
            "status": "exhausted",
            "reason": "deterministic greedy placement-order passes were exhausted",
            "candidates_evaluated": placement_passes,
        },
        {
            "dimension": "side",
            "status": "unavailable",
            "reason": "electrical placement declarations do not expose a side or layer dimension",
            "candidates_evaluated": 0,
        },
    )


def _changeable_dimensions(
    *,
    distance_deficit_mm: float | None,
    clearance_deficit_mm: float | None,
) -> tuple[dict[str, object], ...]:
    return (
        {
            "dimension": "target_placement",
            "status": "changeable",
            "reason": "change the declared target component placement and revalidate the graph",
        },
        {
            "dimension": "surrounding_placement",
            "status": "changeable",
            "reason": "change surrounding component placements and revalidate courtyard clearance",
        },
        {
            "dimension": "footprint_selection",
            "status": "changeable",
            "reason": "select a footprint with compatible pad and courtyard geometry",
        },
        {
            "dimension": "declared_clearance",
            "status": "changeable",
            "reason": "change the declaration-side clearance input; the solver does not relax it",
            "clearance_deficit_mm": clearance_deficit_mm,
            "distance_deficit_mm": distance_deficit_mm,
        },
    )


def _evaluate_candidates(
    *,
    graph: DesignGraph,
    capacitor: ComponentView,
    target: ComponentView,
    net_id: str,
    limit: float,
    fixture_dir: Path,
    library: FootprintLibrary,
    target_positions: tuple[tuple[str, tuple[float, float]], ...],
    occupied: list[tuple[str, tuple[float, float, float, float]]],
    origins: tuple[tuple[float, float], ...],
    offsets: tuple[tuple[str, tuple[float, float]], ...],
    rotation: float,
    metrics: _CandidateMetrics,
) -> DecouplingPlacement | None:
    for origin in origins:
        metrics.origin_candidates_evaluated += 1
        distance = _minimum_distance(offsets, target_positions, origin)
        if distance < metrics.best_distance_mm:
            metrics.best_distance_mm = distance
            metrics.best_placement_x_mm = origin[0]
            metrics.best_placement_y_mm = origin[1]
            metrics.best_rotation_deg = rotation
        if distance > limit:
            continue
        metrics.distance_candidate_count += 1
        candidate_box = _component_box(
            graph,
            capacitor,
            fixture_dir,
            library,
            x_mm=origin[0],
            y_mm=origin[1],
            rotation_deg=rotation,
        )
        blockers: list[tuple[str, float]] = []
        if candidate_box is not None:
            blockers = [
                (
                    refdes,
                    _clearance_deficit(candidate_box, other, COURTYARD_CLEARANCE_MM),
                )
                for refdes, other in occupied
                if refdes != capacitor.refdes
                and _boxes_overlap(candidate_box, other, COURTYARD_CLEARANCE_MM)
            ]
        if blockers:
            deficit = max(item[1] for item in blockers)
            if (
                metrics.clearance_deficit_mm is None
                or deficit < metrics.clearance_deficit_mm
            ):
                metrics.clearance_deficit_mm = deficit
                metrics.blocking_refdes = tuple(
                    sorted(item[0] for item in blockers)
                )
            continue
        return DecouplingPlacement(
            node_id=capacitor.node_id,
            refdes=capacitor.refdes,
            target_refdes=target.refdes,
            net_id=net_id,
            limit_mm=limit,
            distance_mm=distance,
            placement_x_mm=origin[0],
            placement_y_mm=origin[1],
            placement_rotation_deg=rotation,
            changed=True,
        )
    return None


def _solve_pass(
    graph: DesignGraph,
    baseline_graph: DesignGraph,
    fixture_dir: Path,
    order: tuple[ComponentView, ...],
    placement_passes: int,
) -> _PassResult:
    lane = extract_electrical_lane(graph)
    library = FootprintLibrary()
    placements: list[DecouplingPlacement] = []
    deficiencies: list[DecouplingPlacementDeficiency] = []
    occupied: list[tuple[str, tuple[float, float, float, float]]] = []
    for component in sorted(lane.components, key=lambda item: item.refdes):
        box = _component_box(graph, component, fixture_dir, library)
        if box is not None:
            occupied.append((component.refdes, box))

    for capacitor in order:
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
                    explored_dimensions=_explored_dimensions(
                        origin_candidates=0,
                        rotation_available=False,
                        rotation_candidates=0,
                        placement_passes=placement_passes,
                    ),
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
                    explored_dimensions=_explored_dimensions(
                        origin_candidates=0,
                        rotation_available=False,
                        rotation_candidates=0,
                        placement_passes=placement_passes,
                    ),
                )
            )
            continue
        limit = decoupling_distance_limit(capacitance)
        try:
            target_positions = component_net_pad_positions(
                graph, lane, target, net_id, fixture_dir, library
            )
            declared_offsets = _pad_offsets(
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
                    explored_dimensions=_explored_dimensions(
                        origin_candidates=0,
                        rotation_available=False,
                        rotation_candidates=0,
                        placement_passes=placement_passes,
                    ),
                )
            )
            continue

        current_x, current_y, declared_rotation = _placement(
            graph, capacitor.node_id
        )
        current = _minimum_distance(
            declared_offsets, target_positions, (current_x, current_y)
        )
        baseline_x, baseline_y, baseline_rotation = _placement(
            baseline_graph, capacitor.node_id
        )
        changed_from_baseline = (
            (current_x, current_y, declared_rotation)
            != (baseline_x, baseline_y, baseline_rotation)
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
                    placement_rotation_deg=declared_rotation,
                    changed=changed_from_baseline,
                )
            )
            continue

        metrics = _CandidateMetrics(
            best_distance_mm=current,
            best_placement_x_mm=current_x,
            best_placement_y_mm=current_y,
            best_rotation_deg=declared_rotation,
        )
        rotation_unavailable = _rotation_unavailable(graph, capacitor)

        accepted = _evaluate_candidates(
            graph=graph,
            capacitor=capacitor,
            target=target,
            net_id=net_id,
            limit=limit,
            fixture_dir=fixture_dir,
            library=library,
            target_positions=target_positions,
            occupied=occupied,
            origins=_candidate_origins(target_positions, declared_offsets, limit),
            offsets=declared_offsets,
            rotation=declared_rotation,
            metrics=metrics,
        )
        rotation_candidates = 0
        if accepted is None and not rotation_unavailable:
            for rotation in (90.0, 180.0, 270.0):
                offsets = _pad_offsets(
                    graph,
                    lane,
                    capacitor,
                    net_id,
                    fixture_dir,
                    library,
                    rotation_deg=rotation,
                )
                origins = _candidate_origins(target_positions, offsets, limit)
                before = metrics.origin_candidates_evaluated
                accepted = _evaluate_candidates(
                    graph=graph,
                    capacitor=capacitor,
                    target=target,
                    net_id=net_id,
                    limit=limit,
                    fixture_dir=fixture_dir,
                    library=library,
                    target_positions=target_positions,
                    occupied=occupied,
                    origins=origins,
                    offsets=offsets,
                    rotation=rotation,
                    metrics=metrics,
                )
                rotation_candidates += metrics.origin_candidates_evaluated - before
                if accepted is not None:
                    break
        if accepted is None:
            distance_deficit = (
                max(0.0, metrics.best_distance_mm - limit)
                if metrics.distance_candidate_count == 0
                else 0.0
            )
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
                    best_distance_mm=metrics.best_distance_mm,
                    best_placement_x_mm=metrics.best_placement_x_mm,
                    best_placement_y_mm=metrics.best_placement_y_mm,
                    best_rotation_deg=metrics.best_rotation_deg,
                    distance_deficit_mm=distance_deficit,
                    clearance_deficit_mm=(
                        metrics.clearance_deficit_mm
                        if metrics.distance_candidate_count
                        else None
                    ),
                    blocking_refdes=metrics.blocking_refdes,
                    explored_dimensions=_explored_dimensions(
                        origin_candidates=metrics.origin_candidates_evaluated,
                        rotation_available=not rotation_unavailable,
                        rotation_candidates=rotation_candidates,
                        placement_passes=placement_passes,
                    ),
                    changeable_dimensions=_changeable_dimensions(
                        distance_deficit_mm=distance_deficit,
                        clearance_deficit_mm=metrics.clearance_deficit_mm,
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
            rotation_deg=accepted.placement_rotation_deg,
        )
        if moved_box is not None:
            occupied.append((capacitor.refdes, moved_box))
    return _PassResult(tuple(placements), tuple(deficiencies))


def solve_decoupling_placements(
    graph: DesignGraph, fixture_dir: Path
) -> DecouplingPlacementReport:
    """Return placements after deterministic origin, rotation, and order search."""
    baseline_graph = graph
    working_graph = graph
    previous_deficient: set[str] | None = None
    final_result = _PassResult((), ())
    passes = 0
    for pass_number in range(1, 5):
        lane = extract_electrical_lane(working_graph)
        components = sorted(lane.components, key=lambda item: item.refdes)
        if previous_deficient is None:
            order = tuple(components)
        else:
            prior_deficient = previous_deficient
            order = tuple(
                sorted(
                    components,
                    key=lambda item: (
                        item.refdes not in prior_deficient,
                        item.refdes,
                    ),
                )
            )
        final_result = _solve_pass(
            working_graph,
            baseline_graph,
            fixture_dir,
            order,
            pass_number,
        )
        passes = pass_number
        deficient_refs = {item.refdes for item in final_result.deficiencies}
        if not deficient_refs:
            break
        if previous_deficient is not None and deficient_refs == previous_deficient:
            break
        previous_deficient = deficient_refs
        working_graph = apply_decoupling_placements(
            working_graph,
            DecouplingPlacementReport(
                status="adjusted",
                placements=final_result.placements,
                deficiencies=final_result.deficiencies,
            ),
        )

    deficiencies = tuple(
        replace(
            item,
            explored_dimensions=tuple(
                {
                    **dimension,
                    "candidates_evaluated": (
                        passes
                        if dimension["dimension"] == "placement_order"
                        else dimension["candidates_evaluated"]
                    ),
                }
                for dimension in item.explored_dimensions
            ),
        )
        for item in final_result.deficiencies
    )
    status: Literal["satisfied", "adjusted", "deficient"]
    if deficiencies:
        status = "deficient"
    elif any(item.changed for item in final_result.placements):
        status = "adjusted"
    else:
        status = "satisfied"
    return DecouplingPlacementReport(
        status=status,
        placements=final_result.placements,
        deficiencies=deficiencies,
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
                        "placement_rotation_deg": placement.placement_rotation_deg,
                        "placement_source": PLACEMENT_SOURCE,
                        "placement_source_ref": (
                            f"decoupling_target={placement.target_refdes};"
                            f"limit_mm={placement.limit_mm};"
                            f"rotation_deg={placement.placement_rotation_deg}"
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
