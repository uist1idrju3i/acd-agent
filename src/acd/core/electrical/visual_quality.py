"""Deterministic SVG readability analysis for L2 visual steering."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from xml.etree import ElementTree

from acd.schema.visual_quality import (
    ReadabilityFinding,
    ReadabilityPolicy,
    ReadabilityReport,
)

_DEFAULT_FONT_SIZE = 16.0
_GLYPH_WIDTH_RATIO = 0.6
_TRANSFORM_FUNCTION_PATTERN = re.compile(r"(translate|scale|matrix)\s*\(([^)]*)\)")
_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)")
_COLOR_NAMES = {
    "black": (0, 0, 0),
    "blue": (0, 0, 255),
    "gray": (128, 128, 128),
    "green": (0, 128, 0),
    "lime": (0, 255, 0),
    "maroon": (128, 0, 0),
    "navy": (0, 0, 128),
    "olive": (128, 128, 0),
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
    "red": (255, 0, 0),
    "silver": (192, 192, 192),
    "teal": (0, 128, 128),
    "white": (255, 255, 255),
    "yellow": (255, 255, 0),
}


@dataclass(frozen=True)
class _TextBox:
    element_id: str
    x: float
    y: float
    width: float
    height: float
    font_size: float
    fill: str | None
    ancestors: tuple[ElementTree.Element, ...]

    @property
    def left(self) -> float:
        return self.x

    @property
    def top(self) -> float:
        return self.y - self.height

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _style_attributes(element: ElementTree.Element) -> dict[str, str]:
    style = element.attrib.get("style", "")
    values: dict[str, str] = {}
    for declaration in style.split(";"):
        if ":" not in declaration:
            continue
        key, value = declaration.split(":", 1)
        values[key.strip().lower()] = value.strip()
    return values


def _inherited_attribute(
    element: ElementTree.Element,
    ancestors: tuple[ElementTree.Element, ...],
    name: str,
) -> str | None:
    for candidate in (element, *reversed(ancestors)):
        value = candidate.attrib.get(name)
        if value is not None:
            return value
        value = _style_attributes(candidate).get(name)
        if value is not None:
            return value
    return None


def _parse_number(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    match = _NUMBER_PATTERN.search(value)
    if match is None:
        raise ValueError("numeric SVG value is invalid")
    parsed = float(match.group(0))
    if not math.isfinite(parsed):
        raise ValueError("numeric SVG value is not finite")
    return parsed


def _parse_font_size(value: str | None) -> float:
    parsed = _parse_number(value)
    if parsed <= 0:
        raise ValueError("font-size must be positive")
    return parsed


def _parse_viewbox(root: ElementTree.Element) -> tuple[float, float, float, float]:
    raw = root.attrib.get("viewBox")
    if raw is None:
        raise ValueError("SVG viewBox is missing")
    values = raw.replace(",", " ").split()
    if len(values) != 4:
        raise ValueError("SVG viewBox must contain four values")
    viewbox = (
        float(values[0]),
        float(values[1]),
        float(values[2]),
        float(values[3]),
    )
    if not all(math.isfinite(value) for value in viewbox):
        raise ValueError("SVG viewBox values must be finite")
    if viewbox[2] <= 0 or viewbox[3] <= 0:
        raise ValueError("SVG viewBox dimensions must be positive")
    return viewbox


def _parse_color(value: str | None) -> tuple[float, float, float] | None:
    if value is None or value.strip().lower() in {"none", "transparent"}:
        return None
    normalized = value.strip().lower()
    if normalized in _COLOR_NAMES:
        red, green, blue = _COLOR_NAMES[normalized]
        return red / 255, green / 255, blue / 255
    if re.fullmatch(r"#[0-9a-f]{6}", normalized):
        return (
            int(normalized[1:3], 16) / 255,
            int(normalized[3:5], 16) / 255,
            int(normalized[5:7], 16) / 255,
        )
    if re.fullmatch(r"#[0-9a-f]{3}", normalized):
        return (
            int(normalized[1] * 2, 16) / 255,
            int(normalized[2] * 2, 16) / 255,
            int(normalized[3] * 2, 16) / 255,
        )
    match = re.fullmatch(
        r"rgb\(\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*\)",
        normalized,
    )
    if match is not None:
        channels = (
            float(match.group(1)) / 255,
            float(match.group(2)) / 255,
            float(match.group(3)) / 255,
        )
        if all(0 <= channel <= 1 for channel in channels):
            return channels
    raise ValueError(f"unsupported SVG color: {value}")


def _luminance(color: tuple[float, float, float]) -> float:
    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(
    foreground: tuple[float, float, float], background: tuple[float, float, float]
) -> float:
    first = _luminance(foreground)
    second = _luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _transform_offset(
    element: ElementTree.Element,
    ancestors: tuple[ElementTree.Element, ...],
) -> tuple[float, float, float, float, bool]:
    resolved = True

    def compose(
        first: tuple[float, float, float, float, float, float],
        second: tuple[float, float, float, float, float, float],
    ) -> tuple[float, float, float, float, float, float]:
        a, b, c, d, e, f = first
        g, h, i, j, k, last = second
        return (
            a * g + c * h,
            b * g + d * h,
            a * i + c * j,
            b * i + d * j,
            a * k + c * last + e,
            b * k + d * last + f,
        )

    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for candidate in (*ancestors, element):
        transform = candidate.attrib.get("transform")
        if transform is None:
            continue
        cursor = 0
        local = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        for match in _TRANSFORM_FUNCTION_PATTERN.finditer(transform):
            if transform[cursor : match.start()].strip(" ,"):
                resolved = False
                break
            values = [
                float(value) for value in re.split(r"[\s,]+", match.group(2).strip()) if value
            ]
            kind = match.group(1)
            if kind == "translate" and len(values) in {1, 2}:
                local = compose(
                    local,
                    (
                        1,
                        0,
                        0,
                        1,
                        values[0],
                        values[-1] if len(values) == 2 else 0,
                    ),
                )
            elif kind == "scale" and len(values) in {1, 2}:
                sy = values[-1] if len(values) == 2 else values[0]
                local = compose(local, (values[0], 0, 0, sy, 0, 0))
            elif kind == "matrix" and len(values) == 6 and values[1] == 0 and values[2] == 0:
                local = compose(
                    local,
                    (
                        values[0],
                        values[1],
                        values[2],
                        values[3],
                        values[4],
                        values[5],
                    ),
                )
            else:
                resolved = False
                break
            cursor = match.end()
        if transform[cursor:].strip(" ,"):
            resolved = False
        if resolved:
            matrix = compose(matrix, local)
    return matrix[4], matrix[5], matrix[0], matrix[3], resolved


def _text_content(element: ElementTree.Element) -> str:
    if _local_name(element.tag) == "text" and any(
        _local_name(child.tag) == "tspan" for child in element
    ):
        return element.text or ""
    return "".join(element.itertext())


def _raster_px_per_unit(
    root: ElementTree.Element, viewbox: tuple[float, float, float, float]
) -> float | None:
    width = root.attrib.get("width", "")
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)px\s*", width)
    if match is None:
        return None
    pixels = float(match.group(1))
    return pixels / viewbox[2] if pixels > 0 else None


def _unknown_report(
    policy: ReadabilityPolicy,
    code: str,
    detail: str,
    *,
    viewbox: tuple[float, float, float, float] | None = None,
    text_count: int = 0,
) -> ReadabilityReport:
    return ReadabilityReport(
        status="unknown",
        findings=[
            ReadabilityFinding(
                code=code,  # type: ignore[arg-type]
                detail=detail,
            )
        ],
        text_count=text_count,
        viewbox=viewbox,
        policy_hash=policy.policy_hash(),
    )


def analyze_svg_readability(
    svg: bytes,
    *,
    policy: ReadabilityPolicy,
) -> ReadabilityReport:
    """Analyze SVG text geometry and contrast without modifying the projection."""
    try:
        root = ElementTree.fromstring(svg)
    except (ElementTree.ParseError, UnicodeDecodeError) as exc:
        return _unknown_report(policy, "malformed_svg", str(exc))
    try:
        viewbox = _parse_viewbox(root)
    except ValueError as exc:
        return _unknown_report(policy, "unknown_viewbox", str(exc))

    findings: list[ReadabilityFinding] = []
    boxes: list[_TextBox] = []
    text_count = 0

    def visit(element: ElementTree.Element, ancestors: tuple[ElementTree.Element, ...]) -> None:
        nonlocal text_count
        tag = _local_name(element.tag)
        if tag in {"text", "tspan"}:
            content = _text_content(element)
            if content.strip():
                text_count += 1
                element_id = element.attrib.get("id", f"text-{text_count:04d}")
                explicit_size = _inherited_attribute(element, ancestors, "font-size")
                if explicit_size is None:
                    font_size = _DEFAULT_FONT_SIZE
                    findings.append(
                        ReadabilityFinding(
                            code="font_size_missing",
                            element_id=element_id,
                            detail="no explicit font-size in the inheritance chain",
                        )
                    )
                else:
                    try:
                        font_size = _parse_font_size(explicit_size)
                    except ValueError as exc:
                        font_size = _DEFAULT_FONT_SIZE
                        findings.append(
                            ReadabilityFinding(
                                code="unknown_font_size",
                                element_id=element_id,
                                detail=str(exc),
                            )
                        )
                x = _parse_number(_inherited_attribute(element, ancestors, "x"), default=0.0)
                y = _parse_number(_inherited_attribute(element, ancestors, "y"), default=0.0)
                (
                    offset_x,
                    offset_y,
                    scale_x,
                    scale_y,
                    transform_resolved,
                ) = _transform_offset(element, ancestors)
                if not transform_resolved:
                    findings.append(
                        ReadabilityFinding(
                            code="unresolved_transform",
                            element_id=element_id,
                            detail=(
                                "supported transforms are translate, scale, and diagonal matrix"
                            ),
                        )
                    )
                fill = _inherited_attribute(element, ancestors, "fill")
                width = len(content) * font_size * _GLYPH_WIDTH_RATIO
                anchor = _inherited_attribute(element, ancestors, "text-anchor")
                if anchor == "end":
                    x -= width
                elif anchor == "middle":
                    x -= width / 2
                transformed_x = x * scale_x + offset_x
                transformed_y = y * scale_y + offset_y
                transformed_width = width * abs(scale_x)
                transformed_height = font_size * abs(scale_y)
                if scale_x < 0:
                    transformed_x -= transformed_width
                if scale_y < 0:
                    transformed_y += transformed_height
                boxes.append(
                    _TextBox(
                        element_id=element_id,
                        x=transformed_x,
                        y=transformed_y,
                        width=transformed_width,
                        height=transformed_height,
                        font_size=font_size * abs(scale_y),
                        fill=fill,
                        ancestors=ancestors,
                    )
                )
        next_ancestors = (*ancestors, element)
        for child in element:
            visit(child, next_ancestors)

    try:
        visit(root, ())
    except ValueError as exc:
        return _unknown_report(
            policy,
            "malformed_svg",
            str(exc),
            viewbox=viewbox,
            text_count=text_count,
        )

    px_per_unit = _raster_px_per_unit(root, viewbox) or policy.default_px_per_unit
    if px_per_unit is None:
        findings.append(
            ReadabilityFinding(
                code="unknown_resolution",
                detail="raster pixels-per-unit is unavailable",
            )
        )
    for box in boxes:
        if box.font_size / min(viewbox[2], viewbox[3]) > policy.max_text_ratio:
            findings.append(
                ReadabilityFinding(
                    code="text_oversized",
                    element_id=box.element_id,
                    detail="font-size exceeds the configured viewBox ratio",
                )
            )
        if px_per_unit is not None and box.font_size * px_per_unit < policy.min_text_px:
            findings.append(
                ReadabilityFinding(
                    code="text_too_small",
                    element_id=box.element_id,
                    detail="rendered text is below the configured pixel floor",
                )
            )
        if (
            box.left < viewbox[0]
            or box.top < viewbox[1]
            or box.right > viewbox[0] + viewbox[2]
            or box.bottom > viewbox[1] + viewbox[3]
        ):
            findings.append(
                ReadabilityFinding(
                    code="text_out_of_viewbox",
                    element_id=box.element_id,
                    detail="estimated glyph box extends outside the viewBox",
                )
            )
        try:
            text_color = _parse_color(box.fill)
        except ValueError as exc:
            findings.append(
                ReadabilityFinding(
                    code="unknown_color",
                    element_id=box.element_id,
                    detail=str(exc),
                )
            )
            text_color = None
        background_value: str | None = None
        for ancestor in reversed(box.ancestors):
            if _local_name(ancestor.tag) == "rect":
                background_value = ancestor.attrib.get("fill") or _style_attributes(ancestor).get(
                    "fill"
                )
                if background_value is not None:
                    break
        if background_value is None and box.ancestors:
            root_element = box.ancestors[0]
            for sibling in root_element:
                if _local_name(sibling.tag) != "rect":
                    continue
                background_value = sibling.attrib.get("fill") or _style_attributes(sibling).get(
                    "fill"
                )
                if background_value is not None:
                    break
        if background_value is None:
            background_value = root.attrib.get("background") or _style_attributes(root).get(
                "background-color"
            )
        if text_color is not None and background_value not in {None, "none", "transparent"}:
            try:
                background = _parse_color(background_value)
            except ValueError as exc:
                findings.append(
                    ReadabilityFinding(
                        code="unknown_color",
                        element_id=box.element_id,
                        detail=str(exc),
                    )
                )
            else:
                if background is not None and _contrast_ratio(text_color, background) < (
                    policy.min_contrast_ratio
                ):
                    findings.append(
                        ReadabilityFinding(
                            code="low_contrast",
                            element_id=box.element_id,
                            detail="text/background contrast is below the configured ratio",
                        )
                    )

    boxes.sort(key=lambda box: (box.y, box.x, box.element_id))
    for index, first in enumerate(boxes):
        for second in boxes[index + 1 :]:
            width = max(0.0, min(first.right, second.right) - max(first.left, second.left))
            height = max(0.0, min(first.bottom, second.bottom) - max(first.top, second.top))
            intersection = width * height
            denominator = min(first.width * first.height, second.width * second.height)
            ratio = intersection / denominator if denominator > 0 else 0.0
            if ratio > policy.max_overlap_ratio:
                findings.append(
                    ReadabilityFinding(
                        code="text_overlap",
                        element_id=f"{first.element_id},{second.element_id}",
                        detail="estimated glyph boxes overlap beyond the configured ratio",
                    )
                )

    failure_codes = {
        "font_size_missing",
        "text_oversized",
        "text_too_small",
        "text_overlap",
        "text_out_of_viewbox",
        "low_contrast",
    }
    status = (
        "fail"
        if any(item.code in failure_codes for item in findings)
        else "unknown"
        if findings
        else "pass"
    )
    return ReadabilityReport(
        status=status,
        findings=findings,
        text_count=text_count,
        viewbox=viewbox,
        policy_hash=policy.policy_hash(),
    )


__all__ = ["analyze_svg_readability"]
