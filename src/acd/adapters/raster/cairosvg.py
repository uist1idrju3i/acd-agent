"""CairoSVG adapter for deterministic PNG visual projections."""

from __future__ import annotations

import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

import cairosvg  # pyright: ignore[reportMissingTypeStubs]

from acd.core.process import sha256_bytes
from acd.core.visual_projection import normalized_svg_sha256
from acd.schema.visual_projection import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualRegenerationCheck,
    VisualRendererProvenance,
    VisualResolution,
)

CAIROSVG_OUTPUT_WIDTH = 1600
PNG_NORMALIZATION_RULE_ID = "png-identity-v1"
PNG_NORMALIZATION_RULE_DESCRIPTION = (
    "PNG bytes are not normalized; the SHA-256 covers the generated PNG bytes."
)


class RasterizerError(ValueError):
    """Raised when a deterministic raster projection cannot be produced."""


class _CairoSvgModule(Protocol):
    __version__: str

    def svg2png(self, *, bytestring: bytes, output_width: int) -> bytes | None:
        ...


_CAIROSVG = cast(_CairoSvgModule, cairosvg)


def _png_resolution(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise RasterizerError("generated output is not a valid PNG")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        raise RasterizerError("generated PNG has invalid dimensions")
    return width, height


class CairoSvgRasterizer:
    """Rasterize normalized SVG projections and verify byte reproduction."""

    def __init__(self, *, output_width: int = CAIROSVG_OUTPUT_WIDTH) -> None:
        if output_width <= 0:
            raise ValueError("rasterizer output width must be positive")
        self.output_width = output_width

    @staticmethod
    def _resolve_within_base(path: Path, base_dir: Path, field_name: str) -> Path:
        candidate = path if path.is_absolute() else base_dir / path
        resolved = candidate.resolve()
        try:
            resolved.relative_to(base_dir)
        except ValueError as exc:
            raise RasterizerError(
                f"raster projection {field_name} must stay within base directory"
            ) from exc
        return resolved

    def _render_png(self, svg: bytes) -> bytes:
        try:
            rendered = _CAIROSVG.svg2png(
                bytestring=svg,
                output_width=self.output_width,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            raise RasterizerError("CairoSVG failed to rasterize SVG") from exc
        if not isinstance(rendered, bytes):
            raise RasterizerError("CairoSVG returned no PNG bytes")
        return rendered

    @staticmethod
    def _version(cairosvg: _CairoSvgModule) -> str:
        version = cairosvg.__version__
        if not version or version == "unknown":
            raise RasterizerError("CairoSVG version is unknown")
        return version

    def rasterize(
        self,
        *,
        source_record: VisualProjectionRecord,
        output_path: Path,
        base_dir: Path,
    ) -> VisualProjectionRecord:
        if source_record.media_type != "image/svg+xml":
            raise RasterizerError("rasterizer input must be an SVG projection")
        root = base_dir.resolve()
        version = self._version(_CAIROSVG)
        source_path = self._resolve_within_base(
            root / source_record.image_path,
            root,
            "source",
        )
        output = self._resolve_within_base(output_path, root, "output")
        try:
            svg = source_path.read_bytes()
        except OSError as exc:
            raise RasterizerError("source SVG is unavailable") from exc
        if normalized_svg_sha256(svg) != source_record.image_hash:
            raise RasterizerError("source SVG normalized hash does not match record")

        output.parent.mkdir(parents=True, exist_ok=True)
        reproduction = output.parent / "reproduction" / (
            f"{output.stem}.reproduced{output.suffix}"
        )
        reproduction.parent.mkdir(parents=True, exist_ok=True)
        first = self._render_png(svg)
        second = self._render_png(svg)
        first_hash = sha256_bytes(first)
        second_hash = sha256_bytes(second)
        if first_hash != second_hash:
            raise RasterizerError("PNG rasterization hash mismatch")
        try:
            output.write_bytes(first)
            reproduction.write_bytes(second)
        except OSError as exc:
            raise RasterizerError("PNG raster output could not be written") from exc
        width, height = _png_resolution(first)
        return VisualProjectionRecord(
            projection_id=f"{source_record.projection_id}-png",
            projection_type="rasterized_view",
            domain=source_record.domain,
            source_revision=source_record.source_revision,
            input_files=[
                VisualProjectionInput(
                    path=source_path.relative_to(root).as_posix(),
                    content_hash=source_record.image_hash,
                )
            ],
            renderer=VisualRendererProvenance(
                renderer_type="cairosvg",
                tool_name="cairosvg",
                tool_version=version,
                output_width=self.output_width,
            ),
            media_type="image/png",
            resolution=VisualResolution(
                width=f"{width}px",
                height=f"{height}px",
                view_box=(0.0, 0.0, float(width), float(height)),
            ),
            normalization_rule_id=PNG_NORMALIZATION_RULE_ID,
            normalization_rule_description=PNG_NORMALIZATION_RULE_DESCRIPTION,
            image_hash=first_hash,
            generated_at=datetime.now(UTC),
            regeneration_check=VisualRegenerationCheck(
                status="reproduced",
                first_image_hash=first_hash,
                second_image_hash=second_hash,
            ),
            image_path=output.relative_to(root).as_posix(),
        )
