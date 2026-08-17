"""Fail-closed mechanical gates over independently reloaded STEP geometry."""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acd.core.mechanical import ComponentBodyView, MechanicalLane


class MechanicalGateError(ValueError):
    """Raised when a mechanical gate does not pass."""


@dataclass(frozen=True)
class MechanicalGateReport:
    kernel_valid: bool
    interference: bool
    clearance: bool
    wall_thickness: bool
    measured_volume_mm3: float
    measured_min_wall_mm: float
    measured_min_clearance_mm: float
    measured_max_interference_volume_mm3: float


def _body_shape(
    body: ComponentBodyView, board_thickness_mm: float, board_width_mm: float, board_depth_mm: float
) -> Any:
    build123d: Any = importlib.import_module("build123d")

    z = board_thickness_mm if body.mounting_side == "top" else 0.0
    shape = build123d.Pos(0, 0, z + body.height_mm / 2) * build123d.Box(
        body.width_mm, body.depth_mm, body.height_mm
    )
    return build123d.Pos(body.x_mm - board_width_mm / 2, body.y_mm - board_depth_mm / 2, 0) * (
        build123d.Rot(0, 0, body.rotation_deg) * shape
    )


def _measured_wall_thickness(shape: Any, tolerance_mm: float) -> float:
    """Measure the closest opposing planar faces of the reloaded shell."""
    faces = [
        face
        for face in shape.faces()
        if str(face.geom_type).endswith("PLANE")
    ]
    distances: list[float] = []
    for index, face in enumerate(faces):
        normal = face.normal_at(face.center())
        for other in faces[index + 1 :]:
            other_normal = other.normal_at(other.center())
            dot = (
                normal.X * other_normal.X
                + normal.Y * other_normal.Y
                + normal.Z * other_normal.Z
            )
            if dot >= -0.99:
                continue
            distance = face.distance_to(other)
            if distance > tolerance_mm:
                distances.append(distance)
    if not distances:
        raise MechanicalGateError("reloaded STEP has no measurable opposing wall faces")
    return min(distances)


def run_mechanical_gates(
    *,
    step_path: Path,
    lane: MechanicalLane,
    kernel_probe: Any,
) -> MechanicalGateReport:
    if not kernel_probe.is_known:
        raise MechanicalGateError("CAD kernel probe is unknown or unavailable")

    build123d: Any = importlib.import_module("build123d")

    try:
        shape = build123d.import_step(step_path)
    except Exception as exc:
        raise MechanicalGateError(f"STEP reload failed: {type(exc).__name__}: {exc}") from exc
    solids = shape.solids()
    if not shape.is_valid or not solids or any(not solid.is_valid for solid in solids):
        raise MechanicalGateError("reloaded STEP contains an invalid or open solid")
    shell = max(solids, key=lambda solid: solid.volume)
    if shell.volume <= 0:
        raise MechanicalGateError("reloaded STEP shell has no positive volume")

    enclosure = lane.enclosure
    interference = True
    clearance = True
    measured_min_clearance = float("inf")
    measured_max_interference_volume = 0.0
    for body in lane.component_bodies:
        if body.body_type == "none":
            continue
        body_shape = _body_shape(
            body,
            enclosure.wall_thickness_mm + enclosure.internal_clearance_mm,
            lane.outline.width_mm,
            lane.outline.depth_mm,
        )
        intersection = shell & body_shape
        intersection_volume = 0.0 if intersection is None else float(intersection.volume)
        measured_max_interference_volume = max(
            measured_max_interference_volume, intersection_volume
        )
        if (
            intersection is not None
            and intersection_volume > enclosure.interference_tolerance_mm3
        ):
            interference = False
        standoff_area = math.pi * enclosure.standoff_radius_mm**2
        wall_faces = [
            face
            for face in shell.faces()
            if face.area > standoff_area and str(face.geom_type).endswith("PLANE")
        ]
        if not wall_faces:
            raise MechanicalGateError("reloaded STEP has no measurable inner wall faces")
        measured_clearance = min(body_shape.distance_to(face) for face in wall_faces)
        measured_min_clearance = min(measured_min_clearance, measured_clearance)
        if measured_clearance < enclosure.internal_clearance_mm - enclosure.tolerance_mm:
            clearance = False

    measured_wall = _measured_wall_thickness(shell, enclosure.tolerance_mm)
    if measured_min_clearance == float("inf"):
        raise MechanicalGateError("no solid component body has measurable clearance")
    wall_thickness = measured_wall + enclosure.tolerance_mm >= enclosure.min_wall_thickness_mm
    report = MechanicalGateReport(
        kernel_valid=True,
        interference=interference,
        clearance=clearance,
        wall_thickness=wall_thickness,
        measured_volume_mm3=float(shell.volume),
        measured_min_wall_mm=measured_wall,
        measured_min_clearance_mm=measured_min_clearance,
        measured_max_interference_volume_mm3=measured_max_interference_volume,
    )
    failures = [
        name
        for name, passed in (
            ("interference", interference),
            ("clearance", clearance),
            ("wall_thickness", wall_thickness),
        )
        if not passed
    ]
    if failures:
        raise MechanicalGateError("mechanical gates failed: " + ", ".join(failures))
    return report
