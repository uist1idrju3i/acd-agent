# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@ba8e90b14ebf71464fc4579461a67650716b82be",
# ]
# ///
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
# pyright: reportUnknownVariableType=false,reportUnknownArgumentType=false,reportUnknownMemberType=false,reportUnknownParameterType=false,reportInvalidTypeForm=false,reportUnusedVariable=false,reportUnusedImport=false,reportGeneralTypeIssues=false,reportArgumentType=false

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from acd.core.board_model import (
    BoardModel,
    BoardNet,
    ComponentPlacement,
    CopperZone,
    FootprintShape,
    KeepoutRect,
    NetClass,
    PadShape,
)
from acd.core.electrical import GraphExtractionError
from acd.core.silkscreen import SilkGraphicView, SilkscreenLane, SilkTextView

SILK_TEXT_ADVANCE_RATIO = 0.95
SILK_TEXT_ATTRIBUTION_MARGIN_STROKE_WIDTHS = 1.0
SILK_TEXT_DESCENDER_CHARS = frozenset("gjpqy")
SILK_TEXT_DESCENDER_HEIGHT_RATIO = 1.45


@dataclass(frozen=True)
class _ContextGridBundle:
    """Shared context for one text's grid evaluation."""

    text: SilkTextView
    outline: tuple[float, float, float, float]
    pads: tuple[dict[str, Any], ...]
    masks: tuple[dict[str, Any], ...]
    mask_openings: tuple[object, ...]
    existing: tuple[dict[str, Any], ...]
    fixed: tuple[dict[str, Any], ...]
    bodies: tuple[dict[str, Any], ...]
    courtyards: tuple[dict[str, Any], ...]
    dynamic_silk: tuple[dict[str, Any], ...]
    target: tuple[float, float, float, float] | None
    center: tuple[float, float]
    reference: str | None


@dataclass(frozen=True)
class _ContextGridColumn:
    """Describe one rotation and x-column grid partition."""

    rotation: float
    x: float
    width: float
    height: float
    measured_width: float
    measured_height: float


@dataclass(frozen=True)
class _ContextGridChunk:
    """Group grid columns so each process task reuses one context bundle."""

    bundle: _ContextGridBundle
    columns: tuple[_ContextGridColumn, ...]


def _context_bbox(
    item: dict[str, Any], key: str = "bbox_mm"
) -> tuple[float, float, float, float]:
    value = item.get(key)
    if not isinstance(value, list) or len(value) != 4:
        raise GraphExtractionError(f"silkscreen context {key} contains malformed bbox")
    parts = tuple(float(part) for part in value)
    if len(parts) != 4:
        raise GraphExtractionError(f"silkscreen context {key} contains malformed bbox")
    return (parts[0], parts[1], parts[2], parts[3])


def _context_distance(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    dx = max(right[0] - left[2], left[0] - right[2], 0.0)
    dy = max(right[1] - left[3], left[1] - right[3], 0.0)
    return (dx * dx + dy * dy) ** 0.5


def _evaluate_context_grid_partition(
    bundle: _ContextGridBundle,
    column: _ContextGridColumn,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Evaluate one rotation and x-column partition in declaration order."""
    text = bundle.text
    candidates: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    y = bundle.outline[1] + column.height / 2
    while y <= bundle.outline[3] - column.height / 2 + 1e-9:
        candidate_bbox = (
            column.x - column.width / 2,
            y - column.height / 2,
            column.x + column.width / 2,
            y + column.height / 2,
        )
        attribution_bbox = (
            column.x - column.measured_width / 2,
            y - column.measured_height / 2,
            column.x + column.measured_width / 2,
            y + column.measured_height / 2,
        )
        candidate = {
            "x_mm": round(column.x, 9),
            "y_mm": round(y, 9),
            "rotation_deg": column.rotation,
            "layer": text.layer,
            "bbox_mm": list(candidate_bbox),
        }
        reason: str | None = None
        margin = text.board_edge_margin_mm
        if (
            candidate_bbox[0] < bundle.outline[0] + margin
            or candidate_bbox[1] < bundle.outline[1] + margin
            or candidate_bbox[2] > bundle.outline[2] - margin
            or candidate_bbox[3] > bundle.outline[3] - margin
        ):
            reason = "board_edge_margin"
        else:
            for item in bundle.pads:
                layers = item.get("layers")
                if not isinstance(layers, list):
                    raise GraphExtractionError("silkscreen context pad layers are missing")
                if text.layer.replace("SilkS", "Cu") in layers and _rects_overlap(
                    candidate_bbox, _context_bbox(item)
                ):
                    reason = "pad_bboxes_mm"
                    break
        if reason is None:
            mask_layer = "F.Mask" if text.layer == "F.SilkS" else "B.Mask"
            for item in bundle.masks:
                if item.get("layer") == mask_layer and _rects_overlap(
                    candidate_bbox, _context_bbox(item)
                ):
                    reason = "mask_opening_bboxes_mm"
                    break
        if reason is None:
            mask_layer = "F.Mask" if text.layer == "F.SilkS" else "B.Mask"
            for item in bundle.mask_openings:
                if isinstance(item, dict):
                    if item.get("layer") != mask_layer:
                        continue
                    item_bbox = item.get("bbox_mm")
                    if not isinstance(item_bbox, list):
                        raise GraphExtractionError(
                            "silkscreen context mask_opening_bboxes_mm contains malformed bbox"
                        )
                elif isinstance(item, list):
                    item_bbox = item
                else:
                    raise GraphExtractionError(
                        "silkscreen context mask_opening_bboxes_mm contains malformed bbox"
                    )
                if len(item_bbox) != 4:
                    raise GraphExtractionError(
                        "silkscreen context mask_opening_bboxes_mm contains malformed bbox"
                    )
                if _rects_overlap(
                    candidate_bbox,
                    tuple(float(part) for part in item_bbox),
                ):
                    reason = "mask_opening_bboxes_mm"
                    break
        if reason is None:
            for source, item in (
                [("existing_silk_objects", item) for item in bundle.existing]
                + [("fixed_silk_objects", item) for item in bundle.fixed]
            ):
                if item.get("layer") == text.layer and _rects_overlap(
                    candidate_bbox, _context_bbox(item)
                ):
                    reason = source
                    break
        if reason is None:
            for item in bundle.dynamic_silk:
                if item.get("layer") == text.layer and _rects_overlap(
                    candidate_bbox, _context_bbox(item)
                ):
                    reason = "placed_declaration"
                    break
        if reason is None:
            copper_layer = text.layer.replace("SilkS", "Cu")
            for item in bundle.bodies + bundle.courtyards:
                if item.get("layer") == copper_layer and _rects_overlap(
                    candidate_bbox, _context_bbox(item)
                ):
                    reason = (
                        "body_bboxes_mm"
                        if item in bundle.bodies
                        else "courtyard_bboxes_mm"
                    )
                    break
        if reason is None and bundle.reference is not None:
            component_distances: dict[str, float] = {}
            for item in bundle.bodies + bundle.courtyards:
                refdes = item.get("refdes")
                if (
                    isinstance(refdes, str)
                    and item.get("layer") == text.layer.replace("SilkS", "Cu")
                ):
                    component_distances[refdes] = min(
                        component_distances.get(refdes, float("inf")),
                        _context_distance(attribution_bbox, _context_bbox(item)),
                    )
            nearest = (
                min(component_distances.items(), key=lambda item: (item[1], item[0]))
                if component_distances
                else None
            )
            if nearest is not None and nearest[0] != bundle.reference:
                reason = "nearest_component_mismatch"
        if reason is None:
            candidate["distance_mm"] = (
                _context_distance(candidate_bbox, bundle.target)
                if bundle.target is not None
                else _context_distance(
                    candidate_bbox,
                    (
                        bundle.center[0],
                        bundle.center[1],
                        bundle.center[0],
                        bundle.center[1],
                    ),
                )
            )
            candidates.append(candidate)
        else:
            rejected.append({**candidate, "reason": reason})
        y = round(y + text.placement_offset_step_mm, 9)
    return candidates, rejected


def _evaluate_context_grid_chunk(
    chunk: _ContextGridChunk,
) -> tuple[
    tuple[list[dict[str, object]], list[dict[str, object]]],
    ...,
]:
    """Evaluate a declaration-ordered chunk of grid columns."""
    return tuple(
        _evaluate_context_grid_partition(chunk.bundle, column)
        for column in chunk.columns
    )


def _resolve_single_text_for_order(
    item: tuple[SilkscreenLane, dict[str, Any]],
) -> tuple[dict[str, object], ...]:
    """Resolve one text for candidate-count ordering without nested parallelism."""
    lane, context = item
    return _resolve_from_context_impl(lane, context, False, None, 1)


def _text_size(
    text: SilkTextView,
    *,
    advance_ratio: float = SILK_TEXT_ADVANCE_RATIO,
    attribution_margin_stroke_widths: float = SILK_TEXT_ATTRIBUTION_MARGIN_STROKE_WIDTHS,
    descender_chars: str = "".join(sorted(SILK_TEXT_DESCENDER_CHARS)),
    descender_height_ratio: float = SILK_TEXT_DESCENDER_HEIGHT_RATIO,
) -> tuple[float, float]:
    width = max(text.height_mm * advance_ratio * len(text.text), text.height_mm)
    height = text.height_mm * (
        descender_height_ratio if any(char in descender_chars for char in text.text) else 1.0
    )
    margin = text.stroke_width_mm * attribution_margin_stroke_widths
    width += 2.0 * margin
    height += margin
    if int(text.rotation_deg) % 180:
        return height, width
    return width, height


def _footprint_bbox(board: BoardModel, refdes: str) -> tuple[float, float, float, float]:
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
        raise GraphExtractionError(f"silk placement reference {refdes!r} has no footprint geometry")
    # GD1 placements are orthogonal; reject unsupported rotations rather than
    # silently using an incorrect clearance frame.
    rotation = placement.rotation_deg % 360.0
    if rotation not in {0.0, 90.0, 180.0, 270.0}:
        raise GraphExtractionError(f"silk placement reference {refdes!r} has unsupported rotation")
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


def resolve_silkscreen_placements(lane: SilkscreenLane, board: BoardModel) -> SilkscreenLane:
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
        searchable = (
            text.role.startswith("functional_label_")
            or text.role == "connector_identifier"
            or text.role in {"board_type", "board_part_number"}
        )
        if not searchable:
            if text.x_mm is None or text.y_mm is None:
                raise GraphExtractionError(
                    f"silk text {text.node_id!r} has no declared position (fail-closed)"
                )
            resolved.append(text)
            evidence.append(
                {
                    "node_id": text.node_id,
                    "role": text.role,
                    "reference": text.placement_reference,
                    "search_order": text.placement_search_order.split(","),
                    "offset_step_mm": text.placement_offset_step_mm,
                    "search_limit_mm": text.placement_search_limit_mm,
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
            item.strip() for item in text.placement_search_order.split(",") if item.strip()
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
        if not rotations or any(rotation % 90.0 != 0.0 for rotation in rotations):
            raise GraphExtractionError(
                f"silk text {text.node_id!r} has invalid placement rotations"
            )
        rejected: list[dict[str, object]] = []
        valid_candidates: list[dict[str, object]] = []
        offsets = [round(step * index, 9) for index in range(1, int(limit / step) + 1)]
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
                            raise GraphExtractionError("invalid zero placement direction")
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
                                if body_box is not None and _rects_overlap(bbox, body_box):
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
                                        reason = f"pad_overlap:{placement.refdes}:{pad.number}"
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
                "courtyard_overlap_area_mm2": chosen["courtyard_overlap_area_mm2"],
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


def resolve_from_context_offsets(
    lane: SilkscreenLane, context: dict[str, Any]
) -> tuple[dict[str, object], ...]:
    """Return candidates using only gate-measured context geometry."""
    outline_raw = context.get("board_outline_bbox_mm")
    if not isinstance(outline_raw, list) or len(outline_raw) != 4:
        raise GraphExtractionError("silkscreen context outline is missing")
    outline = tuple(float(item) for item in outline_raw)
    min_width = float(context.get("requirements", {}).get("min_silk_width_mm", 0.0))
    min_height = float(context.get("requirements", {}).get("min_silk_height_mm", 0.0))
    if min_width <= 0 or min_height <= 0:
        raise GraphExtractionError("silkscreen context capability requirements are missing")
    forbidden: list[tuple[str, str | None, tuple[float, float, float, float]]] = []
    for key in ("pad_bboxes_mm",):
        values = context.get(key)
        if not isinstance(values, list):
            raise GraphExtractionError(f"silkscreen context {key} is missing")
        for value in values:
            if not isinstance(value, list) or len(value) != 4:
                raise GraphExtractionError(f"silkscreen context {key} contains malformed bbox")
            forbidden.append((key, None, tuple(float(item) for item in value)))
    values = context.get("mask_objects")
    if not isinstance(values, list):
        raise GraphExtractionError("silkscreen context mask_objects is missing")
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("bbox_mm"), list):
            raise GraphExtractionError("silkscreen context mask_objects contains malformed object")
        bbox = value["bbox_mm"]
        if len(bbox) != 4:
            raise GraphExtractionError("silkscreen context mask_objects contains malformed bbox")
        forbidden.append(
            (
                "mask_objects",
                str(value.get("layer")),
                tuple(float(item) for item in bbox),
            )
        )
    for key in ("body_bboxes_mm", "courtyard_bboxes_mm"):
        values = context.get(key)
        if not isinstance(values, list):
            raise GraphExtractionError(f"silkscreen context {key} is missing")
        for value in values:
            if not isinstance(value, dict) or not isinstance(value.get("bbox_mm"), list):
                raise GraphExtractionError(f"silkscreen context {key} contains malformed bbox")
            bbox = value["bbox_mm"]
            if len(bbox) != 4:
                raise GraphExtractionError(f"silkscreen context {key} contains malformed bbox")
            forbidden.append((key, None, tuple(float(item) for item in bbox)))
    for key in ("existing_silk_objects", "fixed_silk_objects"):
        values = context.get(key)
        if not isinstance(values, list):
            raise GraphExtractionError(f"silkscreen context {key} is missing")
        for value in values:
            if not isinstance(value, dict):
                raise GraphExtractionError(f"silkscreen context {key} contains malformed object")
            bbox = value.get("bbox_mm")
            if not isinstance(bbox, list) or len(bbox) != 4:
                raise GraphExtractionError(f"silkscreen context {key} contains malformed bbox")
            forbidden.append(
                (
                    key,
                    str(value.get("layer")),
                    tuple(float(item) for item in bbox),
                )
            )
    for value in context.get("silk_objects", []):
        if not isinstance(value, dict) or not isinstance(value.get("bbox_mm"), list):
            raise GraphExtractionError("silkscreen context silk_objects contains malformed object")
    directions = {
        "top": (0.0, -1.0),
        "bottom": (0.0, 1.0),
        "right": (1.0, 0.0),
        "left": (-1.0, 0.0),
        "top_right": (1.0, -1.0),
        "bottom_right": (1.0, 1.0),
        "bottom_left": (-1.0, 1.0),
        "top_left": (-1.0, -1.0),
    }
    body_by_ref = {
        str(item["refdes"]): tuple(float(value) for value in item["bbox_mm"])
        for item in context["body_bboxes_mm"]
    }
    courtyard_by_ref = {
        str(item["refdes"]): tuple(float(value) for value in item["bbox_mm"])
        for item in context["courtyard_bboxes_mm"]
    }
    results: list[dict[str, object]] = []
    for text in lane.texts:
        target = (
            outline
            if text.placement_reference == lane.board_node_id
            else body_by_ref.get(text.placement_reference)
            or courtyard_by_ref.get(text.placement_reference)
        )
        if target is None:
            raise GraphExtractionError(
                f"silkscreen context has no geometry for {text.placement_reference!r}"
            )
        order = tuple(
            item.strip()
            for item in text.placement_search_order.split(",")
            if item.strip()
        )
        if not order or any(item not in directions for item in order):
            raise GraphExtractionError(f"silk text {text.node_id!r} has invalid search order")
        if text.stroke_width_mm < min_width or text.height_mm < min_height:
            raise GraphExtractionError(
                f"silk text {text.node_id!r} is below measured capability (fail-closed)"
            )
        rejected: list[dict[str, object]] = []
        candidates: list[dict[str, object]] = []
        edge_margin = text.board_edge_margin_mm
        for rotation_index, rotation in enumerate(text.placement_rotation_degrees):
            width, height = _text_size(replace(text, rotation_deg=rotation))
            offsets = [
                round(text.placement_offset_step_mm * index, 9)
                for index in range(
                    1, int(text.placement_search_limit_mm / text.placement_offset_step_mm) + 1
                )
            ]
            for side_index, side in enumerate(order):
                dx, dy = directions[side]
                for offset in offsets:
                    if text.placement_reference == lane.board_node_id:
                        x = (
                            outline[2] - width / 2 - offset
                            if dx > 0
                            else outline[0] + width / 2 + offset
                            if dx < 0
                            else (outline[0] + outline[2]) / 2
                        )
                        y = (
                            outline[1] + height / 2 + offset
                            if dy < 0
                            else outline[3] - height / 2 - offset
                            if dy > 0
                            else (outline[1] + outline[3]) / 2
                        )
                    else:
                        x = (
                            target[2] + width / 2 + offset
                            if dx > 0
                            else target[0] - width / 2 - offset
                            if dx < 0
                            else (target[0] + target[2]) / 2
                        )
                        y = (
                            target[1] - height / 2 - offset
                            if dy < 0
                            else target[3] + height / 2 + offset
                            if dy > 0
                            else (target[1] + target[3]) / 2
                        )
                    bbox = (x - width / 2, y - height / 2, x + width / 2, y + height / 2)
                    reason: str | None = None
                    if (
                        bbox[0] < outline[0] + edge_margin
                        or bbox[1] < outline[1] + edge_margin
                        or bbox[2] > outline[2] - edge_margin
                        or bbox[3] > outline[3] - edge_margin
                    ):
                        reason = "board_edge_margin"
                    else:
                        for name, layer, rect in forbidden:
                            if layer is not None and layer != text.layer:
                                continue
                            if _rects_overlap(bbox, rect):
                                reason = name
                                break
                    candidate = {
                        "x_mm": x,
                        "y_mm": y,
                        "rotation_deg": rotation,
                        "layer": text.layer,
                        "bbox_mm": list(bbox),
                    }
                    if reason is not None:
                        rejected.append({**candidate, "reason": reason})
                    else:
                        candidates.append(
                            {
                                **candidate,
                                "side_index": side_index,
                                "rotation_index": rotation_index,
                                "offset_mm": offset,
                            }
                        )
        if not candidates:
            results.append(
                {
                    "node_id": text.node_id,
                    "role": text.role,
                    "candidates": [],
                    "rejected_candidates": rejected,
                    "resolution": "no_candidate_fail_closed",
                }
            )
            continue
        chosen = min(
            candidates,
            key=lambda item: (
                float(item["offset_mm"]),
                int(item["side_index"]),
                int(item["rotation_index"]),
            ),
        )
        results.append(
            {
                "node_id": text.node_id,
                "role": text.role,
                "candidates": candidates,
                "rejected_candidates": rejected,
                "accepted_position_mm": [chosen["x_mm"], chosen["y_mm"]],
                "accepted_rotation_deg": chosen["rotation_deg"],
                "resolution": "context_candidate",
            }
        )
    return tuple(results)


def _resolve_from_context_impl(
    lane: SilkscreenLane,
    context: dict[str, Any],
    _compute_order: bool = True,
    executor: ProcessPoolExecutor | None = None,
    workers: int = 1,
) -> tuple[dict[str, object], ...]:
    """Search the complete board grid using only measured context."""
    outline_raw = context.get("board_outline_bbox_mm")
    requirements = context.get("requirements")
    if (
        not isinstance(outline_raw, list)
        or len(outline_raw) != 4
        or not isinstance(requirements, dict)
    ):
        raise GraphExtractionError("silkscreen context capability requirements are missing")
    outline = tuple(float(item) for item in outline_raw)
    min_width = float(requirements.get("min_silk_width_mm", 0.0))
    min_height = float(requirements.get("min_silk_height_mm", 0.0))
    advance_ratio = float(requirements.get("silk_text_advance_ratio", 0.0))
    margin_stroke_widths = float(
        requirements.get("silk_text_attribution_margin_stroke_widths", 0.0)
    )
    descender_chars = requirements.get("silk_text_descender_chars")
    descender_ratio = float(
        requirements.get("silk_text_descender_height_ratio", 0.0)
    )
    if (
        min_width <= 0
        or min_height <= 0
        or advance_ratio <= 0
        or margin_stroke_widths <= 0
        or not isinstance(descender_chars, str)
        or not descender_chars
        or descender_ratio <= 0
    ):
        raise GraphExtractionError("silkscreen context capability requirements are missing")

    def boxes(key: str) -> list[dict[str, Any]]:
        value = context.get(key)
        if not isinstance(value, list):
            raise GraphExtractionError(f"silkscreen context {key} is missing")
        if not all(isinstance(item, dict) for item in value):
            raise GraphExtractionError(f"silkscreen context {key} contains malformed bbox")
        return value

    pads = boxes("pad_bboxes_mm")
    masks = boxes("mask_objects")
    mask_openings = context.get("mask_opening_bboxes_mm", [])
    if not isinstance(mask_openings, list):
        raise GraphExtractionError(
            "silkscreen context mask_opening_bboxes_mm is malformed"
        )
    bodies = boxes("body_bboxes_mm")
    courtyards = boxes("courtyard_bboxes_mm")
    existing = boxes("existing_silk_objects")
    fixed = boxes("fixed_silk_objects")
    declarations = boxes("declarations")
    declaration_sizes = {
        str(item["node_id"]): (
            float(item["measured_text_length_mm"]),
            float(item["measured_height_mm"]),
        )
        for item in declarations
        if "node_id" in item
        and "measured_text_length_mm" in item
        and "measured_height_mm" in item
    }

    def bbox(item: dict[str, Any], key: str = "bbox_mm") -> tuple[float, float, float, float]:
        value = item.get(key)
        if not isinstance(value, list) or len(value) != 4:
            raise GraphExtractionError(f"silkscreen context {key} contains malformed bbox")
        parts = tuple(float(part) for part in value)
        if len(parts) != 4:
            raise GraphExtractionError(f"silkscreen context {key} contains malformed bbox")
        return (parts[0], parts[1], parts[2], parts[3])

    known_refs = {
        str(item.get("refdes"))
        for item in bodies + courtyards
        if isinstance(item.get("refdes"), str)
    }
    results_by_id: dict[str, dict[str, object]] = {}
    dynamic_silk: list[dict[str, Any]] = []
    if _compute_order and len(lane.texts) > 1:
        order_inputs = tuple(
            (SilkscreenLane(lane.board_node_id, (text,), ()), context)
            for text in lane.texts
        )
        if executor is None:
            order_results = tuple(
                _resolve_single_text_for_order(item) for item in order_inputs
            )
        else:
            order_results = tuple(
                executor.map(_resolve_single_text_for_order, order_inputs)
            )
        candidate_counts = {
            text.node_id: len(cast(list[object], result[0].get("candidates", [])))
            for text, result in zip(lane.texts, order_results, strict=True)
        }
        ordered_texts = sorted(
            lane.texts,
            key=lambda text: (candidate_counts[text.node_id], text.node_id),
        )
    else:
        ordered_texts = list(lane.texts)
    # Main-pass texts remain sequential because accepted placements update
    # dynamic_silk and become obstacles for later texts.
    for text in ordered_texts:
        if text.height_mm < min_height or text.stroke_width_mm < min_width:
            raise GraphExtractionError(
                f"silk text {text.node_id!r} is below measured capability (fail-closed)"
            )
        reference = (
            text.placement_reference
            if text.placement_reference in known_refs
            else None
        )
        target_boxes = [
            bbox(item)
            for item in bodies + courtyards
            if item.get("refdes") == reference
            and item.get("layer") == text.layer.replace("SilkS", "Cu")
        ]
        target = target_boxes[0] if target_boxes else None
        center = (
            ((target[0] + target[2]) / 2, (target[1] + target[3]) / 2)
            if target is not None
            else ((outline[0] + outline[2]) / 2, (outline[1] + outline[3]) / 2)
        )
        step = text.placement_offset_step_mm
        if step <= 0:
            raise GraphExtractionError("silkscreen context grid step is invalid")
        candidates: list[dict[str, object]] = []
        rejected: list[dict[str, object]] = []
        columns: list[_ContextGridColumn] = []
        for rotation in text.placement_rotation_degrees:
            base_size = declaration_sizes.get(text.node_id)
            if base_size is None:
                raise GraphExtractionError(
                    f"silkscreen context declaration is missing for {text.node_id!r}"
                )
            width, height = _text_size(
                replace(text, rotation_deg=rotation),
                advance_ratio=advance_ratio,
                attribution_margin_stroke_widths=margin_stroke_widths,
                descender_chars=descender_chars,
                descender_height_ratio=descender_ratio,
            )
            measured_width, measured_height = base_size
            if int(rotation) % 180:
                measured_width, measured_height = measured_height, measured_width
            width = max(width, measured_width + 2.0 * text.stroke_width_mm)
            height = max(height, measured_height + text.stroke_width_mm)
            x = outline[0] + width / 2
            while x <= outline[2] - width / 2 + 1e-9:
                columns.append(
                    _ContextGridColumn(
                        rotation=rotation,
                        x=x,
                        width=width,
                        height=height,
                        measured_width=measured_width,
                        measured_height=measured_height,
                    )
                )
                x = round(x + step, 9)
        bundle = _ContextGridBundle(
            text=text,
            outline=outline,
            pads=tuple(pads),
            masks=tuple(masks),
            mask_openings=tuple(mask_openings),
            existing=tuple(existing),
            fixed=tuple(fixed),
            bodies=tuple(bodies),
            courtyards=tuple(courtyards),
            dynamic_silk=tuple(dynamic_silk),
            target=target,
            center=center,
            reference=reference,
        )
        if not columns:
            chunk_results: tuple[
                tuple[
                    tuple[list[dict[str, object]], list[dict[str, object]]],
                    ...,
                ],
                ...,
            ] = ()
        else:
            chunk_count = (
                1
                if executor is None
                else min(len(columns), max(workers * 4, 1))
            )
            chunk_size = math.ceil(len(columns) / chunk_count)
            chunks = tuple(
                _ContextGridChunk(
                    bundle=bundle,
                    columns=tuple(columns[index : index + chunk_size]),
                )
                for index in range(0, len(columns), chunk_size)
            )
            if executor is None:
                chunk_results = tuple(
                    _evaluate_context_grid_chunk(chunk) for chunk in chunks
                )
            else:
                chunk_results = tuple(
                    executor.map(_evaluate_context_grid_chunk, chunks)
                )
        for chunk_result in chunk_results:
            for partition_candidates, partition_rejected in chunk_result:
                candidates.extend(partition_candidates)
                rejected.extend(partition_rejected)
        if not candidates:
            results_by_id[text.node_id] = {
                "node_id": text.node_id,
                "role": text.role,
                "candidates": [],
                "rejected_candidates": rejected,
                "resolution": "no_candidate_fail_closed",
                "placement_order": [item.node_id for item in ordered_texts],
            }
            continue
        chosen = min(
            candidates,
            key=lambda item: (
                float(item["distance_mm"]),
                float(item["y_mm"]),
                float(item["x_mm"]),
                float(item["rotation_deg"]),
            )
        )
        results_by_id[text.node_id] = {
            "node_id": text.node_id,
            "role": text.role,
            "candidates": candidates,
            "rejected_candidates": rejected,
            "accepted_position_mm": [chosen["x_mm"], chosen["y_mm"]],
            "accepted_rotation_deg": chosen["rotation_deg"],
            "resolution": "context_candidate",
            "placement_order": [item.node_id for item in ordered_texts],
        }
        dynamic_silk.append(
            {
                "layer": text.layer,
                "bbox_mm": chosen["bbox_mm"],
            }
        )
    return tuple(
        results_by_id[text.node_id]
        for text in lane.texts
        if text.node_id in results_by_id
    )


def resolve_from_context(
    lane: SilkscreenLane,
    context: dict[str, Any],
    _compute_order: bool = True,
    *,
    workers: int = 1,
) -> tuple[dict[str, object], ...]:
    """Search the complete board grid using only measured context."""
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if workers == 1:
        return _resolve_from_context_impl(lane, context, _compute_order, None, workers)
    # Context search is pure Python and does not inherit native-extension state,
    # so it explicitly uses fork; the CAD path uses spawn for OCP/build123d.
    fork_context = multiprocessing.get_context("fork")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=fork_context,
    ) as executor:
        return _resolve_from_context_impl(
            lane,
            context,
            _compute_order,
            executor,
            workers,
        )


def _positive_workers(value: str) -> int:
    try:
        workers = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("workers must be an integer") from exc
    if workers < 1:
        raise argparse.ArgumentTypeError("workers must be at least 1")
    return workers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--workers",
        type=_positive_workers,
        default=min(os.cpu_count() or 1, 4),
    )
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise GraphExtractionError("silkscreen input must be a JSON object")
        lane = _lane_from_json(payload.get("lane"))
        if "context" in payload:
            candidates = resolve_from_context(
                lane,
                _mapping(payload.get("context"), "context"),
                workers=args.workers,
            )
            result = {"candidates": list(candidates)}
        else:
            board = _board_from_json(payload.get("board"))
            resolved = resolve_silkscreen_placements(lane, board)
            result = {
                "texts": [
                    {
                        "node_id": text.node_id,
                        "role": text.role,
                        "text": text.text,
                        "x_mm": text.x_mm,
                        "y_mm": text.y_mm,
                        "layer": text.layer,
                        "height_mm": text.height_mm,
                        "stroke_width_mm": text.stroke_width_mm,
                        "rotation_deg": text.rotation_deg,
                    }
                    for text in resolved.texts
                ],
                "placement_evidence": list(resolved.placement_evidence),
            }
        encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 0
    except (
        OSError,
        TypeError,
        ValueError,
        KeyError,
        GraphExtractionError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(f"invalid silkscreen input: {exc}")
    return 2


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GraphExtractionError(f"{name} must be an object")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise GraphExtractionError(f"{name} must be numeric")
    return float(value)


def _board_from_json(value: object) -> BoardModel:
    data = _mapping(value, "board")
    placements: list[ComponentPlacement] = []
    for index, item in enumerate(data.get("placements", [])):
        placement = _mapping(item, f"board.placements[{index}]")
        footprint = _mapping(placement.get("footprint"), "footprint")
        pads: list[PadShape] = []
        for pad_index, raw_pad in enumerate(footprint.get("pads", [])):
            pad = _mapping(raw_pad, f"footprint.pads[{pad_index}]")
            pads.append(
                PadShape(
                    **{
                        "number": str(pad["number"]),
                        "x_mm": _number(pad["x_mm"], "pad.x_mm"),
                        "y_mm": _number(pad["y_mm"], "pad.y_mm"),
                        "rotation_deg": _number(pad["rotation_deg"], "pad.rotation_deg"),
                        "shape": str(pad["shape"]),
                        "size_x_mm": _number(pad["size_x_mm"], "pad.size_x_mm"),
                        "size_y_mm": _number(pad["size_y_mm"], "pad.size_y_mm"),
                        "through_hole": _bool(pad["through_hole"], "pad.through_hole"),
                        "drill_mm": (
                            None
                            if pad["drill_mm"] is None
                            else _number(pad["drill_mm"], "pad.drill_mm")
                        ),
                        "on_front": _bool(pad["on_front"], "pad.on_front"),
                        "on_back": _bool(pad["on_back"], "pad.on_back"),
                    }
                )
            )
        placements.append(
            ComponentPlacement(
                refdes=str(placement["refdes"]),
                footprint=FootprintShape(
                    library_ref=str(footprint["library_ref"]),
                    pads=tuple(pads),
                    courtyard_bbox_mm=_bbox(footprint.get("courtyard_bbox_mm")),
                    body_bbox_mm=_bbox(footprint.get("body_bbox_mm")),
                    keepout_bboxes_mm=tuple(
                        _bbox(item) for item in footprint.get("keepout_bboxes_mm", [])
                    ),
                ),
                x_mm=_number(placement["x_mm"], "placement.x_mm"),
                y_mm=_number(placement["y_mm"], "placement.y_mm"),
                rotation_deg=_number(placement["rotation_deg"], "placement.rotation_deg"),
                side=str(placement.get("side", "front")),
            )
        )
    nets = tuple(
        BoardNet(
            name=str(item["name"]),
            pads=tuple((str(pair[0]), str(pair[1])) for pair in item["pads"]),
        )
        for item in (_mapping(item, "board.nets[]") for item in data.get("nets", []))
    )
    keepouts = tuple(
        KeepoutRect(
            name=str(item["name"]),
            x1_mm=_number(item["x1_mm"], "keepout.x1_mm"),
            y1_mm=_number(item["y1_mm"], "keepout.y1_mm"),
            x2_mm=_number(item["x2_mm"], "keepout.x2_mm"),
            y2_mm=_number(item["y2_mm"], "keepout.y2_mm"),
        )
        for item in (_mapping(item, "board.keepouts[]") for item in data.get("keepouts", []))
    )
    zones = tuple(
        CopperZone(
            net=str(item["net"]),
            layers=tuple(str(layer) for layer in item["layers"]),
            inset_mm=_number(item["inset_mm"], "zone.inset_mm"),
            min_island_area_mm2=_number(item["min_island_area_mm2"], "zone.min_island_area_mm2"),
            thermal_relief=_bool(item.get("thermal_relief", True), "zone.thermal_relief"),
        )
        for item in (
            _mapping(item, "board.copper_zones[]") for item in data.get("copper_zones", [])
        )
    )
    netclasses = tuple(
        NetClass(
            name=str(item["name"]),
            width_mm=_number(item["width_mm"], "netclass.width_mm"),
            nets=tuple(str(net) for net in item["nets"]),
        )
        for item in (_mapping(item, "board.netclasses[]") for item in data.get("netclasses", []))
    )
    return BoardModel(
        width_mm=_number(data["width_mm"], "board.width_mm"),
        height_mm=_number(data["height_mm"], "board.height_mm"),
        layers=int(data["layers"]),
        min_track_mm=_number(data["min_track_mm"], "board.min_track_mm"),
        min_clearance_mm=_number(data["min_clearance_mm"], "board.min_clearance_mm"),
        via_drill_mm=_number(data["via_drill_mm"], "board.via_drill_mm"),
        via_diameter_mm=_number(data["via_diameter_mm"], "board.via_diameter_mm"),
        edge_clearance_mm=_number(data["edge_clearance_mm"], "board.edge_clearance_mm"),
        placements=tuple(placements),
        nets=nets,
        keepouts=keepouts,
        copper_zones=zones,
        stitch_via_pitch_mm=data.get("stitch_via_pitch_mm"),
        stitch_via_net=data.get("stitch_via_net"),
        stitch_via_refill_max_iterations=data.get("stitch_via_refill_max_iterations"),
        netclasses=netclasses,
    )


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise GraphExtractionError(f"{name} must be boolean")
    return value


def _bbox(value: object) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    if not isinstance(value, list | tuple) or len(value) != 4:
        raise GraphExtractionError("bounding box must contain four numbers")
    return tuple(_number(item, "bbox") for item in value)  # type: ignore[return-value]


def _lane_from_json(value: object) -> SilkscreenLane:
    data = _mapping(value, "lane")
    texts = tuple(
        SilkTextView(
            node_id=str(item["node_id"]),
            role=str(item["role"]),
            text=str(item["text"]),
            x_mm=(
                None
                if item.get("x_mm") is None
                else _number(item["x_mm"], "text.x_mm")
            ),
            y_mm=(
                None
                if item.get("y_mm") is None
                else _number(item["y_mm"], "text.y_mm")
            ),
            layer=str(item["layer"]),
            height_mm=_number(item["height_mm"], "text.height_mm"),
            stroke_width_mm=_number(item["stroke_width_mm"], "text.stroke_width_mm"),
            rotation_deg=_number(item["rotation_deg"], "text.rotation_deg"),
            placement_basis=str(item["placement_basis"]),
            placement_search_order=str(item["placement_search_order"]),
            placement_reference=str(item["placement_reference"]),
            placement_offset_step_mm=_number(item["placement_offset_step_mm"], "text.step"),
            placement_search_limit_mm=_number(item["placement_search_limit_mm"], "text.limit"),
            board_edge_margin_mm=_number(item.get("board_edge_margin_mm", 0.0), "text.edge_margin"),
            board_edge_margin_source=str(item.get("board_edge_margin_source", "unknown")),
            placement_rotation_degrees=tuple(
                _number(rotation, "text.rotation_options")
                for rotation in item.get("placement_rotation_degrees", [0.0, 90.0])
            ),
            placement_safety_margin_mm=_number(
                item.get("placement_safety_margin_mm", 0.0), "text.safety_margin"
            ),
        )
        for item in (_mapping(item, "lane.texts[]") for item in data.get("texts", []))
    )
    graphics = tuple(
        SilkGraphicView(
            node_id=str(item["node_id"]),
            role=str(item["role"]),
            layer=str(item["layer"]),
            stroke_width_mm=_number(item["stroke_width_mm"], "graphic.stroke_width_mm"),
            polygon_points=tuple(
                (float(point[0]), float(point[1])) for point in item["polygon_points"]
            ),
            placement_basis=str(item["placement_basis"]),
            placement_search_order=str(item["placement_search_order"]),
            board_edge_margin_mm=_number(
                item.get("board_edge_margin_mm", 0.0), "graphic.edge_margin"
            ),
            board_edge_margin_source=str(item.get("board_edge_margin_source", "unknown")),
        )
        for item in (_mapping(item, "lane.graphics[]") for item in data.get("graphics", []))
    )
    if not texts and not graphics:
        raise GraphExtractionError("lane must contain text or graphic declarations")
    return SilkscreenLane(
        board_node_id=str(data["board_node_id"]),
        texts=texts,
        graphics=graphics,
    )


if __name__ == "__main__":
    raise SystemExit(main())
