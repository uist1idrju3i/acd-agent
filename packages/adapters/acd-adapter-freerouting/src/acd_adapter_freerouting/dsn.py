"""Specctra DSN export from the tool-neutral board model.

Coordinates are emitted in micrometres with the Y axis flipped (DSN is
Y-up, the board model is Y-down). Pad shapes are approximated by their
bounding geometry (circle, rect, oval); this is conservative for routing
clearance and final DRC still runs on the exact KiCad geometry.
"""

from __future__ import annotations

from acd_core.board_model import BoardModel, FootprintShape, KeepoutRect, PadShape


class DsnExportError(ValueError):
    """Raised when the board model cannot be expressed as DSN (fail-closed)."""


_LAYERS = ("F.Cu", "B.Cu")


def _um(value_mm: float) -> str:
    return str(round(value_mm * 1000.0))


def _point(x_mm: float, y_mm: float) -> str:
    return f"{_um(x_mm)} {_um(-y_mm)}"


def _pad_axes(pad: PadShape) -> tuple[float, float]:
    if pad.rotation_deg % 180.0 == 90.0:
        return pad.size_y_mm, pad.size_x_mm
    if pad.rotation_deg % 180.0 == 0.0:
        return pad.size_x_mm, pad.size_y_mm
    raise DsnExportError(f"unsupported pad rotation {pad.rotation_deg} (fail-closed)")


def _padstack_name(pad: PadShape) -> str:
    size_x, size_y = _pad_axes(pad)
    layers = "A" if pad.through_hole or (pad.on_front and pad.on_back) else "T"
    return f"Pad_{pad.shape}_{_um(size_x)}x{_um(size_y)}_{layers}"


def _padstack_shapes(pad: PadShape) -> list[str]:
    size_x, size_y = _pad_axes(pad)
    if pad.through_hole or (pad.on_front and pad.on_back):
        layers = list(_LAYERS)
    elif pad.on_front:
        layers = ["F.Cu"]
    elif pad.on_back:
        layers = ["B.Cu"]
    else:
        raise DsnExportError(f"pad {pad.number!r} is on no copper layer (fail-closed)")
    shapes: list[str] = []
    for layer in layers:
        if pad.shape == "circle":
            shapes.append(f"(shape (circle {layer} {_um(size_x)}))")
        elif pad.shape == "oval":
            if size_x >= size_y:
                offset = (size_x - size_y) / 2.0
                path = f"{_um(-offset)} 0 {_um(offset)} 0"
                width = _um(size_y)
            else:
                offset = (size_y - size_x) / 2.0
                path = f"0 {_um(-offset)} 0 {_um(offset)}"
                width = _um(size_x)
            shapes.append(f"(shape (path {layer} {width} {path}))")
        elif pad.shape in ("rect", "roundrect", "custom"):
            hx, hy = size_x / 2.0, size_y / 2.0
            shapes.append(
                f"(shape (rect {layer} {_um(-hx)} {_um(-hy)} {_um(hx)} {_um(hy)}))"
            )
        else:
            raise DsnExportError(f"unsupported pad shape {pad.shape!r} (fail-closed)")
    return shapes


def _via_name(board: BoardModel) -> str:
    return f"Via_{_um(board.via_diameter_mm)}:{_um(board.via_drill_mm)}"


def _image_name(footprint: FootprintShape) -> str:
    return footprint.library_ref.replace(" ", "_")


def _pin_ids(footprint: FootprintShape) -> list[tuple[PadShape, str]]:
    """Unique DSN pin ids for routable pads; duplicate pad numbers (e.g. a
    SOT-223 tab sharing pin 2) get ``@<n>`` suffixes like KiCad's exporter."""
    seen: dict[str, int] = {}
    result: list[tuple[PadShape, str]] = []
    for pad in footprint.pads:
        if not pad.number or not (pad.on_front or pad.on_back):
            continue
        count = seen.get(pad.number, 0)
        seen[pad.number] = count + 1
        pin_id = pad.number if count == 0 else f"{pad.number}@{count}"
        result.append((pad, pin_id))
    return result


def _boundary(board: BoardModel) -> str:
    w, h = board.width_mm, board.height_mm
    points = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h), (0.0, 0.0)]
    coords = " ".join(_point(x, y) for x, y in points)
    return f"(boundary (path pcb 0 {coords}))"


def _keepout(keepout: KeepoutRect) -> list[str]:
    lines: list[str] = []
    for layer in _LAYERS:
        coords = " ".join(
            _point(x, y)
            for x, y in (
                (keepout.x1_mm, keepout.y1_mm),
                (keepout.x2_mm, keepout.y1_mm),
                (keepout.x2_mm, keepout.y2_mm),
                (keepout.x1_mm, keepout.y2_mm),
                (keepout.x1_mm, keepout.y1_mm),
            )
        )
        lines.append(f'(keepout "{keepout.name}_{layer}" (polygon {layer} 0 {coords}))')
    return lines


def _hole_keepouts(board: BoardModel) -> list[str]:
    """Circular keepouts for holes of components that have no routable pads
    (e.g. NPTH mounting holes), so the router avoids them."""
    lines: list[str] = []
    for placement in board.placements:
        for index, pad in enumerate(placement.footprint.pads):
            if pad.number or pad.drill_mm is None:
                continue
            diameter = (
                max(pad.size_x_mm, pad.size_y_mm, pad.drill_mm)
                + 2.0 * board.min_clearance_mm
            )
            x = placement.x_mm + pad.x_mm
            y = placement.y_mm + pad.y_mm
            for layer in _LAYERS:
                lines.append(
                    f'(keepout "hole_{placement.refdes}_{index}_{layer}" '
                    f"(circle {layer} {_um(diameter)} {_point(x, y)}))"
                )
    return lines


def _smd_via_keepouts(board: BoardModel) -> list[str]:
    """Keep via centers outside every SMD pad plus via radius and clearance."""
    lines: list[str] = []
    margin = board.via_diameter_mm / 2.0 + board.min_clearance_mm
    for placement in board.placements:
        for index, pad in enumerate(placement.footprint.pads):
            if pad.through_hole or not (pad.on_front or pad.on_back):
                continue
            size_x, size_y = _pad_axes(pad)
            local_corners = (
                (-size_x / 2.0 - margin, -size_y / 2.0 - margin),
                (size_x / 2.0 + margin, -size_y / 2.0 - margin),
                (size_x / 2.0 + margin, size_y / 2.0 + margin),
                (-size_x / 2.0 - margin, size_y / 2.0 + margin),
            )
            angle = placement.rotation_deg
            import math

            points: list[tuple[float, float]] = []
            for dx, dy in local_corners:
                radians = math.radians(angle)
                px = pad.x_mm + dx * math.cos(radians) - dy * math.sin(radians)
                py = pad.y_mm + dx * math.sin(radians) + dy * math.cos(radians)
                points.append(
                    (
                        placement.x_mm + px * math.cos(radians) - py * math.sin(radians),
                        placement.y_mm + px * math.sin(radians) + py * math.cos(radians),
                    )
                )
            coords = " ".join(_point(x, y) for x, y in (*points, points[0]))
            for layer in _LAYERS:
                lines.append(
                    f'(via_keepout "via_smd_{placement.refdes}_{index}_{layer}" '
                    f"(polygon {layer} 0 {coords}))"
                )
    return lines


def export_dsn(board: BoardModel, design_name: str) -> str:
    if board.layers != 2:
        raise DsnExportError(f"only 2-layer boards supported, got {board.layers}")
    track_um = _um(board.min_track_mm)
    clearance_um = _um(board.min_clearance_mm)
    via_name = _via_name(board)

    images: dict[str, FootprintShape] = {}
    padstacks: dict[str, PadShape] = {}
    for placement in board.placements:
        images.setdefault(_image_name(placement.footprint), placement.footprint)
        for pad in placement.footprint.pads:
            if pad.number and (pad.on_front or pad.on_back):
                padstacks.setdefault(_padstack_name(pad), pad)

    lines: list[str] = [
        f'(pcb "{design_name}"',
        "  (parser (string_quote \") (space_in_quoted_tokens on)"
        ' (host_cad "acd") (host_version "0.0.1"))',
        "  (resolution um 10)",
        "  (unit um)",
        "  (structure",
    ]
    for layer in _LAYERS:
        lines.append(f"    (layer {layer} (type signal))")
    lines.append("    (via_at_smd off)")
    lines.append(f"    {_boundary(board)}")
    for keepout in board.keepouts:
        for entry in _keepout(keepout):
            lines.append(f"    {entry}")
    for entry in _hole_keepouts(board):
        lines.append(f"    {entry}")
    for entry in _smd_via_keepouts(board):
        lines.append(f"    {entry}")
    lines.append(f'    (via "{via_name}")')
    lines.append(f"    (rule (width {track_um}) (clearance {clearance_um})")
    lines.append(f"      (clearance {clearance_um} (type default_smd))")
    lines.append("      (clearance 100 (type smd_smd)))")
    lines.append("  )")

    lines.append("  (placement")
    for placement in sorted(board.placements, key=lambda p: p.refdes):
        if not any(p.number for p in placement.footprint.pads):
            continue
        side = "front" if placement.side == "front" else "back"
        rotation = round(placement.rotation_deg % 360.0, 4)
        lines.append(f'    (component "{_image_name(placement.footprint)}"')
        lines.append(
            f'      (place "{placement.refdes}" '
            f"{_point(placement.x_mm, placement.y_mm)} {side} {rotation:g}))"
        )
    lines.append("  )")

    lines.append("  (library")
    for name in sorted(images):
        footprint = images[name]
        lines.append(f'    (image "{name}"')
        for pad, pin_id in _pin_ids(footprint):
            lines.append(
                f'      (pin "{_padstack_name(pad)}" "{pin_id}" '
                f"{_point(pad.x_mm, pad.y_mm)})"
            )
        lines.append("    )")
    for name in sorted(padstacks):
        pad = padstacks[name]
        lines.append(f'    (padstack "{name}"')
        for shape in _padstack_shapes(pad):
            lines.append(f"      {shape}")
        lines.append("      (attach off)")
        lines.append("    )")
    via_diameter = _um(board.via_diameter_mm)
    lines.append(f'    (padstack "{via_name}"')
    for layer in _LAYERS:
        lines.append(f"      (shape (circle {layer} {via_diameter}))")
    lines.append("      (attach off)")
    lines.append("    )")
    lines.append("  )")

    lines.append("  (network")
    net_names: list[str] = []
    for net in sorted(board.nets, key=lambda n: n.name):
        if not net.pads:
            continue
        net_names.append(net.name)
        pin_refs: list[str] = []
        for refdes, pad_number in sorted(net.pads):
            footprint = board.placement_by_refdes(refdes).footprint
            matches = [
                pin_id for pad, pin_id in _pin_ids(footprint) if pad.number == pad_number
            ]
            if not matches:
                raise DsnExportError(
                    f"net {net.name!r}: pad {refdes}-{pad_number} not routable (fail-closed)"
                )
            pin_refs.extend(f"{refdes}-{pin_id}" for pin_id in matches)
        lines.append(f'    (net "{net.name}" (pins {" ".join(pin_refs)}))')
    quoted_nets = " ".join(f'"{name}"' for name in net_names)
    lines.append(f'    (class kicad_default "" {quoted_nets}')
    lines.append(f'      (circuit (use_via "{via_name}"))')
    lines.append(f"      (rule (width {track_um}) (clearance {clearance_um}))")
    lines.append("    )")
    lines.append("  )")
    lines.append("  (wiring)")
    lines.append(")")
    return "\n".join(lines) + "\n"
