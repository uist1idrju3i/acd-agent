"""Typed extraction of graph-declared board silkscreen.

Only extraction lives here. Resolving label positions by search is provided as
the ``acd-silkscreen-placement`` skill under ``plugins/acd/skills/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from acd.core.electrical import GraphExtractionError
from acd.schema.design_graph import DesignGraph, GraphNode


@dataclass(frozen=True)
class SilkTextView:
    node_id: str
    role: str
    text: str
    x_mm: float | None
    y_mm: float | None
    layer: str
    height_mm: float
    stroke_width_mm: float
    rotation_deg: float
    placement_basis: str
    placement_search_order: str
    placement_reference: str
    placement_offset_step_mm: float
    placement_search_limit_mm: float
    board_edge_margin_mm: float = 0.0
    board_edge_margin_source: str = "unknown"
    placement_rotation_degrees: tuple[float, ...] = (0.0, 90.0, 180.0, 270.0)
    placement_safety_margin_mm: float = 0.0


@dataclass(frozen=True)
class SilkGraphicPartView:
    contours: tuple[tuple[tuple[float, float], ...], ...]
    stroke_width_mm: float
    fill: str = "none"
    fill_rule: str = "nonzero"


@dataclass(frozen=True)
class SilkGraphicView:
    node_id: str
    role: str
    layer: str
    stroke_width_mm: float
    polygon_points: tuple[tuple[float, float], ...]
    placement_basis: str
    placement_search_order: str
    board_edge_margin_mm: float = 0.0
    board_edge_margin_source: str = "unknown"
    contours: tuple[tuple[tuple[float, float], ...], ...] = ()
    fill: str = "none"
    fill_rule: str = "nonzero"
    parts: tuple[SilkGraphicPartView, ...] = ()
    source_path: str | None = None
    source_sha256: str | None = None
    source_scale: float | None = None
    placement_center_mm: tuple[float, float] | None = None
    rotation_degrees: float = 0.0
    qr_module_matrix: tuple[str, ...] = ()
    qr_source_module_pitch_mm: float | None = None
    qr_module_pitch_mm: float | None = None
    qr_quiet_zone_modules: int | None = None


@dataclass(frozen=True)
class SilkscreenLane:
    board_node_id: str
    texts: tuple[SilkTextView, ...]
    graphics: tuple[SilkGraphicView, ...]
    placement_evidence: tuple[dict[str, object], ...] = ()


def _str_attr(node: GraphNode, key: str) -> str:
    value = node.attrs.get(key)
    if not isinstance(value, str) or not value:
        raise GraphExtractionError(f"node {node.id!r}: attr {key!r} missing or invalid")
    return value


def _number_attr(node: GraphNode, key: str) -> float:
    value = node.attrs.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise GraphExtractionError(f"node {node.id!r}: attr {key!r} missing or invalid")
    return float(value)


def _points_attr(node: GraphNode) -> tuple[tuple[float, float], ...]:
    value = node.attrs.get("polygon_points")
    if not isinstance(value, list) or len(value) < 3:
        raise GraphExtractionError(
            f"node {node.id!r}: polygon_points must contain at least three entries"
        )
    points: list[tuple[float, float]] = []
    for item in value:
        parts = item.split(",")
        if len(parts) != 2:
            raise GraphExtractionError(f"node {node.id!r}: polygon point is malformed")
        try:
            x_mm, y_mm = (float(part) for part in parts)
        except ValueError as exc:
            raise GraphExtractionError(
                f"node {node.id!r}: polygon point is not numeric"
            ) from exc
        points.append((x_mm, y_mm))
    if points[0] != points[-1]:
        points.append(points[0])
    return tuple(points)


def _graphic_parts_attr(
    node: GraphNode,
    polygon_points: tuple[tuple[float, float], ...],
    stroke_width: float,
) -> tuple[SilkGraphicPartView, ...]:
    value = node.attrs.get("graphic_parts")
    if value is None:
        return (SilkGraphicPartView((polygon_points,), stroke_width),)
    if not isinstance(value, list) or not value:
        raise GraphExtractionError(f"node {node.id!r}: graphic_parts is invalid")
    parts: list[SilkGraphicPartView] = []
    for encoded in value:
        try:
            raw_item: object = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise GraphExtractionError(
                f"node {node.id!r}: graphic part is malformed"
            ) from exc
        if not isinstance(raw_item, dict):
            raise GraphExtractionError(f"node {node.id!r}: graphic part is invalid")
        item = cast(dict[str, object], raw_item)
        raw_contours_value = item.get("contours")
        if not isinstance(raw_contours_value, list) or not raw_contours_value:
            raise GraphExtractionError(f"node {node.id!r}: graphic contours are invalid")
        raw_contours = cast(list[object], raw_contours_value)
        contours: list[tuple[tuple[float, float], ...]] = []
        for raw_contour_value in raw_contours:
            if not isinstance(raw_contour_value, list):
                raise GraphExtractionError(
                    f"node {node.id!r}: graphic contour is invalid"
                )
            raw_contour = cast(list[object], raw_contour_value)
            if len(raw_contour) < 2:
                raise GraphExtractionError(
                    f"node {node.id!r}: graphic contour is invalid"
                )
            contour: list[tuple[float, float]] = []
            for point_value in raw_contour:
                if not isinstance(point_value, list):
                    raise GraphExtractionError(
                        f"node {node.id!r}: graphic point is invalid"
                    )
                point_values = cast(list[object], point_value)
                if len(point_values) != 2 or any(
                    isinstance(value, bool) or not isinstance(value, int | float)
                    for value in point_values
                ):
                    raise GraphExtractionError(
                        f"node {node.id!r}: graphic point is invalid"
                    )
                x_value, y_value = point_values
                if not isinstance(x_value, int | float) or not isinstance(
                    y_value, int | float
                ):
                    raise GraphExtractionError(
                        f"node {node.id!r}: graphic point is invalid"
                    )
                contour.append((float(x_value), float(y_value)))
            contours.append(tuple(contour))
        part_stroke = item.get("stroke_width_mm", stroke_width)
        if isinstance(part_stroke, bool) or not isinstance(part_stroke, int | float):
            raise GraphExtractionError(f"node {node.id!r}: graphic stroke is invalid")
        fill = item.get("fill", "none")
        fill_rule = item.get("fill_rule", "nonzero")
        if not isinstance(fill, str) or not isinstance(fill_rule, str):
            raise GraphExtractionError(f"node {node.id!r}: graphic fill is invalid")
        parts.append(
            SilkGraphicPartView(
                tuple(contours),
                float(part_stroke),
                fill,
                fill_rule,
            )
        )
    return tuple(parts)


def _rotation_degrees_attr(node: GraphNode) -> tuple[float, ...]:
    value = node.attrs.get("placement_rotation_degrees")
    if value is None:
        return (0.0, 90.0)
    if not isinstance(value, list) or not value:
        raise GraphExtractionError(
            f"node {node.id!r}: placement_rotation_degrees is invalid"
        )
    try:
        rotations = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise GraphExtractionError(
            f"node {node.id!r}: placement_rotation_degrees is invalid"
        ) from exc
    return rotations


def _optional_number_attr(node: GraphNode, key: str) -> float | None:
    value = node.attrs.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise GraphExtractionError(
                f"node {node.id!r}: attr {key!r} missing or invalid"
            ) from exc
    return _number_attr(node, key)


def _placement_center_attr(node: GraphNode) -> tuple[float, float] | None:
    value = node.attrs.get("placement_center_mm")
    if value is None:
        return None
    if not isinstance(value, str):
        raise GraphExtractionError(
            f"node {node.id!r}: placement_center_mm is invalid"
        )
    parts = value.split(",")
    if len(parts) != 2:
        raise GraphExtractionError(
            f"node {node.id!r}: placement_center_mm is invalid"
        )
    try:
        return float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise GraphExtractionError(
            f"node {node.id!r}: placement_center_mm is invalid"
        ) from exc


def _qr_matrix_attr(node: GraphNode) -> tuple[str, ...]:
    value = node.attrs.get("qr_module_matrix")
    if value is None:
        return ()
    if (
        not isinstance(value, list)
        or len(value) != 37
        or any(len(row) != 37 for row in value)
        or any(char not in "01" for row in value for char in row)
    ):
        raise GraphExtractionError(f"node {node.id!r}: qr_module_matrix is invalid")
    return tuple(value)


def _depends_on_board(node: GraphNode, board_id: str) -> None:
    if node.depends_on.count(board_id) != 1:
        raise GraphExtractionError(
            f"node {node.id!r} must depend on board {board_id!r} exactly once"
        )


def extract_silkscreen_lane(graph: DesignGraph) -> SilkscreenLane:
    board_nodes = [node for node in graph.nodes if node.kind == "electrical.board"]
    if len(board_nodes) != 1:
        raise GraphExtractionError(
            f"expected exactly one electrical.board node, got {len(board_nodes)}"
        )
    board_id = board_nodes[0].id
    texts: list[SilkTextView] = []
    graphics: list[SilkGraphicView] = []
    for node in graph.nodes:
        if node.kind == "mechanical.silk_text":
            _depends_on_board(node, board_id)
            layer = _str_attr(node, "layer")
            if layer not in {"F.SilkS", "B.SilkS"}:
                raise GraphExtractionError(f"node {node.id!r}: invalid silk layer")
            height = _number_attr(node, "height_mm")
            stroke = _number_attr(node, "stroke_width_mm")
            if height <= 0 or stroke <= 0:
                raise GraphExtractionError(f"node {node.id!r}: silk dimensions must be positive")
            texts.append(
                SilkTextView(
                    node_id=node.id,
                    role=_str_attr(node, "role"),
                    text=_str_attr(node, "text"),
                    x_mm=(
                        _number_attr(node, "x_mm")
                        if node.attrs.get("x_mm") is not None
                        else None
                    ),
                    y_mm=(
                        _number_attr(node, "y_mm")
                        if node.attrs.get("y_mm") is not None
                        else None
                    ),
                    layer=layer,
                    height_mm=height,
                    stroke_width_mm=stroke,
                    rotation_deg=_number_attr(node, "rotation_deg"),
                    placement_basis=_str_attr(node, "placement_basis"),
                    placement_search_order=_str_attr(node, "placement_search_order"),
                    placement_reference=_str_attr(node, "placement_reference"),
                    placement_offset_step_mm=_number_attr(
                        node, "placement_offset_step_mm"
                    ),
                    placement_search_limit_mm=_number_attr(
                        node, "placement_search_limit_mm"
                    ),
                    board_edge_margin_mm=_number_attr(node, "board_edge_margin_mm"),
                    board_edge_margin_source=_str_attr(
                        node, "board_edge_margin_source"
                    ),
                    placement_rotation_degrees=_rotation_degrees_attr(node),
                    placement_safety_margin_mm=_number_attr(
                        node, "placement_safety_margin_mm"
                    ),
                )
            )
        elif node.kind == "mechanical.silk_graphic":
            _depends_on_board(node, board_id)
            layer = _str_attr(node, "layer")
            if layer not in {"F.SilkS", "B.SilkS"}:
                raise GraphExtractionError(f"node {node.id!r}: invalid silk layer")
            stroke = _number_attr(node, "stroke_width_mm")
            if stroke < 0:
                raise GraphExtractionError(
                    f"node {node.id!r}: stroke width must be nonnegative"
                )
            polygon_points = _points_attr(node)
            parts = _graphic_parts_attr(node, polygon_points, stroke)
            source_path_attr = node.attrs.get("source_path")
            source_sha256_attr = node.attrs.get("source_sha256")
            graphics.append(
                SilkGraphicView(
                    node_id=node.id,
                    role=_str_attr(node, "role"),
                    layer=layer,
                    stroke_width_mm=stroke,
                    polygon_points=polygon_points,
                    placement_basis=_str_attr(node, "placement_basis"),
                    placement_search_order=_str_attr(node, "placement_search_order"),
                    board_edge_margin_mm=_number_attr(node, "board_edge_margin_mm"),
                    board_edge_margin_source=_str_attr(
                        node, "board_edge_margin_source"
                    ),
                    contours=tuple(
                        contour for part in parts for contour in part.contours
                    ),
                    fill=parts[0].fill,
                    fill_rule=parts[0].fill_rule,
                    parts=parts,
                    source_path=(
                        source_path_attr if isinstance(source_path_attr, str) else None
                    ),
                    source_sha256=(
                        source_sha256_attr
                        if isinstance(source_sha256_attr, str)
                        else None
                    ),
                    source_scale=_optional_number_attr(node, "source_scale"),
                    placement_center_mm=_placement_center_attr(node),
                    rotation_degrees=_optional_number_attr(node, "rotation_degrees") or 0.0,
                    qr_module_matrix=_qr_matrix_attr(node),
                    qr_source_module_pitch_mm=_optional_number_attr(
                        node, "qr_source_module_pitch_mm"
                    ),
                    qr_module_pitch_mm=_optional_number_attr(node, "qr_module_pitch_mm"),
                    qr_quiet_zone_modules=(
                        int(_number_attr(node, "qr_quiet_zone_modules"))
                        if node.attrs.get("qr_quiet_zone_modules") is not None
                        else None
                    ),
                )
            )
    if not texts and not graphics:
        raise GraphExtractionError("silkscreen declarations are missing (fail-closed)")
    roles = [item.role for item in (*texts, *graphics)]
    if len(roles) != len(set(roles)):
        raise GraphExtractionError("silkscreen roles must be unique")
    return SilkscreenLane(board_node_id=board_id, texts=tuple(texts), graphics=tuple(graphics))
