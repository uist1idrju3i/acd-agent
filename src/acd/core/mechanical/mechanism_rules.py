"""Deterministic design rules for opt-in enclosure mechanism features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from acd.core.mechanical.mechanical import MechanicalLane, MechanismFeatureView

MechanismStatus = Literal["pass", "fail", "unknown"]

MATERIAL_ALLOWABLE_STRAIN: dict[str, float] = {
    "PLA": 0.012,
    "ABS": 0.03,
    "PETG": 0.02,
    "PA": 0.05,
}


@dataclass(frozen=True)
class MechanismFinding:
    node_id: str
    feature_type: str
    rule_id: str
    status: MechanismStatus
    message: str
    measured: float | None = None
    limit: float | None = None


def _finding(
    feature: MechanismFeatureView,
    rule_id: str,
    status: MechanismStatus,
    message: str,
    measured: float | None = None,
    limit: float | None = None,
) -> MechanismFinding:
    return MechanismFinding(
        node_id=feature.node_id,
        feature_type=feature.feature_type,
        rule_id=rule_id,
        status=status,
        message=message,
        measured=measured,
        limit=limit,
    )


def _positive(feature: MechanismFeatureView, name: str) -> float | None:
    value = feature.dimensions.get(name)
    if value is None or value <= 0:
        return None
    return value


def _check_snap_fit(lane: MechanicalLane, feature: MechanismFeatureView) -> MechanismFinding:
    material = lane.enclosure.material.upper()
    allowable = MATERIAL_ALLOWABLE_STRAIN.get(material)
    y = _positive(feature, "deflection_mm")
    thickness = _positive(feature, "hook_thickness_mm")
    length = _positive(feature, "hook_length_mm")
    if allowable is None or y is None or thickness is None or length is None:
        return _finding(
            feature,
            "snap_fit_strain",
            "unknown",
            "material or cantilever dimensions are unavailable",
        )
    # Cantilever approximation: epsilon = 1.5*y*t/L^2.
    strain = 1.5 * y * thickness / (length * length)
    status: MechanismStatus = "pass" if strain <= allowable else "fail"
    return _finding(
        feature,
        "snap_fit_strain",
        status,
        f"cantilever strain {strain:.9g} against {material} allowable {allowable:.9g}",
        strain,
        allowable,
    )


def check_mechanism_features(lane: MechanicalLane) -> tuple[MechanismFinding, ...]:
    """Evaluate all declared features in stable node/rule order."""
    findings: list[MechanismFinding] = []
    for feature in lane.mechanism_features:
        if feature.feature_type == "snap_fit":
            findings.append(_check_snap_fit(lane, feature))
        elif feature.feature_type == "rib":
            thickness = _positive(feature, "thickness_mm")
            draft = _positive(feature, "draft_deg")
            if thickness is None or draft is None:
                findings.append(
                    _finding(feature, "rib_geometry", "unknown", "rib dimensions unavailable")
                )
            else:
                max_thickness = 0.6 * lane.enclosure.wall_thickness_mm
                status: MechanismStatus = (
                    "pass" if thickness <= max_thickness and draft >= 0.5 else "fail"
                )
                findings.append(
                    _finding(
                        feature,
                        "rib_geometry",
                        status,
                        "rib thickness must be <= 0.6*wall and draft >= 0.5 degrees",
                        thickness,
                        max_thickness,
                    )
                )
        elif feature.feature_type == "boss":
            outer = _positive(feature, "outer_diameter_mm")
            hole = _positive(feature, "hole_diameter_mm")
            if outer is None or hole is None or outer <= hole:
                findings.append(
                    _finding(feature, "boss_wall", "unknown", "boss diameters unavailable")
                )
            else:
                wall = (outer - hole) / 2
                minimum = 0.75 * lane.enclosure.wall_thickness_mm
                findings.append(
                    _finding(
                        feature,
                        "boss_wall",
                        "pass" if wall >= minimum else "fail",
                        "boss annular wall must be >= 0.75*enclosure wall",
                        wall,
                        minimum,
                    )
                )
        elif feature.feature_type == "hinge":
            clearance = _positive(feature, "clearance_mm")
            swing = _positive(feature, "swing_deg")
            if clearance is None or swing is None:
                findings.append(
                    _finding(feature, "hinge_motion", "unknown", "hinge dimensions unavailable")
                )
            else:
                findings.append(
                    _finding(
                        feature,
                        "hinge_motion",
                        "pass" if clearance >= 0.1 and swing <= 180 else "fail",
                        "hinge clearance must be >= 0.1 mm and swing <= 180 degrees",
                        clearance,
                        0.1,
                    )
                )
        elif feature.feature_type == "button":
            stroke = _positive(feature, "stroke_mm")
            travel = _positive(feature, "travel_clearance_mm")
            web = _positive(feature, "web_thickness_mm")
            if stroke is None or travel is None or web is None:
                findings.append(
                    _finding(
                        feature,
                        "button_travel",
                        "unknown",
                        "button stroke, travel clearance, or web thickness unavailable",
                    )
                )
            else:
                findings.append(
                    _finding(
                        feature,
                        "button_travel",
                        "pass" if stroke <= travel else "fail",
                        "button stroke must be <= travel clearance and web thickness "
                        "must be positive",
                        stroke,
                        travel,
                    )
                )
        elif feature.feature_type == "light_pipe":
            diameter = _positive(feature, "diameter_mm")
            body = feature.led_body_size_mm
            if diameter is None or body is None:
                findings.append(
                    _finding(
                        feature,
                        "light_pipe_diameter",
                        "unknown",
                        "LED body dimensions unavailable",
                    )
                )
            else:
                minimum = body + 0.4
                findings.append(
                    _finding(
                        feature,
                        "light_pipe_diameter",
                        "pass" if diameter >= minimum else "fail",
                        "light pipe diameter must be >= LED body size + 0.4 mm",
                        diameter,
                        minimum,
                    )
                )
    return tuple(findings)
