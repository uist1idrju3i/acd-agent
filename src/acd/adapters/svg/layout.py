"""Deterministic SVG writers for electrical placement and stackup observations."""

from __future__ import annotations

import html
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Literal

from acd.adapters.kicad.visual_projection import copper_layers_for_layer_count
from acd.core.board_model import BoardModel, ComponentPlacement
from acd.core.electrical import BoardView
from acd.core.process import sha256_bytes
from acd.core.visual_projection import measure_svg_resolution
from acd.schema.visual_projection import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionSet,
    VisualRegenerationCheck,
    VisualRendererProvenance,
    VisualResolution,
)

ACD_SVG_RENDERER_VERSION = "1.0.0"
ACD_SVG_NORMALIZATION_RULE_ID = "acd-svg-v1"
ACD_SVG_NORMALIZATION_RULE_DESCRIPTION = "byte-exact、正規化不要"


class LayoutVisualProjectionError(ValueError):
    """Raised when a layout visual projection cannot be trusted."""


def _fmt(value: float) -> str:
    if not math.isfinite(value):
        raise LayoutVisualProjectionError("SVG geometry contains a non-finite value")
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _slug(value: str) -> str:
    result = "".join(char.lower() if char.isalnum() else "-" for char in value)
    result = result.strip("-")
    if not result:
        raise LayoutVisualProjectionError("SVG identifier is empty")
    return result


def _relative_path(path: Path, base_dir: Path, field_name: str) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError as exc:
        raise LayoutVisualProjectionError(
            f"{field_name} must be relative to its declared base directory"
        ) from exc


def _input_records(paths: tuple[Path, ...], base_dir: Path) -> list[VisualProjectionInput]:
    if not paths:
        raise LayoutVisualProjectionError("authoritative input files are missing")
    records: list[VisualProjectionInput] = []
    for path in paths:
        if not path.is_file():
            raise LayoutVisualProjectionError(f"authoritative input file is missing: {path}")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise LayoutVisualProjectionError(
                f"authoritative input file is unreadable: {path}"
            ) from exc
        records.append(
            VisualProjectionInput(
                path=_relative_path(path, base_dir, "input file"),
                content_hash=sha256_bytes(content),
            )
        )
    if len({record.path for record in records}) != len(records):
        raise LayoutVisualProjectionError("authoritative input files must be unique")
    return records


def _footprint_bbox(placement: ComponentPlacement) -> tuple[float, float, float, float]:
    bbox = placement.footprint.courtyard_bbox_mm or placement.footprint.body_bbox_mm
    if bbox is None:
        raise LayoutVisualProjectionError(
            f"{placement.refdes}: footprint dimensions are undeclared"
        )
    if len(bbox) != 4 or not all(math.isfinite(value) for value in bbox):
        raise LayoutVisualProjectionError(f"{placement.refdes}: footprint dimensions are invalid")
    x1, y1, x2, y2 = bbox
    if x2 <= x1 or y2 <= y1:
        raise LayoutVisualProjectionError(f"{placement.refdes}: footprint dimensions are empty")
    return bbox


def _rotated_corners(
    placement: ComponentPlacement,
) -> tuple[tuple[float, float], ...]:
    x1, y1, x2, y2 = _footprint_bbox(placement)
    if not all(
        math.isfinite(value)
        for value in (placement.x_mm, placement.y_mm, placement.rotation_deg)
    ):
        raise LayoutVisualProjectionError(f"{placement.refdes}: placement is non-finite")
    angle = math.radians(placement.rotation_deg)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    corners: list[tuple[float, float]] = []
    for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
        corners.append(
            (
                placement.x_mm + x * cosine - y * sine,
                placement.y_mm + x * sine + y * cosine,
            )
        )
    return tuple(corners)


def _validate_placement(placement: ComponentPlacement, board: BoardModel) -> None:
    if placement.side not in {"front", "back"}:
        raise LayoutVisualProjectionError(
            f"{placement.refdes}: unsupported placement side {placement.side!r}"
        )
    if (
        placement.x_mm < 0
        or placement.y_mm < 0
        or placement.x_mm > board.width_mm
        or placement.y_mm > board.height_mm
    ):
        raise LayoutVisualProjectionError(
            f"{placement.refdes}: placement lies outside board outline"
        )


def _placement_svg(board: BoardModel) -> bytes:
    if not board.placements:
        raise LayoutVisualProjectionError("placement projection requires placements")
    refdes = [placement.refdes for placement in board.placements]
    if len(refdes) != len(set(refdes)):
        raise LayoutVisualProjectionError("placement reference designators must be unique")
    for placement in board.placements:
        _validate_placement(placement, board)
    chunks = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_fmt(board.width_mm)}mm" '
            f'height="{_fmt(board.height_mm)}mm" '
            f'viewBox="0 0 {_fmt(board.width_mm)} {_fmt(board.height_mm)}">'
        ),
        '<g id="board-outline">',
        (
            f'<rect id="board-outline-rect" x="0" y="0" width="{_fmt(board.width_mm)}" '
            f'height="{_fmt(board.height_mm)}" fill="none" stroke="#000"/>'
        ),
        "</g>",
    ]
    for side in ("front", "back"):
        chunks.append(f'<g id="{side}">')
        for placement in sorted(board.placements, key=lambda item: item.refdes):
            if placement.side != side:
                continue
            points = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in _rotated_corners(placement))
            identifier = _slug(placement.refdes)
            chunks.extend(
                [
                    f'<g id="placement-{identifier}">',
                    (
                        f'<polygon id="footprint-{identifier}" points="{points}" '
                        f'fill="none" stroke="#0088cc"/>'
                    ),
                    (
                        f'<text id="refdes-{identifier}" x="{_fmt(placement.x_mm)}" '
                        f'y="{_fmt(placement.y_mm)}">{_escape(placement.refdes)}</text>'
                    ),
                    (
                        f'<text id="side-{identifier}" x="{_fmt(placement.x_mm)}" '
                        f'y="{_fmt(placement.y_mm + 0.8)}">{side}</text>'
                    ),
                    "</g>",
                ]
            )
        chunks.append("</g>")
    chunks.append("</svg>")
    return "".join(chunks).encode("utf-8")


def _stackup_svg(board: BoardView) -> bytes:
    try:
        layer_names = copper_layers_for_layer_count(board.layers)
    except ValueError as exc:
        raise LayoutVisualProjectionError("stackup layer count is unsupported") from exc
    if board.layers != len(layer_names):
        raise LayoutVisualProjectionError("stackup layer count is unsupported")
    thickness_mm = board.thickness_mm
    if not math.isfinite(thickness_mm) or thickness_mm <= 0:
        raise LayoutVisualProjectionError("stackup thickness_mm is undeclared or invalid")
    if (
        board.outer_copper_thickness_um is None
        or not math.isfinite(board.outer_copper_thickness_um)
        or board.outer_copper_thickness_um <= 0
    ):
        raise LayoutVisualProjectionError(
            "stackup outer_copper_thickness_um is undeclared or invalid"
        )
    if not board.copper_thickness_source:
        raise LayoutVisualProjectionError("stackup copper_thickness_source is undeclared")
    copper_mm = board.outer_copper_thickness_um / 1000.0
    dielectric_mm = (thickness_mm - len(layer_names) * copper_mm) / (
        len(layer_names) - 1
    )
    if dielectric_mm <= 0:
        raise LayoutVisualProjectionError("stackup declarations have no positive dielectric")
    width = 80.0
    height = thickness_mm + 20.0
    y = 10.0
    chunks = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_fmt(width)}mm" '
            f'height="{_fmt(height)}mm" viewBox="0 0 {_fmt(width)} {_fmt(height)}">'
        ),
        '<g id="stackup">',
    ]
    current_y = y
    for index, layer_name in enumerate(layer_names):
        chunks.append(f'<g id="{_escape(layer_name)}">')
        chunks.append(
            f'<rect id="{_escape(layer_name)}-band" x="10" y="{_fmt(current_y)}" '
            f'width="60" height="{_fmt(copper_mm)}" fill="#c87533"/>'
        )
        chunks.append("</g>")
        current_y += copper_mm
        if index != len(layer_names) - 1:
            current_y += dielectric_mm
    chunks.append("</g>")
    chunks.append("</svg>")
    return "".join(chunks).encode("utf-8")


class SvgLayoutRenderer:
    """Render placement and stackup SVGs without external tools."""

    renderer_type: ClassVar[Literal["acd-svg"]] = "acd-svg"
    tool_name: ClassVar[Literal["acd-svg"]] = "acd-svg"

    def __init__(self, *, tool_version: str = ACD_SVG_RENDERER_VERSION) -> None:
        if not tool_version or tool_version == "unknown":
            raise LayoutVisualProjectionError("renderer version is unknown")
        self.tool_version = tool_version

    def _write_svg(
        self,
        *,
        projection_type: Literal["placement_view", "stackup_view"],
        board: BoardModel,
        board_view: BoardView,
        output_path: Path,
    ) -> None:
        if projection_type == "placement_view":
            content = _placement_svg(board)
        elif projection_type == "stackup_view":
            content = _stackup_svg(board_view)
        else:
            raise LayoutVisualProjectionError(
                f"unsupported layout projection type: {projection_type}"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            output_path.write_bytes(content)
        except OSError as exc:
            raise LayoutVisualProjectionError(
                f"layout SVG could not be written: {output_path}"
            ) from exc

    def render(
        self,
        *,
        projection_id: str,
        projection_type: Literal["placement_view", "stackup_view"],
        source_revision: str,
        board: BoardModel,
        board_view: BoardView,
        input_files: list[VisualProjectionInput],
        output_path: Path,
        base_dir: Path,
    ) -> VisualProjectionRecord:
        if projection_type not in {"placement_view", "stackup_view"}:
            raise LayoutVisualProjectionError("unsupported layout projection type")
        if board.layers != board_view.layers:
            raise LayoutVisualProjectionError("board layer declarations do not match")
        if any(not path.path for path in input_files):
            raise LayoutVisualProjectionError("layout input paths are missing")
        output = output_path.resolve()
        self._write_svg(
            projection_type=projection_type,
            board=board,
            board_view=board_view,
            output_path=output,
        )
        first = output.read_bytes()
        first_hash = sha256_bytes(first)
        reproduction = output.parent / "reproduction" / (
            f"{output.stem}.reproduced{output.suffix}"
        )
        self._write_svg(
            projection_type=projection_type,
            board=board,
            board_view=board_view,
            output_path=reproduction,
        )
        second_hash = sha256_bytes(reproduction.read_bytes())
        if first_hash != second_hash:
            raise LayoutVisualProjectionError("layout visual regeneration hash mismatch")
        try:
            measured = measure_svg_resolution(first)
        except ValueError as exc:
            raise LayoutVisualProjectionError(
                "layout SVG resolution could not be measured"
            ) from exc
        return VisualProjectionRecord(
            projection_id=projection_id,
            projection_type=projection_type,
            domain="electrical",
            source_revision=source_revision,
            input_files=input_files,
            renderer=VisualRendererProvenance(
                renderer_type=self.renderer_type,
                tool_name=self.tool_name,
                tool_version=self.tool_version,
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


def generate_layout_visual_projections(
    *,
    project_name: str,
    out_dir: Path,
    source_revision: str,
    board: BoardModel,
    board_view: BoardView,
    authoritative_inputs: tuple[Path, ...],
    input_base_dir: Path,
    renderer: SvgLayoutRenderer | None = None,
    projection_ids: tuple[str, str] | None = None,
) -> VisualProjectionSet:
    """Generate the placement and stackup projection collection."""
    if board.layers != board_view.layers:
        raise LayoutVisualProjectionError("board layer declarations do not match")
    inputs = _input_records(authoritative_inputs, input_base_dir)
    renderer = renderer or SvgLayoutRenderer()
    ids = projection_ids or (
        f"{_slug(project_name)}-placement",
        f"{_slug(project_name)}-stackup",
    )
    if len(ids) != 2:
        raise LayoutVisualProjectionError("layout projection identifiers are incomplete")
    records = [
        renderer.render(
            projection_id=ids[0],
            projection_type="placement_view",
            source_revision=source_revision,
            board=board,
            board_view=board_view,
            input_files=inputs,
            output_path=out_dir / "visual" / f"{ids[0]}.svg",
            base_dir=out_dir,
        ),
        renderer.render(
            projection_id=ids[1],
            projection_type="stackup_view",
            source_revision=source_revision,
            board=board,
            board_view=board_view,
            input_files=inputs,
            output_path=out_dir / "visual" / f"{ids[1]}.svg",
            base_dir=out_dir,
        ),
    ]
    records.sort(key=lambda record: record.projection_id)
    result = VisualProjectionSet(
        source_revision=source_revision,
        projections=records,
    ).with_computed_hashes()
    (out_dir / "visual-projections-layout.json").write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return result
