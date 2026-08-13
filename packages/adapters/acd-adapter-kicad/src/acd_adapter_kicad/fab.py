"""Independent manufacturing measurements, DFM checks, and JLCPCB exports."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import sexpdata  # pyright: ignore[reportMissingTypeStubs]
from gerbonara.apertures import (  # pyright: ignore[reportMissingTypeStubs]
    CircleAperture,
    ObroundAperture,
    RectangleAperture,
)
from gerbonara.excellon import ExcellonFile  # pyright: ignore[reportMissingTypeStubs]
from gerbonara.graphic_objects import Flash, Line, Region  # pyright: ignore[reportMissingTypeStubs]
from gerbonara.rs274x import GerberFile  # pyright: ignore[reportMissingTypeStubs]

from acd_core.bom import refdes_key
from acd_core.electrical import ComponentView, ElectricalLane
from acd_core.fab import (
    FabOrderIntentView,
    FabProfile,
    ProcessAllowanceView,
    validate_allowances_against_profile,
)


class FabOutputError(ValueError):
    """Raised when manufacturing output cannot be proven correct."""


@dataclass(frozen=True)
class PadMeasurement:
    refdes: str
    kind: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    size_x_mm: float
    size_y_mm: float
    drill_mm: float | None
    net: str | None
    drill_x_mm: float | None = None
    drill_y_mm: float | None = None

    @property
    def annular_ring_mm(self) -> float | None:
        if self.drill_mm is None:
            return None
        drill_x = self.drill_x_mm if self.drill_x_mm is not None else self.drill_mm
        drill_y = self.drill_y_mm if self.drill_y_mm is not None else self.drill_mm
        assert drill_x is not None and drill_y is not None
        return min(
            (self.size_x_mm - drill_x) / 2.0,
            (self.size_y_mm - drill_y) / 2.0,
        )


@dataclass(frozen=True)
class ViaMeasurement:
    x_mm: float
    y_mm: float
    diameter_mm: float
    hole_mm: float
    layers: tuple[str, ...]


@dataclass(frozen=True)
class FootprintMeasurement:
    refdes: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    layer: str
    pads: tuple[PadMeasurement, ...]
    courtyard_bbox_mm: tuple[float, float, float, float] | None = None
    body_bbox_mm: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class BoardMeasurement:
    footprints: tuple[FootprintMeasurement, ...]
    vias: tuple[ViaMeasurement, ...]
    min_track_width_mm: float | None
    silk_min_height_mm: float | None
    silk_min_width_mm: float | None
    outline_bbox_mm: tuple[float, float, float, float] | None
    drill_tool_diameters_mm: tuple[float, ...]
    drill_object_count: int

    @property
    def pads(self) -> tuple[PadMeasurement, ...]:
        return tuple(pad for fp in self.footprints for pad in fp.pads)


def _items(node: object) -> list[object]:
    return cast("list[object]", node) if isinstance(node, list) else []


def _tag(node: object) -> str | None:
    items = _items(node)
    return str(items[0]) if items and not isinstance(items[0], list) else None


def _direct(node: object, tag: str) -> list[list[object]]:
    return [_items(child) for child in _items(node)[1:] if _tag(child) == tag]


def _one(node: object, tag: str) -> list[object] | None:
    matches = _direct(node, tag)
    return matches[0] if matches else None


def _number(value: object) -> float:
    try:
        return float(cast(str, value))
    except (TypeError, ValueError) as exc:
        raise FabOutputError(f"expected numeric s-expression atom, got {value!r}") from exc


def _at(node: object) -> tuple[float, float, float]:
    values = _one(node, "at")
    if values is None or len(values) < 3:
        raise FabOutputError("missing KiCad position")
    return _number(values[1]), _number(values[2]), _number(values[3]) if len(values) > 3 else 0.0


def _property(node: object, name: str) -> str | None:
    for prop in _direct(node, "property"):
        if len(prop) >= 3 and str(prop[1]) == name:
            return str(prop[2])
    for text in _direct(node, "fp_text"):
        if len(text) >= 3 and str(text[1]) == name.lower():
            return str(text[2])
    return None


def rotate(x: float, y: float, angle: float) -> tuple[float, float]:
    radians = math.radians(angle)
    return (
        x * math.cos(radians) + y * math.sin(radians),
        -x * math.sin(radians) + y * math.cos(radians),
    )


def _inverse_rotate(x: float, y: float, angle: float) -> tuple[float, float]:
    return rotate(x, y, -angle)


def _footprint_bbox(
    node: object, fp_at: tuple[float, float, float], layer_suffix: str
) -> tuple[float, float, float, float] | None:
    points: list[tuple[float, float]] = []
    for tag in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly"):
        for item in _direct(node, tag):
            layer = _one(item, "layer")
            if layer is None or not str(layer[1]).endswith(layer_suffix):
                continue
            for point_tag in ("start", "mid", "end", "center"):
                point = _one(item, point_tag)
                if point is not None and len(point) > 2:
                    points.append((_number(point[1]), _number(point[2])))
            pts_node = _one(item, "pts")
            if pts_node is not None:
                for xy in pts_node[1:]:
                    if isinstance(xy, list):
                        values = cast(list[object], xy)
                        if len(values) <= 2:
                            continue
                        points.append((_number(values[1]), _number(values[2])))
    if not points:
        return None
    transformed = [
        (fp_at[0] + rotate(x, y, fp_at[2])[0], fp_at[1] + rotate(x, y, fp_at[2])[1])
        for x, y in points
    ]
    xs, ys = zip(*transformed, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def _point_in_polygon(x: float, y: float, polygon: Sequence[tuple[float, float]]) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, (*polygon[1:], polygon[0]), strict=True):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def verify_smd_pad_centers_in_gerber(
    gerber_path: Path, measurement: BoardMeasurement
) -> None:
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
    for node in _items(root)[1:]:
        tag = _tag(node)
        if tag == "footprint":
            refdes = _property(node, "Reference")
            if not refdes:
                continue
            fp_at = _at(node)
            layer_node = _one(node, "layer")
            layer = str(layer_node[1]) if layer_node and len(layer_node) > 1 else "unknown"
            pads = tuple(
                _parse_pad(refdes, fp_at, pad, net_names) for pad in _direct(node, "pad")
            )
            for text in _direct(node, "fp_text") + _direct(node, "property"):
                layer = _one(text, "layer")
                effects = _one(text, "effects")
                font = _one(effects, "font") if effects else None
                size = _one(font, "size") if font else None
                thickness = _one(font, "thickness") if font else None
                if (
                    layer and len(layer) > 1 and str(layer[1]).endswith("SilkS")
                    and size and len(size) > 2
                ):
                    silk_heights.append(_number(size[2]))
                    if thickness and len(thickness) > 1:
                        silk_widths.append(_number(thickness[1]))
            footprints.append(
                FootprintMeasurement(
                    refdes, fp_at[0], fp_at[1], fp_at[2], str(layer), pads,
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
            if width is not None and len(width) > 1:
                tracks.append(_number(width[1]))
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
    )


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


def _cap(profile: FabProfile, key: str) -> float:
    value = profile.data["capabilities"].get(key)
    if value is None:
        raise FabOutputError(f"profile capability {key!r} is missing")
    return float(value["value"])


def _cap_pair(profile: FabProfile, key: str) -> tuple[float, float]:
    value = profile.data["capabilities"].get(key)
    if value is None or not isinstance(value["value"], list) or len(value["value"]) != 2:
        raise FabOutputError(f"profile capability {key!r} must be a pair")
    return float(value["value"][0]), float(value["value"][1])


def _pref(profile: FabProfile, rule_id: str) -> tuple[float, str, str]:
    for item in profile.data["preferences"]:
        if item["rule_id"] == rule_id:
            threshold = item.get("threshold")
            if not isinstance(threshold, dict):
                raise FabOutputError(f"profile preference {rule_id!r} threshold is missing")
            raw_threshold = cast(dict[str, object], threshold)
            value = raw_threshold.get("value")
            unit = raw_threshold.get("unit")
            comparison = raw_threshold.get("comparison")
            if (
                not isinstance(value, (float, int))
                or not isinstance(unit, str)
                or not isinstance(comparison, str)
            ):
                raise FabOutputError(f"profile preference {rule_id!r} threshold is malformed")
            return (float(value), unit, comparison)
    raise FabOutputError(f"profile preference {rule_id!r} is missing")


def _below(value: float, threshold: tuple[float, str, str]) -> bool:
    return value < threshold[0]


def _equal(value: float, threshold: tuple[float, str, str]) -> bool:
    return math.isclose(value, threshold[0], rel_tol=0.0, abs_tol=1e-9)


def _allowance_map(
    allowances: Iterable[ProcessAllowanceView], profile: FabProfile
) -> dict[str, ProcessAllowanceView]:
    values = tuple(allowances)
    validate_allowances_against_profile(values, profile)
    return {item.rule_id: item for item in values}


def _finding(
    rule_id: str,
    classification: str,
    measured: object,
    threshold: object,
    unit: str,
    locations: Sequence[Mapping[str, object]],
    allowance: ProcessAllowanceView | None,
) -> dict[str, object]:
    is_capability = classification == "capability_violation"
    effective_allowance = None if is_capability else allowance
    return {
        "rule_id": rule_id,
        "classification": classification,
        "measured_value": measured,
        "threshold": threshold,
        "unit": unit,
        "locations": [dict(location) for location in locations],
        "allowance": None
        if effective_allowance is None
        else {
            "node_id": effective_allowance.node_id,
            "reason": effective_allowance.reason,
            "requirement": effective_allowance.requirement,
        },
        "status": "allowed" if effective_allowance is not None else "fail",
    }


def run_dfm(
    measurement: BoardMeasurement,
    profile: FabProfile,
    revision: str,
    allowances: tuple[ProcessAllowanceView, ...],
    lane: ElectricalLane | None = None,
    intent: FabOrderIntentView | None = None,
    edge_clearance_mm: float | None = None,
    edge_overhang_declarations: Mapping[str, float] | None = None,
) -> dict[str, object]:
    if edge_clearance_mm is None:
        raise FabOutputError(
            "board edge copper clearance is required from the electrical graph"
        )
    allowed = _allowance_map(allowances, profile)
    thresholds = {
        rule: _pref(profile, rule)
        for rule in (
            "via-hole-prefer-020",
            "via-hole-015-cost",
            "via-hole-small-diameter-cost",
            "via-diameter-margin-quality",
            "pth-hole-prefer-050",
            "pth-annular-ring-prefer-025",
            "track-width-quality-margin",
            "optimal-layer-balance",
        )
    }
    findings: list[dict[str, object]] = []

    def add(
        rule: str,
        classification: str,
        measured: object,
        threshold: object,
        unit: str,
        locations: Sequence[Mapping[str, object]],
    ) -> None:
        findings.append(
            _finding(rule, classification, measured, threshold, unit, locations, allowed.get(rule))
        )

    for via in measurement.vias:
        loc = [{"x_mm": via.x_mm, "y_mm": via.y_mm}]
        if via.hole_mm < _cap(profile, "min_via_hole"):
            add(
                "via-hole-capability",
                "capability_violation",
                via.hole_mm,
                _cap(profile, "min_via_hole"),
                "mm",
                loc,
            )
        if via.diameter_mm < _cap(profile, "min_via_diameter"):
            add(
                "via-diameter-capability",
                "capability_violation",
                via.diameter_mm,
                _cap(profile, "min_via_diameter"),
                "mm",
                loc,
            )
        if via.diameter_mm - via.hole_mm < _cap(profile, "via_diameter_margin"):
            add(
                "via-margin-capability",
                "capability_violation",
                via.diameter_mm - via.hole_mm,
                _cap(profile, "via_diameter_margin"),
                "mm",
                loc,
            )
        if _equal(via.hole_mm, thresholds["via-hole-015-cost"]):
            add(
                "via-hole-015-cost",
                "cost_or_lead_time_adder",
                via.hole_mm,
                thresholds["via-hole-015-cost"][0],
                "mm",
                loc,
            )
        if via.hole_mm <= _cap(profile, "min_via_diameter") and _below(
            via.diameter_mm, thresholds["via-hole-small-diameter-cost"]
        ):
            add(
                "via-hole-small-diameter-cost",
                "cost_or_lead_time_adder",
                via.diameter_mm,
                thresholds["via-hole-small-diameter-cost"][0],
                "mm",
                loc,
            )
        if _below(via.hole_mm, thresholds["via-hole-prefer-020"]):
            add(
                "via-hole-prefer-020",
                "cost_or_lead_time_adder",
                via.hole_mm,
                thresholds["via-hole-prefer-020"][0],
                "mm",
                loc,
            )
        if _below(via.diameter_mm - via.hole_mm, thresholds["via-diameter-margin-quality"]):
            add(
                "via-diameter-margin-quality",
                "quality_risk",
                via.diameter_mm - via.hole_mm,
                thresholds["via-diameter-margin-quality"][0],
                "mm",
                loc,
            )
        if set(via.layers) != {"F.Cu", "B.Cu"}:
            add(
                "blind-buried-via-unsupported",
                "capability_violation",
                via.layers,
                "F.Cu/B.Cu",
                "layers",
                loc,
            )
    for pad in measurement.pads:
        loc = [{"refdes": pad.refdes, "x_mm": pad.x_mm, "y_mm": pad.y_mm}]
        if pad.kind == "npth" and (pad.drill_mm or 0) < _cap(profile, "min_npth"):
            add(
                "npth-drill-capability",
                "capability_violation",
                pad.drill_mm,
                _cap(profile, "min_npth"),
                "mm",
                loc,
            )
        pad_half_x = pad.size_x_mm / 2.0
        pad_half_y = pad.size_y_mm / 2.0
        outline = measurement.outline_bbox_mm
        if outline is not None and (
            pad.x_mm - pad_half_x < edge_clearance_mm - 1e-6
            or pad.y_mm - pad_half_y < edge_clearance_mm - 1e-6
            or pad.x_mm + pad_half_x
            > outline[2]
            - edge_clearance_mm
            + 1e-6
            or pad.y_mm + pad_half_y
            > outline[3]
            - edge_clearance_mm
            + 1e-6
        ):
            add(
                "pad-to-board-edge-clearance",
                "capability_violation",
                {"refdes": pad.refdes, "x_mm": pad.x_mm, "y_mm": pad.y_mm},
                edge_clearance_mm,
                "mm",
                loc,
            )
        if pad.kind == "through-hole" and pad.annular_ring_mm is not None:
            if pad.annular_ring_mm < _cap(profile, "min_pth_annular_ring_2l_1oz"):
                add(
                    "pth-annular-ring-capability",
                    "capability_violation",
                    pad.annular_ring_mm,
                    _cap(profile, "min_pth_annular_ring_2l_1oz"),
                    "mm",
                    loc,
                )
            if _below(pad.annular_ring_mm, thresholds["pth-annular-ring-prefer-025"]):
                add(
                    "pth-annular-ring-prefer-025",
                    "quality_risk",
                    pad.annular_ring_mm,
                    thresholds["pth-annular-ring-prefer-025"][0],
                    "mm",
                    loc,
                )
            if pad.drill_mm is not None and _below(pad.drill_mm, thresholds["pth-hole-prefer-050"]):
                add(
                    "pth-hole-prefer-050",
                    "quality_risk",
                    pad.drill_mm,
                    thresholds["pth-hole-prefer-050"][0],
                    "mm",
                    loc,
                )
        smd_min = _cap_pair(profile, "min_smd_pad")
        if pad.kind == "smd" and (pad.size_x_mm < smd_min[0] or pad.size_y_mm < smd_min[1]):
            add(
                "smd-pad-capability",
                "capability_violation",
                [pad.size_x_mm, pad.size_y_mm],
                list(smd_min),
                "mm",
                loc,
            )
    if measurement.outline_bbox_mm is None and measurement.pads:
        add(
            "board-outline-geometry-missing",
            "capability_violation",
            None,
            "board outline required",
            "geometry",
            [],
        )
    missing_body_refdes: list[str] = []
    declarations = edge_overhang_declarations or {}
    for fp in measurement.footprints:
        bbox = fp.body_bbox_mm
        if bbox is None or measurement.outline_bbox_mm is None:
            if bbox is None:
                missing_body_refdes.append(fp.refdes)
            continue
        ox1, oy1, ox2, oy2 = measurement.outline_bbox_mm
        overhang = max(ox1 - bbox[0], oy1 - bbox[1], bbox[2] - ox2, bbox[3] - oy2, 0.0)
        if overhang > 1e-9:
            declared_allowed = declarations.get(fp.refdes)
            if declared_allowed is None or overhang > declared_allowed + 1e-6:
                add(
                    "undeclared-board-edge-overhang",
                    "capability_violation",
                    overhang,
                    declared_allowed if declared_allowed is not None else "declaration required",
                    "mm",
                    [{"refdes": fp.refdes, "x_mm": fp.x_mm, "y_mm": fp.y_mm}],
                )
    for via in measurement.vias:
        for pad in measurement.pads:
            if pad.kind != "smd":
                continue
            local_x, local_y = _inverse_rotate(
                via.x_mm - pad.x_mm, via.y_mm - pad.y_mm, pad.rotation_deg
            )
            # DRC owns unrelated-net copper clearance; DFM only checks a drill
            # circle intersecting a soldered SMD pad, which requires filled plating.
            radius = via.hole_mm / 2
            nearest_x = min(max(local_x, -pad.size_x_mm / 2), pad.size_x_mm / 2)
            nearest_y = min(max(local_y, -pad.size_y_mm / 2), pad.size_y_mm / 2)
            if math.hypot(local_x - nearest_x, local_y - nearest_y) <= radius:
                add(
                    "via-in-pad-process",
                    "cost_or_lead_time_adder",
                    {"via_x_mm": via.x_mm, "via_y_mm": via.y_mm},
                    {"refdes": pad.refdes},
                    "overlap",
                    [{"refdes": pad.refdes, "x_mm": via.x_mm, "y_mm": via.y_mm}],
                )
    if measurement.min_track_width_mm is not None:
        if measurement.min_track_width_mm < _cap(profile, "min_track_width"):
            add(
                "track-width-capability",
                "capability_violation",
                measurement.min_track_width_mm,
                _cap(profile, "min_track_width"),
                "mm",
                [],
            )
        if _below(measurement.min_track_width_mm, thresholds["track-width-quality-margin"]):
            add(
                "track-width-quality-margin",
                "quality_risk",
                measurement.min_track_width_mm,
                thresholds["track-width-quality-margin"][0],
                "mm",
                [],
            )
    if measurement.silk_min_height_mm is not None and measurement.silk_min_height_mm < _cap(
        profile, "min_silk_height"
    ):
        add(
            "silk-height-capability",
            "capability_violation",
            measurement.silk_min_height_mm,
            _cap(profile, "min_silk_height"),
            "mm",
            [],
        )
    if measurement.silk_min_width_mm is not None and measurement.silk_min_width_mm < _cap(
        profile, "min_silk_width"
    ):
        add(
            "silk-width-capability",
            "capability_violation",
            measurement.silk_min_width_mm,
            _cap(profile, "min_silk_width"),
            "mm",
            [],
        )
    if lane is not None and intent is not None:
        economic = profile.data["assembly_classes"]["economic"]
        combination = any(
            lane.board.layers == item["layers"]
            and lane.board.thickness_mm == item["thickness_mm"]
            and intent.soldermask_color in item["colors"]
            and intent.surface_finish in item["surface_finishes"]
            and item["quantity_pcs"][0] <= intent.quantity_pcs <= item["quantity_pcs"][1]
            and intent.assembly_sides in economic["assembly_sides"]
            for item in economic["combinations"]
        )
        in_economic = intent.pcba_class_target == "economic" and (
            intent.assembly_sides == "top"
            and combination
            and economic["board_size_mm"]["min"][0]
            <= lane.board.width_mm
            <= economic["board_size_mm"]["max"][0]
            and economic["board_size_mm"]["min"][1]
            <= lane.board.height_mm
            <= economic["board_size_mm"]["max"][1]
        )
        if intent.pcba_class_target == "standard" or not in_economic:
            add(
                "economic-pcba-envelope",
                "cost_or_lead_time_adder",
                {
                    "layers": lane.board.layers,
                    "thickness_mm": lane.board.thickness_mm,
                    "soldermask_color": intent.soldermask_color,
                    "surface_finish": intent.surface_finish,
                    "assembly_sides": intent.assembly_sides,
                    "pcba_class_target": intent.pcba_class_target,
                },
                "economic combination; standard requires edge rails/fiducials and build >= 4 days",
                "combination",
                [],
            )
        if lane.board.layers > thresholds["optimal-layer-balance"][0]:
            add(
                "optimal-layer-balance",
                "quality_risk",
                lane.board.layers,
                thresholds["optimal-layer-balance"][0],
                "layers",
                [],
            )
    checks = [
        {
            "rule_id": "component_body_geometry",
            "reason": (
                "F.Fab body geometry is unavailable for "
                + ", ".join(missing_body_refdes)
                + "; physical overhang was not independently measured for these references."
            ),
        }
        if missing_body_refdes
        else None,
        {
            "rule_id": "pth-to-track-prefer-035",
            "reason": (
                "DFM v1 does not yet independently measure pad-to-track distances; "
                "KiCad DRC clearance is not a substitute."
            ),
        },
        {
            "rule_id": "via_hole_to_hole",
            "reason": "KiCad custom rules do not provide an independently verified "
            "hole-to-hole constraint in this KiCad 10 environment.",
        },
        {
            "rule_id": "routed_edge_copper_clearance",
            "reason": "The KiCad custom-rule edge-clearance constraint was not accepted "
            "as semantically equivalent; independent edge geometry is not implemented.",
        },
        {
            "rule_id": "connector_mating_face_edge_alignment",
            "reason": (
                "Connector mating-face alignment requires a footprint semantic marker not emitted "
                "by the independent board parser."
            ),
        },
        {
            "rule_id": "pad_to_silk",
            "reason": "Silkscreen clearance is not independently measured; DRC is not "
            "treated as an equivalent DFM measurement.",
        },
        {
            "rule_id": "min_via_diameter",
            "reason": "KiCad custom rules cannot be used as a verified via outer-diameter "
            "measurement; the independent DFM measurement remains authoritative.",
        },
        {
            "rule_id": "min_plated_slot_width",
            "reason": "Drill parsing records tool diameters but does not independently "
            "classify plated slot width.",
        },
        {
            "rule_id": "min_nonplated_slot_width",
            "reason": "Drill parsing records tool diameters but does not independently "
            "classify non-plated slot width.",
        },
        {
            "rule_id": "slot_length_width_ratio",
            "reason": "Slot length-to-width ratio is not independently measured.",
        },
        {
            "rule_id": "soldermask_bridge",
            "reason": "Soldermask bridge geometry is not independently measured.",
        },
        {
            "rule_id": "pad_to_track_clearance",
            "reason": "Pad-to-track and PTH-to-track geometry is not independently measured.",
        },
        {
            "rule_id": "min_package",
            "reason": "Graph component data does not include package dimensions.",
        },
        {
            "rule_id": "min_ic_pitch",
            "reason": "Graph component data does not include IC pin pitch.",
        },
        {
            "rule_id": "min_bga_pitch",
            "reason": "Graph component data does not include BGA pitch.",
        },
    ]
    checks = [item for item in checks if item is not None]
    if measurement.silk_min_height_mm is None:
        checks.append(
            {
                "rule_id": "min_silk_height",
                "reason": "No independent silkscreen text geometry was emitted by this board; "
                "the minimum character-height check is not treated as passed.",
            }
        )
    if measurement.silk_min_width_mm is None:
        checks.append(
            {
                "rule_id": "min_silk_width",
                "reason": "No independent silkscreen stroke geometry was emitted by this board; "
                "the minimum line-width check is not treated as passed.",
            }
        )
    unused = [
        item.rule_id
        for item in allowances
        if not any(f["rule_id"] == item.rule_id for f in findings)
    ]
    for rule_id in unused:
        findings.append(
            _finding(
                "unused_allowance",
                "unused_allowance",
                rule_id,
                "finding required",
                "rule_id",
                [],
                None,
            )
        )
    status = "pass" if all(item["status"] == "allowed" for item in findings) else "fail"
    return {
        "schema_version": "0.1",
        "target_revision": revision,
        "profile_id": profile.profile_id,
        "status": status,
        "findings": findings,
        "checks_not_implemented": checks,
        "measurements": {
            "via_count": len(measurement.vias),
            "vias": [
                {
                    "x_mm": via.x_mm,
                    "y_mm": via.y_mm,
                    "outer_diameter_mm": via.diameter_mm,
                    "hole_diameter_mm": via.hole_mm,
                    "layers": list(via.layers),
                }
                for via in measurement.vias
            ],
            "pad_count": len(measurement.pads),
            "min_track_width_mm": measurement.min_track_width_mm,
            "silk_min_height_mm": measurement.silk_min_height_mm,
            "silk_min_width_mm": measurement.silk_min_width_mm,
            "outline_bbox_mm": measurement.outline_bbox_mm,
            "drill_tool_diameters_mm": measurement.drill_tool_diameters_mm,
            "drill_object_count": measurement.drill_object_count,
        },
        "unknowns": {
            "cpl_rotation_basis_fab_lcsc": (
                "unknown: KiCad rotation was emitted without independent fab/LCSC "
                "component-orientation preview comparison"
            )
        },
    }


def parse_pos_csv(path: Path) -> tuple[dict[str, str], ...]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = tuple(csv.DictReader(stream))
    required = {"Ref", "PosX", "PosY", "Rot", "Side"}
    if not rows or not required <= set(rows[0]):
        raise FabOutputError(f"{path.name}: KiCad position CSV missing required columns")
    return rows


def jlcpcb_cpl_csv(rows: Iterable[dict[str, str]], fitted: set[str]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("Designator", "Mid X", "Mid Y", "Rotation", "Layer"))
    seen: set[str] = set()
    for row in sorted(rows, key=lambda item: item["Ref"]):
        ref = row["Ref"]
        if ref not in fitted:
            continue
        seen.add(ref)
        side = row["Side"].strip().lower()
        if side not in {"top", "bottom"}:
            raise FabOutputError(f"{ref}: unknown placement side {row['Side']!r}")
        writer.writerow((ref, row["PosX"], row["PosY"], row["Rot"], side.title()))
    if seen != fitted:
        raise FabOutputError(f"CPL fitted designator mismatch: missing={sorted(fitted - seen)}")
    return output.getvalue()


def jlcpcb_bom_csv(lane: ElectricalLane) -> str:
    fitted = tuple(comp for comp in lane.components if comp.assembly == "fitted")
    if any(not comp.lcsc for comp in fitted):
        raise FabOutputError("fitted component without LCSC part number (fail-closed)")
    grouped: dict[tuple[str, str, str], list[ComponentView]] = {}
    for comp in fitted:
        key = (comp.lcsc, comp.mpn, comp.library.footprint)
        grouped.setdefault(key, []).append(comp)
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("Comment", "Designator", "Footprint", "LCSC Part #"))
    for (lcsc, mpn, footprint), components in sorted(
        grouped.items(),
        key=lambda item: min(refdes_key(c.refdes) for c in item[1]),
    ):
        values = {comp.value for comp in components}
        comment = next(iter(values)) if len(values) == 1 else mpn
        refs = sorted((comp.refdes for comp in components), key=refdes_key)
        writer.writerow((comment, ",".join(refs), footprint, lcsc))
    return output.getvalue()


def cross_validate_bom(
    bom_path: Path,
    lane: ElectricalLane,
    fitted: set[str],
) -> None:
    with bom_path.open(newline="", encoding="utf-8-sig") as stream:
        rows = tuple(csv.DictReader(stream))
    required = {"Comment", "Designator", "Footprint", "LCSC Part #"}
    if not rows or not required <= set(rows[0]):
        raise FabOutputError(f"{bom_path.name}: BOM missing required columns")
    components = {
        comp.refdes: comp for comp in lane.components if comp.assembly == "fitted"
    }
    seen: set[str] = set()
    for row in rows:
        refs = tuple(ref.strip() for ref in row["Designator"].split(",") if ref.strip())
        if not refs:
            raise FabOutputError(f"{bom_path.name}: BOM row has no designator")
        overlap = seen.intersection(refs)
        if overlap:
            raise FabOutputError(
                f"{bom_path.name}: duplicate designators {sorted(overlap, key=refdes_key)}"
            )
        seen.update(refs)
        lcsc = row["LCSC Part #"].strip()
        footprint = row["Footprint"].strip()
        if not lcsc:
            raise FabOutputError(f"{bom_path.name}: BOM row has empty LCSC part number")
        for ref in refs:
            comp = components.get(ref)
            if comp is None:
                raise FabOutputError(f"{bom_path.name}: unknown fitted designator {ref!r}")
            if comp.lcsc != lcsc:
                raise FabOutputError(f"{ref}: BOM LCSC differs from graph")
            if comp.library.footprint != footprint:
                raise FabOutputError(f"{ref}: BOM footprint differs from graph")
    if seen != fitted:
        raise FabOutputError(
            f"BOM fitted designator mismatch: missing={sorted(fitted - seen, key=refdes_key)}, "
            f"extra={sorted(seen - fitted, key=refdes_key)}"
        )


def cross_validate_cpl(
    cpl_path: Path,
    position_rows: tuple[dict[str, str], ...],
    board: BoardMeasurement,
    fitted: set[str],
    tolerance_mm: float = 0.001,
    tolerance_deg: float = 0.01,
) -> None:
    with cpl_path.open(newline="", encoding="utf-8-sig") as stream:
        cpl_rows = tuple(csv.DictReader(stream))
    if {row["Designator"] for row in cpl_rows} != fitted:
        raise FabOutputError("CPL designator set differs from fitted graph components")
    source = {row["Ref"]: row for row in position_rows}
    footprints = {fp.refdes: fp for fp in board.footprints}
    for row in cpl_rows:
        ref = row["Designator"]
        if ref not in source or ref not in footprints:
            raise FabOutputError(f"CPL refdes {ref!r} is absent from independent sources")
        expected = source[ref]
        actual = footprints[ref]
        if abs(float(row["Mid X"]) - actual.x_mm) > tolerance_mm:
            raise FabOutputError(f"{ref}: CPL X differs from routed board")
        if abs(-float(row["Mid Y"]) - actual.y_mm) > tolerance_mm:
            raise FabOutputError(f"{ref}: CPL Y differs from routed board")
        if abs(float(row["Rotation"]) - actual.rotation_deg) > tolerance_deg:
            raise FabOutputError(f"{ref}: CPL rotation differs from routed board")
        if row["Layer"].lower() != expected["Side"].lower():
            raise FabOutputError(f"{ref}: CPL layer differs from position CSV")


def deterministic_zip(output: Path, members: Iterable[Path], root: Path) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(members, key=lambda item: item.relative_to(root).as_posix()):
            info = zipfile.ZipInfo(
                path.relative_to(root).as_posix(), date_time=(1980, 1, 1, 0, 0, 0)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    with zipfile.ZipFile(output) as archive:
        for name in archive.namelist():
            if archive.read(name) != (root / name).read_bytes():
                raise FabOutputError(f"zip member verification failed: {name}")


def zip_content_hash(path: Path) -> str:
    entries: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            data = b"\n".join(
                line
                for line in archive.read(name).splitlines()
                if not line.lstrip().startswith((b"G04", b";"))
            ) + b"\n"
            entries.append(f"{name}:sha256:{hashlib.sha256(data).hexdigest()}")
    return "sha256:" + hashlib.sha256("\n".join(entries).encode()).hexdigest()
