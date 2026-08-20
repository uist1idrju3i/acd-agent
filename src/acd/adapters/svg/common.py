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

ACD_SVG_RENDERER_VERSION = "1.1.0"
ACD_SVG_NORMALIZATION_RULE_ID = "acd-svg-v1"
ACD_SVG_NORMALIZATION_RULE_DESCRIPTION = "byte-exact、正規化不要"

# Text is sized relative to the viewBox so that a projection stays legible at
# any rendered scale. Board-sized diagrams use the smaller board dimension as
# the reference extent; schematic-scale diagrams use the viewBox width.
BOARD_FONT_SIZE_RATIO = 0.05
DIAGRAM_FONT_SIZE_RATIO = 0.0125

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
