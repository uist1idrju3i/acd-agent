"""Deterministic manufacturing-process checks over reloaded enclosure solids."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from acd.core.mechanical.mechanical import MechanicalLane, MechanismFeatureView

DfmStatus = Literal["pass", "fail", "unknown"]


@dataclass(frozen=True)
class MechanicalDfmFinding:
    rule_id: str
    status: DfmStatus
    message: str
    measured: float | None = None
    limit: float | None = None
    face_center_mm: tuple[float, float, float] | None = None
    feature_id: str | None = None


def _finding(
    rule_id: str,
    status: DfmStatus,
    message: str,
    *,
    measured: float | None = None,
    limit: float | None = None,
    face_center_mm: tuple[float, float, float] | None = None,
    feature_id: str | None = None,
) -> MechanicalDfmFinding:
    return MechanicalDfmFinding(
        rule_id=rule_id,
        status=status,
        message=message,
        measured=measured,
        limit=limit,
        face_center_mm=face_center_mm,
        feature_id=feature_id,
    )


def _profile_number(profile: dict[str, object], name: str) -> float | None:
    value = profile.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _center(face: Any) -> tuple[float, float, float]:
    point = face.center()
    return (
        round(float(point.X), 3),
        round(float(point.Y), 3),
        round(float(point.Z), 3),
    )


def _faces(
    solids: tuple[Any, ...], min_feature_mm: float
) -> list[tuple[Any, tuple[float, float, float]]]:
    minimum_area = min_feature_mm * min_feature_mm
    result: list[tuple[Any, tuple[float, float, float]]] = []
    for solid in solids:
        for face in solid.faces():
            area = float(face.area)
            if not math.isfinite(area) or area < minimum_area:
                continue
            result.append((face, _center(face)))
    return sorted(result, key=lambda item: (item[1], round(float(item[0].area), 3)))


def _normal(face: Any) -> tuple[float, float, float]:
    normal = face.normal_at(face.center())
    vector = (float(normal.X), float(normal.Y), float(normal.Z))
    length = math.sqrt(sum(value * value for value in vector))
    if length <= 0 or not math.isfinite(length):
        raise ValueError("face normal is invalid")
    return (
        vector[0] / length,
        vector[1] / length,
        vector[2] / length,
    )


def _cylinder_radius_axis(face: Any) -> tuple[float, float] | None:
    try:
        adaptor = face.geom_adaptor()
        axis = adaptor.Axis().Direction()
        radius = float(adaptor.Radius())
    except (AttributeError, TypeError, ValueError):
        return None
    return radius, float(axis.Z())


def _wall_distances(solids: tuple[Any, ...], tolerance_mm: float) -> list[float]:
    distances: list[float] = []
    for solid in solids:
        faces = [
            face
            for face in solid.faces()
            if str(face.geom_type).endswith("PLANE")
        ]
        for index, face in enumerate(faces):
            normal = _normal(face)
            for other in faces[index + 1 :]:
                other_normal = _normal(other)
                dot = sum(left * right for left, right in zip(normal, other_normal, strict=True))
                if dot >= -0.99:
                    continue
                distance = float(face.distance_to(other))
                if distance > tolerance_mm and math.isfinite(distance):
                    distances.append(distance)
    return distances


def _feature_thicknesses(
    features: tuple[MechanismFeatureView, ...],
) -> list[tuple[str, float]]:
    thicknesses: list[tuple[str, float]] = []
    for feature in features:
        attr = {
            "rib": "thickness_mm",
            "snap_fit": "hook_thickness_mm",
            "button": "web_thickness_mm",
        }.get(feature.feature_type)
        if attr is not None:
            value = feature.dimensions.get(attr)
            if value is None or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{feature.node_id}: {attr} is invalid")
            thicknesses.append((feature.node_id, value))
    return thicknesses


def _check_min_wall(
    lane: MechanicalLane,
    solids: tuple[Any, ...],
    profile: dict[str, object],
) -> list[MechanicalDfmFinding]:
    minimum = _profile_number(profile, "min_wall_mm")
    if minimum is None:
        return [_finding("min_wall", "unknown", "min_wall_mm is missing or invalid")]
    from acd.adapters.cad.mechanical import (
        _measured_wall_thickness,  # pyright: ignore[reportPrivateUsage]
    )

    measured = min(
        _measured_wall_thickness(
            solid,
            lane.enclosure.tolerance_mm,
            exclude_small_feature_faces=bool(lane.mechanism_features),
        )
        for solid in solids
    )
    findings = [
        _finding(
            "min_wall",
            "pass" if measured >= minimum else "fail",
            "reloaded enclosure wall thickness against manufacturing minimum",
            measured=round(measured, 3),
            limit=minimum,
        )
    ]
    for feature_id, thickness in _feature_thicknesses(lane.mechanism_features):
        findings.append(
            _finding(
                "feature_min_wall",
                "pass" if thickness >= minimum else "fail",
                "declared mechanism feature thickness against manufacturing minimum",
                measured=round(thickness, 3),
                limit=minimum,
                feature_id=feature_id,
            )
        )
    return findings


def _check_injection(
    lane: MechanicalLane,
    solids: tuple[Any, ...],
    profile: dict[str, object],
) -> list[MechanicalDfmFinding]:
    minimum = _profile_number(profile, "min_wall_mm")
    maximum = _profile_number(profile, "max_wall_mm")
    ratio_limit = _profile_number(profile, "max_thickness_ratio")
    draft_limit = _profile_number(profile, "min_draft_deg")
    min_feature = _profile_number(profile, "min_feature_mm")
    if (
        minimum is None
        or maximum is None
        or ratio_limit is None
        or draft_limit is None
        or min_feature is None
    ):
        return [_finding("injection_profile", "unknown", "injection molding profile is incomplete")]
    findings = _check_min_wall(lane, solids, profile)
    distances = _wall_distances(solids, lane.enclosure.tolerance_mm)
    if not distances:
        return [
            *findings,
            _finding("max_wall", "unknown", "no opposing wall faces were measurable"),
        ]
    minimum_finding = next(
        (item for item in findings if item.rule_id == "min_wall"),
        None,
    )
    minimum_measured = (
        minimum_finding.measured
        if minimum_finding is not None and minimum_finding.measured is not None
        else min(distances)
    )
    maximum_measured = max(distances)
    findings.extend(
        (
            _finding(
                "max_wall",
                "pass" if maximum_measured <= maximum else "fail",
                "maximum measured wall thickness against injection limit",
                measured=round(maximum_measured, 3),
                limit=maximum,
            ),
            _finding(
                "thickness_ratio",
                "pass"
                if maximum_measured / minimum_measured <= ratio_limit
                else "fail",
                "maximum-to-minimum measured wall ratio",
                measured=round(maximum_measured / minimum_measured, 3),
                limit=ratio_limit,
            ),
        )
    )
    parting_plane = profile.get("parting_plane")
    pull_z = 1.0 if parting_plane == "xy_top" else -1.0 if parting_plane == "xy_bottom" else None
    if pull_z is None:
        findings.append(_finding("injection_parting_plane", "unknown", "parting_plane is invalid"))
        return findings
    for face, center in _faces(solids, min_feature):
        geom_type = str(face.geom_type).upper()
        normal = _normal(face)
        if geom_type.endswith("PLANE"):
            draft = math.degrees(math.asin(min(1.0, abs(normal[2]))))
        elif "CYLINDER" in geom_type:
            draft = 0.0 if abs(normal[2]) < 0.99 else 90.0
        else:
            continue
        if draft < draft_limit:
            findings.append(
                _finding(
                    "draft",
                    "fail",
                    "face draft is below the injection molding minimum",
                    measured=round(draft, 3),
                    limit=draft_limit,
                    face_center_mm=center,
                )
            )
    if not any(item.rule_id == "draft" for item in findings):
        findings.append(_finding("draft", "pass", "all significant pull faces meet draft minimum"))
    return findings


def _check_overhang(
    solids: tuple[Any, ...],
    profile: dict[str, object],
    *,
    process: str,
) -> list[MechanicalDfmFinding]:
    limit_name = (
        "max_overhang_deg"
        if process == "fdm"
        else "max_unsupported_overhang_deg"
    )
    limit = _profile_number(profile, limit_name)
    min_feature = _profile_number(profile, "min_feature_mm")
    if limit is None or min_feature is None:
        return [_finding("overhang", "unknown", f"{limit_name} or min_feature_mm is missing")]
    findings: list[MechanicalDfmFinding] = []
    for solid_index, solid in enumerate(solids):
        build_z = 1.0 if solid_index == 0 else -1.0
        for face, center in _faces((solid,), min_feature):
            normal = _normal(face)
            alignment = normal[2] * build_z
            if alignment >= 0:
                continue
            angle = math.degrees(math.acos(min(1.0, max(-1.0, alignment))))
            if angle > limit:
                findings.append(
                    _finding(
                        "overhang",
                        "fail",
                        f"{process} face overhang exceeds the declared limit",
                        measured=round(angle, 3),
                        limit=limit,
                        face_center_mm=center,
                    )
                )
    if not findings:
        findings.append(_finding("overhang", "pass", "all significant faces meet overhang limit"))
    return findings


def _check_sla_drain(
    solids: tuple[Any, ...],
    profile: dict[str, object],
) -> MechanicalDfmFinding:
    required = profile.get("drain_hole_required")
    min_feature = _profile_number(profile, "min_feature_mm")
    if not isinstance(required, bool) or min_feature is None:
        return _finding("drain_hole", "unknown", "SLA drain-hole profile is incomplete")
    if not required:
        return _finding("drain_hole", "pass", "SLA drain hole is not required")
    for solid in solids:
        for face in solid.faces():
            if "CYLINDER" not in str(face.geom_type).upper():
                continue
            cylinder = _cylinder_radius_axis(face)
            center = face.center()
            if (
                cylinder is not None
                and cylinder[0] >= 1.5
                and abs(cylinder[1]) >= 0.99
                and float(center.Z) <= 2.0
                and float(face.area) >= 2 * math.pi * cylinder[0] * 1.5
            ):
                return _finding("drain_hole", "pass", "a qualifying through-hole is present")
    return _finding(
        "drain_hole",
        "fail",
        "SLA profile requires a through-hole of at least 3 mm",
        limit=3.0,
    )


def check_mechanical_dfm(
    lane: MechanicalLane,
    solids: tuple[Any, ...],
) -> tuple[MechanicalDfmFinding, ...]:
    """Evaluate the declared manufacturing process against reloaded solids."""
    process = lane.enclosure.manufacturing_process
    if process is None:
        return ()
    profile = lane.enclosure.dfm_profile
    if profile is None:
        return (_finding("dfm_profile", "unknown", "manufacturing process has no dfm_profile"),)
    try:
        solids = tuple(sorted(solids, key=lambda solid: float(solid.volume), reverse=True))
        findings = _check_min_wall(lane, solids, profile)
        if process == "fdm":
            findings.extend(_check_overhang(solids, profile, process=process))
        elif process == "sla":
            findings.extend(_check_overhang(solids, profile, process=process))
            findings.append(_check_sla_drain(solids, profile))
        elif process == "injection_molding":
            findings = _check_injection(lane, solids, profile)
        else:
            return (_finding("manufacturing_process", "unknown", "unsupported process"),)
        return tuple(findings)
    except Exception as exc:
        return (
            _finding(
                "dfm_evaluation",
                "unknown",
                f"DFM measurement failed: {type(exc).__name__}",
            ),
        )
