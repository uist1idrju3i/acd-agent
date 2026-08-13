"""Injection of externally routed wires/vias into a generated KiCad board.

Routes come from the freerouting adapter as tool-neutral wires/vias in the
KiCad board frame. Unknown nets or layers fail closed; the routed board is
only trusted after kicad-cli DRC reruns on the result.
"""

from __future__ import annotations

import math

from acd_adapter_kicad.emit import det_uuid, fmt
from acd_adapter_kicad.placement import rotate_point
from acd_core.board_model import BoardModel, RoutedDesign, RoutedWire

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
) -> tuple[str, tuple[tuple[float, float], ...]]:
    """Add deterministic GND stitching vias outside occupied geometry."""
    if pitch_mm is None or model.stitch_via_net is None:
        return board_content, ()
    net_number = net_numbers.get(model.stitch_via_net)
    if net_number is None:
        raise RouteInjectionError("stitch-via net is unknown (fail-closed)")
    inset = model.edge_clearance_mm
    radius = via_diameter_mm / 2.0
    clearance = model.min_clearance_mm
    candidates: list[tuple[float, float]] = []
    x = inset + radius + pitch_mm
    while x <= model.width_mm - inset - radius + 1e-9:
        candidates.extend(((x, inset + radius), (x, model.height_mm - inset - radius)))
        x += pitch_mm
    y = inset + radius + pitch_mm
    while y <= model.height_mm - inset - radius - pitch_mm + 1e-9:
        candidates.extend(((inset + radius, y), (model.width_mm - inset - radius, y)))
        y += pitch_mm

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

    def occupied(point: tuple[float, float]) -> bool:
        for keepout in model.keepouts:
            if (
                keepout.x1_mm <= point[0] <= keepout.x2_mm
                and keepout.y1_mm <= point[1] <= keepout.y2_mm
            ):
                return True
        for placement in model.placements:
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
                    return True
            for pad in placement.footprint.pads:
                px, py = rotate_point(pad.x_mm, pad.y_mm, placement.rotation_deg)
                px += placement.x_mm
                py += placement.y_mm
                if math.hypot(point[0] - px, point[1] - py) <= (
                    max(pad.size_x_mm, pad.size_y_mm) / 2.0 + radius + clearance
                ):
                    return True
        for wire in routes.wires:
            for start, end in zip(wire.points, wire.points[1:], strict=False):
                if (
                    distance_to_segment(point, start, end)
                    <= radius + wire.width_mm / 2.0 + clearance
                ):
                    return True
        for via in routes.vias:
            if math.hypot(point[0] - via.x_mm, point[1] - via.y_mm) <= radius + clearance:
                return True
        return False

    selected = tuple(point for point in candidates if not occupied(point))
    lines = [
        f'  (via (at {fmt(x)} {fmt(y)}) (size {fmt(via_diameter_mm)}) '
        f'(drill {fmt(via_drill_mm)}) (layers "F.Cu" "B.Cu") '
        f'(net {net_number}) (uuid "{det_uuid("stitch-via", fmt(x), fmt(y))}"))'
        for x, y in selected
    ]
    stripped = board_content.rstrip()
    if not lines:
        raise RouteInjectionError("no safe stitch-via locations remain (fail-closed)")
    return stripped[:-1].rstrip() + "\n" + "\n".join(lines) + "\n)\n", selected


def _wire_key(wire: RoutedWire) -> tuple[str, str, tuple[tuple[float, float], ...]]:
    return wire.net, wire.layer, wire.points
