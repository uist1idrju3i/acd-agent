"""Typed extraction of graph-declared board silkscreen.

Only extraction lives here. Resolving label positions by search is provided as
the ``acd-silkscreen-placement`` skill under ``plugins/acd/skills/``.
"""

from __future__ import annotations

from dataclasses import dataclass

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
            if stroke <= 0:
                raise GraphExtractionError(f"node {node.id!r}: stroke width must be positive")
            graphics.append(
                SilkGraphicView(
                    node_id=node.id,
                    role=_str_attr(node, "role"),
                    layer=layer,
                    stroke_width_mm=stroke,
                    polygon_points=_points_attr(node),
                    placement_basis=_str_attr(node, "placement_basis"),
                    placement_search_order=_str_attr(node, "placement_search_order"),
                    board_edge_margin_mm=_number_attr(node, "board_edge_margin_mm"),
                    board_edge_margin_source=_str_attr(
                        node, "board_edge_margin_source"
                    ),
                )
            )
    if not texts and not graphics:
        raise GraphExtractionError("silkscreen declarations are missing (fail-closed)")
    roles = [item.role for item in (*texts, *graphics)]
    if len(roles) != len(set(roles)):
        raise GraphExtractionError("silkscreen roles must be unique")
    return SilkscreenLane(board_node_id=board_id, texts=tuple(texts), graphics=tuple(graphics))
