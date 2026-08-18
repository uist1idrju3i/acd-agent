# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@4cca489171ac53e6e55639b791c8571482167bd2",
# ]
# ///
"""Deterministic component placement search (skill asset, not an ACD gate).

Fixed anchors (RF module at the top edge with the antenna overhanging, USB
connector at the bottom edge, mounting holes in the corners) plus a greedy
first-fit grid scan for the remaining components. The scan order is fully
deterministic: components sorted by refdes, candidate positions row-major on a
0.25 mm grid. The search fails closed if any component cannot be placed.

The coordinates produced here are only candidates. They become design data by
being written into the design input files, and they are judged by the ACD
projections and deterministic gates (ERC/DRC, independent reload), never by this
script.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acd.adapters.kicad.board import board_keepouts, load_board_footprints
from acd.adapters.kicad.library import FootprintLibrary
from acd.adapters.kicad.placement import (
    MARGIN_MM,
    Placement,
    PlacementError,
    Rect,
    pad_bbox,
    pad_position,
    placed_rect,
)
from acd.core.board_model import FootprintShape
from acd.core.electrical import (
    BoardView,
    ComponentView,
    NetView,
    PinView,
    extract_electrical_lane,
)
from acd.core.fab import load_fab_profile
from acd.schema.design_graph import DesignGraph

_GRID_MM = 0.25
# Preferred spacing between neighbouring components leaves a routing channel
# (track width + clearance on both sides); tighter fallbacks keep dense boards
# placeable while still fully deterministic.
_SPACING_STEPS_MM = (0.45, 0.15, 0.0)
_COMPACTNESS_WEIGHT = 0.05

MOUNTING_HOLE_INSET_MM = 3.0
_EDGE_TOLERANCE_MM = 1e-6


def _edge_anchor_y(board: BoardView, footprint: FootprintShape, *, kind: str) -> float:
    if kind == "usb_connector":
        body = footprint.body_bbox_mm
        if body is None:
            raise PlacementError("USB connector body geometry missing (fail-closed)")
        pad_y = sum(pad.y_mm for pad in footprint.pads) / len(footprint.pads)
        edge = body[3] if body[3] >= pad_y else body[1]
        return board.height_mm - edge if edge >= pad_y else -edge
    if kind == "rf_module":
        if len(footprint.keepout_bboxes_mm) != 1:
            raise PlacementError("RF antenna keepout is not unique (fail-closed)")
        keepout = footprint.keepout_bboxes_mm[0]
        pad_y = max(pad.y_mm for pad in footprint.pads)
        inner = keepout[3] if keepout[3] < pad_y else keepout[1]
        return -inner
    raise PlacementError(f"unsupported edge anchor kind {kind!r}")


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
    pins: tuple[PinView, ...] = (),
    nets: tuple[NetView, ...] = (),
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
        if kind == "rf_module" or kind == "usb_connector":
            x, y, rot = center_x, _edge_anchor_y(board, footprint, kind=kind), 0.0
        elif kind == "mounting_hole":
            x, y = hole_positions[holes.index(comp)]
            rot = 0.0
        else:
            continue
        placements.append(Placement(comp.refdes, x, y, rot))
        placed_pad = placed_rect(FootprintShape(footprint.library_ref, footprint.pads), x, y, rot)
        edge_clearance = board.edge_copper_clearance_mm
        if (
            placed_pad.x1 < edge_clearance - _EDGE_TOLERANCE_MM
            or placed_pad.y1 < edge_clearance - _EDGE_TOLERANCE_MM
            or placed_pad.x2 > board.width_mm - edge_clearance + _EDGE_TOLERANCE_MM
            or placed_pad.y2 > board.height_mm - edge_clearance + _EDGE_TOLERANCE_MM
        ):
            raise PlacementError(f"{comp.refdes}: pad edge clearance violated")
        occupied.append(placed_rect(footprint, x, y, rot))

    def bbox_area(comp: ComponentView) -> float:
        x1, y1, x2, y2 = pad_bbox(footprints[comp.refdes], MARGIN_MM)
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
    placed_at: dict[str, tuple[float, float]] = {p.refdes: (p.x_mm, p.y_mm) for p in placements}
    by_refdes = {comp.refdes: comp for comp in components}
    net_names = {net.node_id: net.name for net in nets}
    pins_by_component: dict[str, tuple[PinView, ...]] = {
        comp.node_id: tuple(pin for pin in pins if pin.component_id == comp.node_id)
        for comp in components
    }
    decoupling: dict[str, tuple[str, str, str]] = {}
    for comp in generic:
        target_ref = comp.decoupling_target
        if target_ref is None:
            continue
        target = by_refdes.get(target_ref)
        if target is None:
            raise PlacementError(f"decoupling target not found: {comp.refdes}->{target_ref}")
        cap_pins = pins_by_component[comp.node_id]
        target_pins = pins_by_component[target.node_id]
        power_cap = [
            pin
            for pin in cap_pins
            if pin.net_id is not None
            and net_names.get(pin.net_id) != "GND"
            and any(
                target_pin.net_id == pin.net_id
                for target_pin in target_pins
                if target_pin.pad != pin.pad
            )
        ]
        ground_cap = [
            pin for pin in cap_pins if pin.net_id is not None and net_names.get(pin.net_id) == "GND"
        ]
        shared_target = [
            pin for pin in target_pins if power_cap and pin.net_id == power_cap[0].net_id
        ]
        if len(power_cap) != 1 or len(ground_cap) != 1 or len(shared_target) != 1:
            raise PlacementError(f"ambiguous decoupling declaration: {comp.refdes}")
        decoupling[comp.refdes] = (target_ref, shared_target[0].pad, power_cap[0].pad)

    active_refs = {
        comp.refdes
        for comp in generic
        if comp.refdes in {target for target, _, _ in decoupling.values()}
        or comp.library.footprint.startswith(("Espressif:", "Package_TO_SOT", "Sensor_"))
    }
    active = sorted(
        (comp for comp in generic if comp.refdes in active_refs),
        key=lambda c: (-bbox_area(c), c.refdes),
    )
    decoupling_components = sorted(
        (comp for comp in generic if comp.refdes in decoupling),
        key=lambda c: c.refdes,
    )
    remaining = sorted(
        (
            comp
            for comp in generic
            if comp.refdes not in active_refs and comp.refdes not in decoupling
        ),
        key=lambda c: (-bbox_area(c), c.refdes),
    )

    for comp in (*active, *decoupling_components, *remaining):
        footprint = footprints[comp.refdes]
        anchors = tuple(
            placed_at[ref] for ref in sorted(neighbours.get(comp.refdes, ())) if ref in placed_at
        )
        spot = None
        spacing_steps = (0.0,) if comp.refdes in decoupling else _SPACING_STEPS_MM
        for spacing in spacing_steps:
            target = None
            if comp.refdes in decoupling:
                target_ref, target_pad, cap_pad = decoupling[comp.refdes]
                target = (
                    placed_at[target_ref],
                    footprints[target_ref],
                    target_pad,
                    cap_pad,
                )
            spot = _best_fit(board, footprint, occupied, spacing, anchors, target)
            if spot is not None:
                break
        if spot is None:
            raise PlacementError(
                f"no placement found for {comp.refdes} (fail-closed); placed={placed_at}"
            )
        x, y, rot = spot
        placements.append(Placement(comp.refdes, x, y, rot))
        occupied.append(placed_rect(footprint, x, y, rot))
        placed_at[comp.refdes] = (x, y)

    return tuple(sorted(placements, key=lambda p: p.refdes))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--fab-profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    graph = json.loads(args.input.read_text(encoding="utf-8"))
    placements = compute_placements_from_json(
        {
            "graph": graph,
            "fixture_dir": str(args.fixture_dir),
            "fab_profile": str(args.fab_profile),
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            [
                {
                    "refdes": item.refdes,
                    "x_mm": item.x_mm,
                    "y_mm": item.y_mm,
                    "rotation_deg": item.rotation_deg,
                }
                for item in placements
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


def compute_placements_from_json(payload: dict[str, object]) -> tuple[Placement, ...]:
    """Resolve the graph/fixture JSON CLI contract into typed search inputs."""
    graph = DesignGraph.model_validate(payload["graph"])
    lane = extract_electrical_lane(graph)
    fixture_dir = Path(str(payload["fixture_dir"]))
    profile = load_fab_profile(Path(str(payload["fab_profile"])))
    footprints = load_board_footprints(lane, FootprintLibrary(), fixture_dir, profile).shapes
    keepouts = tuple(
        Rect(item.x1_mm, item.y1_mm, item.x2_mm, item.y2_mm)
        for item in board_keepouts(lane, footprints)
    )
    net_refdes = tuple(
        tuple(ref for ref, _pad in lane.pads_of_net(net.node_id))
        for net in sorted(lane.nets, key=lambda n: n.name)
    )
    return compute_placements(
        lane.board,
        lane.components,
        footprints,
        keepouts,
        net_refdes,
        lane.pins,
        lane.nets,
    )


def _best_fit(
    board: BoardView,
    footprint: FootprintShape,
    occupied: list[Rect],
    spacing: float,
    anchors: tuple[tuple[float, float], ...],
    target: tuple[tuple[float, float], FootprintShape, str, str] | None = None,
) -> tuple[float, float, float] | None:
    """Deterministic candidate scan; among all fitting spots pick the one that
    minimises the summed distance to connected, already-placed components so
    nets stay short and routable. Ties resolve row-major with rotation 0 first."""
    edge = board.edge_copper_clearance_mm
    bx1, by1, bx2, by2 = pad_bbox(footprint, MARGIN_MM)
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
                    if target is None:
                        cost = sum(abs(x - ax) + abs(y - ay) for ax, ay in anchors)
                    else:
                        target_at, target_footprint, target_pad, cap_pad = target
                        candidate_point = pad_position(footprint, (x, y), rotation, cap_pad)
                        cost = min(
                            abs(candidate_point[0] - target_point[0])
                            + abs(candidate_point[1] - target_point[1])
                            for target_point in _pad_positions(
                                target_footprint, target_at, 0.0, target_pad
                            )
                        )
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


def _pad_positions(
    footprint: FootprintShape,
    placement: tuple[float, float],
    rotation: float,
    pad_number: str,
) -> tuple[tuple[float, float], ...]:
    return tuple(
        pad_position(
            FootprintShape(
                library_ref=footprint.library_ref,
                pads=(pad,),
            ),
            placement,
            rotation,
            pad_number,
        )
        for pad in footprint.pads
        if pad.number == pad_number
    )


if __name__ == "__main__":
    raise SystemExit(main())
