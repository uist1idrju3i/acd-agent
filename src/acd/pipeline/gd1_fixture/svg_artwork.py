"""Deterministic SVG-to-silkscreen geometry conversion for GD1 artwork."""

from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

_TOKEN_RE = re.compile(r"[A-Za-z]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


@dataclass(frozen=True)
class SvgGraphicPart:
    contours: tuple[tuple[tuple[float, float], ...], ...]
    stroke_width_mm: float
    fill: str
    fill_rule: str


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _style(element: ET.Element, inherited: dict[str, str]) -> dict[str, str]:
    result = dict(inherited)
    style = element.attrib.get("style", "")
    for declaration in style.split(";"):
        if ":" in declaration:
            key, value = declaration.split(":", 1)
            result[key.strip()] = value.strip()
    for key in ("fill", "stroke", "stroke-width", "fill-rule"):
        if key in element.attrib:
            result[key] = element.attrib[key]
    return result


def _number(value: str, name: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"SVG {name} is malformed") from exc


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
            raise ValueError("SVG path is missing a coordinate")
        value = _number(tokens[index], "path coordinate")
        index += 1
        return value

    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
        if command is None:
            raise ValueError("SVG path starts without a command")
        absolute = command.isupper()
        op = command.upper()
        if op == "Z":
            if contours and contours[-1][-1] != start:
                contours[-1].append(start)
            current = start
            command = None
            continue
        if op not in {"M", "L", "H", "V"}:
            raise ValueError(f"SVG path command {command!r} is unsupported")
        if op == "M":
            x: float = take()
            y: float = take()
            if not absolute:
                x += current[0]
                y += current[1]
            current = (x, y)
            start = current
            contours.append([current])
            command = "L" if absolute else "l"
            continue
        if op == "L":
            x: float = take()
            y: float = take()
            if not absolute:
                x += current[0]
                y += current[1]
            current = (x, y)
        elif op == "H":
            x = take()
            current = (x, current[1]) if absolute else (current[0] + x, current[1])
        else:
            y = take()
            current = (current[0], y) if absolute else (current[0], current[1] + y)
        if not contours:
            raise ValueError("SVG path command precedes move-to")
        contours[-1].append(current)
    if any(len(contour) < 2 for contour in contours):
        raise ValueError("SVG path contains an insufficient contour")
    return tuple(tuple(contour) for contour in contours)


def _rect_contours(element: ET.Element) -> tuple[tuple[tuple[float, float], ...], ...]:
    x = _number(element.attrib.get("x", "0"), "rect x")
    y = _number(element.attrib.get("y", "0"), "rect y")
    width = _number(element.attrib["width"], "rect width")
    height = _number(element.attrib["height"], "rect height")
    if width <= 0 or height <= 0:
        raise ValueError("SVG rect dimensions must be positive")
    return (
        (
            (x, y),
            (x + width, y),
            (x + width, y + height),
            (x, y + height),
            (x, y),
        ),
    )


def _collect(
    element: ET.Element,
    inherited: dict[str, str],
    result: list[SvgGraphicPart],
) -> None:
    if element.attrib.get("id") == "board-preview":
        return
    style = _style(element, inherited)
    tag = element.tag.rsplit("}", 1)[-1]
    contours: tuple[tuple[tuple[float, float], ...], ...] | None = None
    if tag == "path":
        contours = _path_contours(element.attrib.get("d", ""))
    elif tag == "rect":
        contours = _rect_contours(element)
    if contours is not None:
        fill = style.get("fill", "none").lower()
        stroke = style.get("stroke", "none").lower()
        if fill != "none" or stroke != "none":
            result.append(
                SvgGraphicPart(
                    contours=contours,
                    stroke_width_mm=_number(style.get("stroke-width", "0"), "stroke width"),
                    fill=fill,
                    fill_rule=style.get("fill-rule", "nonzero").lower(),
                )
            )
    for child in element:
        _collect(child, style, result)


def load_svg(path: Path) -> tuple[tuple[float, float], tuple[SvgGraphicPart, ...]]:
    root = ET.fromstring(path.read_bytes())
    viewbox = root.attrib.get("viewBox")
    if viewbox is None:
        raise ValueError(f"{path}: SVG viewBox is missing")
    values = tuple(_number(item, "viewBox") for item in viewbox.replace(",", " ").split())
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        raise ValueError(f"{path}: SVG viewBox is invalid")
    parts: list[SvgGraphicPart] = []
    _collect(root, {}, parts)
    if not parts:
        raise ValueError(f"{path}: SVG silkscreen geometry is empty")
    offset_x, offset_y, width, height = values
    if offset_x != 0.0 or offset_y != 0.0:
        parts = [
            SvgGraphicPart(
                tuple(
                    tuple((x - offset_x, y - offset_y) for x, y in contour)
                    for contour in part.contours
                ),
                part.stroke_width_mm,
                part.fill,
                part.fill_rule,
            )
            for part in parts
        ]
    return (width, height), tuple(parts)


def place_svg(
    path: Path,
    *,
    board_width_mm: float,
    center_x_mm: float,
    center_y_mm: float,
    width_mm: float,
    layer: str = "B.SilkS",
    rotation_degrees: float = 0.0,
    minimum_stroke_width_mm: float | None = None,
) -> tuple[tuple[dict[str, object], ...], dict[str, str]]:
    (source_width, source_height), parts = load_svg(path)
    scale = width_mm / source_width
    scaled_height = source_height * scale
    radians = math.radians(rotation_degrees)
    cos_angle, sin_angle = math.cos(radians), math.sin(radians)

    def transform(point: tuple[float, float]) -> tuple[float, float]:
        local_x = (point[0] - source_width / 2.0) * scale
        local_y = (point[1] - source_height / 2.0) * scale
        rotated_x = local_x * cos_angle - local_y * sin_angle
        rotated_y = local_x * sin_angle + local_y * cos_angle
        x = center_x_mm + rotated_x
        y = center_y_mm + rotated_y
        if layer == "B.SilkS":
            x = 2.0 * center_x_mm - x
        return x, y

    encoded_parts: list[dict[str, object]] = []
    for part in parts:
        scaled_stroke = part.stroke_width_mm * scale
        if minimum_stroke_width_mm is not None and 0 < scaled_stroke < minimum_stroke_width_mm:
            raise ValueError(
                f"SVG stroke width {scaled_stroke:.9f} mm is below the "
                f"minimum silkscreen width {minimum_stroke_width_mm:.9f} mm"
            )
        encoded_parts.append(
            {
                "contours": [
                    [[round(x, 9), round(y, 9)] for x, y in (transform(point) for point in contour)]
                    for contour in part.contours
                ],
                "fill": part.fill,
                "fill_rule": part.fill_rule,
                "stroke_width_mm": round(scaled_stroke, 9),
            }
        )
    placed_width, placed_height = (
        (width_mm, scaled_height)
        if rotation_degrees % 180 == 0
        else (scaled_height, width_mm)
    )
    provenance = {
        "source_path": str(path),
        "source_sha256": sha256_of(path),
        "source_viewbox_mm": f"{source_width:g}x{source_height:g}",
        "scale": f"{scale:.9f}",
        "placed_size_mm": f"{placed_width:.9f}x{placed_height:.9f}",
        "placement_center_mm": f"{center_x_mm:.9f},{center_y_mm:.9f}",
        "rotation_degrees": f"{rotation_degrees:.9f}",
        "layer": layer,
    }
    return tuple(encoded_parts), provenance


def encode_parts(parts: tuple[dict[str, object], ...]) -> list[str]:
    return [
        json.dumps(part, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for part in parts
    ]
