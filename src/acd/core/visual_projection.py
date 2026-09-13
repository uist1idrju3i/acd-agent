"""Pure functions for deterministic KiCad SVG normalization and measurement."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from xml.etree import ElementTree

SVG_TITLE_NORMALIZATION_RULE_ID = "kicad-svg-title-v1"
ACD_SVG_NORMALIZATION_RULE_ID = "acd-svg-v1"
CAD_SVG_NORMALIZATION_RULE_ID = "build123d-svg-v1"
KICAD_LAYER_SVG_NORMALIZATION_RULE_ID = "kicad-layer-svg-title-v1"
BYTE_EXACT_SVG_NORMALIZATION_RULE_IDS = frozenset(
    {ACD_SVG_NORMALIZATION_RULE_ID, CAD_SVG_NORMALIZATION_RULE_ID}
)
SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION = (
    "Replace the single KiCad SVG title containing output filename and "
    "second-resolution creation time with a fixed title."
)
KICAD_LAYER_SVG_NORMALIZATION_RULE_DESCRIPTION = (
    "Replace the single KiCad SVG title inside svg#layer-view containing "
    "output filename and creation time with a fixed title; the outer "
    "acd-svg document is hashed byte-exact."
)
_NORMALIZED_TITLE = (
    "<title>SVG Image created as normalized.svg date 1970-01-01T00:00:00Z </title>"
)
_TITLE_CONTENT = (
    r"SVG Image created as [^<>\r\n]+ date "
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})? "
)
_TITLE_PATTERN = re.compile(r"<title>" + _TITLE_CONTENT + r"</title>")
_SVG_ROOT_PATTERN = re.compile(r"<svg\b(?P<attributes>[^>]*)>", re.DOTALL)
_SVG_CLOSE_PATTERN = re.compile(r"</svg\s*>")
_SVG_PREFIX_PATTERN = re.compile(
    r"(?:\s|<!--.*?-->|<\?xml\b.*?\?>|<!DOCTYPE\b.*?>)*",
    re.DOTALL,
)
_ATTRIBUTE_PATTERN = re.compile(
    r'(?P<name>width|height|viewBox)\s*=\s*"(?P<value>[^"]*)"'
)
_DIMENSION_PATTERN = re.compile(
    r"^(?P<value>(?:0|[1-9][0-9]*)(?:\.[0-9]+)?)(?P<unit>mm|cm|in|pt|pc)$"
)
_RAW_SVG_ATTRIBUTE_PATTERN = re.compile(
    r'(?P<name>[A-Za-z_][A-Za-z0-9_.:-]*)\s*=\s*"(?P<value>[^"]*)"'
)


class SvgNormalizationError(ValueError):
    """Raised when an SVG is not safe to normalize."""


class SvgResolutionError(ValueError):
    """Raised when an SVG root does not carry measurable resolution."""


@dataclass(frozen=True)
class MeasuredSvgResolution:
    width: str
    height: str
    view_box: tuple[float, float, float, float]


@dataclass(frozen=True)
class LayerViewAnnotations:
    project_name: str
    layer: str
    board_width_mm: float
    board_height_mm: float
    layer_count: int


def normalize_svg(svg: bytes) -> bytes:
    """Replace exactly one expected KiCad title and no other SVG content."""
    try:
        text = svg.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SvgNormalizationError("SVG must be UTF-8") from exc
    if text.count("<title") != 1 or text.count("</title>") != 1:
        raise SvgNormalizationError("SVG must contain exactly one title element")
    match = _TITLE_PATTERN.search(text)
    if match is None:
        raise SvgNormalizationError("SVG title does not match the KiCad format")
    return (text[: match.start()] + _NORMALIZED_TITLE + text[match.end() :]).encode("utf-8")


def _element_bounds(text: str, element_id: str) -> tuple[int, int] | None:
    roots = list(_SVG_ROOT_PATTERN.finditer(text))
    closes = list(_SVG_CLOSE_PATTERN.finditer(text))
    events = sorted(
        [(match.start(), True, match) for match in roots]
        + [(match.start(), False, match) for match in closes],
        key=lambda event: event[0],
    )
    stack: list[re.Match[str]] = []
    for _position, is_open, match in events:
        if is_open:
            if not match.group(0).rstrip().endswith("/>"):
                stack.append(match)
        elif stack:
            opening = stack.pop()
            attributes = {
                item.group("name"): item.group("value")
                for item in _RAW_SVG_ATTRIBUTE_PATTERN.finditer(
                    opening.group("attributes")
                )
            }
            if attributes.get("id") == element_id:
                return opening.start(), match.start()
    return None


def normalize_kicad_layer_svg(svg: bytes) -> bytes:
    """Normalize the volatile KiCad title inside the nested layer view."""
    try:
        text = svg.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SvgNormalizationError("SVG must be UTF-8") from exc
    if text.count("<title") != 2 or text.count("</title>") != 2:
        raise SvgNormalizationError(
            "KiCad layer SVG must contain exactly two title elements"
        )
    matches = list(_TITLE_PATTERN.finditer(text))
    if len(matches) != 1:
        raise SvgNormalizationError("KiCad layer SVG title does not match the KiCad format")
    bounds = _element_bounds(text, "layer-view")
    if bounds is None:
        raise SvgNormalizationError("KiCad layer SVG must contain svg#layer-view")
    title = matches[0]
    if not bounds[0] < title.start() < bounds[1]:
        raise SvgNormalizationError(
            "KiCad layer SVG title must be inside svg#layer-view"
        )
    return (text[: title.start()] + _NORMALIZED_TITLE + text[title.end() :]).encode(
        "utf-8"
    )


def normalized_svg_sha256(svg: bytes) -> str:
    """Return the hash of an SVG after strict title normalization."""
    normalized = normalize_svg(svg)
    return f"sha256:{hashlib.sha256(normalized).hexdigest()}"


def svg_source_hash(svg: bytes, normalization_rule_id: str) -> str:
    """Hash SVG bytes under the normalization rule recorded for the projection."""
    if normalization_rule_id == SVG_TITLE_NORMALIZATION_RULE_ID:
        return normalized_svg_sha256(svg)
    if normalization_rule_id == KICAD_LAYER_SVG_NORMALIZATION_RULE_ID:
        normalized = normalize_kicad_layer_svg(svg)
        return f"sha256:{hashlib.sha256(normalized).hexdigest()}"
    if normalization_rule_id in BYTE_EXACT_SVG_NORMALIZATION_RULE_IDS:
        return f"sha256:{hashlib.sha256(svg).hexdigest()}"
    raise SvgNormalizationError(
        f"unsupported SVG normalization rule: {normalization_rule_id}"
    )


def measure_svg_resolution(svg: bytes) -> MeasuredSvgResolution:
    """Measure width, height, and viewBox directly from an SVG root."""
    try:
        text = svg.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SvgResolutionError("SVG must be UTF-8") from exc
    roots = list(_SVG_ROOT_PATTERN.finditer(text))
    closes = list(_SVG_CLOSE_PATTERN.finditer(text))
    if not roots or not closes or not _SVG_PREFIX_PATTERN.fullmatch(text[: roots[0].start()]):
        raise SvgResolutionError("SVG must contain exactly one root element")
    root = roots[0]
    depth = 0
    matching_close: re.Match[str] | None = None
    events = sorted(
        [(match.start(), True, match) for match in roots]
        + [(match.start(), False, match) for match in closes],
        key=lambda event: event[0],
    )
    for _position, is_open, match in events:
        if is_open:
            if depth == 0 and match is not roots[0]:
                raise SvgResolutionError("SVG must contain exactly one root element")
            if not match.group(0).rstrip().endswith("/>"):
                depth += 1
        else:
            depth -= 1
            if depth < 0:
                raise SvgResolutionError("SVG must contain exactly one root element")
            if depth == 0:
                if matching_close is not None:
                    raise SvgResolutionError("SVG must contain exactly one root element")
                matching_close = match
    if depth != 0 or matching_close is not closes[-1]:
        raise SvgResolutionError("SVG must contain exactly one root element")
    attributes = {
        match.group("name"): match.group("value")
        for match in _ATTRIBUTE_PATTERN.finditer(root.group("attributes"))
    }
    if set(attributes) != {"width", "height", "viewBox"}:
        raise SvgResolutionError("SVG root must declare width, height, and viewBox")
    for name in ("width", "height"):
        match = _DIMENSION_PATTERN.fullmatch(attributes[name])
        if match is None or not math.isfinite(float(match.group("value"))):
            raise SvgResolutionError(f"SVG {name} has an unknown or invalid unit")
    values = attributes["viewBox"].split()
    if len(values) != 4:
        raise SvgResolutionError("SVG viewBox must contain four values")
    try:
        view_box = (
            float(values[0]),
            float(values[1]),
            float(values[2]),
            float(values[3]),
        )
    except ValueError as exc:
        raise SvgResolutionError("SVG viewBox values must be numeric") from exc
    if not all(math.isfinite(value) for value in view_box):
        raise SvgResolutionError("SVG viewBox values must be finite")
    return MeasuredSvgResolution(
        width=attributes["width"],
        height=attributes["height"],
        view_box=view_box,
    )


def nested_view_geometry(
    svg: bytes,
    view_id: str,
) -> tuple[str, str, tuple[str, str, str, str]]:
    """Return geometry strings from one nested SVG view."""
    try:
        root = ElementTree.fromstring(svg)
    except (ElementTree.ParseError, UnicodeDecodeError) as exc:
        raise ValueError("nested SVG could not be parsed") from exc
    views = [element for element in root.iter() if element.attrib.get("id") == view_id]
    if len(views) != 1:
        raise ValueError(f"SVG must contain exactly one svg#{view_id}")
    view = views[0]
    if view.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError(f"SVG {view_id} view must be an svg element")
    width = view.attrib.get("width")
    height = view.attrib.get("height")
    view_box = view.attrib.get("viewBox")
    if width is None or height is None or view_box is None:
        raise ValueError(f"SVG {view_id} geometry is incomplete")
    values = tuple(view_box.split())
    if len(values) != 4:
        raise ValueError(f"SVG {view_id} viewBox is malformed")
    return width, height, values


def cad_view_geometry(svg: bytes) -> tuple[str, str, tuple[str, str, str, str]]:
    """Return the geometry strings from the single nested CAD view."""
    return nested_view_geometry(svg, "cad-view")


def raw_svg_parts(raw: bytes) -> tuple[str, str, float, float, str]:
    """Extract raw SVG geometry and inner markup without re-serialization."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SvgNormalizationError("raw SVG is not UTF-8") from exc
    roots = list(_SVG_ROOT_PATTERN.finditer(text))
    closing = list(_SVG_CLOSE_PATTERN.finditer(text))
    if len(roots) != 1 or len(closing) != 1:
        raise SvgNormalizationError("raw SVG must contain one root")
    root = roots[0]
    close = closing[0]
    if close.start() < root.end():
        raise SvgNormalizationError("raw SVG root is malformed")
    attributes = list(_RAW_SVG_ATTRIBUTE_PATTERN.finditer(root.group("attributes")))
    values = {match.group("name"): match.group("value") for match in attributes}
    view_box = values.get("viewBox")
    if view_box is None:
        raise SvgNormalizationError("raw SVG viewBox is missing")
    view_box_values = view_box.split()
    if len(view_box_values) != 4:
        raise SvgNormalizationError("raw SVG viewBox is malformed")
    try:
        width = float(view_box_values[2])
        height = float(view_box_values[3])
    except ValueError as exc:
        raise SvgNormalizationError("raw SVG viewBox is non-numeric") from exc
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
        raise SvgNormalizationError("raw SVG viewBox is invalid")
    kept_attributes: list[str] = []
    cursor = 0
    for match in attributes:
        if match.group("name") in {"width", "height", "viewBox", "xmlns"}:
            kept_attributes.append(root.group("attributes")[cursor : match.start()])
        else:
            kept_attributes.append(root.group("attributes")[cursor : match.end()])
        cursor = match.end()
    kept_attributes.append(root.group("attributes")[cursor:])
    return (
        view_box,
        "".join(kept_attributes).strip(),
        width,
        height,
        text[root.end() : close.start()],
    )
