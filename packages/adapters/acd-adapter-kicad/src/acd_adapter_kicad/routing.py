"""Injection of externally routed wires/vias into a generated KiCad board.

Routes come from the freerouting adapter as tool-neutral wires/vias in the
KiCad board frame. Unknown nets or layers fail closed; the routed board is
only trusted after kicad-cli DRC reruns on the result.
"""

from __future__ import annotations

from acd_adapter_kicad.emit import det_uuid, fmt
from acd_core.board_model import RoutedDesign, RoutedWire

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


def _wire_key(wire: RoutedWire) -> tuple[str, str, tuple[tuple[float, float], ...]]:
    return wire.net, wire.layer, wire.points
