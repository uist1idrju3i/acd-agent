"""QR module-matrix fidelity measurement against printed silkscreen ink."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

from acd.core.electrical.qr_geometry import (
    QR_DATA_MODULES,
    QR_QUIET_ZONE_MODULES,
    qr_module_matrix_from_svg,
)
from acd.core.electrical.silkscreen import SilkGraphicView
from acd.core.runtime.fileio import sha256_hex

from .common import FabOutputError
from .geometry import _point_in_polygon
from .silkscreen_objects import (  # pyright: ignore[reportPrivateUsage]
    _silk_overlaps_rect,
    _SilkObject,
    _union_bbox,
)


def _point_has_ink(
    objects: Sequence[_SilkObject],
    point: tuple[float, float],
) -> bool:
    tiny = (point[0], point[1], point[0], point[1])
    for item in objects:
        if item.kind == "Region" and item.points_mm:
            if _point_in_polygon(point[0], point[1], item.points_mm):
                return True
        elif _silk_overlaps_rect(item, tiny):
            return True
    return False


def _axis_ink_intervals(
    objects: Sequence[_SilkObject],
    coordinate: float,
    *,
    horizontal: bool,
) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    for item in objects:
        if item.kind == "Region" and item.points_mm:
            intersections: list[float] = []
            for first, second in zip(item.points_mm, item.points_mm[1:], strict=False):
                first_axis = first[1] if horizontal else first[0]
                second_axis = second[1] if horizontal else second[0]
                if (first_axis <= coordinate < second_axis) or (
                    second_axis <= coordinate < first_axis
                ):
                    ratio = (coordinate - first_axis) / (second_axis - first_axis)
                    first_other = first[0] if horizontal else first[1]
                    second_other = second[0] if horizontal else second[1]
                    intersections.append(first_other + ratio * (second_other - first_other))
            intersections.sort()
            intervals.extend(
                (left, right)
                for left, right in zip(intersections[::2], intersections[1::2], strict=False)
                if right > left
            )
            continue
        if horizontal:
            if item.bbox_mm[1] <= coordinate <= item.bbox_mm[3]:
                intervals.append((item.bbox_mm[0], item.bbox_mm[2]))
        elif item.bbox_mm[0] <= coordinate <= item.bbox_mm[2]:
            intervals.append((item.bbox_mm[1], item.bbox_mm[3]))
    return intervals


def _maximum_interval_length(
    intervals: Sequence[tuple[float, float]],
    lower: float,
    upper: float,
    *,
    ink: bool,
) -> float:
    clipped = sorted(
        (max(lower, left), min(upper, right))
        for left, right in intervals
        if min(upper, right) > max(lower, left)
    )
    if ink:
        merged: list[tuple[float, float]] = []
        for interval in clipped:
            if merged and interval[0] <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], interval[1]))
            else:
                merged.append(interval)
        return max((right - left for left, right in merged), default=0.0)
    gaps: list[tuple[float, float]] = []
    cursor = lower
    for left, right in clipped:
        if left > cursor:
            gaps.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < upper:
        gaps.append((cursor, upper))
    return max((right - left for left, right in gaps), default=0.0)


def _minimum_region_gap(objects: Sequence[_SilkObject]) -> float | None:
    regions = [item for item in objects if item.kind == "Region"]
    gaps: list[float] = []
    for index, first in enumerate(regions):
        for second in regions[index + 1 :]:
            vertical_overlap = min(first.bbox_mm[3], second.bbox_mm[3]) - max(
                first.bbox_mm[1], second.bbox_mm[1]
            )
            horizontal_overlap = min(first.bbox_mm[2], second.bbox_mm[2]) - max(
                first.bbox_mm[0], second.bbox_mm[0]
            )
            if vertical_overlap > 0:
                if first.bbox_mm[2] <= second.bbox_mm[0]:
                    gap = second.bbox_mm[0] - first.bbox_mm[2]
                    if gap > 1e-9:
                        gaps.append(gap)
                elif second.bbox_mm[2] <= first.bbox_mm[0]:
                    gap = first.bbox_mm[0] - second.bbox_mm[2]
                    if gap > 1e-9:
                        gaps.append(gap)
            if horizontal_overlap > 0:
                if first.bbox_mm[3] <= second.bbox_mm[1]:
                    gap = second.bbox_mm[1] - first.bbox_mm[3]
                    if gap > 1e-9:
                        gaps.append(gap)
                elif second.bbox_mm[3] <= first.bbox_mm[1]:
                    gap = first.bbox_mm[1] - second.bbox_mm[3]
                    if gap > 1e-9:
                        gaps.append(gap)
    return min(gaps) if gaps else None


def _qr_fidelity_measurement(
    graphic: SilkGraphicView,
    objects: Sequence[_SilkObject],
    minimum_gap_mm: float,
    source_path: Path,
) -> dict[str, object]:
    if graphic.source_path is None or graphic.source_sha256 is None:
        raise FabOutputError(f"QR graphic {graphic.node_id!r} lacks SVG provenance (fail-closed)")
    if not source_path.is_file():
        raise FabOutputError(f"QR source SVG {str(source_path)!r} is unavailable (fail-closed)")
    try:
        actual_hash = sha256_hex(source_path.read_bytes())
    except OSError as exc:
        raise FabOutputError(
            f"QR source SVG {str(source_path)!r} is unreadable (fail-closed)"
        ) from exc
    if actual_hash != graphic.source_sha256:
        raise FabOutputError(f"QR source SVG hash mismatch for {graphic.node_id!r} (fail-closed)")
    source_matrix, source_pitch = qr_module_matrix_from_svg(source_path)
    if graphic.qr_module_matrix != source_matrix:
        raise FabOutputError(
            f"QR module matrix provenance mismatch for {graphic.node_id!r} (fail-closed)"
        )
    if graphic.placement_center_mm is None or graphic.source_scale is None:
        raise FabOutputError(
            f"QR placement provenance is incomplete for {graphic.node_id!r} (fail-closed)"
        )
    if abs(graphic.rotation_degrees % 360.0) > 1e-9:
        raise FabOutputError("QR rotation must be zero for fidelity measurement (fail-closed)")
    center_x, center_y = graphic.placement_center_mm
    scale = graphic.source_scale
    source_full_modules = QR_DATA_MODULES + 2 * QR_QUIET_ZONE_MODULES
    measured_pitch = source_pitch * scale
    expected_extent = source_full_modules * measured_pitch
    measured_bbox = _union_bbox(objects)
    measured_extent = min(
        measured_bbox[2] - measured_bbox[0],
        measured_bbox[3] - measured_bbox[1],
    )
    if abs(measured_extent - expected_extent) > 1e-6:
        raise FabOutputError(
            f"QR quiet-zone extent mismatch for {graphic.node_id!r}: "
            f"measured={measured_extent:.9f} expected={expected_extent:.9f} "
            "(fail-closed)"
        )
    mismatches: list[dict[str, object]] = []
    minimum_printed_width = math.inf
    minimum_unprinted_gap = math.inf
    for row in range(source_full_modules):
        for column in range(source_full_modules):
            in_data = (
                QR_QUIET_ZONE_MODULES <= row < QR_QUIET_ZONE_MODULES + QR_DATA_MODULES
                and QR_QUIET_ZONE_MODULES <= column < QR_QUIET_ZONE_MODULES + QR_DATA_MODULES
            )
            expected_hole = (
                source_matrix[row - QR_QUIET_ZONE_MODULES][column - QR_QUIET_ZONE_MODULES] == "1"
                if in_data
                else False
            )
            source_x = (column + 0.5) * source_pitch
            source_y = (row + 0.5) * source_pitch
            local_x = (source_x - 18.0) * scale
            local_y = (source_y - 18.0) * scale
            point = (center_x - local_x, center_y + local_y)
            samples = (
                point,
                (point[0] + measured_pitch * 0.45, point[1]),
                (point[0] - measured_pitch * 0.45, point[1]),
                (point[0], point[1] + measured_pitch * 0.45),
                (point[0], point[1] - measured_pitch * 0.45),
            )
            actual_ink = any(_point_has_ink(objects, sample) for sample in samples)
            cell_left = point[0] - measured_pitch / 2.0
            cell_right = point[0] + measured_pitch / 2.0
            cell_bottom = point[1] - measured_pitch / 2.0
            cell_top = point[1] + measured_pitch / 2.0
            horizontal_intervals = _axis_ink_intervals(objects, point[1], horizontal=True)
            vertical_intervals = _axis_ink_intervals(objects, point[0], horizontal=False)
            if expected_hole:
                minimum_unprinted_gap = min(
                    minimum_unprinted_gap,
                    _maximum_interval_length(
                        horizontal_intervals,
                        cell_left,
                        cell_right,
                        ink=False,
                    ),
                    _maximum_interval_length(
                        vertical_intervals,
                        cell_bottom,
                        cell_top,
                        ink=False,
                    ),
                )
            else:
                minimum_printed_width = min(
                    minimum_printed_width,
                    _maximum_interval_length(
                        horizontal_intervals,
                        cell_left,
                        cell_right,
                        ink=True,
                    ),
                    _maximum_interval_length(
                        vertical_intervals,
                        cell_bottom,
                        cell_top,
                        ink=True,
                    ),
                )
            # A QR hole must remain unprinted, and a printed module must remain inked.
            if actual_ink == expected_hole:
                mismatches.append(
                    {
                        "row": row,
                        "column": column,
                        "expected_hole": expected_hole,
                        "actual_ink": actual_ink,
                    }
                )
    if minimum_unprinted_gap < minimum_gap_mm:
        raise FabOutputError(
            f"QR minimum unprinted gap {minimum_unprinted_gap:.9f} mm is below "
            f"profile minimum {minimum_gap_mm:.9f} mm (fail-closed)"
        )
    if mismatches:
        raise FabOutputError(f"QR module matrix mismatch: {len(mismatches)} cells (fail-closed)")
    return {
        "module_matrix_match": True,
        "module_count": QR_DATA_MODULES,
        "quiet_zone_modules": QR_QUIET_ZONE_MODULES,
        "source_module_pitch_mm": source_pitch,
        "projected_cell_pitch_mm": measured_pitch,
        "expected_projected_cell_pitch_mm": measured_pitch,
        "declared_module_pitch_mm": graphic.qr_module_pitch_mm,
        "minimum_unprinted_gap_mm": minimum_unprinted_gap,
        "minimum_printed_width_mm": minimum_printed_width,
        "mismatch_count": 0,
    }


__all__ = [
    "_axis_ink_intervals",
    "_maximum_interval_length",
    "_minimum_region_gap",
    "_point_has_ink",
    "_qr_fidelity_measurement",
]
