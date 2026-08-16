"""Deterministic silkscreen label placement search (skill asset, not an ACD gate).

Functional labels declared in the design graph without a fixed position are
resolved by a perimeter search around the declared reference: candidate sides in
the declared order, offsets on the declared step, orthogonal rotations only.
Candidates overlapping pads, component bodies or the board edge margin are
rejected and recorded as evidence.

The chosen positions are candidates. They become design data once written to the
design input files, and the silkscreen result is judged by the ACD projection and
the DRC/reload gates, not by this script.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import cast

from acd_core.board_model import BoardModel, ComponentPlacement, PadShape
from acd_core.electrical import GraphExtractionError
from acd_core.silkscreen import SilkscreenLane, SilkTextView


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
