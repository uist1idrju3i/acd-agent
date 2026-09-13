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
BYTE_EXACT_SVG_NORMALIZATION_RULE_IDS = frozenset(
    {ACD_SVG_NORMALIZATION_RULE_ID, CAD_SVG_NORMALIZATION_RULE_ID}
)
SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION = (
    "Replace the single KiCad SVG title containing output filename and "
    "second-resolution creation time with a fixed title."
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


class SvgNormalizationError(ValueError):
    """Raised when an SVG is not safe to normalize."""


class SvgResolutionError(ValueError):
    """Raised when an SVG root does not carry measurable resolution."""


@dataclass(frozen=True)
class MeasuredSvgResolution:
    width: str
    height: str
    view_box: tuple[float, float, float, float]


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


def normalized_svg_sha256(svg: bytes) -> str:
    """Return the hash of an SVG after strict title normalization."""
    normalized = normalize_svg(svg)
    return f"sha256:{hashlib.sha256(normalized).hexdigest()}"


def svg_source_hash(svg: bytes, normalization_rule_id: str) -> str:
    """Hash SVG bytes under the normalization rule recorded for the projection."""
    if normalization_rule_id == SVG_TITLE_NORMALIZATION_RULE_ID:
        return normalized_svg_sha256(svg)
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


def cad_view_geometry(svg: bytes) -> tuple[str, str, tuple[str, str, str, str]]:
    """Return the geometry strings from the single nested CAD view."""
    try:
        root = ElementTree.fromstring(svg)
    except (ElementTree.ParseError, UnicodeDecodeError) as exc:
        raise ValueError("CAD SVG could not be parsed") from exc
    views = [element for element in root.iter() if element.attrib.get("id") == "cad-view"]
    if len(views) != 1:
        raise ValueError("CAD SVG must contain exactly one svg#cad-view")
    view = views[0]
    if view.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError("CAD SVG cad-view must be an svg element")
    width = view.attrib.get("width")
    height = view.attrib.get("height")
    view_box = view.attrib.get("viewBox")
    if width is None or height is None or view_box is None:
        raise ValueError("CAD SVG cad-view geometry is incomplete")
    values = tuple(view_box.split())
    if len(values) != 4:
        raise ValueError("CAD SVG cad-view viewBox is malformed")
    return width, height, values
