"""Shared contracts and helpers for deterministic SVG observations."""

from __future__ import annotations

import html
import math
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from acd.core.process import sha256_bytes
from acd.core.visual_projection import measure_svg_resolution
from acd.schema.visual_projection import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionType,
    VisualRegenerationCheck,
    VisualRendererProvenance,
    VisualResolution,
)

ACD_SVG_RENDERER_VERSION = "2.0.0"
ACD_SVG_NORMALIZATION_RULE_ID = "acd-svg-v1"
ACD_SVG_NORMALIZATION_RULE_DESCRIPTION = "byte-exact、正規化不要"

# Text is sized relative to the viewBox so that a projection stays legible at
# any rendered scale. Board-sized diagrams use the smaller board dimension as
# the reference extent; schematic-scale diagrams use a 240-unit reference width.
BOARD_FONT_SIZE_RATIO = 0.05
DIAGRAM_FONT_SIZE_RATIO = 0.0125
DIAGRAM_REFERENCE_WIDTH = 240.0

# Human-facing diagram typography, in viewBox units relative to the body size.
TITLE_FONT_SCALE = 1.8
SUBTITLE_FONT_SCALE = 1.1
SMALL_FONT_SCALE = 0.8
# Average glyph advance of a sans-serif face relative to its font size; used
# only to size boxes deterministically, never to assert layout correctness.
GLYPH_ADVANCE_RATIO = 0.58
FONT_FAMILY = "DejaVu Sans, Liberation Sans, Arial, sans-serif"

# Shared palette (light background, dark text, WCAG-AA-level contrast).
COLOR_BACKGROUND = "#ffffff"
COLOR_TEXT = "#1a1a1a"
COLOR_TEXT_MUTED = "#555555"
COLOR_EDGE = "#4a4a4a"
COLOR_EDGE_MUTED = "#9a9a9a"
COLOR_FRONT = "#005fa3"
COLOR_BACK = "#c2410c"
COLOR_COPPER = "#b87333"
COLOR_DIELECTRIC = "#d9e2b0"
COLOR_HEADER_RULE = "#bbbbbb"
KIND_FILL = {
    "safety.boundary": "#fde2e2",
    "electrical.board": "#e0ecf8",
    "firmware.module": "#e6f4ea",
    "electrical.component": "#fff6d5",
    "electrical.net": "#ececec",
}
KIND_STROKE = {
    "safety.boundary": "#b3261e",
    "electrical.board": "#1e5aa8",
    "firmware.module": "#1b7f3b",
    "electrical.component": "#a87400",
    "electrical.net": "#666666",
}

_TEXT_ELEMENT_PATTERN = re.compile(r"<text\b[^>]*>", re.DOTALL)
_FONT_SIZE_ATTRIBUTE_PATTERN = re.compile(r'\bfont-size\s*=\s*"[^"]+"')


class SvgVisualProjectionError(ValueError):
    """Raised when a deterministic SVG projection cannot be trusted."""


def format_svg_number(value: float) -> str:
    if not math.isfinite(value):
        raise SvgVisualProjectionError("SVG geometry contains a non-finite value")
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def view_box_font_size(reference_extent: float, *, ratio: float) -> float:
    """Return a viewBox-relative font size for legible text at any scale."""
    if not math.isfinite(reference_extent) or reference_extent <= 0:
        raise SvgVisualProjectionError(
            "SVG font-size reference extent is undeclared or invalid"
        )
    if not math.isfinite(ratio) or ratio <= 0:
        raise SvgVisualProjectionError("SVG font-size ratio is invalid")
    font_size = reference_extent * ratio
    if not math.isfinite(font_size) or font_size <= 0:
        raise SvgVisualProjectionError("SVG font-size is not positive")
    return font_size


def assert_text_font_size(svg: bytes) -> None:
    """Reject an SVG whose text elements rely on the renderer default size."""
    try:
        text = svg.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SvgVisualProjectionError("SVG must be UTF-8") from exc
    for element in _TEXT_ELEMENT_PATTERN.finditer(text):
        if _FONT_SIZE_ATTRIBUTE_PATTERN.search(element.group(0)) is None:
            raise SvgVisualProjectionError(
                "SVG text element does not declare a viewBox-relative font-size"
            )


def escape_xml(value: str) -> str:
    return html.escape(value, quote=True)


def diagram_font_size() -> float:
    """Body font size shared by all schematic-scale (240-unit) diagrams."""
    return view_box_font_size(DIAGRAM_REFERENCE_WIDTH, ratio=DIAGRAM_FONT_SIZE_RATIO)


def text_advance(text: str, font_size: float, *, bold: bool = False) -> float:
    """Deterministic width estimate of a text run, for box sizing only."""
    return len(text) * font_size * GLYPH_ADVANCE_RATIO * (1.12 if bold else 1.0)


def svg_text(
    text: str,
    *,
    x: float,
    y: float,
    font_size: float,
    element_id: str | None = None,
    anchor: Literal["start", "middle", "end"] = "start",
    weight: Literal["normal", "bold"] = "normal",
    fill: str = COLOR_TEXT,
    extra: str = "",
) -> str:
    """One `<text>` element with an explicit font-size (renderer contract)."""
    attributes = [
        f'id="{element_id}"' if element_id else "",
        f'x="{format_svg_number(x)}"',
        f'y="{format_svg_number(y)}"',
        f'font-size="{format_svg_number(font_size)}"',
        f'text-anchor="{anchor}"' if anchor != "start" else "",
        'font-weight="bold"' if weight == "bold" else "",
        f'fill="{fill}"' if fill != COLOR_TEXT else "",
        extra,
    ]
    joined = " ".join(item for item in attributes if item)
    return f"<text {joined}>{escape_xml(text)}</text>"


def svg_document(
    *,
    width: float,
    height: float,
    title: str,
    subtitle: str,
    body: list[str],
    font_size: float,
    footer: str = "acd-svg L3 observation - not Evidence, does not judge the design",
) -> bytes:
    """Wrap diagram body chunks in a titled, white-background SVG document.

    The header occupies the top `header_height(font_size)` units; callers lay
    out the body below it so that title text never overlaps content.
    """
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
        raise SvgVisualProjectionError("SVG document dimensions are invalid")
    title_size = font_size * TITLE_FONT_SCALE
    subtitle_size = font_size * SUBTITLE_FONT_SCALE
    small_size = font_size * SMALL_FONT_SCALE
    chunks = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{format_svg_number(width)}mm" '
        f'height="{format_svg_number(height)}mm" '
        f'viewBox="0 0 {format_svg_number(width)} {format_svg_number(height)}">',
        f"<title>{escape_xml(title)}</title>",
        f'<rect id="background" x="0" y="0" width="{format_svg_number(width)}" '
        f'height="{format_svg_number(height)}" fill="{COLOR_BACKGROUND}"/>',
        f'<g id="document" font-family="{escape_xml(FONT_FAMILY)}" fill="{COLOR_TEXT}">',
        '<g id="header">',
        svg_text(
            title,
            x=font_size * 2,
            y=title_size * 1.4,
            font_size=title_size,
            element_id="title",
            weight="bold",
        ),
        svg_text(
            subtitle,
            x=font_size * 2,
            y=title_size * 1.4 + subtitle_size * 1.5,
            font_size=subtitle_size,
            element_id="subtitle",
            fill=COLOR_TEXT_MUTED,
        ),
        f'<line x1="{format_svg_number(font_size * 2)}" '
        f'y1="{format_svg_number(header_height(font_size) - font_size)}" '
        f'x2="{format_svg_number(width - font_size * 2)}" '
        f'y2="{format_svg_number(header_height(font_size) - font_size)}" '
        f'stroke="{COLOR_HEADER_RULE}" stroke-width="{format_svg_number(font_size * 0.1)}"/>',
        "</g>",
        *body,
        svg_text(
            footer,
            x=width - font_size * 2,
            y=height - small_size * 0.8,
            font_size=small_size,
            element_id="footer",
            anchor="end",
            fill=COLOR_TEXT_MUTED,
        ),
        "</g></svg>",
    ]
    return "".join(chunks).encode("utf-8")


def header_height(font_size: float) -> float:
    """Vertical space reserved for the title block of `svg_document`."""
    return font_size * (TITLE_FONT_SCALE * 1.4 + SUBTITLE_FONT_SCALE * 1.5 + 2.0)


def footer_height(font_size: float) -> float:
    """Vertical space reserved for the footer note of `svg_document`."""
    return font_size * SMALL_FONT_SCALE * 2.0


def arrow_marker_defs(font_size: float, *, marker_id: str = "arrow", color: str = COLOR_EDGE) -> str:
    """`<defs>` with one arrowhead marker sized relative to the body font."""
    size = font_size * 0.9
    return (
        f'<defs><marker id="{marker_id}" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="{format_svg_number(size)}" markerHeight="{format_svg_number(size)}" '
        'markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker></defs>'
    )


def legend(
    items: list[tuple[str, str, str]],
    *,
    x: float,
    y: float,
    font_size: float,
    element_id: str = "legend",
) -> list[str]:
    """Horizontal legend of `(label, fill, stroke)` swatches starting at (x, y)."""
    chunks = [f'<g id="{element_id}">']
    cursor = x
    swatch = font_size * 1.1
    for label, fill, stroke in items:
        chunks.append(
            f'<rect x="{format_svg_number(cursor)}" y="{format_svg_number(y - swatch * 0.85)}" '
            f'width="{format_svg_number(swatch)}" height="{format_svg_number(swatch)}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{format_svg_number(font_size * 0.12)}"/>'
        )
        cursor += swatch * 1.4
        chunks.append(svg_text(label, x=cursor, y=y, font_size=font_size))
        cursor += text_advance(label, font_size) + font_size * 2.0
    chunks.append("</g>")
    return chunks


def slugify_identifier(value: str) -> str:
    result = "".join(char.lower() if char.isalnum() else "-" for char in value)
    result = result.strip("-")
    if not result:
        raise SvgVisualProjectionError("SVG identifier is empty")
    return result


def relative_path(path: Path, base_dir: Path, field_name: str) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError as exc:
        raise SvgVisualProjectionError(
            f"{field_name} must be relative to its declared base directory"
        ) from exc


def input_records(paths: tuple[Path, ...], base_dir: Path) -> list[VisualProjectionInput]:
    if not paths:
        raise SvgVisualProjectionError("authoritative input files are missing")
    records: list[VisualProjectionInput] = []
    for path in paths:
        if not path.is_file():
            raise SvgVisualProjectionError(
                f"authoritative input file is missing: {path}"
            )
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise SvgVisualProjectionError(
                f"authoritative input file is unreadable: {path}"
            ) from exc
        records.append(
            VisualProjectionInput(
                path=relative_path(path, base_dir, "input file"),
                content_hash=sha256_bytes(content),
            )
        )
    if len({record.path for record in records}) != len(records):
        raise SvgVisualProjectionError("authoritative input files must be unique")
    return records


def render_svg_projection(
    *,
    projection_id: str,
    projection_type: VisualProjectionType,
    domain: Literal["electrical", "mechanical", "firmware", "system"],
    source_revision: str,
    input_files: list[VisualProjectionInput],
    output_path: Path,
    base_dir: Path,
    renderer_type: Literal["acd-svg"] = "acd-svg",
    tool_name: Literal["acd-svg"] = "acd-svg",
    tool_version: str,
    write_svg: Callable[[Path], None],
) -> VisualProjectionRecord:
    if not projection_type:
        raise SvgVisualProjectionError("projection type is missing")
    if not tool_version or tool_version == "unknown":
        raise SvgVisualProjectionError("renderer version is unknown")
    if any(not path.path for path in input_files):
        raise SvgVisualProjectionError("SVG input paths are missing")
    output = output_path.resolve()
    write_svg(output)
    first = output.read_bytes()
    assert_text_font_size(first)
    first_hash = sha256_bytes(first)
    reproduction = output.parent / "reproduction" / (
        f"{output.stem}.reproduced{output.suffix}"
    )
    write_svg(reproduction)
    second_hash = sha256_bytes(reproduction.read_bytes())
    if first_hash != second_hash:
        raise SvgVisualProjectionError("SVG visual regeneration hash mismatch")
    try:
        measured = measure_svg_resolution(first)
    except ValueError as exc:
        raise SvgVisualProjectionError("SVG resolution could not be measured") from exc
    return VisualProjectionRecord(
        projection_id=projection_id,
        projection_type=projection_type,
        domain=domain,
        source_revision=source_revision,
        input_files=input_files,
        renderer=VisualRendererProvenance(
            renderer_type=renderer_type,
            tool_name=tool_name,
            tool_version=tool_version,
        ),
        resolution=VisualResolution(
            width=measured.width,
            height=measured.height,
            view_box=measured.view_box,
        ),
        normalization_rule_id=ACD_SVG_NORMALIZATION_RULE_ID,
        normalization_rule_description=ACD_SVG_NORMALIZATION_RULE_DESCRIPTION,
        image_hash=first_hash,
        generated_at=datetime.now(UTC),
        regeneration_check=VisualRegenerationCheck(
            status="reproduced",
            first_image_hash=first_hash,
            second_image_hash=second_hash,
        ),
        image_path=relative_path(output, base_dir, "image"),
    )
