"""Pure functions for deterministic KiCad SVG normalization and measurement."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

SVG_TITLE_NORMALIZATION_RULE_ID = "kicad-svg-title-v1"
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


def measure_svg_resolution(svg: bytes) -> MeasuredSvgResolution:
    """Measure width, height, and viewBox directly from an SVG root."""
    try:
        text = svg.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SvgResolutionError("SVG must be UTF-8") from exc
    roots = list(_SVG_ROOT_PATTERN.finditer(text))
    if len(roots) != 1:
        raise SvgResolutionError("SVG must contain exactly one root element")
    attributes = {
        match.group("name"): match.group("value")
        for match in _ATTRIBUTE_PATTERN.finditer(roots[0].group("attributes"))
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
