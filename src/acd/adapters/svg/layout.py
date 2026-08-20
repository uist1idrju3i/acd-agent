"""Deterministic SVG writers for electrical placement and stackup observations."""

from __future__ import annotations

import math
from pathlib import Path
from typing import ClassVar, Literal

from acd.adapters.kicad.visual_projection import copper_layers_for_layer_count
from acd.adapters.svg.common import (
    ACD_SVG_NORMALIZATION_RULE_DESCRIPTION,
    ACD_SVG_NORMALIZATION_RULE_ID,
    ACD_SVG_RENDERER_VERSION,
    BOARD_FONT_SIZE_RATIO,
    SvgVisualProjectionError,
    escape_xml,
    format_svg_number,
    input_records,
    render_svg_projection,
    slugify_identifier,
    view_box_font_size,
)
from acd.core.board_model import BoardModel, ComponentPlacement
from acd.core.electrical import BoardView
from acd.schema.visual_projection import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionSet,
)

__all__ = [
    "ACD_SVG_NORMALIZATION_RULE_DESCRIPTION",
    "ACD_SVG_NORMALIZATION_RULE_ID",
    "ACD_SVG_RENDERER_VERSION",
    "SvgLayoutRenderer",
    "SvgVisualProjectionError",
    "generate_layout_visual_projections",
]


def _footprint_bbox(placement: ComponentPlacement) -> tuple[float, float, float, float]:
    bbox = placement.footprint.courtyard_bbox_mm or placement.footprint.body_bbox_mm
    if bbox is None:
        raise SvgVisualProjectionError(
            f"{placement.refdes}: footprint dimensions are undeclared"
        )
    if len(bbox) != 4 or not all(math.isfinite(value) for value in bbox):
        raise SvgVisualProjectionError(f"{placement.refdes}: footprint dimensions are invalid")
    x1, y1, x2, y2 = bbox
    if x2 <= x1 or y2 <= y1:
        raise SvgVisualProjectionError(f"{placement.refdes}: footprint dimensions are empty")
    return bbox


def _rotated_corners(
    placement: ComponentPlacement,
) -> tuple[tuple[float, float], ...]:
    x1, y1, x2, y2 = _footprint_bbox(placement)
    if not all(
        math.isfinite(value)
        for value in (placement.x_mm, placement.y_mm, placement.rotation_deg)
    ):
        raise SvgVisualProjectionError(f"{placement.refdes}: placement is non-finite")
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
        raise SvgVisualProjectionError(
            f"{placement.refdes}: unsupported placement side {placement.side!r}"
        )
    if (
        placement.x_mm < 0
        or placement.y_mm < 0
        or placement.x_mm > board.width_mm
        or placement.y_mm > board.height_mm
    ):
        raise SvgVisualProjectionError(
            f"{placement.refdes}: placement lies outside board outline"
        )


def _placement_svg(board: BoardModel) -> bytes:
    if not board.placements:
        raise SvgVisualProjectionError("placement projection requires placements")
    refdes = [placement.refdes for placement in board.placements]
    if len(refdes) != len(set(refdes)):
        raise SvgVisualProjectionError("placement reference designators must be unique")
    for placement in board.placements:
        _validate_placement(placement, board)
    font_size = view_box_font_size(
        min(board.width_mm, board.height_mm),
        ratio=BOARD_FONT_SIZE_RATIO,
    )
    line_height = font_size * 1.2
    chunks = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{format_svg_number(board.width_mm)}mm" '
            f'height="{format_svg_number(board.height_mm)}mm" '
            f'viewBox="0 0 {format_svg_number(board.width_mm)} '
            f'{format_svg_number(board.height_mm)}">'
        ),
        '<g id="board-outline">',
        (
            f'<rect id="board-outline-rect" x="0" y="0" '
            f'width="{format_svg_number(board.width_mm)}" '
            f'height="{format_svg_number(board.height_mm)}" fill="none" stroke="#000"/>'
        ),
        "</g>",
    ]
    for side in ("front", "back"):
        chunks.append(f'<g id="{side}">')
        for placement in sorted(board.placements, key=lambda item: item.refdes):
            if placement.side != side:
                continue
            points = " ".join(
                f"{format_svg_number(x)},{format_svg_number(y)}"
                for x, y in _rotated_corners(placement)
            )
            identifier = slugify_identifier(placement.refdes)
            chunks.extend(
                [
                    f'<g id="placement-{identifier}">',
                    (
                        f'<polygon id="footprint-{identifier}" points="{points}" '
                        f'fill="none" stroke="#0088cc"/>'
                    ),
                    (
                        f'<text id="refdes-{identifier}" x="{format_svg_number(placement.x_mm)}" '
                        f'y="{format_svg_number(placement.y_mm)}" '
                        f'font-size="{format_svg_number(font_size)}">'
                        f"{escape_xml(placement.refdes)}</text>"
                    ),
                    (
                        f'<text id="side-{identifier}" x="{format_svg_number(placement.x_mm)}" '
                        f'y="{format_svg_number(placement.y_mm + line_height)}" '
                        f'font-size="{format_svg_number(font_size)}">{side}</text>'
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
        raise SvgVisualProjectionError("stackup layer count is unsupported") from exc
    if board.layers != len(layer_names):
        raise SvgVisualProjectionError("stackup layer count is unsupported")
    thickness_mm = board.thickness_mm
    if not math.isfinite(thickness_mm) or thickness_mm <= 0:
        raise SvgVisualProjectionError("stackup thickness_mm is undeclared or invalid")
    if (
        board.outer_copper_thickness_um is None
        or not math.isfinite(board.outer_copper_thickness_um)
        or board.outer_copper_thickness_um <= 0
    ):
        raise SvgVisualProjectionError(
            "stackup outer_copper_thickness_um is undeclared or invalid"
        )
    if not board.copper_thickness_source:
        raise SvgVisualProjectionError("stackup copper_thickness_source is undeclared")
    copper_mm = board.outer_copper_thickness_um / 1000.0
    dielectric_mm = (thickness_mm - len(layer_names) * copper_mm) / (
        len(layer_names) - 1
    )
    if dielectric_mm <= 0:
        raise SvgVisualProjectionError("stackup declarations have no positive dielectric")
    width = 80.0
    height = thickness_mm + 20.0
    y = 10.0
    chunks = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{format_svg_number(width)}mm" '
            f'height="{format_svg_number(height)}mm" '
            f'viewBox="0 0 {format_svg_number(width)} {format_svg_number(height)}">'
        ),
        '<g id="stackup">',
    ]
    current_y = y
    for index, layer_name in enumerate(layer_names):
        chunks.append(f'<g id="{escape_xml(layer_name)}">')
        chunks.append(
            f'<rect id="{escape_xml(layer_name)}-band" x="10" '
            f'y="{format_svg_number(current_y)}" width="60" '
            f'height="{format_svg_number(copper_mm)}" fill="#c87533"/>'
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
            raise SvgVisualProjectionError("renderer version is unknown")
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
            raise SvgVisualProjectionError(
                f"unsupported layout projection type: {projection_type}"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            output_path.write_bytes(content)
        except OSError as exc:
            raise SvgVisualProjectionError(
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
            raise SvgVisualProjectionError("unsupported layout projection type")
        if board.layers != board_view.layers:
            raise SvgVisualProjectionError("board layer declarations do not match")
        if any(not path.path for path in input_files):
            raise SvgVisualProjectionError("layout input paths are missing")
        return render_svg_projection(
            projection_id=projection_id,
            projection_type=projection_type,
            domain="electrical",
            source_revision=source_revision,
            input_files=input_files,
            output_path=output_path,
            base_dir=base_dir,
            tool_version=self.tool_version,
            write_svg=lambda path: self._write_svg(
                projection_type=projection_type,
                board=board,
                board_view=board_view,
                output_path=path,
            ),
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
        raise SvgVisualProjectionError("board layer declarations do not match")
    inputs = input_records(authoritative_inputs, input_base_dir)
    renderer = renderer or SvgLayoutRenderer()
    ids = projection_ids or (
        f"{slugify_identifier(project_name)}-placement",
        f"{slugify_identifier(project_name)}-stackup",
    )
    if len(ids) != 2:
        raise SvgVisualProjectionError("layout projection identifiers are incomplete")
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
