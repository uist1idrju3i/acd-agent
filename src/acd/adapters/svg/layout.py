"""Deterministic SVG writers for electrical placement and stackup observations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, TypedDict

from acd.adapters.kicad.layers import copper_layers_for_layer_count
from acd.adapters.svg.common import (
    ACD_SVG_NORMALIZATION_RULE_DESCRIPTION,
    ACD_SVG_NORMALIZATION_RULE_ID,
    ACD_SVG_RENDERER_VERSION,
    COLOR_BACK,
    COLOR_COPPER,
    COLOR_DIELECTRIC,
    COLOR_EDGE,
    COLOR_EDGE_MUTED,
    COLOR_FRONT,
    COLOR_TEXT_MUTED,
    SMALL_FONT_SCALE,
    SUBTITLE_FONT_SCALE,
    TITLE_FONT_SCALE,
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
)
from acd.core.electrical.board_model import (
    BoardModel,
    ComponentPlacement,
    EdgeOverhangDeclaration,
    PlacementAnnotations,
)
from acd.core.electrical.electrical import BoardView
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


# Darker footprint strokes keep adjacent parts distinguishable.
_FRONT_STROKE = "#004a80"
_BACK_STROKE = "#8a2f08"
_EMPTY_PLACEMENT_ANNOTATIONS = PlacementAnnotations()


class _PlacementGeometry(TypedDict):
    placement: ComponentPlacement
    points: str
    identifier: str
    cx: float
    cy: float
    inside: bool
    large: bool
    outside_label_y: float
    outside_anchor_x: float
    outside_anchor: Literal["start", "middle", "end"]


@dataclass(frozen=True)
class _OverhangGeometry:
    identifier: str
    edge: Literal["top", "bottom", "left", "right"]
    declaration: EdgeOverhangDeclaration | None
    text: str
    text_x: float
    text_y: float
    anchor: Literal["start", "middle", "end"]
    tick_x1: float
    tick_y1: float
    tick_x2: float
    tick_y2: float


def _footprint_bbox(placement: ComponentPlacement) -> tuple[float, float, float, float]:
    bbox = placement.footprint.courtyard_bbox_mm or placement.footprint.body_bbox_mm
    if bbox is None:
        raise SvgVisualProjectionError(f"{placement.refdes}: footprint dimensions are undeclared")
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
        math.isfinite(value) for value in (placement.x_mm, placement.y_mm, placement.rotation_deg)
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
        raise SvgVisualProjectionError(f"{placement.refdes}: placement lies outside board outline")


def _placement_svg(
    board: BoardModel,
    board_view: BoardView,
    annotations: PlacementAnnotations,
) -> bytes:
    if not board.placements:
        raise SvgVisualProjectionError("placement projection requires placements")
    refdes = [placement.refdes for placement in board.placements]
    if len(refdes) != len(set(refdes)):
        raise SvgVisualProjectionError("placement reference designators must be unique")
    for placement in board.placements:
        _validate_placement(placement, board)
    placement_refdes = {placement.refdes for placement in board.placements}
    missing_declaration_placements = sorted(
        {
            declaration.component_refdes
            for declaration in annotations.edge_overhangs
            if declaration.component_refdes not in placement_refdes
        }
    )
    if missing_declaration_placements:
        raise SvgVisualProjectionError(
            "overhang declaration has no placement for " + ", ".join(missing_declaration_placements)
        )
    font_size = diagram_font_size()
    small = font_size * SMALL_FONT_SCALE
    margin = font_size * 2
    # The board keeps millimetre coordinates; it is scaled up so the longer
    # side occupies at least 160 viewBox units.
    scale = 160.0 / max(board.width_mm, board.height_mm)
    mm_font = font_size / scale
    mm_small = small / scale
    dim_offset = mm_font * 2.4
    side_fill = {"front": COLOR_FRONT, "back": COLOR_BACK}
    side_stroke = {"front": _FRONT_STROKE, "back": _BACK_STROKE}
    board_area = board.width_mm * board.height_mm
    hole_labels: dict[int, tuple[str, float]] = {}
    for hole in annotations.mount_holes:
        if (
            not all(math.isfinite(value) for value in (hole.x_mm, hole.y_mm, hole.diameter_mm))
            or hole.diameter_mm <= 0
        ):
            raise SvgVisualProjectionError(f"mount hole {hole.index} has invalid geometry")
        if not (0.0 <= hole.x_mm <= board.width_mm and 0.0 <= hole.y_mm <= board.height_mm):
            raise SvgVisualProjectionError(
                f"mount hole {hole.index} centre lies outside board outline"
            )
        label = f"Ø{format_svg_number(hole.diameter_mm)} mm"
        hole_labels[hole.index] = (label, text_advance(label, small) / scale)

    # Per-component geometry in board millimetre coordinates.
    geometry: list[_PlacementGeometry] = []
    for placement in sorted(board.placements, key=lambda item: item.refdes):
        corners = _rotated_corners(placement)
        fx1 = min(x for x, _ in corners)
        fy1 = min(y for _, y in corners)
        fx2 = max(x for x, _ in corners)
        fy2 = max(y for _, y in corners)
        footprint_width = fx2 - fx1
        footprint_height = fy2 - fy1
        label_width = text_advance(placement.refdes, font_size, bold=True) / scale
        inside = label_width <= footprint_width * 0.9 and mm_font <= footprint_height * 0.8
        geometry.append(
            {
                "placement": placement,
                "points": " ".join(
                    f"{format_svg_number(x)},{format_svg_number(y)}" for x, y in corners
                ),
                "identifier": slugify_identifier(placement.refdes),
                "cx": (fx1 + fx2) / 2,
                "cy": (fy1 + fy2) / 2,
                "inside": inside,
                "large": footprint_width * footprint_height > board_area * 0.2,
                "outside_label_y": 0.0,
                "outside_anchor_x": 0.0,
                "outside_anchor": "start",
            }
        )
    declarations = {
        (declaration.component_refdes, declaration.edge): declaration
        for declaration in annotations.edge_overhangs
    }
    overhangs: list[_OverhangGeometry] = []
    for item in geometry:
        placement = item["placement"]
        corners = _rotated_corners(placement)
        fx1 = min(x for x, _ in corners)
        fy1 = min(y for _, y in corners)
        fx2 = max(x for x, _ in corners)
        fy2 = max(y for _, y in corners)
        edge_amounts: dict[Literal["top", "bottom", "left", "right"], float] = {
            "top": max(0.0, -fy1),
            "bottom": max(0.0, fy2 - board.height_mm),
            "left": max(0.0, -fx1),
            "right": max(0.0, fx2 - board.width_mm),
        }
        for edge, amount in edge_amounts.items():
            if amount <= 0:
                continue
            measured = round(amount, 1)
            declaration = declarations.get((placement.refdes, edge))
            if declaration is None:
                text = f"overhang {format_svg_number(measured)} mm (undeclared)"
            elif abs(declaration.overhang_mm - measured) > 0.05:
                text = (
                    f"overhang {format_svg_number(measured)} mm "
                    f"(declared {format_svg_number(declaration.overhang_mm)} mm: "
                    f"{declaration.requirement_id})"
                )
            else:
                text = (
                    f"overhang {format_svg_number(measured)} mm "
                    f"(declared: {declaration.requirement_id})"
                )
            center_x = (fx1 + fx2) / 2
            center_y = (fy1 + fy2) / 2
            if edge == "top":
                text_x, text_y, anchor = center_x, fy1 - mm_small, "middle"
                tick_x1, tick_y1, tick_x2, tick_y2 = center_x, 0.0, center_x, fy1
            elif edge == "bottom":
                text_x, text_y, anchor = center_x, fy2 + mm_small * 1.2, "middle"
                tick_x1, tick_y1, tick_x2, tick_y2 = (
                    center_x,
                    board.height_mm,
                    center_x,
                    fy2,
                )
            elif edge == "left":
                text_x, text_y, anchor = fx1 - mm_small, center_y, "end"
                tick_x1, tick_y1, tick_x2, tick_y2 = 0.0, center_y, fx1, center_y
            else:
                text_x, text_y, anchor = fx2 + mm_small, center_y, "start"
                tick_x1, tick_y1, tick_x2, tick_y2 = (
                    board.width_mm,
                    center_y,
                    fx2,
                    center_y,
                )
            overhangs.append(
                _OverhangGeometry(
                    identifier=f"{slugify_identifier(placement.refdes)}-{edge}",
                    edge=edge,
                    declaration=declaration,
                    text=text,
                    text_x=text_x,
                    text_y=text_y,
                    anchor=anchor,
                    tick_x1=tick_x1,
                    tick_y1=tick_y1,
                    tick_x2=tick_x2,
                    tick_y2=tick_y2,
                )
            )
    # Margins reserve the footprint overhang beyond the board outline so that
    # courtyard boxes (e.g. antenna keep-outs) never clip the legend or title.
    min_x = min(
        0.0,
        *(min(x for x, _ in _rotated_corners(item["placement"])) for item in geometry),
    )
    min_y = min(
        0.0,
        *(min(y for _, y in _rotated_corners(item["placement"])) for item in geometry),
    )
    max_x = max(
        board.width_mm,
        *(max(x for x, _ in _rotated_corners(item["placement"])) for item in geometry),
    )
    max_y = max(
        board.height_mm,
        *(max(y for _, y in _rotated_corners(item["placement"])) for item in geometry),
    )
    for hole in annotations.mount_holes:
        _label, label_width = hole_labels[hole.index]
        radius = hole.diameter_mm / 2
        min_x = min(min_x, hole.x_mm - radius)
        max_x = max(max_x, hole.x_mm + radius + mm_small + label_width)
    for overhang in overhangs:
        text_width = text_advance(overhang.text, mm_small)
        if overhang.anchor == "start":
            max_x = max(max_x, overhang.text_x + text_width)
        elif overhang.anchor == "end":
            min_x = min(min_x, overhang.text_x - text_width)
        else:
            min_x = min(min_x, overhang.text_x - text_width / 2)
            max_x = max(max_x, overhang.text_x + text_width / 2)
        min_y = min(min_y, overhang.text_y - mm_small)
        max_y = max(max_y, overhang.text_y)

    # Outside labels: left column for components left of centre, right column
    # for the rest; each column is sorted by centre y and stacked at a fixed
    # pitch starting at the board top so labels can never overlap.
    outside_left = sorted(
        (item for item in geometry if not item["inside"] and item["cx"] < board.width_mm / 2),
        key=lambda item: item["cy"],
    )
    outside_right = sorted(
        (item for item in geometry if not item["inside"] and item["cx"] >= board.width_mm / 2),
        key=lambda item: item["cy"],
    )
    line_pitch = mm_font * 1.6
    left_width = (
        max(text_advance(item["placement"].refdes, font_size, bold=True) for item in outside_left)
        / scale
        + mm_font * 1.5
        if outside_left
        else 0.0
    )
    right_width = (
        max(text_advance(item["placement"].refdes, font_size, bold=True) for item in outside_right)
        / scale
        + mm_font * 1.5
        if outside_right
        else 0.0
    )
    label_bottom = 0.0
    left_anchor_x = min_x - mm_font * 0.6
    right_anchor_x = max_x + mm_font * 0.6
    dim_x = right_anchor_x + right_width + mm_font * 0.6
    label_columns: tuple[tuple[list[_PlacementGeometry], float, Literal["start", "end"]], ...] = (
        (outside_left, left_anchor_x, "end"),
        (outside_right, right_anchor_x, "start"),
    )
    for column, anchor_x, anchor in label_columns:
        for index, item in enumerate(column):
            item["outside_label_y"] = line_pitch * index + mm_font
            item["outside_anchor_x"] = anchor_x
            item["outside_anchor"] = anchor
            label_bottom = max(label_bottom, item["outside_label_y"] + mm_small)

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
    if board.keepouts:
        inner.append('<g id="keepouts">')
        keepout_ids: set[str] = set()
        for keepout in sorted(board.keepouts, key=lambda item: item.name):
            identifier = f"keepout-{slugify_identifier(keepout.name)}"
            if identifier in keepout_ids:
                raise SvgVisualProjectionError(f"duplicate keepout identifier: {keepout.name}")
            keepout_ids.add(identifier)
            width = keepout.x2_mm - keepout.x1_mm
            height = keepout.y2_mm - keepout.y1_mm
            if width <= 0 or height <= 0:
                raise SvgVisualProjectionError(f"keepout {keepout.name} has empty geometry")
            inner.extend(
                [
                    f'<g id="{identifier}-group">',
                    f'<rect id="{identifier}" '
                    f'x="{format_svg_number(keepout.x1_mm)}" '
                    f'y="{format_svg_number(keepout.y1_mm)}" '
                    f'width="{format_svg_number(width)}" '
                    f'height="{format_svg_number(height)}" '
                    f'fill="{COLOR_BACK}" fill-opacity="0.08" '
                    f'stroke="#b00020" stroke-dasharray="{format_svg_number(mm_small)} '
                    f'{format_svg_number(mm_small * 0.6)}" '
                    f'stroke-width="{format_svg_number(mm_small * 0.12)}"/>',
                    svg_text(
                        keepout.name,
                        x=keepout.x1_mm + mm_small * 0.4,
                        y=keepout.y1_mm + mm_small,
                        font_size=mm_small,
                        fill="#b00020",
                        element_id=f"{identifier}-label",
                    ),
                    "</g>",
                ]
            )
        inner.append("</g>")
    if annotations.mount_holes:
        inner.append('<g id="mount-holes">')
        for hole in annotations.mount_holes:
            label, _label_width = hole_labels[hole.index]
            radius = hole.diameter_mm / 2
            cross = max(mm_small, radius * 1.5)
            inner.extend(
                [
                    f'<g id="mount-hole-{hole.index}-group">',
                    f'<circle id="mount-hole-{hole.index}" '
                    f'cx="{format_svg_number(hole.x_mm)}" '
                    f'cy="{format_svg_number(hole.y_mm)}" '
                    f'r="{format_svg_number(radius)}" fill="none" '
                    f'stroke="{COLOR_EDGE}" '
                    f'stroke-width="{format_svg_number(mm_small * 0.12)}"/>',
                    f'<line x1="{format_svg_number(hole.x_mm - cross)}" '
                    f'y1="{format_svg_number(hole.y_mm)}" '
                    f'x2="{format_svg_number(hole.x_mm + cross)}" '
                    f'y2="{format_svg_number(hole.y_mm)}" '
                    f'stroke="{COLOR_EDGE}" '
                    f'stroke-width="{format_svg_number(mm_small * 0.08)}"/>',
                    f'<line x1="{format_svg_number(hole.x_mm)}" '
                    f'y1="{format_svg_number(hole.y_mm - cross)}" '
                    f'x2="{format_svg_number(hole.x_mm)}" '
                    f'y2="{format_svg_number(hole.y_mm + cross)}" '
                    f'stroke="{COLOR_EDGE}" '
                    f'stroke-width="{format_svg_number(mm_small * 0.08)}"/>',
                    svg_text(
                        label,
                        x=hole.x_mm + radius + mm_small,
                        y=hole.y_mm + mm_small * 0.35,
                        font_size=mm_small,
                        fill=COLOR_TEXT_MUTED,
                        element_id=f"mount-hole-{hole.index}-label",
                    ),
                    "</g>",
                ]
            )
        inner.append("</g>")
    for side in ("front", "back"):
        inner.append(f'<g id="{side}">')
        for item in geometry:
            placement = item["placement"]
            if placement.side != side:
                continue
            identifier = item["identifier"]
            fill_opacity = "0.12" if item["large"] else "0.3"
            inner.append(
                f'<g id="placement-{identifier}" data-side="{side}">'
                f'<polygon id="footprint-{identifier}" points="{item["points"]}" '
                f'fill="{side_fill[side]}" fill-opacity="{fill_opacity}" '
                f'stroke="{side_stroke[side]}" '
                f'stroke-width="{format_svg_number(mm_font * 0.15)}"/>'
            )
            if item["inside"]:
                inner.append(
                    svg_text(
                        placement.refdes,
                        x=item["cx"],
                        y=item["cy"] + mm_font * 0.35,
                        font_size=mm_font,
                        element_id=f"refdes-{identifier}",
                        anchor="middle",
                        weight="bold",
                    )
                )
            inner.append("</g>")
        inner.append("</g>")
    # Labels and leader lines in a second pass so they sit above footprints.
    inner.append('<g id="placement-labels">')
    for item in geometry:
        if item["inside"]:
            continue
        identifier = item["identifier"]
        label_y = item["outside_label_y"]
        anchor_x = item["outside_anchor_x"]
        inner.extend(
            [
                f'<g id="placement-label-outside-{identifier}">',
                f'<line x1="{format_svg_number(anchor_x)}" '
                f'y1="{format_svg_number(label_y - mm_font * 0.35)}" '
                f'x2="{format_svg_number(item["cx"])}" '
                f'y2="{format_svg_number(item["cy"])}" '
                f'stroke="{COLOR_EDGE_MUTED}" '
                f'stroke-width="{format_svg_number(mm_font * 0.08)}"/>',
                svg_text(
                    item["placement"].refdes,
                    x=anchor_x,
                    y=label_y,
                    font_size=mm_font,
                    element_id=f"refdes-{identifier}",
                    anchor=item["outside_anchor"],
                    weight="bold",
                ),
                "</g>",
            ]
        )
    inner.append("</g>")
    if overhangs:
        inner.append('<g id="overhangs">')
        for overhang in overhangs:
            declared = overhang.declaration is not None
            color = COLOR_TEXT_MUTED if declared else "#b00020"
            inner.extend(
                [
                    f'<g id="overhang-{overhang.identifier}" '
                    f'data-declared="{str(declared).lower()}">',
                    f'<line x1="{format_svg_number(overhang.tick_x1)}" '
                    f'y1="{format_svg_number(overhang.tick_y1)}" '
                    f'x2="{format_svg_number(overhang.tick_x2)}" '
                    f'y2="{format_svg_number(overhang.tick_y2)}" '
                    f'stroke="{color}" '
                    f'stroke-width="{format_svg_number(mm_small * 0.12)}"/>',
                    svg_text(
                        overhang.text,
                        x=overhang.text_x,
                        y=overhang.text_y,
                        font_size=mm_small,
                        anchor=overhang.anchor,
                        fill=color,
                        element_id=f"overhang-{overhang.identifier}-label",
                    ),
                    "</g>",
                ]
            )
        inner.append("</g>")
    # Board dimensions in millimetres, below and to the right of the outline.
    dim_y = max(max_y, label_bottom) + dim_offset
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
            f'<line x1="{format_svg_number(dim_x)}" '
            f'y1="{format_svg_number(min_y)}" x2="{format_svg_number(dim_x)}" '
            f'y2="{format_svg_number(max_y)}" '
            f'stroke="{COLOR_EDGE_MUTED}" '
            f'stroke-width="{format_svg_number(mm_font * 0.1)}"/>',
            svg_text(
                f"{format_svg_number(board.height_mm)} mm",
                x=dim_x + mm_small,
                y=(min_y + max_y) / 2,
                font_size=mm_small,
                fill=COLOR_TEXT_MUTED,
            ),
            "</g>",
        ]
    )
    board_right = (
        dim_x + mm_small + text_advance(f"{format_svg_number(board.height_mm)} mm", mm_small)
    )
    board_bottom = dim_y + mm_font
    front_count = sum(1 for item in board.placements if item.side == "front")
    back_count = len(board.placements) - front_count
    body = ['<g id="placement-view">']
    legend_items = [
        ("front component", COLOR_FRONT, COLOR_FRONT),
        ("back component", COLOR_BACK, COLOR_BACK),
        ("board outline", "none", COLOR_EDGE),
    ]
    if annotations.mount_holes:
        legend_items.append(("mount hole", "none", COLOR_EDGE))
    if board.keepouts:
        legend_items.append(("keepout", "none", "#b00020"))
    if any(item.declaration is not None for item in overhangs):
        legend_items.append(("overhang (declared)", "none", COLOR_TEXT_MUTED))
    if any(item.declaration is None for item in overhangs):
        legend_items.append(("overhang (undeclared) — L3 warning", "none", "#b00020"))
    body += legend(
        legend_items,
        x=margin,
        y=header_height(font_size) + font_size * 1.2,
        font_size=small,
        element_id="placement-legend",
    )
    # Translate so the left-most content (overhang or label column) starts at
    # the margin and the top overhang stays below the legend.
    view_min_x = min_x
    if outside_left:
        view_min_x = left_anchor_x - (left_width - mm_font * 1.5) - mm_font * 0.4
    view_min_y = min(min_y, 0.0)
    board_x = margin - view_min_x * scale
    board_y = header_height(font_size) + font_size * 3.5 - view_min_y * scale
    body.append(
        f'<g transform="translate({format_svg_number(board_x)} '
        f"{format_svg_number(board_y)}) "
        f'scale({format_svg_number(scale)})">'
    )
    body += inner
    body.append("</g>")
    body.append("</g>")
    title = f"Component placement — {board_view.node_id}"
    subtitle = (
        f"{format_svg_number(board.width_mm)} mm × "
        f"{format_svg_number(board.height_mm)} mm, "
        f"{len(board.placements)} components "
        f"(front {front_count} / back {back_count})"
    )
    if annotations.mount_holes:
        subtitle += f", {len(annotations.mount_holes)} mount holes"
    width = max(
        margin * 2 + (board_right - view_min_x) * scale,
        text_advance(title, font_size * TITLE_FONT_SCALE, bold=True) + margin * 2,
        text_advance(subtitle, font_size * SUBTITLE_FONT_SCALE) + margin * 2,
    )
    height = board_y + board_bottom * scale + footer_height(font_size)
    return svg_document(
        width=width,
        height=height,
        title=title,
        subtitle=subtitle,
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
        raise SvgVisualProjectionError("stackup outer_copper_thickness_um is undeclared or invalid")
    if not board.copper_thickness_source:
        raise SvgVisualProjectionError("stackup copper_thickness_source is undeclared")
    copper_mm = board.outer_copper_thickness_um / 1000.0
    dielectric_mm = (thickness_mm - len(layer_names) * copper_mm) / (len(layer_names) - 1)
    if dielectric_mm <= 0:
        raise SvgVisualProjectionError("stackup declarations have no positive dielectric")
    font_size = diagram_font_size()
    small = font_size * SMALL_FONT_SCALE
    margin = font_size * 2
    copper_label = (
        f"{format_svg_number(board.outer_copper_thickness_um)} µm "
        f"({board.outer_copper_thickness_um / 34.79:.2f} oz)"
    )
    dielectric_label = f"{format_svg_number(dielectric_mm)} mm"
    label_width = max(text_advance(name, font_size, bold=True) for name in layer_names)
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
    title = f"Layer stackup — {board.layers} layers, {format_svg_number(thickness_mm)} mm"
    subtitle = f"copper thickness source: {board.copper_thickness_source}"
    width = max(
        dim_x + font_size + text_advance(total_label, small) + margin,
        text_advance(title, font_size * TITLE_FONT_SCALE, bold=True) + margin * 2,
        text_advance(subtitle, font_size * SUBTITLE_FONT_SCALE) + margin * 2,
    )
    height = current_y + font_size * 2 + footer_height(font_size)
    return svg_document(
        width=width,
        height=height,
        title=title,
        subtitle=subtitle,
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
        annotations: PlacementAnnotations,
        output_path: Path,
    ) -> None:
        if projection_type == "placement_view":
            content = _placement_svg(board, board_view, annotations)
        elif projection_type == "stackup_view":
            content = _stackup_svg(board_view)
        else:
            raise SvgVisualProjectionError(f"unsupported layout projection type: {projection_type}")
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
        annotations: PlacementAnnotations = _EMPTY_PLACEMENT_ANNOTATIONS,
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
                annotations=annotations,
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
    annotations: PlacementAnnotations = _EMPTY_PLACEMENT_ANNOTATIONS,
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
            annotations=annotations,
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
            annotations=annotations,
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
