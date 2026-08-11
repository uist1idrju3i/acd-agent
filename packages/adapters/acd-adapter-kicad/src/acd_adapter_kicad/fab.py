"""Independent manufacturing measurements, DFM checks, and JLCPCB exports."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import sexpdata  # pyright: ignore[reportMissingTypeStubs]
from gerbonara.excellon import ExcellonFile  # pyright: ignore[reportMissingTypeStubs]

from acd_core.bom import BomRow, build_bom
from acd_core.electrical import ElectricalLane
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

    @property
    def annular_ring_mm(self) -> float | None:
        if self.drill_mm is None:
            return None
        return min(self.size_x_mm, self.size_y_mm) / 2.0 - self.drill_mm / 2.0


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


def _rotate(x: float, y: float, angle: float) -> tuple[float, float]:
    radians = math.radians(angle)
    return (
        x * math.cos(radians) - y * math.sin(radians),
        x * math.sin(radians) + y * math.cos(radians),
    )


def _parse_pad(fp_ref: str, fp_at: tuple[float, float, float], node: object) -> PadMeasurement:
    values = _items(node)
    if len(values) < 5:
        raise FabOutputError("malformed KiCad pad")
    pad_at = _one(node, "at")
    size = _one(node, "size")
    if pad_at is None or size is None or len(pad_at) < 3 or len(size) < 3:
        raise FabOutputError(f"{fp_ref}: pad missing at/size")
    local_x, local_y = _number(pad_at[1]), _number(pad_at[2])
    x_off, y_off = _rotate(local_x, local_y, fp_at[2])
    drill = _one(node, "drill")
    drill_mm = None
    if drill is not None and len(drill) > 1:
        drill_values = [
            _number(item) for item in drill[1:] if not isinstance(item, (list, sexpdata.Symbol))
        ]
        if drill_values:
            drill_mm = min(drill_values)
    kind = "through-hole" if "thru_hole" in {str(item) for item in values} else "smd"
    if "np_thru_hole" in {str(item) for item in values}:
        kind = "npth"
    return PadMeasurement(
        refdes=fp_ref,
        kind=kind,
        x_mm=fp_at[0] + x_off,
        y_mm=fp_at[1] + y_off,
        rotation_deg=fp_at[2] + (_number(pad_at[3]) if len(pad_at) > 3 else 0.0),
        size_x_mm=_number(size[1]),
        size_y_mm=_number(size[2]),
        drill_mm=drill_mm,
        net=None,
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
    for node in _items(root)[1:]:
        tag = _tag(node)
        if tag == "footprint":
            refdes = _property(node, "Reference")
            if not refdes:
                continue
            fp_at = _at(node)
            layer_node = _one(node, "layer")
            layer = str(layer_node[1]) if layer_node and len(layer_node) > 1 else "unknown"
            pads = tuple(_parse_pad(refdes, fp_at, pad) for pad in _direct(node, "pad"))
            footprints.append(
                FootprintMeasurement(refdes, fp_at[0], fp_at[1], fp_at[2], layer, pads)
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
            if start and end and len(start) > 2 and len(end) > 2:
                outline_points.extend(
                    [(_number(start[1]), _number(start[2])), (_number(end[1]), _number(end[2]))]
                )
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
    tools = tuple(
        sorted(
            {float(match.group(1)) for match in re.finditer(r"T\d+C([0-9.]+)", path.read_text())}
        )
    )
    return tools, len(objects)


def _cap(profile: FabProfile, key: str) -> float:
    value = profile.data["capabilities"].get(key)
    if value is None:
        raise FabOutputError(f"profile capability {key!r} is missing")
    return float(value["value"])


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
    return {
        "rule_id": rule_id,
        "classification": classification,
        "measured_value": measured,
        "threshold": threshold,
        "unit": unit,
        "locations": [dict(location) for location in locations],
        "allowance": None
        if allowance is None
        else {
            "node_id": allowance.node_id,
            "reason": allowance.reason,
            "requirement": allowance.requirement,
        },
        "status": "allowed" if allowance is not None else "fail",
    }


def run_dfm(
    measurement: BoardMeasurement,
    profile: FabProfile,
    revision: str,
    allowances: tuple[ProcessAllowanceView, ...],
    lane: ElectricalLane | None = None,
    intent: FabOrderIntentView | None = None,
) -> dict[str, object]:
    allowed = _allowance_map(allowances, profile)
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
        if via.hole_mm == 0.15:
            add("via-hole-015-cost", "cost_or_lead_time_adder", via.hole_mm, 0.20, "mm", loc)
        if via.hole_mm <= 0.25 and via.diameter_mm < 0.45:
            add(
                "via-hole-small-diameter-cost",
                "cost_or_lead_time_adder",
                via.diameter_mm,
                0.45,
                "mm",
                loc,
            )
        if via.hole_mm < 0.20:
            add("via-hole-prefer-020", "cost_or_lead_time_adder", via.hole_mm, 0.20, "mm", loc)
        if via.diameter_mm - via.hole_mm < 0.15:
            add(
                "via-diameter-margin-quality",
                "quality_risk",
                via.diameter_mm - via.hole_mm,
                0.15,
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
        if pad.kind == "through-hole" and pad.annular_ring_mm is not None:
            if pad.annular_ring_mm < _cap(profile, "min_pth_annular_ring_2l_1oz"):
                add(
                    "pth-annular-ring-capability",
                    "capability_violation",
                    pad.annular_ring_mm,
                    0.18,
                    "mm",
                    loc,
                )
            if pad.annular_ring_mm < 0.25:
                add(
                    "pth-annular-ring-prefer-025",
                    "quality_risk",
                    pad.annular_ring_mm,
                    0.25,
                    "mm",
                    loc,
                )
            if pad.drill_mm is not None and pad.drill_mm < 0.50:
                add("pth-hole-prefer-050", "quality_risk", pad.drill_mm, 0.50, "mm", loc)
        if pad.kind == "smd" and (pad.size_x_mm < 0.25 or pad.size_y_mm < 0.25):
            add(
                "smd-pad-capability",
                "capability_violation",
                [pad.size_x_mm, pad.size_y_mm],
                [0.25, 0.25],
                "mm",
                loc,
            )
    for via in measurement.vias:
        for pad in measurement.pads:
            if pad.kind != "smd":
                continue
            if (
                abs(via.x_mm - pad.x_mm) <= pad.size_x_mm / 2
                and abs(via.y_mm - pad.y_mm) <= pad.size_y_mm / 2
            ):
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
                0.10,
                "mm",
                [],
            )
        if measurement.min_track_width_mm < 0.15:
            add(
                "track-width-quality-margin",
                "quality_risk",
                measurement.min_track_width_mm,
                0.15,
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
            1.0,
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
            0.15,
            "mm",
            [],
        )
    if lane is not None and intent is not None:
        economic = profile.data["assembly_classes"]["economic"]
        in_economic = intent.pcba_class_target != "economic" or (
            intent.assembly_sides == "top"
            and lane.board.layers in economic["layers"]
            and lane.board.thickness_mm in economic["thickness_mm"]
            and economic["board_size_mm"]["min"][0]
            <= lane.board.width_mm
            <= economic["board_size_mm"]["max"][0]
            and economic["board_size_mm"]["min"][1]
            <= lane.board.height_mm
            <= economic["board_size_mm"]["max"][1]
            and economic["quantity_pcs"]["min"]
            <= intent.quantity_pcs
            <= economic["quantity_pcs"]["max"]
        )
        if not in_economic:
            add(
                "economic-pcba-envelope",
                "cost_or_lead_time_adder",
                {"layers": lane.board.layers, "thickness_mm": lane.board.thickness_mm},
                "economic combination",
                "combination",
                [],
            )
        if lane.board.layers >= 7:
            add("optimal-layer-balance", "quality_risk", lane.board.layers, 6, "layers", [])
    checks = [
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
                "capability_violation",
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
    grouped: dict[tuple[str, ...], BomRow] = {}
    for row in build_bom(lane):
        refs = tuple(ref for ref in row.refdes if any(comp.refdes == ref for comp in fitted))
        if refs:
            grouped[refs] = row
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("Comment", "Designator", "Footprint", "LCSC Part #"))
    for refs, row in sorted(grouped.items(), key=lambda item: item[0][0]):
        writer.writerow((row.value, ",".join(refs), row.footprint, row.lcsc))
    return output.getvalue()


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


def normalized_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()
