"""Independent manufacturing measurements, DFM checks, and JLCPCB exports."""
# pyright: reportUnusedImport=false,reportUnknownVariableType=false,reportUnknownMemberType=false
# ruff: noqa

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
import math
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import sexpdata  # pyright: ignore[reportMissingTypeStubs]
from gerbonara.apertures import (  # pyright: ignore[reportMissingTypeStubs]
    CircleAperture,
    ObroundAperture,
    RectangleAperture,
)
from gerbonara.excellon import ExcellonFile  # pyright: ignore[reportMissingTypeStubs]
from gerbonara.graphic_objects import (  # pyright: ignore[reportMissingTypeStubs]
    Arc,
    Flash,
    Line,
    Region,
)
from gerbonara.rs274x import GerberFile  # pyright: ignore[reportMissingTypeStubs]

from acd.adapters.kicad.library import SymbolLibrary
from acd.adapters.kicad.placement import rotate_point
from acd.core.electrical.board_model import BoardModel, RoutedDesign, RoutedVia
from acd.core.manufacturing.bom import refdes_key
from acd.core.electrical.electrical import ComponentView, ElectricalLane
from acd.core.manufacturing.fab import (
    FabOrderIntentView,
    FabProfile,
    ProcessAllowanceView,
    validate_allowances_against_profile,
)
from acd.core.electrical.routing_width import NetWidthRequirement
from acd.core.electrical.qr_geometry import (
    QR_DATA_MODULES,
    QR_QUIET_ZONE_MODULES,
    qr_module_matrix_from_svg,
)
from acd.core.electrical.silkscreen import (
    SilkGraphicPartView,
    SilkGraphicView,
    SilkTextView,
    SilkscreenLane,
)


from .common import *  # noqa: F401,F403
from .geometry import *  # noqa: F401,F403
from .sexpr_query import *  # noqa: F401,F403
from .silkscreen_objects import (
    SILK_TEXT_ADVANCE_RATIO,
    SILK_TEXT_ATTRIBUTION_MARGIN_STROKE_WIDTHS,
    SILK_TEXT_DESCENDER_CHARS,
    SILK_TEXT_DESCENDER_HEIGHT_RATIO,
    SilkscreenGateError,
    _declared_bbox,
    _gerber_silk_objects,
    _local_silk_bounds,
    _mask_layer_for_silk,
    _point_rect_distance,
    _same_side,
    _segment_distance_to_rect,
    _silk_aperture_width,
    _silk_object,
    _silk_objects_overlap,
    _silk_overlaps_rect,
    _silk_rect_distance,
    _silk_side,
    _SilkObject,
    _text_attribution_overflow,
    _text_model_size,
    _union_bbox,
)
from .silkscreen_qr import (
    _axis_ink_intervals,
    _maximum_interval_length,
    _minimum_region_gap,
    _point_has_ink,
    _qr_fidelity_measurement,
)


def _load_silk_gerbers(
    silk_paths: Mapping[str, Path],
    mask_paths: Mapping[str, Path],
    edge_path: Path,
) -> tuple[list[_SilkObject], dict[str, int], list[_SilkObject]]:
    all_silk: list[_SilkObject] = []
    type_counts: dict[str, int] = defaultdict(int)
    for layer, path in silk_paths.items():
        objects = _gerber_silk_objects(path, layer)
        all_silk.extend(objects)
        for item in objects:
            type_counts[item.kind] += 1
    if not all_silk:
        raise FabOutputError("silkscreen Gerber contains no objects (fail-closed)")
    masks: list[_SilkObject] = []
    for layer, path in mask_paths.items():
        masks.extend(_gerber_silk_objects(path, layer))
    edge_objects = _gerber_silk_objects(edge_path, "Edge.Cuts")
    if not edge_objects:
        raise FabOutputError("Edge.Cuts Gerber contains no objects (fail-closed)")
    return all_silk, type_counts, masks


def _nearby_silk(
    all_silk: Sequence[_SilkObject],
    layer: str,
    stroke_width_mm: float,
    target: tuple[float, float, float, float],
    center: tuple[float, float],
) -> list[_SilkObject]:
    """Return silk objects on ``layer`` whose bbox overlaps ``target`` and whose
    bbox centre lies inside the target's half extents around ``center``."""
    half_width = (target[2] - target[0]) / 2.0
    half_height = (target[3] - target[1]) / 2.0
    return [
        item
        for item in all_silk
        if item.layer == layer
        and (item.stroke_width_mm is None or item.stroke_width_mm + 1e-6 >= stroke_width_mm)
        and _bbox_overlap_area(item.bbox_mm, target) > 0
        and abs((item.bbox_mm[0] + item.bbox_mm[2]) / 2.0 - center[0]) <= half_width
        and abs((item.bbox_mm[1] + item.bbox_mm[3]) / 2.0 - center[1]) <= half_height
    ]


def _minimum_stroke_width(objects: Sequence[_SilkObject]) -> float | None:
    widths = [item.stroke_width_mm for item in objects if item.stroke_width_mm is not None]
    return min(widths) if widths else None


def _measure_declared_text(
    text: SilkTextView,
    all_silk: Sequence[_SilkObject],
    min_width: float,
    min_height: float,
) -> tuple[dict[str, object], tuple[_SilkObject, ...]]:
    if text.x_mm is None or text.y_mm is None:
        raise FabOutputError(
            f"silkscreen text {text.node_id!r} has no declared position (fail-closed)"
        )
    target = _declared_bbox(
        text.x_mm,
        text.y_mm,
        text.text,
        text.height_mm,
        text.stroke_width_mm,
        text.rotation_deg,
    )
    center = ((target[0] + target[2]) / 2.0, (target[1] + target[3]) / 2.0)
    nearby = _nearby_silk(all_silk, text.layer, text.stroke_width_mm, target, center)
    bbox = _union_bbox(nearby)
    measured_width = _minimum_stroke_width(nearby)
    area = sum(item.area_mm2 for item in nearby)
    local_bbox = _local_silk_bounds(nearby, (text.x_mm, text.y_mm), text.rotation_deg)
    height = local_bbox[3] - local_bbox[1]
    text_length = local_bbox[2] - local_bbox[0]
    estimated_local_width, estimated_local_height = _text_model_size(
        text.text,
        text.height_mm,
        text.stroke_width_mm,
    )
    attribution_overflows = list(_text_attribution_overflow(text, text_length, height))
    if area <= 0 or measured_width is None:
        raise FabOutputError(
            f"silkscreen text {text.node_id!r} has no measurable ink (fail-closed)"
        )
    if text.height_mm < min_height or text.stroke_width_mm < min_width:
        raise FabOutputError(
            f"silkscreen declaration {text.node_id!r} is below fab capability (fail-closed)"
        )
    if measured_width < min_width or height < min_height:
        raise FabOutputError(
            f"silkscreen text {text.node_id!r} measured below fab capability (fail-closed)"
        )
    entry: dict[str, object] = {
        "node_id": text.node_id,
        "role": text.role,
        "text": text.text,
        "layer": text.layer,
        "declared_position_mm": [text.x_mm, text.y_mm],
        "declared_height_mm": text.height_mm,
        "declared_stroke_width_mm": text.stroke_width_mm,
        "declared_rotation_deg": text.rotation_deg,
        "measured_bbox_mm": list(bbox),
        "measured_ink_area_mm2": area,
        "measured_height_mm": height,
        "measured_text_length_mm": text_length,
        "attribution_upper_bound_width_mm": estimated_local_width,
        "attribution_upper_bound_height_mm": estimated_local_height,
        "attribution_overflow": attribution_overflows,
        "measured_minimum_stroke_width_mm": measured_width,
        "measurement_coordinate_system": ("text-local coordinates after inverse declared rotation"),
        "placement_basis": text.placement_basis,
        "placement_search_order": text.placement_search_order,
        "placement_reference": text.placement_reference,
        "placement_offset_step_mm": text.placement_offset_step_mm,
        "placement_search_limit_mm": text.placement_search_limit_mm,
        "board_edge_margin_mm": text.board_edge_margin_mm,
    }
    return entry, tuple(nearby)


def _measure_declared_graphic(
    graphic: SilkGraphicView,
    all_silk: Sequence[_SilkObject],
    min_width: float,
    resolved_source_paths: Mapping[str, Path] | None,
    qr_fidelity_results: list[dict[str, object]],
    qr_fidelity_failures: list[dict[str, object]],
) -> tuple[dict[str, object], tuple[_SilkObject, ...]]:
    graphic_parts = graphic.parts
    if not graphic_parts:
        graphic_parts = (
            SilkGraphicPartView(
                graphic.contours or (graphic.polygon_points,),
                graphic.stroke_width_mm,
            ),
        )
    graphic_points = [
        point for part in graphic_parts for contour in part.contours for point in contour
    ]
    xs, ys = zip(*graphic_points, strict=True)
    target = (min(xs) - 0.5, min(ys) - 0.5, max(xs) + 0.5, max(ys) + 0.5)
    center = ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)
    nearby = _nearby_silk(all_silk, graphic.layer, graphic.stroke_width_mm, target, center)
    bbox = _union_bbox(nearby)
    measured_width = _minimum_stroke_width(nearby)
    area = sum(item.area_mm2 for item in nearby)
    fill_only = bool(graphic_parts) and all(
        part.fill != "none" and part.stroke_width_mm == 0.0 for part in graphic_parts
    )
    if area <= 0 or measured_width is None:
        if not fill_only or area <= 0:
            raise FabOutputError(
                f"silkscreen graphic {graphic.node_id!r} has no measurable ink (fail-closed)"
            )
    if (not fill_only and graphic.stroke_width_mm < min_width) or (
        measured_width is not None and measured_width < min_width
    ):
        raise FabOutputError(
            f"silkscreen graphic {graphic.node_id!r} is below fab capability (fail-closed)"
        )
    minimum_printed_width = measured_width
    if minimum_printed_width is None and fill_only:
        region_widths = [
            min(item.bbox_mm[2] - item.bbox_mm[0], item.bbox_mm[3] - item.bbox_mm[1])
            for item in nearby
            if item.kind == "Region"
        ]
        minimum_printed_width = min(region_widths) if region_widths else None
    minimum_unprinted_gap = _minimum_region_gap(nearby) if fill_only else None
    if minimum_printed_width is None or minimum_printed_width < min_width:
        raise FabOutputError(
            f"silkscreen graphic {graphic.node_id!r} minimum printed width is "
            "below fab capability (fail-closed)"
        )
    if minimum_unprinted_gap is not None and minimum_unprinted_gap < min_width:
        raise FabOutputError(
            f"silkscreen graphic {graphic.node_id!r} minimum unprinted gap is "
            "below fab capability (fail-closed)"
        )
    entry: dict[str, object] = {
        "node_id": graphic.node_id,
        "role": graphic.role,
        "layer": graphic.layer,
        "declared_polygon_points": [list(point) for point in graphic_points],
        "measured_bbox_mm": list(bbox),
        "measured_ink_area_mm2": area,
        "measured_minimum_stroke_width_mm": measured_width,
        "minimum_printed_width_mm": minimum_printed_width,
        "minimum_unprinted_gap_mm": minimum_unprinted_gap,
        "placement_basis": graphic.placement_basis,
        "placement_search_order": graphic.placement_search_order,
        "board_edge_margin_mm": graphic.board_edge_margin_mm,
    }
    if graphic.role == "repository_qr":
        try:
            source_path = (resolved_source_paths or {}).get(graphic.node_id)
            if source_path is None:
                raise FabOutputError(
                    f"QR source SVG path is unresolved for {graphic.node_id!r} (fail-closed)"
                )
            qr_objects = tuple(item for item in nearby if item.kind == "Region")
            qr_result = _qr_fidelity_measurement(graphic, qr_objects, min_width, source_path)
        except FabOutputError as exc:
            qr_fidelity_failures.append({"node_id": graphic.node_id, "error": str(exc)})
        else:
            entry.update(qr_result)
            qr_fidelity_results.append({"node_id": graphic.node_id, **qr_result})
    return entry, tuple(nearby)


_RefdesRect = tuple[str, str, tuple[float, float, float, float]]


@dataclass
class _ClearanceFindings:
    """Fail conditions accumulated across declared silkscreen elements."""

    body_overlaps: list[dict[str, object]] = field(default_factory=list)
    courtyard_overlaps: list[dict[str, object]] = field(default_factory=list)
    existing_silk_overlaps: list[dict[str, object]] = field(default_factory=list)
    edge_margin_violations: list[dict[str, object]] = field(default_factory=list)
    nearest_component_mismatches: list[dict[str, object]] = field(default_factory=list)


def _edge_distance(item: _SilkObject, outline: tuple[float, float, float, float]) -> float:
    return min(
        item.bbox_mm[0] - outline[0],
        outline[2] - item.bbox_mm[2],
        item.bbox_mm[1] - outline[1],
        outline[3] - item.bbox_mm[3],
    )


def _rect_hits(
    node_id: str,
    objects: Sequence[_SilkObject],
    rects: Sequence[_RefdesRect],
    rect_key: str,
) -> list[dict[str, object]]:
    return [
        {
            "node_id": node_id,
            "refdes": refdes,
            "silk_bbox_mm": list(item.bbox_mm),
            rect_key: list(rect),
            "overlap_area_mm2": _bbox_overlap_area(item.bbox_mm, rect),
        }
        for item in objects
        for refdes, layer, rect in rects
        if _same_side(item.layer, (layer,)) and _silk_overlaps_rect(item, rect)
    ]


def _rect_distances(
    objects: Sequence[_SilkObject], rects: Sequence[_RefdesRect]
) -> list[tuple[float, str]]:
    return [
        (_silk_rect_distance(item, rect), refdes)
        for item in objects
        for refdes, layer, rect in rects
        if _same_side(item.layer, (layer,))
    ]


def _annotate_component_clearance(
    entry: dict[str, object],
    objects: Sequence[_SilkObject],
    *,
    body_rects: Sequence[_RefdesRect],
    courtyard_rects: Sequence[_RefdesRect],
    non_declared_silk: Sequence[_SilkObject],
    outline: tuple[float, float, float, float],
    findings: _ClearanceFindings,
) -> None:
    """Record component/edge clearance for one declared element into ``entry``
    and append any violations to ``findings``."""
    node_id = str(entry["node_id"])
    body_hits = _rect_hits(node_id, objects, body_rects, "body_bbox_mm")
    courtyard_hits = _rect_hits(node_id, objects, courtyard_rects, "courtyard_bbox_mm")
    other_hits: list[dict[str, object]] = [
        {
            "node_id": node_id,
            "silk_bbox_mm": list(item.bbox_mm),
            "existing_silk_bbox_mm": list(other.bbox_mm),
            "layer": item.layer,
            "existing_silk_kind": other.kind,
            "overlap_area_mm2": _bbox_overlap_area(item.bbox_mm, other.bbox_mm),
        }
        for item in objects
        for other in non_declared_silk
        if item.layer == other.layer and _silk_objects_overlap(item, other)
    ]
    findings.body_overlaps.extend(body_hits)
    findings.courtyard_overlaps.extend(courtyard_hits)
    findings.existing_silk_overlaps.extend(other_hits)
    entry["body_overlap_count"] = len(body_hits)
    entry["courtyard_overlap_count"] = len(courtyard_hits)
    entry["existing_footprint_silk_overlap_count"] = len(other_hits)
    body_distances = _rect_distances(objects, body_rects)
    courtyard_distances = _rect_distances(objects, courtyard_rects)
    entry["nearest_body_distance_mm"] = min(body_distances)[0] if body_distances else None
    entry["nearest_body_refdes"] = min(body_distances)[1] if body_distances else None
    entry["nearest_courtyard_distance_mm"] = (
        min(courtyard_distances)[0] if courtyard_distances else None
    )
    entry["nearest_courtyard_refdes"] = min(courtyard_distances)[1] if courtyard_distances else None
    edge_distances = [_edge_distance(item, outline) for item in objects]
    entry["board_edge_minimum_distance_mm"] = min(edge_distances) if edge_distances else None
    margin = float(cast(float, entry["board_edge_margin_mm"]))
    for item in objects:
        distance = _edge_distance(item, outline)
        if distance < margin:
            findings.edge_margin_violations.append(
                {
                    "node_id": node_id,
                    "silk_bbox_mm": list(item.bbox_mm),
                    "minimum_distance_mm": distance,
                    "declared_margin_mm": margin,
                }
            )
    reference_value = entry.get("placement_reference")
    reference = str(reference_value) if isinstance(reference_value, str) else None
    all_rects = list(body_rects) + list(courtyard_rects)
    component_distances: list[tuple[float, str]] = []
    for refdes in sorted({ref for ref, _, _ in all_rects}):
        distances = [
            _silk_rect_distance(item, rect)
            for item in objects
            for candidate_ref, layer, rect in all_rects
            if candidate_ref == refdes and _same_side(item.layer, (layer,))
        ]
        if distances:
            component_distances.append((min(distances), refdes))
    if not component_distances:
        return
    nearest_distance, nearest_refdes = min(component_distances)
    entry["nearest_component_distance_mm"] = nearest_distance
    entry["nearest_component_refdes"] = nearest_refdes
    if reference is None or reference not in {refdes for _, refdes in component_distances}:
        return
    reference_distance = next(
        (distance for distance, refdes in component_distances if refdes == reference),
        None,
    )
    entry["reference_component_distance_mm"] = reference_distance
    entry["reference_is_nearest_component"] = (
        reference_distance is not None
        and reference_distance <= nearest_distance + 1e-9
        and nearest_refdes == reference
    )
    if not entry["reference_is_nearest_component"]:
        findings.nearest_component_mismatches.append(
            {
                "node_id": node_id,
                "reference": reference,
                "reference_distance_mm": reference_distance,
                "nearest_refdes": nearest_refdes,
                "nearest_distance_mm": nearest_distance,
            }
        )


def _silk_object_summary(item: _SilkObject, *, with_metrics: bool) -> dict[str, object]:
    summary: dict[str, object] = {
        "kind": item.kind,
        "layer": item.layer,
        "bbox_mm": list(item.bbox_mm),
    }
    if with_metrics:
        summary["area_mm2"] = item.area_mm2
        summary["stroke_width_mm"] = item.stroke_width_mm
    return summary


def measure_silkscreen(
    silk_paths: Mapping[str, Path],
    mask_paths: Mapping[str, Path],
    edge_path: Path,
    measurement: BoardMeasurement,
    declarations: SilkscreenLane,
    profile: FabProfile,
    resolved_source_paths: Mapping[str, Path] | None = None,
) -> dict[str, object]:
    """Independently measure declared silk ink and clearance against fab output."""
    min_width = float(profile.data["capabilities"]["min_silk_width"]["value"])
    min_height = float(profile.data["capabilities"]["min_silk_height"]["value"])
    all_silk, type_counts, masks = _load_silk_gerbers(silk_paths, mask_paths, edge_path)
    outline = measurement.outline_bbox_mm
    if outline is None:
        raise FabOutputError("board outline measurement is missing (fail-closed)")
    declared: list[dict[str, object]] = []
    declared_objects: list[_SilkObject] = []
    declared_groups: list[tuple[dict[str, object], tuple[_SilkObject, ...]]] = []
    qr_fidelity_results: list[dict[str, object]] = []
    qr_fidelity_failures: list[dict[str, object]] = []
    for text in declarations.texts:
        entry, nearby = _measure_declared_text(text, all_silk, min_width, min_height)
        declared_objects.extend(nearby)
        declared.append(entry)
        declared_groups.append((entry, nearby))
    for graphic in declarations.graphics:
        entry, nearby = _measure_declared_graphic(
            graphic,
            all_silk,
            min_width,
            resolved_source_paths,
            qr_fidelity_results,
            qr_fidelity_failures,
        )
        declared_objects.extend(nearby)
        declared.append(entry)
        declared_groups.append((entry, nearby))
    pad_bboxes = [
        (
            (
                pad.x_mm - pad.size_x_mm / 2.0,
                pad.y_mm - pad.size_y_mm / 2.0,
                pad.x_mm + pad.size_x_mm / 2.0,
                pad.y_mm + pad.size_y_mm / 2.0,
            ),
            pad.layers,
        )
        for pad in measurement.pads
    ]
    pad_overlaps = [
        {
            "silk_bbox_mm": list(item.bbox_mm),
            "pad_bbox_mm": list(pad_bbox),
            "layer": item.layer,
        }
        for item in declared_objects
        for pad_bbox, pad_layers in pad_bboxes
        if _same_side(item.layer, pad_layers) and _silk_overlaps_rect(item, pad_bbox)
    ]
    mask_overlaps = [
        {"silk_bbox_mm": list(item.bbox_mm), "mask_bbox_mm": list(mask.bbox_mm)}
        for item in declared_objects
        for mask in masks
        if _mask_layer_for_silk(item.layer) == mask.layer and _silk_objects_overlap(item, mask)
    ]
    outside = [
        list(item.bbox_mm)
        for item in declared_objects
        if item.bbox_mm[0] < outline[0]
        or item.bbox_mm[1] < outline[1]
        or item.bbox_mm[2] > outline[2]
        or item.bbox_mm[3] > outline[3]
    ]
    body_rects: list[_RefdesRect] = [
        (fp.refdes, fp.layer, fp.body_bbox_mm)
        for fp in measurement.footprints
        if fp.body_bbox_mm is not None
    ]
    courtyard_rects: list[_RefdesRect] = [
        (fp.refdes, fp.layer, fp.courtyard_bbox_mm)
        for fp in measurement.footprints
        if fp.courtyard_bbox_mm is not None
    ]
    declared_ids = {id(item) for item in declared_objects}
    non_declared_silk = [item for item in all_silk if id(item) not in declared_ids]
    graphic_node_ids = {graphic.node_id for graphic in declarations.graphics}
    fixed_declared_silk = [
        item
        for entry, objects in declared_groups
        if str(entry["node_id"]) in graphic_node_ids
        for item in objects
    ]
    findings = _ClearanceFindings()
    for entry, objects in declared_groups:
        _annotate_component_clearance(
            entry,
            objects,
            body_rects=body_rects,
            courtyard_rects=courtyard_rects,
            non_declared_silk=non_declared_silk,
            outline=outline,
            findings=findings,
        )
    attribution_overflows: list[dict[str, object]] = [
        {
            "node_id": entry["node_id"],
            **overflow,
        }
        for entry in declared
        for overflow in cast(
            list[object],
            entry.get("attribution_overflow", [])
            if isinstance(entry.get("attribution_overflow"), list)
            else [],
        )
        if isinstance(overflow, dict)
    ]
    context = {
        "schema_version": "0.1",
        "measurement_method": (
            "independent gerbonara parse of F.Silkscreen/B.Silkscreen, F.Mask/B.Mask, and Edge.Cuts"
        ),
        "silk_objects": [_silk_object_summary(item, with_metrics=True) for item in all_silk],
        "mask_objects": [_silk_object_summary(item, with_metrics=True) for item in masks],
        "existing_silk_objects": [
            _silk_object_summary(item, with_metrics=False) for item in non_declared_silk
        ],
        "fixed_silk_objects": [
            _silk_object_summary(item, with_metrics=False) for item in fixed_declared_silk
        ],
        "mask_opening_bboxes_mm": [
            {"bbox_mm": list(item.bbox_mm), "layer": item.layer} for item in masks
        ],
        "pad_bboxes_mm": [
            {"bbox_mm": list(bbox), "layers": list(layers)} for bbox, layers in pad_bboxes
        ],
        "body_bboxes_mm": [
            {"refdes": refdes, "layer": layer, "bbox_mm": list(rect)}
            for refdes, layer, rect in body_rects
        ],
        "courtyard_bboxes_mm": [
            {"refdes": refdes, "layer": layer, "bbox_mm": list(rect)}
            for refdes, layer, rect in courtyard_rects
        ],
        "board_outline_bbox_mm": list(outline),
        "declarations": declared,
        "requirements": {
            "min_silk_width_mm": min_width,
            "min_silk_height_mm": min_height,
            "silk_text_advance_ratio": SILK_TEXT_ADVANCE_RATIO,
            "silk_text_attribution_margin_stroke_widths": (
                SILK_TEXT_ATTRIBUTION_MARGIN_STROKE_WIDTHS
            ),
            "silk_text_descender_chars": "".join(sorted(SILK_TEXT_DESCENDER_CHARS)),
            "silk_text_descender_height_ratio": SILK_TEXT_DESCENDER_HEIGHT_RATIO,
            "min_silk_gap_mm": min_width,
            "declared_board_edge_margin_mm": sorted(
                {
                    float(cast(float, item["board_edge_margin_mm"]))
                    for item in declared
                    if "board_edge_margin_mm" in item
                }
            ),
        },
        "fail_conditions": {
            "pad_overlap": pad_overlaps,
            "mask_overlap": mask_overlaps,
            "board_edge_overflow": outside,
            "board_edge_margin": findings.edge_margin_violations,
            "attribution_overflow": attribution_overflows,
            "body_overlap": findings.body_overlaps,
            "courtyard_overlap": findings.courtyard_overlaps,
            "existing_silk_overlap": findings.existing_silk_overlaps,
            "nearest_component_mismatch": findings.nearest_component_mismatches,
            "qr_fidelity": qr_fidelity_failures,
        },
    }
    if (
        pad_overlaps
        or mask_overlaps
        or outside
        or findings.edge_margin_violations
        or attribution_overflows
        or findings.body_overlaps
        or findings.courtyard_overlaps
        or findings.existing_silk_overlaps
        or findings.nearest_component_mismatches
        or qr_fidelity_failures
    ):
        raise SilkscreenGateError(
            "silkscreen clearance or board-edge overlap detected (fail-closed): "
            f"pad={len(pad_overlaps)}, mask={len(mask_overlaps)}, edge={len(outside)}, "
            f"edge_margin={len(findings.edge_margin_violations)}, "
            f"attribution_overflow={len(attribution_overflows)}, "
            f"body={len(findings.body_overlaps)}, courtyard={len(findings.courtyard_overlaps)}, "
            f"existing_silk={len(findings.existing_silk_overlaps)}, "
            f"nearest_component={len(findings.nearest_component_mismatches)}; "
            f"qr_fidelity={len(qr_fidelity_failures)}; "
            f"pad_examples={pad_overlaps[:3]}, mask_examples={mask_overlaps[:3]}, "
            f"edge_examples={outside[:3]}, body_examples={findings.body_overlaps[:3]}, "
            f"edge_margin_examples={findings.edge_margin_violations[:3]}, "
            f"attribution_examples={attribution_overflows[:3]}, "
            f"nearest_component_examples={findings.nearest_component_mismatches[:3]}",
            cast(dict[str, object], context),
        )
    return {
        "measurement_method": (
            "independent gerbonara parse of F.Silkscreen/B.Silkscreen, "
            "F.Mask/B.Mask, and Edge.Cuts with object geometry and bbox overlap checks"
        ),
        "capability_min_silk_width_mm": min_width,
        "capability_min_silk_height_mm": min_height,
        "object_type_counts": dict(sorted(type_counts.items())),
        "recognized_object_count": len(all_silk),
        "declared_elements": declared,
        "placement_evidence": [dict(item) for item in declarations.placement_evidence],
        "pad_to_silk_overlap_count": len(pad_overlaps),
        "mask_to_silk_overlap_count": len(mask_overlaps),
        "board_edge_overflow_count": len(outside),
        "board_edge_margin_violation_count": len(findings.edge_margin_violations),
        "attribution_overflow_count": len(attribution_overflows),
        "body_overlap_count": len(findings.body_overlaps),
        "courtyard_overlap_count": len(findings.courtyard_overlaps),
        "existing_footprint_silk_overlap_count": len(findings.existing_silk_overlaps),
        "nearest_component_mismatch_count": len(findings.nearest_component_mismatches),
        "qr_fidelity_failure_count": len(qr_fidelity_failures),
        "qr_fidelity": qr_fidelity_results,
        "pad_to_silk_overlaps": pad_overlaps,
        "mask_to_silk_overlaps": mask_overlaps,
        "board_edge_overflows": outside,
        "board_edge_margin_violations": findings.edge_margin_violations,
        "attribution_overflows": attribution_overflows,
        "body_overlaps": findings.body_overlaps,
        "courtyard_overlaps": findings.courtyard_overlaps,
        "existing_footprint_silk_overlaps": findings.existing_silk_overlaps,
        "nearest_component_mismatches": findings.nearest_component_mismatches,
        "silkscreen_context": context,
        "status": "measured_pass",
    }


def build_silkscreen_context(
    silk_paths: Mapping[str, Path],
    mask_paths: Mapping[str, Path],
    edge_path: Path,
    measurement: BoardMeasurement,
    declarations: SilkscreenLane,
    profile: FabProfile,
    resolved_source_paths: Mapping[str, Path] | None = None,
) -> dict[str, object]:
    """Return the gate's measured context without turning approximation into proof.

    The context is collected by the same measurement gate.  A failed clearance
    check is represented as a context with ``status=measured_fail``; callers
    must still run the routed-board gate before accepting a design.
    """
    try:
        result = measure_silkscreen(
            silk_paths,
            mask_paths,
            edge_path,
            measurement,
            declarations,
            profile,
            resolved_source_paths,
        )
    except SilkscreenGateError as exc:
        context = dict(exc.context)
        context["status"] = "measured_fail"
        context["failure_reason"] = str(exc)
        return context
    context_value = result.get("silkscreen_context")
    if not isinstance(context_value, dict):
        raise FabOutputError("silkscreen context missing from measurement (fail-closed)")
    context = dict(cast(Mapping[str, object], context_value))
    context["status"] = "measured_pass"
    return context
