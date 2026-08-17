"""Independent manufacturing measurements, DFM checks, and JLCPCB exports."""
# pyright: reportUnusedImport=false
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
from dataclasses import dataclass
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
from acd.core.board_model import BoardModel, RoutedDesign, RoutedVia
from acd.core.bom import refdes_key
from acd.core.electrical import ComponentView, ElectricalLane
from acd.core.fab import (
    FabOrderIntentView,
    FabProfile,
    ProcessAllowanceView,
    validate_allowances_against_profile,
)
from acd.core.routing_width import NetWidthRequirement
from acd.core.silkscreen import SilkscreenLane


from .common import *  # noqa: F401,F403
from .geometry import *  # noqa: F401,F403
from .sexpr_query import *  # noqa: F401,F403


def verify_smd_pad_centers_in_gerber(gerber_path: Path, measurement: BoardMeasurement) -> None:
    try:
        layer = GerberFile.open(gerber_path)  # pyright: ignore[reportUnknownMemberType]
        objects = cast("list[Flash | Region | Line]", layer.objects)  # pyright: ignore[reportUnknownMemberType]
    except Exception as exc:
        raise FabOutputError(
            f"{gerber_path.name}: Gerber pad coverage parse failed: {exc}"
        ) from exc

    def covered(x: float, y: float) -> bool:
        for obj in objects:
            if not obj.polarity_dark:
                continue
            if isinstance(obj, Flash):
                if not isinstance(
                    obj.aperture,
                    (CircleAperture, ObroundAperture, RectangleAperture),
                ):
                    raise FabOutputError(
                        f"{gerber_path.name}: unsupported Flash aperture "
                        f"{type(obj.aperture).__name__}; SMD pad coverage is unknown"
                    )
                if isinstance(obj.aperture, CircleAperture):
                    width = height = float(obj.aperture.diameter)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                else:
                    width = float(obj.aperture.w)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                    height = float(obj.aperture.h)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                obj_x = float(obj.x)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                obj_y = float(obj.y)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                if abs(x - obj_x) <= width / 2 and abs(y - obj_y) <= height / 2:
                    return True
            elif isinstance(obj, Region):
                outline = cast("list[tuple[float, float]]", obj.outline)  # pyright: ignore[reportUnknownMemberType]
                if _point_in_polygon(x, y, outline):
                    return True
            else:
                if not isinstance(obj.aperture, CircleAperture):
                    raise FabOutputError(
                        f"{gerber_path.name}: unsupported Line aperture "
                        f"{type(obj.aperture).__name__}; SMD pad coverage is unknown"
                    )
                x1 = float(obj.x1)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                y1 = float(obj.y1)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                x2 = float(obj.x2)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                y2 = float(obj.y2)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                dx, dy = x2 - x1, y2 - y1
                length_sq = dx * dx + dy * dy
                t = (
                    0.0
                    if length_sq == 0
                    else max(
                        0.0,
                        min(1.0, ((x - x1) * dx + (y - y1) * dy) / length_sq),
                    )
                )
                nearest_x, nearest_y = x1 + t * dx, y1 + t * dy
                radius = float(obj.aperture.diameter) / 2  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                if math.hypot(x - nearest_x, y - nearest_y) <= radius:
                    return True
        return False

    missing = [
        pad.refdes
        for pad in measurement.pads
        if pad.kind == "smd"
        and not covered(
            pad.x_mm,
            -pad.y_mm,  # KiCad Y increases downward; Gerber Y increases upward.
        )
    ]
    if missing:
        raise FabOutputError(
            f"{gerber_path.name}: F.Cu does not cover SMD pad centers {sorted(set(missing))}"
        )


def verify_ground_plane_gerbers(
    front_path: Path,
    back_path: Path,
    model: BoardModel,
    stitch_vias: Sequence[tuple[float, float]],
    routes: RoutedDesign,
) -> dict[str, object]:
    """Measure filled copper independently from both plane Gerbers."""
    if not model.copper_zones:
        raise FabOutputError("ground-plane declaration is absent (fail-closed)")
    if not stitch_vias:
        raise FabOutputError("no stitch vias were generated (fail-closed)")

    def read_regions(path: Path) -> tuple[GerberRegionRecord, ...]:
        try:
            text = path.read_text(encoding="ascii")
        except Exception as exc:
            raise FabOutputError(f"{path.name}: copper Gerber parse failed: {exc}") from exc
        fs_match = re.search(r"%FSLAX(\d)(\d)Y(\d)(\d)\*%", text)
        mo_match = re.search(r"%MO(MM|IN)\*%", text)
        if fs_match is None or mo_match is None:
            raise FabOutputError(f"{path.name}: missing Gerber format or units (fail-closed)")
        if (fs_match.group(1), fs_match.group(2), fs_match.group(3), fs_match.group(4)) != (
            "4",
            "6",
            "4",
            "6",
        ):
            raise FabOutputError(f"{path.name}: unsupported Gerber coordinate format (fail-closed)")
        if mo_match.group(1) != "MM":
            raise FabOutputError(f"{path.name}: unsupported Gerber units (fail-closed)")
        scale = 10.0 ** -int(fs_match.group(2))
        current_function: str | None = None
        interpolation = "G01"
        in_region = False
        region_points: list[tuple[float, float]] = []
        regions: list[GerberRegionRecord] = []
        for command in text.split("*"):
            command = command.strip()
            if not command:
                continue
            function_match = re.search(r"G04 #@! TA\.AperFunction,([^*]+)", command)
            if function_match is not None:
                current_function = function_match.group(1).strip()
                continue
            if "G04 #@! TD.AperFunction" in command:
                current_function = None
                continue
            if command == "G36":
                if in_region or current_function is None:
                    raise FabOutputError(
                        f"{path.name}: region without unique AperFunction (fail-closed)"
                    )
                in_region = True
                region_points = []
                continue
            if command == "G37":
                if not in_region or len(region_points) < 3 or current_function is None:
                    raise FabOutputError(f"{path.name}: malformed Gerber region (fail-closed)")
                board_points = tuple((x, -y) for x, y in region_points)
                area = (
                    abs(
                        sum(
                            x1 * y2 - x2 * y1
                            for (x1, y1), (x2, y2) in zip(
                                board_points, (*board_points[1:], board_points[0]), strict=True
                            )
                        )
                    )
                    / 2.0
                )
                xs, ys = zip(*board_points, strict=True)
                regions.append(
                    GerberRegionRecord(
                        current_function,
                        board_points,
                        area,
                        (min(xs), min(ys), max(xs), max(ys)),
                    )
                )
                in_region = False
                continue
            if in_region:
                if command in {"G01", "G02", "G03", "G75"}:
                    if command != "G75":
                        interpolation = command
                    continue
                match = re.fullmatch(r"(?:G01)?X(-?\d+)Y(-?\d+)D0([123])", command)
                arc_match = re.fullmatch(
                    r"(?:G0([23]))?X(-?\d+)Y(-?\d+)I(-?\d+)J(-?\d+)D0([123])",
                    command,
                )
                if arc_match is not None:
                    if arc_match.group(6) != "1" or not region_points:
                        raise FabOutputError(f"{path.name}: malformed region arc (fail-closed)")
                    start = region_points[-1]
                    end = (
                        int(arc_match.group(2)) * scale,
                        int(arc_match.group(3)) * scale,
                    )
                    center = (
                        start[0] + int(arc_match.group(4)) * scale,
                        start[1] + int(arc_match.group(5)) * scale,
                    )
                    start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
                    end_angle = math.atan2(end[1] - center[1], end[0] - center[0])
                    arc_direction = arc_match.group(1) or interpolation.removeprefix("G0")
                    if arc_direction == "2":
                        while end_angle >= start_angle:
                            end_angle -= math.tau
                    else:
                        while end_angle <= start_angle:
                            end_angle += math.tau
                    steps = max(2, int(abs(end_angle - start_angle) / (math.pi / 18)))
                    radius = math.hypot(start[0] - center[0], start[1] - center[1])
                    region_points.extend(
                        (
                            center[0] + radius * math.cos(angle),
                            center[1] + radius * math.sin(angle),
                        )
                        for angle in (
                            start_angle + (end_angle - start_angle) * index / steps
                            for index in range(1, steps + 1)
                        )
                    )
                    continue
                if match is None:
                    raise FabOutputError(
                        f"{path.name}: unsupported region command {command!r} (fail-closed)"
                    )
                point = (int(match.group(1)) * scale, int(match.group(2)) * scale)
                operation = match.group(3)
                if operation == "2":
                    if region_points:
                        raise FabOutputError(
                            f"{path.name}: multiple region contours unsupported (fail-closed)"
                        )
                    region_points.append(point)
                elif operation == "1":
                    region_points.append(point)
        if in_region:
            raise FabOutputError(f"{path.name}: unterminated Gerber region (fail-closed)")
        return tuple(regions)

    def read(path: Path) -> list[object]:
        try:
            layer = GerberFile.open(path)  # pyright: ignore[reportUnknownMemberType]
            return list(cast("Iterable[object]", layer.objects))  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:
            raise FabOutputError(f"{path.name}: copper Gerber parse failed: {exc}") from exc

    def bbox(obj: object) -> tuple[float, float, float, float] | None:
        if isinstance(obj, Flash):
            x = float(cast(float, obj.x))  # pyright: ignore[reportUnknownMemberType]
            y = float(cast(float, obj.y))  # pyright: ignore[reportUnknownMemberType]
            aperture = obj.aperture
            if isinstance(aperture, CircleAperture):
                sx = sy = float(
                    cast(float, aperture.diameter)  # pyright: ignore[reportUnknownMemberType]
                )
            elif isinstance(aperture, (RectangleAperture, ObroundAperture)):
                sx = float(cast(float, aperture.w))  # pyright: ignore[reportUnknownMemberType]
                sy = float(cast(float, aperture.h))  # pyright: ignore[reportUnknownMemberType]
            else:
                raise FabOutputError("unsupported copper flash aperture (fail-closed)")
            return x - sx / 2, y - sy / 2, x + sx / 2, y + sy / 2
        if isinstance(obj, Region):
            points = cast("Sequence[tuple[float, float]]", obj.outline)  # pyright: ignore[reportUnknownMemberType]
            if not points:
                return None
            xs, ys = zip(*points, strict=True)
            return min(xs), min(ys), max(xs), max(ys)
        if isinstance(obj, Line):
            aperture = obj.aperture
            if not isinstance(aperture, CircleAperture):
                raise FabOutputError("unsupported copper line aperture (fail-closed)")
            radius = (
                float(
                    cast(float, aperture.diameter)  # pyright: ignore[reportUnknownMemberType]
                )
                / 2
            )
            x1 = float(cast(float, obj.x1))  # pyright: ignore[reportUnknownMemberType]
            y1 = float(cast(float, obj.y1))  # pyright: ignore[reportUnknownMemberType]
            x2 = float(cast(float, obj.x2))  # pyright: ignore[reportUnknownMemberType]
            y2 = float(cast(float, obj.y2))  # pyright: ignore[reportUnknownMemberType]
            return (
                min(x1, x2) - radius,
                min(y1, y2) - radius,
                max(x1, x2) + radius,
                max(y1, y2) + radius,
            )
        raise FabOutputError(f"unsupported copper object {type(obj).__name__} (fail-closed)")

    all_boxes: list[tuple[float, float, float, float]] = []
    region_records: list[tuple[Path, GerberRegionRecord]] = []
    flash_records: list[tuple[Path, Flash]] = []
    for path in (front_path, back_path):
        raw_regions = read_regions(path)
        for region in raw_regions:
            if region.function not in {
                "Conductor",
                "SMDPad,CuDef",
                "ComponentPad",
                "ViaPad",
            }:
                raise FabOutputError(
                    f"{path.name}: unknown region AperFunction {region.function!r} (fail-closed)"
                )
            region_records.append((path, region))
        for obj in read(path):
            if isinstance(obj, (Flash, Region, Line)) and not obj.polarity_dark:
                continue
            if isinstance(obj, Flash):
                flash_records.append((path, obj))
            box = bbox(obj)
            if box is None:
                continue
            all_boxes.append(box)
    if not all_boxes or not region_records:
        raise FabOutputError("filled copper regions are absent (fail-closed)")
    conductor_records = [
        (path, region) for path, region in region_records if region.function == "Conductor"
    ]
    if not conductor_records:
        raise FabOutputError("zone fill regions are absent (fail-closed)")
    gnd_net = next(
        (net for net in model.nets if net.name == "GND"),
        None,
    )
    if gnd_net is None:
        raise FabOutputError("GND net declaration is absent (fail-closed)")
    gnd_pads: list[tuple[str, float, float]] = []
    for placement in model.placements:
        if placement.side not in {"front", "back"}:
            raise FabOutputError(f"{placement.refdes}: unknown placement side (fail-closed)")
        for refdes, pad_number in gnd_net.pads:
            if refdes != placement.refdes:
                continue
            for pad in placement.footprint.pads:
                if pad.number != pad_number:
                    continue
                x, y = rotate_point(pad.x_mm, pad.y_mm, placement.rotation_deg)
                if pad.through_hole:
                    layers = ("F.Cu", "B.Cu")
                elif pad.on_front == pad.on_back:
                    raise FabOutputError(
                        f"{placement.refdes} pad {pad.number}: copper layer is "
                        "ambiguous (fail-closed)"
                    )
                elif placement.side == "front":
                    layers = ("F.Cu",) if pad.on_front else ("B.Cu",)
                else:
                    layers = ("B.Cu",) if pad.on_front else ("F.Cu",)
                gnd_pads.extend((layer, placement.x_mm + x, placement.y_mm + y) for layer in layers)
    gnd_points = [
        *[
            (layer, via.x_mm, via.y_mm)
            for via in routes.vias
            if via.net == "GND"
            for layer in ("F.Cu", "B.Cu")
        ],
        *[(layer, x, y) for x, y in stitch_vias for layer in ("F.Cu", "B.Cu")],
    ]
    inset = model.edge_clearance_mm
    for _, region in conductor_records:
        x1, y1, x2, y2 = region.bbox_mm
        if x1 < inset or y1 < inset or x2 > model.width_mm - inset or y2 > model.height_mm - inset:
            raise FabOutputError("copper violates board edge clearance (fail-closed)")
    declared = min(zone.min_island_area_mm2 for zone in model.copper_zones)
    if min(region.area_mm2 for _, region in conductor_records) < declared:
        raise FabOutputError("copper island is below declared minimum area (fail-closed)")

    def point_in_polygon(
        point: tuple[float, float], polygon: Sequence[tuple[float, float]]
    ) -> bool:
        inside = False
        for first, second in zip(polygon, (*polygon[1:], polygon[0]), strict=True):
            if (first[1] > point[1]) != (second[1] > point[1]):
                x_intersection = (second[0] - first[0]) * (point[1] - first[1]) / (
                    second[1] - first[1]
                ) + first[0]
                if point[0] < x_intersection:
                    inside = not inside
        return inside

    if not model.keepouts:
        raise FabOutputError("antenna keepout declaration is absent (fail-closed)")

    def polygon_area(points: Sequence[tuple[float, float]]) -> float:
        if len(points) < 3:
            return 0.0
        return (
            abs(
                sum(
                    x1 * y2 - x2 * y1
                    for (x1, y1), (x2, y2) in zip(points, (*points[1:], points[0]), strict=True)
                )
            )
            / 2.0
        )

    def clip_polygon(
        polygon: Sequence[tuple[float, float]],
        axis: int,
        bound: float,
        keep_greater: bool,
    ) -> list[tuple[float, float]]:
        if not polygon:
            return []
        result: list[tuple[float, float]] = []
        for first, second in zip(polygon, (*polygon[1:], polygon[0]), strict=True):
            first_inside = first[axis] >= bound if keep_greater else first[axis] <= bound
            second_inside = second[axis] >= bound if keep_greater else second[axis] <= bound
            if first_inside != second_inside:
                denominator = second[axis] - first[axis]
                if denominator == 0:
                    continue
                ratio = (bound - first[axis]) / denominator
                result.append(
                    (
                        first[0] + ratio * (second[0] - first[0]),
                        first[1] + ratio * (second[1] - first[1]),
                    )
                )
            if second_inside:
                result.append(second)
        return result

    keepout_measurements: list[dict[str, object]] = []
    keepout_copper_area_mm2 = 0.0
    for keepout in model.keepouts:
        rect = (keepout.x1_mm, keepout.y1_mm, keepout.x2_mm, keepout.y2_mm)
        overlap_area = 0.0
        for _, region in conductor_records:
            clipped = list(region.points_mm)
            for axis, bound, keep_greater in (
                (0, rect[0], True),
                (0, rect[2], False),
                (1, rect[1], True),
                (1, rect[3], False),
            ):
                clipped = clip_polygon(clipped, axis, bound, keep_greater)
            overlap_area += polygon_area(clipped)
        keepout_copper_area_mm2 += overlap_area
        keepout_measurements.append({"name": keepout.name, "copper_area_mm2": overlap_area})
    if keepout_copper_area_mm2 > 1e-9:
        raise FabOutputError(
            "copper inside antenna keepout (fail-closed): "
            f"measured_area_mm2={keepout_copper_area_mm2}"
        )

    uncovered_stitch_vias = [
        (x, y)
        for x, y in stitch_vias
        if not any(point_in_polygon((x, y), region.points_mm) for _, region in conductor_records)
    ]
    if uncovered_stitch_vias:
        raise UncoveredStitchViasError(tuple(uncovered_stitch_vias))

    uncovered_gnd_points = [
        (layer, x, y)
        for layer, x, y in gnd_points
        if not any(
            ("F.Cu" if path == front_path else "B.Cu") == layer
            and point_in_polygon((x, y), region.points_mm)
            for path, region in conductor_records
        )
    ]
    uncovered_gnd_pads = [
        (layer, x, y)
        for layer, x, y in gnd_pads
        if not any(
            ("F.Cu" if path == front_path else "B.Cu") == layer
            and point_in_polygon((x, y), region.points_mm)
            for path, region in region_records
            if region.function in {"Conductor", "SMDPad,CuDef", "ComponentPad", "ViaPad"}
        )
        and not any(
            ("F.Cu" if path == front_path else "B.Cu") == layer
            and (flash_box := bbox(flash)) is not None
            and flash_box[0] <= x <= flash_box[2]
            # Gerbonara flash Y is in a Y-up frame; board coordinates are Y-down.
            and flash_box[1] <= -y <= flash_box[3]
            for path, flash in flash_records
        )
    ]
    if uncovered_gnd_points or uncovered_gnd_pads:
        uncovered = (*uncovered_gnd_points, *uncovered_gnd_pads)
        locations = ", ".join(f"{layer}@({x}, {y})" for layer, x, y in uncovered)
        raise FabOutputError(
            f"GND connection points lack copper coverage (fail-closed): {locations}"
        )
    connection_points = (*gnd_points, *gnd_pads)
    region_connection_points = [
        {
            "layer": "F.Cu" if path == front_path else "B.Cu",
            "area_mm2": region.area_mm2,
            "bbox_mm": region.bbox_mm,
            "gnd_connection_point_count": sum(
                point_layer == ("F.Cu" if path == front_path else "B.Cu")
                and point_in_polygon((x, y), region.points_mm)
                for point_layer, x, y in connection_points
            ),
        }
        for path, region in conductor_records
    ]

    parent = list(range(len(conductor_records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        left, right = find(first), find(second)
        if left != right:
            parent[right] = left

    for layer, x, y in connection_points:
        covered = [
            index
            for index, (path, region) in enumerate(conductor_records)
            if ("F.Cu" if path == front_path else "B.Cu") == layer
            and point_in_polygon((x, y), region.points_mm)
        ]
        if not covered:
            continue
        other_layer = [
            index
            for index, (path, region) in enumerate(conductor_records)
            if ("F.Cu" if path == front_path else "B.Cu") != layer
            and point_in_polygon((x, y), region.points_mm)
        ]
        for first in covered:
            for second in other_layer:
                union(first, second)
    for _index, (path, region) in enumerate(conductor_records):
        layer = "F.Cu" if path == front_path else "B.Cu"
        if not any(
            point_layer == layer and point_in_polygon((x, y), region.points_mm)
            for point_layer, x, y in connection_points
        ):
            raise FabOutputError(
                "Conductor region lacks a GND connection point (fail-closed): "
                f"layer={layer}, bbox_mm={region.bbox_mm}"
            )
    components = len({find(index) for index in range(len(conductor_records))})
    if components != 1:
        raise FabOutputError(
            "GND conductor regions are disconnected (fail-closed): "
            f"connected_components={components}"
        )

    def gerber_point(path: Path, flash: Flash) -> tuple[float, float]:
        x = float(cast(float, flash.x))  # pyright: ignore[reportUnknownMemberType]
        y = float(cast(float, flash.y))  # pyright: ignore[reportUnknownMemberType]
        return _gerber_to_board_point(x, y)

    def matching_flash(path: Path, point: tuple[float, float]) -> tuple[float, float] | None:
        gerber_match_tolerance_mm = 1e-4
        matches = [
            gerber_point(path, flash) for record_path, flash in flash_records if record_path == path
        ]
        if not matches:
            return None
        match = min(
            matches,
            key=lambda candidate: math.hypot(candidate[0] - point[0], candidate[1] - point[1]),
        )
        return (
            match
            if math.hypot(match[0] - point[0], match[1] - point[1]) <= gerber_match_tolerance_mm
            else None
        )

    measured_stitch_points: list[tuple[float, float]] = []
    for stitch_point in stitch_vias:
        front_match = matching_flash(front_path, stitch_point)
        back_match = matching_flash(back_path, stitch_point)
        if front_match is None or back_match is None:
            raise FabOutputError(
                "stitch via flash is absent from filled Gerbers (fail-closed): "
                f"location={stitch_point}"
            )
        measured_stitch_points.append(front_match)
    if len(measured_stitch_points) < 2:
        raise FabOutputError(
            "at least two stitch via flashes are required for pitch measurement (fail-closed)"
        )
    nearest_distances = [
        min(
            math.hypot(point[0] - other[0], point[1] - other[1])
            for other in measured_stitch_points
            if other != point
        )
        for point in measured_stitch_points
    ]
    edge_x = model.edge_clearance_mm + model.via_diameter_mm / 2.0
    edge_y = edge_x
    edge_points = [
        point
        for point in measured_stitch_points
        if min(
            abs(point[0] - edge_x),
            abs(point[0] - (model.width_mm - edge_x)),
            abs(point[1] - edge_y),
            abs(point[1] - (model.height_mm - edge_y)),
        )
        <= 1e-5
    ]
    if len(edge_points) < 2:
        raise FabOutputError(
            "at least two perimeter stitch via flashes are required for perimeter "
            "pitch measurement (fail-closed)"
        )
    perimeter_width = model.width_mm - 2.0 * edge_x
    perimeter_height = model.height_mm - 2.0 * edge_y

    def perimeter_coordinate(point: tuple[float, float]) -> float:
        x, y = point
        distances = (
            abs(y - edge_y),
            abs(x - (model.width_mm - edge_x)),
            abs(y - (model.height_mm - edge_y)),
            abs(x - edge_x),
        )
        side = min(range(4), key=distances.__getitem__)
        if side == 0:
            return x - edge_x
        if side == 1:
            return perimeter_width + y - edge_y
        if side == 2:
            return perimeter_width + perimeter_height + (model.width_mm - edge_x - x)
        return perimeter_width + perimeter_height + perimeter_width + (model.height_mm - edge_y - y)

    perimeter_length = 2.0 * (perimeter_width + perimeter_height)
    perimeter_coordinates = sorted(perimeter_coordinate(point) for point in edge_points)
    perimeter_gaps = [second - first for first, second in itertools.pairwise(perimeter_coordinates)]
    perimeter_gaps.append(perimeter_length - perimeter_coordinates[-1] + perimeter_coordinates[0])
    declared_pitch = model.stitch_via_pitch_mm
    if declared_pitch is None:
        raise FabOutputError("declared stitch via pitch is unknown (fail-closed)")
    perimeter_max_gap = max(perimeter_gaps)
    nearest_max_distance = max(nearest_distances)
    pitch_measurement = {
        "declared_pitch_mm": declared_pitch,
        "perimeter_adjacent_max_gap_mm": perimeter_max_gap,
        "all_stitch_nearest_neighbor_max_distance_mm": nearest_max_distance,
        "perimeter_stitch_via_count": len(edge_points),
        "stitch_via_count": len(measured_stitch_points),
        "declared_pitch_satisfied": (
            perimeter_max_gap <= declared_pitch + 1e-6
            and nearest_max_distance <= declared_pitch + 1e-6
        ),
        "basis": (
            "Filled F.Cu and B.Cu Gerber flash centers independently matched "
            "to each requested stitch via location."
        ),
    }
    return {
        "front_regions": sum(path == front_path for path, _ in conductor_records),
        "back_regions": sum(path == back_path for path, _ in conductor_records),
        "copper_area_mm2": sum(region.area_mm2 for _, region in conductor_records),
        "connected_components": components,
        "min_island_area_mm2": min(region.area_mm2 for _, region in conductor_records),
        "stitch_via_coverage": len(stitch_vias),
        "zone_regions": [
            {
                "layer": "F.Cu" if path == front_path else "B.Cu",
                "area_mm2": region.area_mm2,
                "bbox_mm": region.bbox_mm,
            }
            for path, region in conductor_records
        ],
        "region_connection_points": region_connection_points,
        "keepout_copper": keepout_copper_area_mm2 > 1e-9,
        "keepout_copper_area_mm2": keepout_copper_area_mm2,
        "keepout_measurements": keepout_measurements,
        "stitch_via_pitch_measurement": pitch_measurement,
    }
