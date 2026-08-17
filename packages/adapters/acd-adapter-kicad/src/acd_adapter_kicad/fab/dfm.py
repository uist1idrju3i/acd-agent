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
    cpl_unknowns: Mapping[str, Sequence[str]] | None = None,
    silkscreen_evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if edge_clearance_mm is None:
        raise FabOutputError("board edge copper clearance is required from the electrical graph")
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
            or pad.x_mm + pad_half_x > outline[2] - edge_clearance_mm + 1e-6
            or pad.y_mm + pad_half_y > outline[3] - edge_clearance_mm + 1e-6
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
        }
        if silkscreen_evidence is None
        else None,
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
    unknowns: dict[str, object] = {
        "cpl_rotation_basis_fab_lcsc": (
            "unknown: KiCad rotation was emitted without independent fab/LCSC "
            "component-orientation preview comparison"
        )
    }
    if cpl_unknowns is not None:
        for key, refs in cpl_unknowns.items():
            unknowns[key] = {
                "status": "unknown",
                "designators": list(refs),
                "reason": "実装基準はfab側プレビューでの目視確認が必要",
            }
    report = {
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
        "unknowns": unknowns,
    }
    if silkscreen_evidence is not None:
        report["silkscreen"] = dict(silkscreen_evidence)
    return cast(dict[str, object], report)
