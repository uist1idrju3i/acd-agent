"""Specctra SES (session) parsing back into tool-neutral routes.

Only the ``routes`` section is consumed; placement echoed by the router is
ignored (the graph-derived placement stays canonical). Coordinates are
converted back to millimetres in the KiCad board frame (Y-down).
"""

from __future__ import annotations

from acd.core.board_model import RoutedDesign, RoutedVia, RoutedWire
from acd.core.sexpr import SExpr, find_all, find_one, parse_one


class SesImportError(ValueError):
    """Raised when a session file cannot be interpreted (fail-closed)."""


def _as_float(value: SExpr) -> float:
    if not isinstance(value, str):
        raise SesImportError(f"expected atom, got list: {value!r}")
    return float(value)


def _as_str(value: SExpr) -> str:
    if not isinstance(value, str):
        raise SesImportError(f"expected atom, got list: {value!r}")
    return value


def _resolution_divisor(routes: list[SExpr]) -> float:
    resolution = find_one(routes, "resolution")
    if resolution is None or len(resolution) < 3:
        raise SesImportError("session routes missing resolution (fail-closed)")
    unit = _as_str(resolution[1])
    per_unit = _as_float(resolution[2])
    if unit == "um":
        return 1000.0 * per_unit
    if unit == "mm":
        return per_unit
    raise SesImportError(f"unsupported session resolution unit {unit!r} (fail-closed)")


def parse_ses(text: str, *, minimum_width_mm: float | None = None) -> RoutedDesign:
    """Parse a router session and enforce the board's minimum trace width.

    FreeRouting may emit short neck-down segments narrower than the DSN class
    width near component pads.  The routed board must not contain those
    segments when the design graph specifies a larger minimum, so normalize
    them to the graph value before KiCad DRC evaluates the projection.
    """
    root = parse_one(text)
    if not isinstance(root, list) or not root or root[0] != "session":
        raise SesImportError("not a session file (fail-closed)")
    routes = find_one(root, "routes")
    if routes is None:
        raise SesImportError("session has no routes section (fail-closed)")
    divisor = _resolution_divisor(routes)
    network_out = find_one(routes, "network_out")
    if network_out is None:
        raise SesImportError("session has no network_out section (fail-closed)")

    wires: list[RoutedWire] = []
    vias: list[RoutedVia] = []
    observed_widths: list[float] = []
    normalized_wire_count = 0
    for net in find_all(network_out, "net"):
        if len(net) < 2:
            raise SesImportError("net entry missing name (fail-closed)")
        net_name = _as_str(net[1])
        for wire in find_all(net, "wire"):
            path = find_one(wire, "path")
            if path is None or len(path) < 3:
                raise SesImportError(f"net {net_name!r}: wire without path (fail-closed)")
            layer = _as_str(path[1])
            width_mm = _as_float(path[2]) / divisor
            observed_widths.append(width_mm)
            if minimum_width_mm is not None:
                normalized_width_mm = max(width_mm, minimum_width_mm)
                if normalized_width_mm != width_mm:
                    normalized_wire_count += 1
                width_mm = normalized_width_mm
            coords = [_as_float(item) for item in path[3:] if isinstance(item, str)]
            if len(coords) < 4 or len(coords) % 2 != 0:
                raise SesImportError(f"net {net_name!r}: malformed wire path (fail-closed)")
            points = tuple(
                (coords[i] / divisor, -coords[i + 1] / divisor)
                for i in range(0, len(coords), 2)
            )
            wires.append(RoutedWire(net=net_name, layer=layer, width_mm=width_mm, points=points))
        for via in find_all(net, "via"):
            if len(via) < 4:
                raise SesImportError(f"net {net_name!r}: malformed via (fail-closed)")
            vias.append(
                RoutedVia(
                    net=net_name,
                    x_mm=_as_float(via[2]) / divisor,
                    y_mm=-_as_float(via[3]) / divisor,
                )
            )
    if not wires:
        raise SesImportError("session contains no routed wires (fail-closed)")
    return RoutedDesign(
        wires=tuple(wires),
        vias=tuple(vias),
        observed_min_width_mm=min(observed_widths),
        normalized_wire_count=normalized_wire_count,
    )
