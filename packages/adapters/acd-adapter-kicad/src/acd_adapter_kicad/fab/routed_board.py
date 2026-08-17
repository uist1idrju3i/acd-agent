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

from acd_adapter_kicad.library import SymbolLibrary
from acd_adapter_kicad.placement import rotate_point
from acd_core.board_model import BoardModel, RoutedDesign, RoutedVia
from acd_core.bom import refdes_key
from acd_core.electrical import ComponentView, ElectricalLane
from acd_core.fab import (
    FabOrderIntentView,
    FabProfile,
    ProcessAllowanceView,
    validate_allowances_against_profile,
)
from acd_core.routing_width import NetWidthRequirement
from acd_core.silkscreen import SilkscreenLane


from .common import *  # noqa: F401,F403
from .geometry import *  # noqa: F401,F403
from .sexpr_query import *  # noqa: F401,F403


def _parse_pad(
    fp_ref: str,
    fp_at: tuple[float, float, float],
    node: object,
    net_names: Mapping[str, str],
) -> PadMeasurement:
    values = _items(node)
    if len(values) < 5:
        raise FabOutputError("malformed KiCad pad")
    pad_at = _one(node, "at")
    size = _one(node, "size")
    if pad_at is None or size is None or len(pad_at) < 3 or len(size) < 3:
        raise FabOutputError(f"{fp_ref}: pad missing at/size")
    local_x, local_y = _number(pad_at[1]), _number(pad_at[2])
    x_off, y_off = rotate(local_x, local_y, fp_at[2])
    drill = _one(node, "drill")
    drill_mm = None
    drill_x_mm = None
    drill_y_mm = None
    if drill is not None and len(drill) > 1:
        drill_values = [
            _number(item) for item in drill[1:] if not isinstance(item, (list, sexpdata.Symbol))
        ]
        if drill_values:
            drill_x_mm = drill_values[0]
            drill_y_mm = drill_values[1] if len(drill_values) > 1 else drill_values[0]
            drill_mm = min(drill_x_mm, drill_y_mm)
    kind = "through-hole" if "thru_hole" in {str(item) for item in values} else "smd"
    if "np_thru_hole" in {str(item) for item in values}:
        kind = "npth"
    net_node = _one(node, "net")
    net_value = (
        net_names.get(str(net_node[1]), str(net_node[1]))
        if net_node is not None and len(net_node) > 1
        else None
    )
    return PadMeasurement(
        refdes=fp_ref,
        kind=kind,
        x_mm=fp_at[0] + x_off,
        y_mm=fp_at[1] + y_off,
        rotation_deg=fp_at[2] + (_number(pad_at[3]) if len(pad_at) > 3 else 0.0),
        size_x_mm=_number(size[1]),
        size_y_mm=_number(size[2]),
        drill_mm=drill_mm,
        net=net_value,
        drill_x_mm=drill_x_mm,
        drill_y_mm=drill_y_mm,
        number=str(values[1]) if len(values) > 1 else None,
    )


def parse_routed_board(path: Path) -> BoardMeasurement:
    try:
        root = cast(
            object,
            sexpdata.loads(path.read_text(encoding="utf-8")),  # pyright: ignore[reportUnknownMemberType]
        )
    except Exception as exc:  # pragma: no cover - parser-specific errors
        raise FabOutputError(f"{path.name}: sexpdata parse failed: {exc}") from exc
    if _tag(root) != "kicad_pcb":
        raise FabOutputError(f"{path.name}: not a kicad_pcb document")
    footprints: list[FootprintMeasurement] = []
    vias: list[ViaMeasurement] = []
    tracks: list[float] = []
    segments: list[SegmentMeasurement] = []
    outline_points: list[tuple[float, float]] = []
    silk_heights: list[float] = []
    silk_widths: list[float] = []
    net_names = {
        str(items[1]): str(items[2])
        for child in _items(root)[1:]
        if _tag(child) == "net"
        for items in [_items(child)]
        if len(items) > 2
    }
    net_name_source = "board_net_declarations"
    if not net_names:
        net_name_source = "pad_net_fallback"
        for footprint in _direct(root, "footprint"):
            for pad in _direct(footprint, "pad"):
                net_node = _one(pad, "net")
                if net_node is not None and len(net_node) > 1:
                    net_names[str(net_node[1])] = str(
                        net_node[2] if len(net_node) > 2 else net_node[1]
                    )
    if not net_names:
        raise FabOutputError(f"{path.name}: net names unavailable (fail-closed)")
    for footprint in _direct(root, "footprint"):
        for pad in _direct(footprint, "pad"):
            net_node = _one(pad, "net")
            if net_node is not None and (len(net_node) < 2 or str(net_node[1]) not in net_names):
                raise FabOutputError(f"{path.name}: pad net name unavailable (fail-closed)")
    for node in _items(root)[1:]:
        tag = _tag(node)
        if tag == "footprint":
            refdes = _property(node, "Reference")
            if not refdes:
                continue
            fp_at = _at(node)
            layer_node = _one(node, "layer")
            layer = str(layer_node[1]) if layer_node and len(layer_node) > 1 else "unknown"
            pads = tuple(_parse_pad(refdes, fp_at, pad, net_names) for pad in _direct(node, "pad"))
            for text in _direct(node, "fp_text") + _direct(node, "property"):
                layer = _one(text, "layer")
                effects = _one(text, "effects")
                font = _one(effects, "font") if effects else None
                size = _one(font, "size") if font else None
                thickness = _one(font, "thickness") if font else None
                if (
                    layer
                    and len(layer) > 1
                    and str(layer[1]).endswith("SilkS")
                    and size
                    and len(size) > 2
                ):
                    silk_heights.append(_number(size[2]))
                    if thickness and len(thickness) > 1:
                        silk_widths.append(_number(thickness[1]))
            footprints.append(
                FootprintMeasurement(
                    refdes,
                    fp_at[0],
                    fp_at[1],
                    fp_at[2],
                    str(layer),
                    pads,
                    _footprint_bbox(node, fp_at, "CrtYd"),
                    _footprint_bbox(node, fp_at, "Fab"),
                )
            )
        elif tag == "via":
            at = _one(node, "at")
            size = _one(node, "size")
            drill = _one(node, "drill")
            layers = _one(node, "layers")
            if at is None or size is None or drill is None or layers is None:
                raise FabOutputError("via missing at/size/drill/layers")
            vias.append(
                ViaMeasurement(
                    _number(at[1]),
                    _number(at[2]),
                    _number(size[1]),
                    _number(drill[1]),
                    tuple(str(x) for x in layers[1:]),
                )
            )
        elif tag == "segment":
            width = _one(node, "width")
            start = _one(node, "start")
            end = _one(node, "end")
            layer_node = _one(node, "layer")
            net_node = _one(node, "net")
            if (
                width is None
                or len(width) < 2
                or start is None
                or len(start) < 3
                or end is None
                or len(end) < 3
                or layer_node is None
                or len(layer_node) < 2
                or net_node is None
                or len(net_node) < 2
            ):
                raise FabOutputError("segment missing width/start/end/layer/net")
            net_id = str(net_node[1])
            if net_id not in net_names:
                raise FabOutputError("segment net name unavailable (fail-closed)")
            tracks.append(_number(width[1]))
            segments.append(
                SegmentMeasurement(
                    net=net_names[net_id],
                    layer=str(layer_node[1]),
                    width_mm=_number(width[1]),
                    start=(_number(start[1]), _number(start[2])),
                    end=(_number(end[1]), _number(end[2])),
                )
            )
        elif tag in {"gr_line", "gr_rect", "gr_arc", "gr_poly"}:
            layer = _one(node, "layer")
            if layer is None or len(layer) < 2 or str(layer[1]) != "Edge.Cuts":
                continue
            start = _one(node, "start")
            end = _one(node, "end")
            if start and end:
                outline_points.extend(
                    [(_number(start[1]), _number(start[2])), (_number(end[1]), _number(end[2]))]
                )
        elif tag == "gr_text":
            layer = _one(node, "layer")
            effects = _one(node, "effects")
            font = _one(effects, "font") if effects else None
            size = _one(font, "size") if font else None
            thickness = _one(font, "thickness") if font else None
            if (
                layer
                and len(layer) > 1
                and str(layer[1]).endswith("SilkS")
                and size
                and len(size) > 2
            ):
                silk_heights.append(_number(size[2]))
                if thickness and len(thickness) > 1:
                    silk_widths.append(_number(thickness[1]))
    bbox = None
    if outline_points:
        xs, ys = zip(*outline_points, strict=True)
        bbox = (min(xs), min(ys), max(xs), max(ys))
    return BoardMeasurement(
        tuple(footprints),
        tuple(vias),
        min(tracks) if tracks else None,
        min(silk_heights) if silk_heights else None,
        min(silk_widths) if silk_widths else None,
        bbox,
        (),
        0,
        net_name_source,
        tuple(segments),
    )


def measure_net_track_widths(
    gerber_paths: Mapping[str, Path],
    measurement: BoardMeasurement,
    requirements: Sequence[NetWidthRequirement],
    tolerance_mm: float,
) -> dict[str, object]:
    """Match every routed Gerber line to a saved-board segment and measure width."""
    if not math.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise FabOutputError("width measurement tolerance is invalid (fail-closed)")
    segments = measurement.segments
    if not segments:
        raise FabOutputError("saved board has no net segments (fail-closed)")
    matched: dict[str, list[float]] = defaultdict(list)
    lengths: dict[str, float] = defaultdict(float)
    matched_objects = 0
    object_type_counts: dict[str, int] = defaultdict(int)
    for layer_name, path in sorted(gerber_paths.items()):
        if layer_name not in {"F.Cu", "B.Cu"}:
            continue
        try:
            gerber = GerberFile.open(path)  # pyright: ignore[reportUnknownMemberType]
            objects = cast("list[object]", gerber.objects)  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:
            raise FabOutputError(
                f"{path.name}: Gerber width measurement parse failed: {exc}"
            ) from exc
        for obj in objects:
            object_type = type(obj).__name__
            object_type_counts[object_type] += 1
            if isinstance(obj, (Region, Flash)):
                continue
            if not isinstance(obj, Line):
                raise FabOutputError(
                    f"{path.name}: unexpected conductor object type {object_type} (fail-closed)"
                )
            aperture = obj.aperture
            if not isinstance(aperture, CircleAperture):
                raise FabOutputError(
                    f"{path.name}: unsupported conductor aperture "
                    f"{type(aperture).__name__}; width is unknown"
                )
            start = _gerber_to_board_point(
                float(obj.x1),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                float(obj.y1),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            )
            end = _gerber_to_board_point(
                float(obj.x2),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                float(obj.y2),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            )
            candidates = [
                segment
                for segment in segments
                if segment.layer == layer_name
                and (
                    (
                        math.dist(start, segment.start) <= tolerance_mm
                        and math.dist(end, segment.end) <= tolerance_mm
                    )
                    or (
                        math.dist(start, segment.end) <= tolerance_mm
                        and math.dist(end, segment.start) <= tolerance_mm
                    )
                )
            ]
            if len(candidates) != 1:
                raise FabOutputError(
                    f"{path.name}: conductor line cannot be uniquely matched "
                    f"to saved-board net segment at {start}->{end}"
                )
            segment = candidates[0]
            width_mm = float(aperture.diameter)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            matched[segment.net].append(width_mm)
            lengths[segment.net] += math.dist(segment.start, segment.end)
            matched_objects += 1
    if matched_objects == 0:
        raise FabOutputError("no routed Gerber conductor lines were measured (fail-closed)")
    by_net = {requirement.net_name: requirement for requirement in requirements}
    if set(matched) - set(by_net):
        raise FabOutputError(
            f"Gerber conductor attributed to undeclared net(s): "
            f"{sorted(set(matched) - set(by_net))}"
        )
    evidence: dict[str, object] = {
        "matching_method": (
            "post-refill Gerber Line endpoints to saved-board segment endpoints; "
            "Gerber Y-up converted to board Y-down"
        ),
        "tolerance_mm": tolerance_mm,
        "matched_object_count": matched_objects,
        "recognized_object_count": sum(object_type_counts.values()),
        "object_type_counts": dict(sorted(object_type_counts.items())),
        "nets": {},
    }
    net_evidence: dict[str, object] = {}
    for requirement in requirements:
        widths = matched.get(requirement.net_name)
        if not widths:
            raise FabOutputError(f"net {requirement.net_name}: no matched Gerber conductor width")
        measured = min(widths)
        passed = measured + tolerance_mm >= requirement.adopted_width_mm
        net_evidence[requirement.net_name] = {
            **requirement.evidence(),
            "measured_minimum_mm": measured,
            "sample_count": len(widths),
            "matched_object_count": len(widths),
            "pass": passed,
            "total_conductor_length_mm": lengths[requirement.net_name],
        }
        if not passed:
            raise FabOutputError(
                f"net {requirement.net_name}: measured width {measured:.6f} mm "
                f"is below adopted width {requirement.adopted_width_mm:.6f} mm"
            )
    evidence["nets"] = net_evidence
    return evidence


def measure_net_path_resistance(
    measurement: BoardMeasurement,
    requirements: Sequence[NetWidthRequirement],
    routed_vias: Sequence[RoutedVia],
    copper_thickness_mm: float,
    tolerance_mm: float = 1e-4,
) -> dict[str, object]:
    """Measure shortest pad-to-pad resistance through saved routed geometry."""
    if not math.isfinite(copper_thickness_mm) or copper_thickness_mm <= 0:
        raise FabOutputError("copper thickness is invalid (fail-closed)")
    if not math.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise FabOutputError("path matching tolerance is invalid (fail-closed)")
    rho_ohm_mm = 1.724e-5
    by_net: dict[str, list[SegmentMeasurement]] = defaultdict(list)
    for segment in measurement.segments:
        by_net[segment.net].append(segment)
    result: dict[str, object] = {}
    for requirement in requirements:
        segments = by_net.get(requirement.net_name, [])
        pads = [pad for pad in measurement.pads if pad.net == requirement.net_name]
        nodes: set[tuple[str, float, float]] = set()
        edges: dict[
            tuple[str, float, float],
            list[tuple[tuple[str, float, float], float]],
        ] = defaultdict(list)

        def node_for(
            layer: str,
            point: tuple[float, float],
            nodes_ref: set[tuple[str, float, float]] = nodes,
        ) -> tuple[str, float, float]:
            for existing in nodes_ref:
                if existing[0] == layer and math.dist(existing[1:], point) <= tolerance_mm:
                    return existing
            node = (layer, round(point[0], 6), round(point[1], 6))
            nodes_ref.add(node)
            return node

        for segment in segments:
            start = node_for(segment.layer, segment.start)
            end = node_for(segment.layer, segment.end)
            length_mm = math.dist(segment.start, segment.end)
            resistance = rho_ohm_mm * length_mm / (segment.width_mm * copper_thickness_mm)
            edges[start].append((end, resistance))
            edges[end].append((start, resistance))
        for via in routed_vias:
            if via.net != requirement.net_name:
                continue
            front = node_for("F.Cu", (via.x_mm, via.y_mm))
            back = node_for("B.Cu", (via.x_mm, via.y_mm))
            edges[front].append((back, 0.0))
            edges[back].append((front, 0.0))

        pad_nodes: list[tuple[str, tuple[str, float, float]]] = []
        for pad in pads:
            candidates = [
                node for node in nodes if math.dist(node[1:], (pad.x_mm, pad.y_mm)) <= tolerance_mm
            ]
            if len(candidates) != 1:
                continue
            label = f"{pad.refdes}-{pad.number or '?'}"
            pad_nodes.append((label, candidates[0]))

        def shortest_path(
            source: tuple[str, float, float],
            target: tuple[str, float, float],
            edges_ref: dict[
                tuple[str, float, float],
                list[tuple[tuple[str, float, float], float]],
            ] = edges,
        ) -> float | None:
            distances: dict[tuple[str, float, float], float] = {source: 0.0}
            pending: list[tuple[float, tuple[str, float, float]]] = [(0.0, source)]
            while pending:
                pending.sort(key=lambda pending_item: pending_item[0], reverse=True)
                distance, current = pending.pop()
                if current == target:
                    return distance
                if distance > distances.get(current, math.inf):
                    continue
                for neighbor, weight in edges_ref.get(current, []):
                    candidate = distance + weight
                    if candidate < distances.get(neighbor, math.inf):
                        distances[neighbor] = candidate
                        pending.append((candidate, neighbor))
            return None

        path_candidates: list[tuple[float, str, str]] = []
        for index, (source_label, source_node) in enumerate(pad_nodes):
            for target_label, target_node in pad_nodes[index + 1 :]:
                resistance = shortest_path(source_node, target_node)
                if resistance is not None:
                    path_candidates.append((resistance, source_label, target_label))
        total_length = sum(math.dist(segment.start, segment.end) for segment in segments)
        total_resistance = (
            rho_ohm_mm * total_length / (requirement.adopted_width_mm * copper_thickness_mm)
        )
        current = requirement.current_max_a
        upper_bound_basis = (
            "Total routed conductor length is treated as one series path; "
            "parallel branches are ignored. For GND, the filled-plane return path "
            "is omitted, so this is a pessimistic routed-conductor upper bound."
        )
        item: dict[str, object] = {
            "total_conductor_length_mm": total_length,
            "series_resistance_upper_bound_ohm": total_resistance,
            "ir_drop_upper_bound_v": (total_resistance * current if current is not None else None),
            "upper_bound_basis": upper_bound_basis,
            "path_resistance_basis": (
                "Shortest resistance path between measured pads over saved-board "
                "segment endpoints and routed via endpoints; GND plane return is "
                "not represented."
            ),
            "via_resistance_model": (
                "Routed via endpoint connections are modeled as ideal zero-ohm "
                "connections because barrel plating resistance is not measured."
            ),
            "path_measurement_status": "measured" if path_candidates else "unknown",
        }
        if path_candidates:
            resistance, source_label, target_label = max(path_candidates)
            item.update(
                {
                    "farthest_pad_pair": [source_label, target_label],
                    "farthest_pad_path_resistance_ohm": resistance,
                    "farthest_pad_path_ir_drop_v": (
                        resistance * current if current is not None else None
                    ),
                }
            )
        result[requirement.net_name] = item
    return result


def read_drill_measurement(path: Path) -> tuple[tuple[float, ...], int]:
    try:
        drill = ExcellonFile.open(path)  # pyright: ignore[reportUnknownMemberType]
        objects = cast("list[object]", drill.objects)  # pyright: ignore[reportUnknownMemberType]
    except Exception as exc:  # pragma: no cover
        raise FabOutputError(f"{path.name}: gerbonara parse failed: {exc}") from exc
    tools: set[float] = set()
    for obj in objects:
        aperture = getattr(obj, "aperture", None)
        diameter = getattr(aperture, "diameter", None)
        if diameter is not None:
            tools.add(float(cast(float, diameter)))
    return tuple(sorted(tools)), len(objects)
