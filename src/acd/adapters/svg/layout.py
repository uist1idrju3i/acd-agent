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
    COLOR_BACK,
    COLOR_COPPER,
    COLOR_DIELECTRIC,
    COLOR_EDGE,
    COLOR_EDGE_MUTED,
    COLOR_FRONT,
    COLOR_TEXT_MUTED,
    SMALL_FONT_SCALE,
    SvgVisualProjectionError,
    diagram_font_size,
    escape_xml,
    footer_height,
    format_svg_number,
    header_height,
    input_records,
    legend,
    render_svg_projection,
    slugify_identifier,
    svg_document,
    svg_text,
    text_advance,
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


def _placement_svg(board: BoardModel, board_view: BoardView) -> bytes:
    if not board.placements:
        raise SvgVisualProjectionError("placement projection requires placements")
    refdes = [placement.refdes for placement in board.placements]
    if len(refdes) != len(set(refdes)):
        raise SvgVisualProjectionError("placement reference designators must be unique")
    for placement in board.placements:
        _validate_placement(placement, board)
    font_size = diagram_font_size()
    small = font_size * SMALL_FONT_SCALE
    margin = font_size * 2
    # The board keeps millimetre coordinates; it is scaled up so the shorter
    # side occupies at least 60 viewBox units.
    scale = 60.0 / min(board.width_mm, board.height_mm)
    mm_font = view_box_font_size(
        min(board.width_mm, board.height_mm), ratio=BOARD_FONT_SIZE_RATIO
    )
    mm_small = mm_font * 0.8
    line_height = mm_font * 1.4
    dim_offset = mm_font * 2.4
    side_fill = {"front": COLOR_FRONT, "back": COLOR_BACK}

    inner: list[str] = [
        '<g id="board-outline">',
        (
            f'<rect id="board-outline-rect" x="0" y="0" '
            f'width="{format_svg_number(board.width_mm)}" '
            f'height="{format_svg_number(board.height_mm)}" fill="none" '
            f'stroke="{COLOR_EDGE}" '
            f'stroke-width="{format_svg_number(mm_font * 0.12)}"/>'
        ),
        "</g>",
    ]
    placed_labels: list[tuple[float, float, float, float]] = []
    max_label_bottom = board.height_mm
    for side in ("front", "back"):
        inner.append(f'<g id="{side}">')
        for placement in sorted(board.placements, key=lambda item: item.refdes):
            if placement.side != side:
                continue
            points = " ".join(
                f"{format_svg_number(x)},{format_svg_number(y)}"
                for x, y in _rotated_corners(placement)
            )
            identifier = slugify_identifier(placement.refdes)
            corners = _rotated_corners(placement)
            fx1 = min(x for x, _ in corners)
            fx2 = max(x for x, _ in corners)
            fy2 = max(y for _, y in corners)
            cx = (fx1 + fx2) / 2
            footprint_width = fx2 - fx1
            label_width = text_advance(placement.refdes, mm_font, bold=True)
            inner.append(f'<g id="placement-{identifier}">')
            inner.append(
                f'<polygon id="footprint-{identifier}" points="{points}" '
                f'fill="{side_fill[side]}" fill-opacity="0.25" '
                f'stroke="{side_fill[side]}" '
                f'stroke-width="{format_svg_number(mm_font * 0.12)}"/>'
            )
            if label_width + mm_font * 0.4 <= footprint_width:
                # Label inside the footprint: primary refdes + side caption.
                inner.extend(
                    [
                        svg_text(
                            placement.refdes,
                            x=cx,
                            y=placement.y_mm - mm_font * 0.4,
                            font_size=mm_font,
                            element_id=f"refdes-{identifier}",
                            anchor="middle",
                            weight="bold",
                        ),
                        svg_text(
                            side,
                            x=cx,
                            y=placement.y_mm + mm_small,
                            font_size=mm_small,
                            element_id=f"side-{identifier}",
                            anchor="middle",
                            fill=COLOR_TEXT_MUTED,
                        ),
                    ]
                )
            else:
                # Label outside with a leader line; shift down until clear.
                label_y = fy2 + line_height
                shifts = 0
                while shifts < 8:
                    rect = (
                        cx - label_width / 2,
                        label_y - mm_font,
                        cx + label_width / 2,
                        label_y + mm_font * 0.3,
                    )
                    if not any(
                        rect[0] < other[2]
                        and rect[2] > other[0]
                        and rect[1] < other[3]
                        and rect[3] > other[1]
                        for other in placed_labels
                    ):
                        break
                    label_y += line_height
                    shifts += 1
                placed_labels.append(
                    (
                        cx - label_width / 2,
                        label_y - mm_font,
                        cx + label_width / 2,
                        label_y + mm_font * 0.3,
                    )
                )
                max_label_bottom = max(max_label_bottom, label_y + mm_font * 0.3)
                inner.extend(
                    [
                        f'<line x1="{format_svg_number(cx)}" '
                        f'y1="{format_svg_number(fy2)}" '
                        f'x2="{format_svg_number(cx)}" '
                        f'y2="{format_svg_number(label_y - mm_font)}" '
                        f'stroke="{COLOR_EDGE_MUTED}" '
                        f'stroke-width="{format_svg_number(mm_font * 0.08)}"/>',
                        svg_text(
                            placement.refdes,
                            x=cx,
                            y=label_y,
                            font_size=mm_font,
                            element_id=f"refdes-{identifier}",
                            anchor="middle",
                            weight="bold",
                        ),
                        svg_text(
                            side,
                            x=cx,
                            y=label_y + line_height,
                            font_size=mm_small,
                            element_id=f"side-{identifier}",
                            anchor="middle",
                            fill=COLOR_TEXT_MUTED,
                        ),
                    ]
                )
                max_label_bottom = max(max_label_bottom, label_y + line_height)
            inner.append("</g>")
        inner.append("</g>")
    # Board dimensions in millimetres, below and to the right of the outline.
    dim_y = max_label_bottom + dim_offset
    inner.extend(
        [
            '<g id="board-dimensions">',
            f'<line x1="0" y1="{format_svg_number(dim_y)}" '
            f'x2="{format_svg_number(board.width_mm)}" '
            f'y2="{format_svg_number(dim_y)}" stroke="{COLOR_EDGE_MUTED}" '
            f'stroke-width="{format_svg_number(mm_font * 0.1)}"/>',
            f'<line x1="0" y1="{format_svg_number(dim_y - mm_font * 0.5)}" '
            f'x2="0" y2="{format_svg_number(dim_y + mm_font * 0.5)}" '
            f'stroke="{COLOR_EDGE_MUTED}" '
            f'stroke-width="{format_svg_number(mm_font * 0.1)}"/>',
            f'<line x1="{format_svg_number(board.width_mm)}" '
            f'y1="{format_svg_number(dim_y - mm_font * 0.5)}" '
            f'x2="{format_svg_number(board.width_mm)}" '
            f'y2="{format_svg_number(dim_y + mm_font * 0.5)}" '
            f'stroke="{COLOR_EDGE_MUTED}" '
            f'stroke-width="{format_svg_number(mm_font * 0.1)}"/>',
            svg_text(
                f"{format_svg_number(board.width_mm)} mm",
                x=board.width_mm / 2,
                y=dim_y - mm_font * 0.6,
                font_size=mm_small,
                anchor="middle",
                fill=COLOR_TEXT_MUTED,
            ),
            f'<line x1="{format_svg_number(board.width_mm + dim_offset * 0.5)}" '
            f'y1="0" x2="{format_svg_number(board.width_mm + dim_offset * 0.5)}" '
            f'y2="{format_svg_number(board.height_mm)}" '
            f'stroke="{COLOR_EDGE_MUTED}" '
            f'stroke-width="{format_svg_number(mm_font * 0.1)}"/>',
            svg_text(
                f"{format_svg_number(board.height_mm)} mm",
                x=board.width_mm + dim_offset * 0.5 + mm_small,
                y=board.height_mm / 2,
                font_size=mm_small,
                fill=COLOR_TEXT_MUTED,
            ),
            "</g>",
        ]
    )
    board_right = board.width_mm + dim_offset * 0.5 + mm_small + text_advance(
        f"{format_svg_number(board.height_mm)} mm", mm_small
    )
    board_bottom = dim_y + mm_font
    front_count = sum(1 for item in board.placements if item.side == "front")
    back_count = len(board.placements) - front_count
    body = ['<g id="placement-view">']
    body += legend(
        [
            ("front component", COLOR_FRONT, COLOR_FRONT),
            ("back component", COLOR_BACK, COLOR_BACK),
            ("board outline", "none", COLOR_EDGE),
        ],
        x=margin,
        y=header_height(font_size) + font_size * 1.2,
        font_size=small,
        element_id="placement-legend",
    )
    board_x = margin
    board_y = header_height(font_size) + font_size * 3.5
    body.append(
        f'<g transform="translate({format_svg_number(board_x)} '
        f'{format_svg_number(board_y)}) '
        f'scale({format_svg_number(scale)})">'
    )
    body += inner
    body.append("</g>")
    body.append("</g>")
    width = margin * 2 + board_right * scale
    height = board_y + board_bottom * scale + footer_height(font_size)
    return svg_document(
        width=width,
        height=height,
        title=f"Component placement — {board_view.node_id}",
        subtitle=(
            f"{format_svg_number(board.width_mm)} mm × "
            f"{format_svg_number(board.height_mm)} mm, "
            f"{len(board.placements)} components "
            f"(front {front_count} / back {back_count})"
        ),
        body=body,
        font_size=font_size,
    )


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
    font_size = diagram_font_size()
    small = font_size * SMALL_FONT_SCALE
    margin = font_size * 2
    copper_label = (
        f"{format_svg_number(board.outer_copper_thickness_um)} µm "
        f"({format_svg_number(board.outer_copper_thickness_um / 34.79)} oz)"
    )
    dielectric_label = f"{format_svg_number(dielectric_mm)} mm"
    label_width = max(
        text_advance(name, font_size, bold=True) for name in layer_names
    )
    label_width = max(
        label_width,
        text_advance(copper_label, small),
        text_advance(dielectric_label, small),
        text_advance("dielectric", font_size, bold=True),
    )
    band_x = margin + label_width + font_size * 2
    band_width = font_size * 16
    scale = font_size * 20 / thickness_mm
    total_label = f"total {format_svg_number(thickness_mm)} mm"
    dim_x = band_x + band_width + font_size * 3

    y = header_height(font_size) + font_size * 3.5
    body = ['<g id="stackup-view">']
    body += legend(
        [
            ("copper", COLOR_COPPER, COLOR_COPPER),
            ("dielectric", COLOR_DIELECTRIC, COLOR_DIELECTRIC),
        ],
        x=margin,
        y=header_height(font_size) + font_size * 1.2,
        font_size=small,
        element_id="stackup-legend",
    )
    body.append('<g id="stackup">')
    current_y = y
    dielectric_index = 0
    for index, layer_name in enumerate(layer_names):
        band_height = copper_mm * scale
        label_y = current_y + max(band_height, font_size) / 2 + font_size * 0.35
        body.extend(
            [
                f'<g id="{escape_xml(layer_name)}">',
                svg_text(
                    layer_name,
                    x=margin,
                    y=label_y - font_size * 0.5,
                    font_size=font_size,
                    weight="bold",
                ),
                svg_text(
                    copper_label,
                    x=margin,
                    y=label_y + small * 0.9,
                    font_size=small,
                    fill=COLOR_TEXT_MUTED,
                ),
                f'<rect id="{escape_xml(layer_name)}-band" '
                f'x="{format_svg_number(band_x)}" '
                f'y="{format_svg_number(current_y)}" '
                f'width="{format_svg_number(band_width)}" '
                f'height="{format_svg_number(band_height)}" '
                f'fill="{COLOR_COPPER}"/>',
                "</g>",
            ]
        )
        current_y += band_height
        if index != len(layer_names) - 1:
            dielectric_index += 1
            gap_height = dielectric_mm * scale
            body.extend(
                [
                    svg_text(
                        "dielectric",
                        x=margin,
                        y=current_y + gap_height / 2 - small * 0.2,
                        font_size=font_size,
                        weight="bold",
                    ),
                    svg_text(
                        dielectric_label,
                        x=margin,
                        y=current_y + gap_height / 2 + small * 1.1,
                        font_size=small,
                        fill=COLOR_TEXT_MUTED,
                    ),
                    f'<rect id="dielectric-band-{dielectric_index}" '
                    f'x="{format_svg_number(band_x)}" '
                    f'y="{format_svg_number(current_y)}" '
                    f'width="{format_svg_number(band_width)}" '
                    f'height="{format_svg_number(gap_height)}" '
                    f'fill="{COLOR_DIELECTRIC}"/>',
                ]
            )
            current_y += gap_height
    body.append("</g>")
    # Total-thickness dimension on the right of the stack.
    body.extend(
        [
            '<g id="stackup-dimension">',
            f'<line x1="{format_svg_number(dim_x)}" y1="{format_svg_number(y)}" '
            f'x2="{format_svg_number(dim_x)}" '
            f'y2="{format_svg_number(current_y)}" '
            f'stroke="{COLOR_EDGE_MUTED}" '
            f'stroke-width="{format_svg_number(font_size * 0.12)}"/>',
            f'<line x1="{format_svg_number(dim_x - font_size * 0.6)}" '
            f'y1="{format_svg_number(y)}" '
            f'x2="{format_svg_number(dim_x + font_size * 0.6)}" '
            f'y2="{format_svg_number(y)}" stroke="{COLOR_EDGE_MUTED}" '
            f'stroke-width="{format_svg_number(font_size * 0.12)}"/>',
            f'<line x1="{format_svg_number(dim_x - font_size * 0.6)}" '
            f'y1="{format_svg_number(current_y)}" '
            f'x2="{format_svg_number(dim_x + font_size * 0.6)}" '
            f'y2="{format_svg_number(current_y)}" '
            f'stroke="{COLOR_EDGE_MUTED}" '
            f'stroke-width="{format_svg_number(font_size * 0.12)}"/>',
            svg_text(
                total_label,
                x=dim_x + font_size,
                y=(y + current_y) / 2,
                font_size=small,
                fill=COLOR_TEXT_MUTED,
            ),
            "</g>",
        ]
    )
    body.append("</g>")
    width = dim_x + font_size + text_advance(total_label, small) + margin
    height = current_y + font_size * 2 + footer_height(font_size)
    return svg_document(
        width=width,
        height=height,
        title=(
            f"Layer stackup — {board.layers} layers, "
            f"{format_svg_number(thickness_mm)} mm"
        ),
        subtitle=(
            f"copper thickness source: {board.copper_thickness_source}"
        ),
        body=body,
        font_size=font_size,
    )


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
            content = _placement_svg(board, board_view)
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
