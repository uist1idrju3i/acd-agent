# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@3153a012e008621e8f30711ed54cddf97f6b21ca",
# ]
# ///
"""Accept vision-derived placement proposals as search input (skill asset).

A vision response is an observation, never a verdict and never Evidence. This
script turns the numeric part of such a response into a placement candidate:
it validates the declared provenance, snaps positions and rotations to what the
versioned relaxation profile permits, legalizes the geometry deterministically
against the lane region and keepouts, and ranks the result against the
deterministic baseline search.

The free-text part of a vision response is never interpreted here. Only
coordinates, rotations, and provenance cross this boundary, so text rendered
inside an image cannot become a command. The proposal, its ranking, and its
surrogate metrics stay non-authoritative: acceptance is decided by the ACD
projections and the deterministic gates (ERC/DRC, independent reload) after the
candidate has been written into the design input files.

The same legalization works for both lanes: the electrical lane supplies
footprint geometry and board keepouts, the mechanical lane supplies the
enclosure interior and component bodies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from acd.adapters.kicad.board import board_keepouts, load_board_footprints
from acd.adapters.kicad.library import FootprintLibrary
from acd.adapters.kicad.placement import MARGIN_MM, Placement, Rect, pad_bbox
from acd.core.board_model import FootprintShape
from acd.core.electrical import ElectricalLane, extract_electrical_lane
from acd.core.fab import load_fab_profile
from acd.core.mechanical import extract_mechanical_lane
from acd.schema.design_graph import DesignGraph
from placement_score import PlacementScore, score_placement
from placement_search import compute_placements

PROPOSAL_ARTIFACT_KIND = "vision_placement_proposal"
CANDIDATE_ARTIFACT_KIND = "vision_placement_candidates"
SKILL_NAME = "acd-placement-search"
VISION_TOOL_NAME = "inspect_image_with_vision"
DEFAULT_ROTATION_STEP_DEG = 90.0
_TOLERANCE = 1e-9
_ROUND_DIGITS = 4

Lane = Literal["electrical", "mechanical"]
_LANES: tuple[Lane, ...] = ("electrical", "mechanical")


class VisionProposalError(ValueError):
    """Raised when a vision proposal cannot be accepted (fail-closed)."""


@dataclass(frozen=True)
class VisionObservationRef:
    """Provenance of the observation a proposal was derived from."""

    tool_name: str
    profile_name: str
    model: str
    projection_id: str
    image_hash: str
    response_sha256: str


@dataclass(frozen=True)
class ProposedItem:
    item_id: str
    x_mm: float
    y_mm: float
    rotation_deg: float


@dataclass(frozen=True)
class VisionProposal:
    lane: Lane
    observation: VisionObservationRef
    items: tuple[ProposedItem, ...]


@dataclass(frozen=True)
class RelaxationProfile:
    """Versioned declaration of the permitted placement freedom."""

    profile_id: str
    grid_step_mm: float
    max_shift_mm: float
    rotation_step_deg: float
    allowed_rotations_deg: tuple[float, ...]
    arc_tracks: bool
    off_grid_angles: bool


@dataclass(frozen=True)
class LegalizationContext:
    """Lane-neutral geometry the legalizer needs.

    ``region`` is the area items must stay inside, ``extents`` the local
    bounding box of every item at rotation 0, and ``keepouts`` the areas no item
    may overlap.
    """

    lane: Lane
    region: Rect
    extents: dict[str, tuple[float, float, float, float]]
    keepouts: tuple[Rect, ...]


@dataclass(frozen=True)
class LegalizationMetrics:
    """Surrogate metrics of one legalization; never a pass verdict."""

    max_shift_mm: float
    total_shift_mm: float
    rotation_changes: int
    min_item_gap_mm: float
    min_region_gap_mm: float

    @property
    def rank_key(self) -> tuple[float, float, float, int]:
        """Deterministic sort key; lower is better."""
        return (
            round(self.max_shift_mm, 6),
            round(self.total_shift_mm, 6),
            -round(self.min_item_gap_mm, 6),
            self.rotation_changes,
        )


def string_field(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise VisionProposalError(f"{key} must be a non-empty string (fail-closed)")
    return value


def mapping_field(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise VisionProposalError(f"{key} must be an object (fail-closed)")
    return cast(dict[str, object], value)


def float_field(payload: dict[str, object], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise VisionProposalError(f"{key} must be a number (fail-closed)")
    number = float(value)
    if not math.isfinite(number):
        raise VisionProposalError(f"{key} must be finite (fail-closed)")
    return number


def bool_field(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise VisionProposalError(f"{key} must be a boolean (fail-closed)")
    return value


def sha256_field(payload: dict[str, object], key: str) -> str:
    value = string_field(payload, key)
    if not value.startswith("sha256:") or len(value) != len("sha256:") + 64:
        raise VisionProposalError(f"{key} must be a sha256: digest (fail-closed)")
    if any(char not in "0123456789abcdef" for char in value.removeprefix("sha256:")):
        raise VisionProposalError(f"{key} must be a lowercase hex digest (fail-closed)")
    return value


def sha256_of_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def sha256_of_file(path: Path) -> str:
    try:
        return sha256_of_bytes(path.read_bytes())
    except OSError as error:
        raise VisionProposalError(f"cannot hash {path} (fail-closed): {error}") from error


def parse_vision_proposal(payload: dict[str, object]) -> VisionProposal:
    """Validate the proposal contract; every deviation is a stop condition."""
    if payload.get("artifact_kind") != PROPOSAL_ARTIFACT_KIND:
        raise VisionProposalError(
            f"artifact_kind must be {PROPOSAL_ARTIFACT_KIND!r} (fail-closed)"
        )
    if payload.get("pass_evidence") is not False:
        raise VisionProposalError("vision proposals must declare pass_evidence=false")
    lane = string_field(payload, "lane")
    if lane not in _LANES:
        raise VisionProposalError(f"unsupported lane {lane!r} (fail-closed)")

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

    raw_items = payload.get("proposals")
    if not isinstance(raw_items, list) or not raw_items:
        raise VisionProposalError("proposals must be a non-empty array (fail-closed)")
    items: list[ProposedItem] = []
    seen: set[str] = set()
    for entry in cast(list[object], raw_items):
        if not isinstance(entry, dict):
            raise VisionProposalError("each proposal must be an object (fail-closed)")
        item = cast(dict[str, object], entry)
        item_id = string_field(item, "item_id")
        if item_id in seen:
            raise VisionProposalError(f"duplicate proposal for {item_id} (fail-closed)")
        seen.add(item_id)
        items.append(
            ProposedItem(
                item_id=item_id,
                x_mm=float_field(item, "x_mm"),
                y_mm=float_field(item, "y_mm"),
                rotation_deg=float_field(item, "rotation_deg"),
            )
        )
    return VisionProposal(
        lane=lane,
        observation=reference,
        items=tuple(sorted(items, key=lambda proposed: proposed.item_id)),
    )


def load_relaxation_profile(path: Path) -> RelaxationProfile:
    """Load the versioned freedom declaration; unmeasured relaxations fail closed."""
    try:
        document = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        raise VisionProposalError(
            f"relaxation profile is unreadable (fail-closed): {error}"
        ) from error
    if not isinstance(document, dict):
        raise VisionProposalError("relaxation profile must be a JSON object (fail-closed)")
    payload = cast(dict[str, object], document)
    if payload.get("schema_version") != "1.0":
        raise VisionProposalError("unsupported relaxation profile schema_version")

    position = mapping_field(payload, "position")
    grid_step = float_field(position, "grid_step_mm")
    max_shift = float_field(position, "max_legalization_shift_mm")
    if grid_step <= 0.0 or max_shift <= 0.0:
        raise VisionProposalError("grid step and shift limit must be positive")

    rotation = mapping_field(payload, "rotation")
    step = float_field(rotation, "step_deg")
    if step <= 0.0 or step > 360.0:
        raise VisionProposalError("rotation step must be within (0, 360]")
    raw_allowed = rotation.get("allowed_deg")
    if not isinstance(raw_allowed, list) or not raw_allowed:
        raise VisionProposalError("rotation allowed_deg must be a non-empty array")
    allowed: list[float] = []
    for value in cast(list[object], raw_allowed):
        angle = float_field({"angle": value}, "angle")
        if angle < 0.0 or angle >= 360.0:
            raise VisionProposalError("allowed rotations must be within [0, 360)")
        if math.fmod(angle, step) > _TOLERANCE and step - math.fmod(angle, step) > _TOLERANCE:
            raise VisionProposalError(f"allowed rotation {angle} is not a multiple of the step")
        allowed.append(angle)
    if len(set(allowed)) != len(allowed) or allowed != sorted(allowed):
        raise VisionProposalError("allowed rotations must be unique and sorted")

    raw_evidence = payload.get("relaxation_evidence")
    if not isinstance(raw_evidence, list):
        raise VisionProposalError("relaxation_evidence must be an array (fail-closed)")
    evidence = cast(list[object], raw_evidence)
    measured = bool(evidence) and rotation.get("relaxation_evidence_status") == "measured"
    rotation_relaxed = abs(step - DEFAULT_ROTATION_STEP_DEG) > _TOLERANCE or any(
        math.fmod(angle, DEFAULT_ROTATION_STEP_DEG) > _TOLERANCE for angle in allowed
    )
    if rotation_relaxed and not measured:
        raise VisionProposalError(
            "rotation relaxation beyond 90 degrees requires measured Evidence (fail-closed)"
        )

    routing = mapping_field(payload, "routing")
    arc_tracks = bool_field(routing, "arc_tracks")
    off_grid_angles = bool_field(routing, "off_grid_angles")
    routing_measured = bool(evidence) and routing.get("relaxation_evidence_status") == "measured"
    if (arc_tracks or off_grid_angles) and not routing_measured:
        raise VisionProposalError(
            "routing relaxation requires measured Evidence (fail-closed)"
        )

    return RelaxationProfile(
        profile_id=string_field(payload, "profile_id"),
        grid_step_mm=grid_step,
        max_shift_mm=max_shift,
        rotation_step_deg=step,
        allowed_rotations_deg=tuple(allowed),
        arc_tracks=arc_tracks,
        off_grid_angles=off_grid_angles,
    )


def snap_rotation(rotation_deg: float, profile: RelaxationProfile) -> float:
    """Snap to the nearest permitted rotation; ties resolve to the smaller angle."""
    normalized = math.fmod(rotation_deg, 360.0)
    if normalized < 0.0:
        normalized += 360.0

    def distance(angle: float) -> tuple[float, float]:
        delta = abs(angle - normalized)
        return (round(min(delta, 360.0 - delta), 6), angle)

    return min(profile.allowed_rotations_deg, key=distance)


def _rotated_extent(
    extent: tuple[float, float, float, float], rotation_deg: float
) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = extent
    radians = math.radians(rotation_deg)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    corners = [
        (x * cosine + y * sine, -x * sine + y * cosine)
        for x, y in ((x1, y1), (x2, y1), (x1, y2), (x2, y2))
    ]
    xs = [corner[0] for corner in corners]
    ys = [corner[1] for corner in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _placed(
    extent: tuple[float, float, float, float], x: float, y: float, rotation_deg: float
) -> Rect:
    x1, y1, x2, y2 = _rotated_extent(extent, rotation_deg)
    return Rect(x + x1, y + y1, x + x2, y + y2)


def _inside(region: Rect, rect: Rect) -> bool:
    return (
        rect.x1 >= region.x1 - _TOLERANCE
        and rect.y1 >= region.y1 - _TOLERANCE
        and rect.x2 <= region.x2 + _TOLERANCE
        and rect.y2 <= region.y2 + _TOLERANCE
    )


def _search_offsets(grid_step_mm: float, max_shift_mm: float) -> Iterator[tuple[float, float]]:
    """Deterministic outward grid scan: ring by ring, row-major inside a ring."""
    rings = math.floor(max_shift_mm / grid_step_mm + _TOLERANCE)
    for ring in range(rings + 1):
        offsets = [
            (dx, dy)
            for dy in range(-ring, ring + 1)
            for dx in range(-ring, ring + 1)
            if max(abs(dx), abs(dy)) == ring
        ]
        for dx, dy in offsets:
            yield dx * grid_step_mm, dy * grid_step_mm


def legalize_items(
    items: tuple[ProposedItem, ...],
    context: LegalizationContext,
    profile: RelaxationProfile,
) -> tuple[ProposedItem, ...]:
    """Snap and shift seed positions onto legal, non-overlapping positions.

    Items are legalized in the given order, so earlier items keep priority over
    later ones.
    """
    unknown = sorted(item.item_id for item in items if item.item_id not in context.extents)
    if unknown:
        raise VisionProposalError(f"unknown proposal targets: {', '.join(unknown)} (fail-closed)")

    occupied: list[Rect] = list(context.keepouts)
    legalized: list[ProposedItem] = []
    for item in items:
        extent = context.extents[item.item_id]
        rotation = snap_rotation(item.rotation_deg, profile)
        anchor_x = round(item.x_mm / profile.grid_step_mm) * profile.grid_step_mm
        anchor_y = round(item.y_mm / profile.grid_step_mm) * profile.grid_step_mm
        spot: tuple[float, float] | None = None
        for offset_x, offset_y in _search_offsets(profile.grid_step_mm, profile.max_shift_mm):
            x = anchor_x + offset_x
            y = anchor_y + offset_y
            if math.hypot(x - item.x_mm, y - item.y_mm) > profile.max_shift_mm + _TOLERANCE:
                continue
            rect = _placed(extent, x, y, rotation)
            if not _inside(context.region, rect):
                continue
            if any(rect.overlaps(other) for other in occupied):
                continue
            spot = (x, y)
            break
        if spot is None:
            raise VisionProposalError(
                f"no legal position for {item.item_id} within "
                f"{profile.max_shift_mm}mm of the proposal (fail-closed)"
            )
        legalized.append(
            ProposedItem(
                item_id=item.item_id,
                x_mm=round(spot[0], _ROUND_DIGITS),
                y_mm=round(spot[1], _ROUND_DIGITS),
                rotation_deg=rotation,
            )
        )
        occupied.append(_placed(extent, spot[0], spot[1], rotation))
    return tuple(legalized)


def legalize_proposal(
    proposal: VisionProposal,
    context: LegalizationContext,
    profile: RelaxationProfile,
) -> tuple[ProposedItem, ...]:
    """Legalize a vision proposal against the lane it declares."""
    if proposal.lane != context.lane:
        raise VisionProposalError("proposal lane and context lane differ (fail-closed)")
    return legalize_items(proposal.items, context, profile)


def _gap(first: Rect, second: Rect) -> float:
    dx = max(first.x1 - second.x2, second.x1 - first.x2, 0.0)
    dy = max(first.y1 - second.y2, second.y1 - first.y2, 0.0)
    return math.hypot(dx, dy)


def legalization_metrics(
    seeds: tuple[ProposedItem, ...],
    legalized: tuple[ProposedItem, ...],
    context: LegalizationContext,
) -> LegalizationMetrics:
    """Surrogate metrics of how far legalization moved the seed positions."""
    proposed = {item.item_id: item for item in seeds}
    if sorted(proposed) != sorted(item.item_id for item in legalized):
        raise VisionProposalError("legalized items do not match the seeds (fail-closed)")
    shifts = [
        math.hypot(
            item.x_mm - proposed[item.item_id].x_mm,
            item.y_mm - proposed[item.item_id].y_mm,
        )
        for item in legalized
    ]
    rotation_changes = sum(
        1
        for item in legalized
        if abs(item.rotation_deg - proposed[item.item_id].rotation_deg) > _TOLERANCE
    )
    rects = [
        (
            item.item_id,
            _placed(context.extents[item.item_id], item.x_mm, item.y_mm, item.rotation_deg),
        )
        for item in sorted(legalized, key=lambda entry: entry.item_id)
    ]
    gaps = [
        _gap(first, second)
        for index, (_, first) in enumerate(rects)
        for _, second in rects[index + 1 :]
    ]
    region_gaps = [
        value
        for _, rect in rects
        for value in (
            rect.x1 - context.region.x1,
            rect.y1 - context.region.y1,
            context.region.x2 - rect.x2,
            context.region.y2 - rect.y2,
        )
    ]
    return LegalizationMetrics(
        max_shift_mm=max(shifts) if shifts else 0.0,
        total_shift_mm=sum(shifts),
        rotation_changes=rotation_changes,
        min_item_gap_mm=min(gaps) if gaps else 0.0,
        min_region_gap_mm=min(region_gaps) if region_gaps else 0.0,
    )


@dataclass(frozen=True)
class ElectricalContext:
    """Electrical lane inputs shared by legalization and ranking."""

    lane: ElectricalLane
    footprints: dict[str, FootprintShape]
    keepouts: tuple[Rect, ...]
    context: LegalizationContext


def electrical_context(
    graph: DesignGraph, fixture_dir: Path, fab_profile_path: Path
) -> ElectricalContext:
    lane = extract_electrical_lane(graph)
    profile = load_fab_profile(fab_profile_path)
    footprints = load_board_footprints(lane, FootprintLibrary(), fixture_dir, profile).shapes
    keepouts = tuple(
        Rect(item.x1_mm, item.y1_mm, item.x2_mm, item.y2_mm)
        for item in board_keepouts(lane, footprints)
    )
    clearance = lane.board.edge_copper_clearance_mm
    region = Rect(
        clearance,
        clearance,
        lane.board.width_mm - clearance,
        lane.board.height_mm - clearance,
    )
    extents = {
        component.refdes: pad_bbox(footprints[component.refdes], MARGIN_MM)
        for component in lane.components
        if component.refdes in footprints
    }
    return ElectricalContext(
        lane=lane,
        footprints=footprints,
        keepouts=keepouts,
        context=LegalizationContext(
            lane="electrical", region=region, extents=extents, keepouts=keepouts
        ),
    )


def mechanical_baseline(graph: DesignGraph) -> tuple[ProposedItem, ...]:
    """Declared body placements of the mechanical lane."""
    lane = extract_mechanical_lane(graph)
    return tuple(
        sorted(
            (
                ProposedItem(body.component_id, body.x_mm, body.y_mm, body.rotation_deg)
                for body in lane.component_bodies
            ),
            key=lambda item: item.item_id,
        )
    )


def mechanical_context(graph: DesignGraph) -> LegalizationContext:
    """Enclosure interior and component bodies as the same legalization abstraction."""
    lane = extract_mechanical_lane(graph)
    inset = lane.enclosure.wall_thickness_mm + lane.enclosure.internal_clearance_mm
    region = Rect(
        inset,
        inset,
        lane.outline.width_mm - inset,
        lane.outline.depth_mm - inset,
    )
    if region.x2 <= region.x1 or region.y2 <= region.y1:
        raise VisionProposalError("enclosure interior is empty (fail-closed)")
    extents = {
        body.component_id: (
            -body.width_mm / 2.0,
            -body.depth_mm / 2.0,
            body.width_mm / 2.0,
            body.depth_mm / 2.0,
        )
        for body in lane.component_bodies
    }
    keepouts = tuple(
        Rect(
            hole.x_mm - hole.diameter_mm / 2.0,
            hole.y_mm - hole.diameter_mm / 2.0,
            hole.x_mm + hole.diameter_mm / 2.0,
            hole.y_mm + hole.diameter_mm / 2.0,
        )
        for hole in lane.outline.mount_holes
    )
    return LegalizationContext(
        lane="mechanical", region=region, extents=extents, keepouts=keepouts
    )


def net_refdes_of(lane: ElectricalLane) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(refdes for refdes, _pad in lane.pads_of_net(net.node_id))
        for net in sorted(lane.nets, key=lambda net: net.name)
    )


def deterministic_placements(
    electrical: ElectricalContext, seeds: tuple[ProposedItem, ...] = ()
) -> tuple[ProposedItem, ...]:
    """Deterministic search around the seeded (already legalized) items."""
    return tuple(
        ProposedItem(item.refdes, item.x_mm, item.y_mm, item.rotation_deg)
        for item in compute_placements(
            electrical.lane.board,
            electrical.lane.components,
            electrical.footprints,
            electrical.keepouts,
            net_refdes_of(electrical.lane),
            electrical.lane.pins,
            electrical.lane.nets,
            _placements(seeds),
        )
    )


def _placements(items: tuple[ProposedItem, ...]) -> tuple[Placement, ...]:
    return tuple(
        Placement(item.item_id, item.x_mm, item.y_mm, item.rotation_deg) for item in items
    )


def _score_payload(score: PlacementScore) -> dict[str, float]:
    return {
        "hpwl_mm": round(score.hpwl_mm, 6),
        "min_component_gap_mm": round(score.min_component_gap_mm, 6),
        "min_edge_gap_mm": round(score.min_edge_gap_mm, 6),
    }


def _metrics_payload(metrics: LegalizationMetrics) -> dict[str, float | int]:
    return {
        "max_shift_mm": round(metrics.max_shift_mm, 6),
        "total_shift_mm": round(metrics.total_shift_mm, 6),
        "rotation_changes": metrics.rotation_changes,
        "min_item_gap_mm": round(metrics.min_item_gap_mm, 6),
        "min_region_gap_mm": round(metrics.min_region_gap_mm, 6),
    }


def _items_payload(items: tuple[ProposedItem, ...]) -> list[dict[str, object]]:
    return [
        {
            "item_id": item.item_id,
            "x_mm": item.x_mm,
            "y_mm": item.y_mm,
            "rotation_deg": item.rotation_deg,
        }
        for item in items
    ]


def build_candidate_report(
    *,
    proposal: VisionProposal,
    candidate: tuple[ProposedItem, ...],
    metrics: LegalizationMetrics,
    baseline: tuple[ProposedItem, ...],
    electrical: ElectricalContext | None,
    provenance: dict[str, object],
) -> dict[str, object]:
    """Assemble the non-authoritative candidate report."""
    candidates: dict[str, object] = {
        "vision": _items_payload(candidate),
        "baseline": _items_payload(baseline),
    }
    surrogate: dict[str, object] = {}
    if electrical is not None:
        surrogate["vision"] = _score_payload(
            score_placement(electrical.lane, _placements(candidate), electrical.footprints)
        )
        surrogate["baseline"] = _score_payload(
            score_placement(electrical.lane, _placements(baseline), electrical.footprints)
        )
    return {
        "artifact_kind": CANDIDATE_ARTIFACT_KIND,
        "pass_evidence": False,
        "lane": proposal.lane,
        "proposed_item_ids": [item.item_id for item in proposal.items],
        "candidates": candidates,
        "surrogate_metrics": surrogate,
        "legalization_metrics": _metrics_payload(metrics),
        "provenance": provenance,
    }


def _provenance(
    *,
    proposal: VisionProposal,
    proposal_path: Path,
    relaxation_profile_path: Path,
    relaxation_profile: RelaxationProfile,
    graph_revision: str,
) -> dict[str, object]:
    script = Path(__file__).resolve()
    return {
        "skill_name": SKILL_NAME,
        "script_name": script.name,
        "script_sha256": sha256_of_file(script),
        "proposal_sha256": sha256_of_file(proposal_path),
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
    parser.add_argument("--fixture-dir", type=Path)
    parser.add_argument("--fab-profile", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    document = cast(object, json.loads(args.proposal.read_text(encoding="utf-8")))
    if not isinstance(document, dict):
        raise VisionProposalError("proposal must be a JSON object (fail-closed)")
    proposal = parse_vision_proposal(cast(dict[str, object], document))
    relaxation_profile = load_relaxation_profile(args.relaxation_profile)
    graph = DesignGraph.model_validate(
        cast(object, json.loads(args.input.read_text(encoding="utf-8")))
    )

    proposed_ids = frozenset(item.item_id for item in proposal.items)
    electrical: ElectricalContext | None = None
    if proposal.lane == "electrical":
        if args.fixture_dir is None or args.fab_profile is None:
            raise VisionProposalError(
                "the electrical lane requires --fixture-dir and --fab-profile (fail-closed)"
            )
        electrical = electrical_context(graph, args.fixture_dir, args.fab_profile)
        context = electrical.context
        baseline = deterministic_placements(electrical)
        # The proposal seeds the search: proposed items are legalized first and
        # pinned, then the deterministic search places the rest around them.
        legalized = legalize_proposal(proposal, context, relaxation_profile)
        metrics = legalization_metrics(proposal.items, legalized, context)
        candidate = deterministic_placements(electrical, legalized)
    else:
        # Declared body positions are the mechanical baseline; the candidate
        # covers the proposed bodies only, and the mechanical lane gates decide
        # whether it is acceptable.
        context = mechanical_context(graph)
        baseline = tuple(
            item for item in mechanical_baseline(graph) if item.item_id in proposed_ids
        )
        legalized = legalize_proposal(proposal, context, relaxation_profile)
        metrics = legalization_metrics(proposal.items, legalized, context)
        candidate = legalized

    report = build_candidate_report(
        proposal=proposal,
        candidate=candidate,
        metrics=metrics,
        baseline=baseline,
        electrical=electrical,
        provenance=_provenance(
            proposal=proposal,
            proposal_path=args.proposal,
            relaxation_profile_path=args.relaxation_profile,
            relaxation_profile=relaxation_profile,
            graph_revision=graph.revision,
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
