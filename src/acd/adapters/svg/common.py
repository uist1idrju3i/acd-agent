"""Shared contracts and helpers for deterministic SVG observations."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import html
import math
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

ACD_SVG_RENDERER_VERSION = "1.0.0"
ACD_SVG_NORMALIZATION_RULE_ID = "acd-svg-v1"
ACD_SVG_NORMALIZATION_RULE_DESCRIPTION = "byte-exact、正規化不要"


class SvgVisualProjectionError(ValueError):
    """Raised when a deterministic SVG projection cannot be trusted."""


def _fmt(value: float) -> str:
    if not math.isfinite(value):
        raise SvgVisualProjectionError("SVG geometry contains a non-finite value")
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _slug(value: str) -> str:
    result = "".join(char.lower() if char.isalnum() else "-" for char in value)
    result = result.strip("-")
    if not result:
        raise SvgVisualProjectionError("SVG identifier is empty")
    return result


def _relative_path(path: Path, base_dir: Path, field_name: str) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError as exc:
        raise SvgVisualProjectionError(
            f"{field_name} must be relative to its declared base directory"
        ) from exc


def _input_records(paths: tuple[Path, ...], base_dir: Path) -> list[VisualProjectionInput]:
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
                path=_relative_path(path, base_dir, "input file"),
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
        image_path=_relative_path(output, base_dir, "image"),
    )
