"""Fail-closed mechanical gates over independently reloaded STEP geometry."""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acd_core.mechanical import ComponentBodyView, MechanicalLane


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


def _measured_wall_thickness(
    shape: Any, lane: MechanicalLane, outer_width: float, outer_depth: float, height: float
) -> float:
    enclosure = lane.enclosure
    standoff_volume = (
        len(lane.outline.mount_holes)
        * math.pi
        * enclosure.standoff_radius_mm**2
        * enclosure.standoff_height_mm
    )
    opening_volume = sum(
        (opening.width_mm + 2 * opening.margin_mm)
        * (opening.height_mm + 2 * opening.margin_mm)
        * enclosure.wall_thickness_mm
        for opening in lane.connector_openings
    )
    shell_volume = shape.volume - standoff_volume + opening_volume

    def volume_for_wall(wall: float) -> float:
        return outer_width * outer_depth * height - (
            outer_width - 2 * wall
        ) * (outer_depth - 2 * wall) * (height - wall)

    low = 0.001
    high = min(outer_width, outer_depth, height) / 2 - 0.001
    for _ in range(60):
        middle = (low + high) / 2
        if volume_for_wall(middle) < shell_volume:
            low = middle
        else:
            high = middle
    return (low + high) / 2


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

    bbox = shell.bounding_box()
    outer_width = bbox.max.X - bbox.min.X
    outer_depth = bbox.max.Y - bbox.min.Y
    height = bbox.max.Z - bbox.min.Z
    enclosure = lane.enclosure
    inner_min_x = bbox.min.X + enclosure.wall_thickness_mm
    inner_max_x = bbox.max.X - enclosure.wall_thickness_mm
    inner_min_y = bbox.min.Y + enclosure.wall_thickness_mm
    inner_max_y = bbox.max.Y - enclosure.wall_thickness_mm
    interference = True
    clearance = True
    for body in lane.component_bodies:
        body_shape = _body_shape(
            body,
            enclosure.wall_thickness_mm + enclosure.internal_clearance_mm,
            lane.outline.width_mm,
            lane.outline.depth_mm,
        )
        intersection = shell & body_shape
        if intersection is not None and intersection.volume > enclosure.tolerance_mm:
            interference = False
        body_box = body_shape.bounding_box()
        distances = (
            body_box.min.X - inner_min_x,
            inner_max_x - body_box.max.X,
            body_box.min.Y - inner_min_y,
            inner_max_y - body_box.max.Y,
            body_box.min.Z - enclosure.wall_thickness_mm,
            height - enclosure.wall_thickness_mm - body_box.max.Z,
        )
        if min(distances) < enclosure.internal_clearance_mm - enclosure.tolerance_mm:
            clearance = False

    measured_wall = _measured_wall_thickness(shell, lane, outer_width, outer_depth, height)
    wall_thickness = measured_wall + enclosure.tolerance_mm >= enclosure.min_wall_thickness_mm
    report = MechanicalGateReport(
        kernel_valid=True,
        interference=interference,
        clearance=clearance,
        wall_thickness=wall_thickness,
        measured_volume_mm3=float(shell.volume),
        measured_min_wall_mm=measured_wall,
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
