"""Injection of externally routed wires/vias into a generated KiCad board.

Routes come from the freerouting adapter as tool-neutral wires/vias in the
KiCad board frame. Unknown nets or layers fail closed; the routed board is
only trusted after kicad-cli DRC reruns on the result.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from acd.adapters.kicad.emit import det_uuid, fmt
from acd.adapters.kicad.placement import rotate_point
from acd.core.board_model import BoardModel, RoutedDesign, RoutedWire

_LAYERS = frozenset({"F.Cu", "B.Cu"})


class RouteInjectionError(ValueError):
    """Raised when routed geometry cannot be mapped onto the board (fail-closed)."""


def inject_routes(
    board_content: str,
    routes: RoutedDesign,
    net_numbers: dict[str, int],
    via_diameter_mm: float,
    via_drill_mm: float,
) -> str:
    if not board_content.rstrip().endswith(")"):
        raise RouteInjectionError("board content is not a closed s-expression")
    lines: list[str] = []
    for index, wire in enumerate(sorted(routes.wires, key=_wire_key)):
        if wire.layer not in _LAYERS:
            raise RouteInjectionError(f"unknown copper layer {wire.layer!r} (fail-closed)")
        net_number = net_numbers.get(wire.net)
        if net_number is None:
            raise RouteInjectionError(f"routed wire references unknown net {wire.net!r}")
        for start, end in zip(wire.points, wire.points[1:], strict=False):
            uuid = det_uuid(
                "segment", str(index), fmt(start[0]), fmt(start[1]), fmt(end[0]), fmt(end[1])
            )
            lines.append(
                f"  (segment (start {fmt(start[0])} {fmt(start[1])}) "
                f"(end {fmt(end[0])} {fmt(end[1])}) (width {fmt(wire.width_mm)}) "
                f'(layer "{wire.layer}") (net {net_number}) (uuid "{uuid}"))'
            )
    for via in sorted(routes.vias, key=lambda v: (v.net, v.x_mm, v.y_mm)):
        net_number = net_numbers.get(via.net)
        if net_number is None:
            raise RouteInjectionError(f"routed via references unknown net {via.net!r}")
        uuid = det_uuid("via", via.net, fmt(via.x_mm), fmt(via.y_mm))
        lines.append(
            f"  (via (at {fmt(via.x_mm)} {fmt(via.y_mm)}) (size {fmt(via_diameter_mm)}) "
            f'(drill {fmt(via_drill_mm)}) (layers "F.Cu" "B.Cu") '
            f'(net {net_number}) (uuid "{uuid}"))'
        )
    stripped = board_content.rstrip()
    return stripped[:-1].rstrip() + "\n" + "\n".join(lines) + "\n)\n"


def inject_stitch_vias(
    board_content: str,
    model: BoardModel,
    routes: RoutedDesign,
    net_numbers: dict[str, int],
    pitch_mm: float | None,
    via_diameter_mm: float,
    via_drill_mm: float,
    allowed_points: Sequence[tuple[float, float]] | None = None,
)-> tuple[str, tuple[tuple[float, float], ...], dict[str, object]]:
    """Add deterministic GND stitching vias outside occupied geometry."""
    empty_report: dict[str, object] = {
        "candidate_total": 0,
        "selected_count": 0,
        "exclusion_counts": {
            "keepout": 0,
            "footprint_body_or_courtyard": 0,
            "pad": 0,
            "wire": 0,
            "via": 0,
            "board_edge_inset": 0,
            "inter_via_spacing": 0,
        },
        "exclusion_combinations": {},
        "board_edge_inset_basis": (
            "Candidates are generated inside the board edge inset; "
            "no post-generation edge rejection is performed."
        ),
        "footprint_clearance_method": (
            "Rotated body/courtyard corners with an axis-aligned bounding "
            "box, expanded by via radius plus clearance."
        ),
        "candidates": [],
        "allowed_points_override": allowed_points is not None,
        "selected_points": [],
    }
    if pitch_mm is None or model.stitch_via_net is None:
        return board_content, (), empty_report
    net_number = net_numbers.get(model.stitch_via_net)
    if net_number is None:
        raise RouteInjectionError("stitch-via net is unknown (fail-closed)")
    inset = model.edge_clearance_mm
    radius = via_diameter_mm / 2.0
    clearance = model.min_clearance_mm
    candidates: list[tuple[float, float]] = []
    def add_candidate(point: tuple[float, float]) -> None:
        if point not in candidates:
            candidates.append(point)

    x = inset + radius + pitch_mm
    while x <= model.width_mm - inset - radius + 1e-9:
        add_candidate((x, inset + radius))
        add_candidate((x, model.height_mm - inset - radius))
        x += pitch_mm
    y = inset + radius + pitch_mm
    while y <= model.height_mm - inset - radius - pitch_mm + 1e-9:
        add_candidate((inset + radius, y))
        add_candidate((model.width_mm - inset - radius, y))
        y += pitch_mm
    x = inset + radius + pitch_mm
    while x <= model.width_mm - inset - radius + 1e-9:
        y = inset + radius + pitch_mm
        while y <= model.height_mm - inset - radius + 1e-9:
            add_candidate((x, y))
            y += pitch_mm
        x += pitch_mm

    def distance_to_segment(
        point: tuple[float, float],
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> float:
        dx, dy = end[0] - start[0], end[1] - start[1]
        length_sq = dx * dx + dy * dy
        t = 0.0 if length_sq == 0 else max(
            0.0,
            min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq),
        )
        return math.hypot(point[0] - (start[0] + t * dx), point[1] - (start[1] + t * dy))

    def occupied_reasons(point: tuple[float, float]) -> tuple[str, ...]:
        reasons: set[str] = set()
        for keepout in model.keepouts:
            if (
                keepout.x1_mm <= point[0] <= keepout.x2_mm
                and keepout.y1_mm <= point[1] <= keepout.y2_mm
            ):
                reasons.add("keepout")
        for placement in model.placements:
            for footprint_box in (
                placement.footprint.courtyard_bbox_mm,
                placement.footprint.body_bbox_mm,
            ):
                if footprint_box is None:
                    continue
                x1, y1, x2, y2 = footprint_box
                corners = [
                    tuple(
                        placement_value + offset
                        for placement_value, offset in zip(
                            (placement.x_mm, placement.y_mm),
                            rotate_point(x, y, placement.rotation_deg),
                            strict=True,
                        )
                    )
                    for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
                ]
                xs, ys = zip(*corners, strict=True)
                if (
                    min(xs) - radius - clearance <= point[0] <= max(xs) + radius + clearance
                    and min(ys) - radius - clearance <= point[1] <= max(ys) + radius + clearance
                ):
                    reasons.add("footprint_body_or_courtyard")
            for x1, y1, x2, y2 in placement.footprint.keepout_bboxes_mm:
                corners = [
                    tuple(
                        placement_value + offset
                        for placement_value, offset in zip(
                            (placement.x_mm, placement.y_mm),
                            rotate_point(x, y, placement.rotation_deg),
                            strict=True,
                        )
                    )
                    for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
                ]
                xs, ys = zip(*corners, strict=True)
                if min(xs) <= point[0] <= max(xs) and min(ys) <= point[1] <= max(ys):
                    reasons.add("keepout")
            for pad in placement.footprint.pads:
                px, py = rotate_point(pad.x_mm, pad.y_mm, placement.rotation_deg)
                px += placement.x_mm
                py += placement.y_mm
                pad_angle = placement.rotation_deg + pad.rotation_deg
                margin = radius + clearance
                for orientation in (pad_angle, pad_angle + 90.0):
                    local_x, local_y = rotate_point(
                        point[0] - px, point[1] - py, -orientation
                    )
                    if (
                        abs(local_x) <= pad.size_x_mm / 2.0 + margin
                        and abs(local_y) <= pad.size_y_mm / 2.0 + margin
                    ):
                        reasons.add("pad")
        for wire in routes.wires:
            for start, end in zip(wire.points, wire.points[1:], strict=False):
                if (
                    distance_to_segment(point, start, end)
                    <= radius + wire.width_mm / 2.0 + clearance
                ):
                    reasons.add("wire")
        for via in routes.vias:
            if math.hypot(point[0] - via.x_mm, point[1] - via.y_mm) <= radius + clearance:
                reasons.add("via")
        return tuple(sorted(reasons))

    selected_points: list[tuple[float, float]] = []
    exclusion_counts = {
        "keepout": 0,
        "footprint_body_or_courtyard": 0,
        "pad": 0,
        "wire": 0,
        "via": 0,
        "board_edge_inset": 0,
        "inter_via_spacing": 0,
    }
    exclusion_combinations: dict[str, int] = {}
    candidate_reasons: dict[tuple[float, float], tuple[str, ...]] = {}
    for point in candidates:
        reasons = occupied_reasons(point)
        if reasons:
            candidate_reasons[point] = reasons
            for reason in reasons:
                exclusion_counts[reason] += 1
            combination = "+".join(reasons)
            exclusion_combinations[combination] = (
                exclusion_combinations.get(combination, 0) + 1
            )
            continue
        if any(
            math.hypot(point[0] - other[0], point[1] - other[1])
            <= via_diameter_mm + clearance
            for other in selected_points
        ):
            candidate_reasons[point] = ("inter_via_spacing",)
            exclusion_counts["inter_via_spacing"] += 1
            exclusion_combinations["inter_via_spacing"] = (
                exclusion_combinations.get("inter_via_spacing", 0) + 1
            )
            continue
        candidate_reasons[point] = ()
        selected_points.append(point)
    selected = tuple(selected_points)
    if allowed_points is not None:
        selected = tuple(dict.fromkeys(allowed_points))
    selected_set = set(selected)
    report: dict[str, object] = {
        "candidate_total": len(candidates),
        "selected_count": len(selected),
        "exclusion_counts": exclusion_counts,
        "exclusion_combinations": exclusion_combinations,
        "board_edge_inset_basis": (
            "Candidates are generated inside the board edge inset; "
            "no post-generation edge rejection is performed."
        ),
        "footprint_clearance_method": (
            "Rotated body/courtyard corners with an axis-aligned bounding "
            "box, expanded by via radius plus clearance."
        ),
        "candidates": [
            {
                "position_mm": [round(point[0], 6), round(point[1], 6)],
                "selected": point in selected_set,
                "exclusion_reasons": (
                    [] if point in selected_set else list(candidate_reasons[point])
                ),
            }
            for point in sorted(candidates, key=lambda item: (item[0], item[1]))
        ],
        "allowed_points_override": allowed_points is not None,
        "selected_points": [
            [round(point[0], 6), round(point[1], 6)] for point in selected
        ],
    }
    lines = [
        f'  (via (at {fmt(x)} {fmt(y)}) (size {fmt(via_diameter_mm)}) '
        f'(drill {fmt(via_drill_mm)}) (layers "F.Cu" "B.Cu") '
        f'(net {net_number}) (uuid "{det_uuid("stitch-via", fmt(x), fmt(y))}"))'
        for x, y in selected
    ]
    stripped = board_content.rstrip()
    if not lines:
        raise RouteInjectionError("no safe stitch-via locations remain (fail-closed)")
    return stripped[:-1].rstrip() + "\n" + "\n".join(lines) + "\n)\n", selected, report


def _wire_key(wire: RoutedWire) -> tuple[str, str, tuple[tuple[float, float], ...]]:
    return wire.net, wire.layer, wire.points
