"""Pure geometry helpers for the repository QR silkscreen asset."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

QR_DATA_MODULES = 37
QR_QUIET_ZONE_MODULES = 4
_TOKEN_RE = re.compile(r"[A-Za-z]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _path_contours(data: str) -> tuple[tuple[tuple[float, float], ...], ...]:
    tokens = _TOKEN_RE.findall(data)
    index = 0
    command: str | None = None
    current: tuple[float, float] = (0.0, 0.0)
    start: tuple[float, float] = current
    contours: list[list[tuple[float, float]]] = []

    def take() -> float:
        nonlocal index
        if index >= len(tokens) or tokens[index].isalpha():
            raise ValueError("QR SVG path is missing a coordinate")
        value = float(tokens[index])
        index += 1
        return value

    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
        if command is None:
            raise ValueError("QR SVG path starts without a command")
        absolute = command.isupper()
        op = command.upper()
        if op == "Z":
            if contours and contours[-1][-1] != start:
                contours[-1].append(start)
            current = start
            command = None
            continue
        if op not in {"M", "L", "H", "V"}:
            raise ValueError(f"QR SVG path command {command!r} is unsupported")
        if op == "M":
            x: float = take()
            y: float = take()
            current = (x, y) if absolute else (current[0] + x, current[1] + y)
            start = current
            contours.append([current])
            command = "L" if absolute else "l"
            continue
        if op == "L":
            x, y = take(), take()
            current = (x, y) if absolute else (current[0] + x, current[1] + y)
        elif op == "H":
            x = take()
            current = (x, current[1]) if absolute else (current[0] + x, current[1])
        else:
            y = take()
            current = (current[0], y) if absolute else (current[0], current[1] + y)
        contours[-1].append(current)
    return tuple(tuple(contour) for contour in contours)


def qr_module_matrix_from_svg(path: Path) -> tuple[tuple[str, ...], float]:
    """Extract the 37x37 unprinted-module matrix and source cell pitch."""
    root = ET.fromstring(path.read_bytes())
    viewbox = root.attrib.get("viewBox")
    if viewbox is None:
        raise ValueError("QR SVG viewBox is missing")
    values = tuple(float(item) for item in viewbox.replace(",", " ").split())
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        raise ValueError("QR SVG viewBox is invalid")
    paths = [
        child
        for child in root.iter()
        if child.tag.rsplit("}", 1)[-1] == "path"
        and child.attrib.get("fill-rule", "").lower() == "evenodd"
    ]
    if len(paths) != 1:
        raise ValueError("QR SVG must contain exactly one even-odd path")
    contours = _path_contours(paths[0].attrib.get("d", ""))
    if len(contours) < 2:
        raise ValueError("QR SVG even-odd path has no module holes")
    source_width, source_height = values[2], values[3]
    full_modules = QR_DATA_MODULES + 2 * QR_QUIET_ZONE_MODULES
    pitch = source_width / full_modules
    if abs(source_height / full_modules - pitch) > 1e-9:
        raise ValueError("QR SVG source is not square")
    holes = tuple(
        (
            min(point[0] for point in contour),
            min(point[1] for point in contour),
            max(point[0] for point in contour),
            max(point[1] for point in contour),
        )
        for contour in contours[1:]
    )
    matrix: list[str] = []
    origin = QR_QUIET_ZONE_MODULES * pitch
    for row in range(QR_DATA_MODULES):
        bits: list[str] = []
        for column in range(QR_DATA_MODULES):
            x1 = origin + column * pitch
            y1 = origin + row * pitch
            center_x = x1 + pitch / 2.0
            center_y = y1 + pitch / 2.0
            hole = any(
                x_min <= center_x < x_max and y_min <= center_y < y_max
                for x_min, y_min, x_max, y_max in holes
            )
            bits.append("1" if hole else "0")
        matrix.append("".join(bits))
    return tuple(matrix), pitch
