"""Typed extraction of graph-declared board silkscreen."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import cast

from acd_core.board_model import BoardModel, ComponentPlacement, PadShape
from acd_core.electrical import GraphExtractionError
from acd_schema.design_graph import DesignGraph, GraphNode


@dataclass(frozen=True)
class SilkTextView:
    node_id: str
    role: str
    text: str
    x_mm: float
    y_mm: float
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
    placement_rotation_degrees: tuple[float, ...] = (0.0, 90.0)
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
                    x_mm=_number_attr(node, "x_mm"),
                    y_mm=_number_attr(node, "y_mm"),
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


def _text_size(text: SilkTextView) -> tuple[float, float]:
    width = max(text.height_mm * 0.6 * len(text.text), text.height_mm)
    if int(text.rotation_deg) % 180:
        return text.height_mm, width
    return width, text.height_mm


def _footprint_bbox(
    board: BoardModel, refdes: str
) -> tuple[float, float, float, float]:
    placement = board.placement_by_refdes(refdes)
    footprint = placement.footprint
    points: list[tuple[float, float]] = []
    for pad in footprint.pads:
        half_x = pad.size_x_mm / 2.0
        half_y = pad.size_y_mm / 2.0
        points.extend(
            (
                (pad.x_mm - half_x, pad.y_mm - half_y),
                (pad.x_mm + half_x, pad.y_mm + half_y),
            )
        )
    if footprint.courtyard_bbox_mm is not None:
        x1, y1, x2, y2 = footprint.courtyard_bbox_mm
        points.extend(((x1, y1), (x2, y2)))
    if not points:
        raise GraphExtractionError(
            f"silk placement reference {refdes!r} has no footprint geometry"
        )
    # GD1 placements are orthogonal; reject unsupported rotations rather than
    # silently using an incorrect clearance frame.
    rotation = placement.rotation_deg % 360.0
    if rotation not in {0.0, 90.0, 180.0, 270.0}:
        raise GraphExtractionError(
            f"silk placement reference {refdes!r} has unsupported rotation"
        )
    transformed: list[tuple[float, float]] = []
    for x, y in points:
        if rotation == 0.0:
            tx, ty = x, y
        elif rotation == 90.0:
            tx, ty = -y, x
        elif rotation == 180.0:
            tx, ty = -x, -y
        else:
            tx, ty = y, -x
        transformed.append((placement.x_mm + tx, placement.y_mm + ty))
    xs, ys = zip(*transformed, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def _pad_bbox(
    board: BoardModel, placement: ComponentPlacement, pad: PadShape
) -> tuple[float, float, float, float]:
    """Return a conservative world-space pad bbox including both rotations."""
    component = placement
    pad_rotation = (pad.rotation_deg + component.rotation_deg) % 360.0
    if pad_rotation not in {0.0, 90.0, 180.0, 270.0}:
        raise GraphExtractionError("unsupported pad rotation in silk placement search")
    points: list[tuple[float, float]] = []
    for x, y in (
        (pad.x_mm - pad.size_x_mm / 2.0, pad.y_mm - pad.size_y_mm / 2.0),
        (pad.x_mm + pad.size_x_mm / 2.0, pad.y_mm + pad.size_y_mm / 2.0),
    ):
        if pad_rotation == 0.0:
            tx, ty = x, y
        elif pad_rotation == 90.0:
            tx, ty = -y, x
        elif pad_rotation == 180.0:
            tx, ty = -x, -y
        else:
            tx, ty = y, -x
        points.append((component.x_mm + tx, component.y_mm + ty))
    xs, ys = zip(*points, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def _placement_bbox(
    placement: ComponentPlacement,
) -> tuple[float, float, float, float] | None:
    local = placement.footprint.body_bbox_mm
    if local is None:
        return None
    x1, y1, x2, y2 = local
    return _transform_bbox(placement, (x1, y1, x2, y2))


def _transform_bbox(
    placement: ComponentPlacement,
    bbox: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = bbox
    corners = ((x1, y1), (x1, y2), (x2, y1), (x2, y2))
    angle = placement.rotation_deg % 360.0
    if angle not in {0.0, 90.0, 180.0, 270.0}:
        raise GraphExtractionError("unsupported body rotation in silk search")
    transformed: list[tuple[float, float]] = []
    for x, y in corners:
        if angle == 0.0:
            tx, ty = x, y
        elif angle == 90.0:
            tx, ty = -y, x
        elif angle == 180.0:
            tx, ty = -x, -y
        else:
            tx, ty = y, -x
        transformed.append((placement.x_mm + tx, placement.y_mm + ty))
    xs, ys = zip(*transformed, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def _rects_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return not (
        first[2] <= second[0]
        or second[2] <= first[0]
        or first[3] <= second[1]
        or second[3] <= first[1]
    )


def _rect_overlap_area(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    x_overlap = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    y_overlap = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    return x_overlap * y_overlap


def resolve_silkscreen_placements(
    lane: SilkscreenLane, board: BoardModel
) -> SilkscreenLane:
    """Resolve declared functional labels by deterministic perimeter search."""
    resolved: list[SilkTextView] = []
    evidence: list[dict[str, object]] = []
    order_aliases = {
        "top": (0.0, -1.0),
        "bottom": (0.0, 1.0),
        "right": (1.0, 0.0),
        "left": (-1.0, 0.0),
        "top_right": (1.0, -1.0),
        "bottom_right": (1.0, 1.0),
        "bottom_left": (-1.0, 1.0),
        "top_left": (-1.0, -1.0),
    }
    for text in lane.texts:
        if not (
            text.role.startswith("functional_label_")
            or text.role == "connector_identifier"
        ):
            resolved.append(text)
            evidence.append(
                {
                    "node_id": text.node_id,
                    "role": text.role,
                    "reference": text.placement_reference,
                    "search_order": text.placement_search_order.split(","),
                    "offset_step_mm": text.placement_offset_step_mm,
                    "search_limit_mm": text.placement_search_limit_mm,
                    "board_edge_margin_mm": text.board_edge_margin_mm,
                    "accepted_position_mm": [text.x_mm, text.y_mm],
                    "rejected_candidates": [],
                    "resolution": "graph_declared_backside_position",
                }
            )
            continue
        reference = text.placement_reference
        is_board_target = reference == lane.board_node_id
        target = (
            (0.0, 0.0, board.width_mm, board.height_mm)
            if is_board_target
            else _footprint_bbox(board, reference)
        )
        edge_margin = text.stroke_width_mm * 3.5 + text.placement_safety_margin_mm
        order = tuple(
            item.strip()
            for item in text.placement_search_order.split(",")
            if item.strip()
        )
        if not order or any(item not in order_aliases for item in order):
            raise GraphExtractionError(
                f"silk text {text.node_id!r} has invalid placement search order"
            )
        step = text.placement_offset_step_mm
        limit = text.placement_search_limit_mm
        if step <= 0 or limit < step:
            raise GraphExtractionError(
                f"silk text {text.node_id!r} has invalid placement search range"
            )
        rotations = tuple(text.placement_rotation_degrees)
        if not rotations or any(
            rotation % 90.0 != 0.0 for rotation in rotations
        ):
            raise GraphExtractionError(
                f"silk text {text.node_id!r} has invalid placement rotations"
            )
        rejected: list[dict[str, object]] = []
        valid_candidates: list[dict[str, object]] = []
        offsets = [
            round(step * index, 9)
            for index in range(1, int(limit / step) + 1)
        ]
        tangent_offsets = [0.0]
        for offset in offsets:
            tangent_offsets.extend((offset, -offset))
        for rotation_index, rotation in enumerate(rotations):
            sized_text = replace(text, rotation_deg=rotation)
            text_width, text_height = _text_size(sized_text)
            text_width += edge_margin
            text_height += edge_margin
            for side_index, side in enumerate(order):
                dx, dy = order_aliases[side]
                for offset in offsets:
                    for tangent in tangent_offsets:
                        if is_board_target:
                            if dx > 0:
                                x = board.width_mm - text_width / 2 - offset
                                y = board.height_mm / 2 + tangent
                            elif dx < 0:
                                x = text_width / 2 + offset
                                y = board.height_mm / 2 + tangent
                            elif dy < 0:
                                x = board.width_mm / 2 + tangent
                                y = text_height / 2 + offset
                            else:
                                x = board.width_mm / 2 + tangent
                                y = board.height_mm - text_height / 2 - offset
                        elif dx:
                            x = (
                                target[2] + text_width / 2 + offset
                                if dx > 0
                                else target[0] - text_width / 2 - offset
                            )
                            y = (target[1] + target[3]) / 2 + tangent
                        elif dy:
                            x = (target[0] + target[2]) / 2 + tangent
                            y = (
                                target[1] - text_height / 2 - offset
                                if dy < 0
                                else target[3] + text_height / 2 + offset
                            )
                        else:
                            raise GraphExtractionError(
                                "invalid zero placement direction"
                            )
                        bbox = (
                            x - text_width / 2,
                            y - text_height / 2,
                            x + text_width / 2,
                            y + text_height / 2,
                        )
                        if (
                            bbox[0] < text.board_edge_margin_mm
                            or bbox[1] < text.board_edge_margin_mm
                            or bbox[2] > board.width_mm - text.board_edge_margin_mm
                            or bbox[3] > board.height_mm - text.board_edge_margin_mm
                        ):
                            reason = "board_edge_overflow"
                            courtyard_overlap_area = 0.0
                        else:
                            reason = None
                            courtyard_overlap_area = 0.0
                            for placement in board.placements:
                                body_box = _placement_bbox(placement)
                                if body_box is not None and _rects_overlap(
                                    bbox, body_box
                                ):
                                    reason = f"body_overlap:{placement.refdes}"
                                    break
                                courtyard_box = placement.footprint.courtyard_bbox_mm
                                if courtyard_box is not None:
                                    transformed_courtyard = _transform_bbox(
                                        placement, courtyard_box
                                    )
                                    courtyard_overlap_area += _rect_overlap_area(
                                        bbox, transformed_courtyard
                                    )
                                for pad in placement.footprint.pads:
                                    pad_box = _pad_bbox(board, placement, pad)
                                    if _rects_overlap(bbox, pad_box):
                                        reason = (
                                            f"pad_overlap:{placement.refdes}:"
                                            f"{pad.number}"
                                        )
                                        break
                                if reason:
                                    break
                        if reason is not None:
                            rejected.append(
                                {
                                    "side": side,
                                    "rotation_deg": rotation,
                                    "offset_mm": offset,
                                    "tangent_offset_mm": tangent,
                                    "reason": reason,
                                }
                            )
                            continue
                        valid_candidates.append(
                            {
                                "x_mm": x,
                                "y_mm": y,
                                "rotation_deg": rotation,
                                "distance_mm": math.hypot(
                                    x - (target[0] + target[2]) / 2.0,
                                    y - (target[1] + target[3]) / 2.0,
                                ),
                                "courtyard_overlap_area_mm2": courtyard_overlap_area,
                                "side_index": side_index,
                                "rotation_index": rotation_index,
                                "offset_mm": offset,
                                "tangent_offset_mm": tangent,
                            }
                        )
        if not valid_candidates:
            raise GraphExtractionError(
                f"silk text {text.node_id!r} has no valid placement (fail-closed)"
            )
        chosen = min(
            valid_candidates,
            key=lambda candidate: (
                candidate["distance_mm"],
                candidate["side_index"],
                candidate["rotation_index"],
                candidate["courtyard_overlap_area_mm2"],
                candidate["offset_mm"],
                candidate["tangent_offset_mm"],
            ),
        )
        resolved_text = replace(
            text,
            x_mm=cast(float, chosen["x_mm"]),
            y_mm=cast(float, chosen["y_mm"]),
            rotation_deg=cast(float, chosen["rotation_deg"]),
        )
        resolved.append(resolved_text)
        evidence.append(
            {
                "node_id": text.node_id,
                "role": text.role,
                "reference": reference,
                "search_order": list(order),
                "offset_step_mm": step,
                "search_limit_mm": limit,
                "board_edge_margin_mm": text.board_edge_margin_mm,
                    "rotation_degrees": list(rotations),
                    "placement_safety_margin_mm": text.placement_safety_margin_mm,
                "accepted_position_mm": [chosen["x_mm"], chosen["y_mm"]],
                "accepted_rotation_deg": chosen["rotation_deg"],
                "reference_center_distance_mm": chosen["distance_mm"],
                "courtyard_overlap_area_mm2": chosen[
                    "courtyard_overlap_area_mm2"
                ],
                "candidate_selection": (
                    "minimum reference-center distance; ties use declared "
                    "search order, rotation order, then courtyard overlap"
                ),
                "rejected_candidates": rejected,
            }
        )
    return replace(
        lane,
        texts=tuple(resolved),
        placement_evidence=tuple(evidence),
    )
