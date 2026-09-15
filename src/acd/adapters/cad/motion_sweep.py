"""Deterministic discrete-pose motion interference checks."""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from typing import Any

from acd.adapters.cad.mechanical import (
    board_plane_z,
    build_component_body_shape,
)
from acd.adapters.cad.mechanisms import build_mechanism_feature
from acd.core.mechanical import MechanicalLane, MechanismFeatureView


@dataclass(frozen=True)
class MotionSweepFinding:
    feature_id: str
    poses_checked: int
    worst_pose: float | None
    worst_interference_mm3: float
    colliding_ids: tuple[str, ...]
    status: str


def _bd() -> Any:
    return importlib.import_module("build123d")


def _pose_values(limit: float, step: float) -> tuple[float, ...]:
    count = math.floor(limit / step)
    values = [round(index * step, 9) for index in range(count + 1)]
    if not math.isclose(values[-1], limit, rel_tol=0.0, abs_tol=1e-9):
        values.append(limit)
    return tuple(values)


def _offset(shape: Any, margin: float) -> Any:
    if margin <= 0:
        return shape
    try:
        offset = shape.offset_3d(None, margin)
        if not offset.solids() and offset.volume > 0:
            return _bd().Solid(offset)
        return offset
    except Exception:
        solids = tuple(solid.offset_3d(None, margin) for solid in shape.solids())
        if not solids:
            raise
        return _bd().Compound(solids)


def _hinge_pose(
    lid: Any,
    feature: MechanismFeatureView,
    angle_deg: float,
    lane: MechanicalLane,
) -> Any:
    bd = _bd()
    anchor = (
        feature.x_mm - lane.outline.width_mm / 2,
        feature.y_mm - lane.outline.depth_mm / 2,
        board_plane_z(lane.enclosure) + lane.outline.thickness_mm,
    )
    return (
        bd.Pos(*anchor)
        * bd.Rot(angle_deg, 0, 0)
        * bd.Pos(-anchor[0], -anchor[1], -anchor[2])
        * lid
    )


def _button_pose(
    feature: MechanismFeatureView,
    travel_mm: float,
) -> Any:
    bd = _bd()
    moving = bd.Pos(0, 0, travel_mm) * build_mechanism_feature(feature)
    clearance = feature.dimensions["travel_clearance_mm"]
    if clearance <= 0:
        return moving
    envelope = bd.Pos(
        feature.x_mm,
        feature.y_mm,
        feature.dimensions["web_thickness_mm"]
        + feature.dimensions["stroke_mm"]
        + clearance / 2
        + travel_mm,
    ) * bd.Cylinder(feature.dimensions["cap_diameter_mm"] / 2, clearance)
    return bd.Compound([moving, envelope])


def _board_shape(lane: MechanicalLane) -> Any:
    bd = _bd()
    z = board_plane_z(lane.enclosure)
    board = bd.Pos(
        0,
        0,
        z + lane.outline.thickness_mm / 2,
    ) * bd.Box(
        lane.outline.width_mm,
        lane.outline.depth_mm,
        lane.outline.thickness_mm,
    )
    for hole in lane.outline.mount_holes:
        board -= bd.Pos(
            hole.x_mm - lane.outline.width_mm / 2,
            hole.y_mm - lane.outline.depth_mm / 2,
            z,
        ) * bd.Cylinder(hole.diameter_mm / 2, lane.outline.thickness_mm)
    return board


def _static_bodies(
    lane: MechanicalLane,
    shell: Any,
    lid: Any,
    feature: MechanismFeatureView,
) -> tuple[tuple[str, Any], ...]:
    bodies: list[tuple[str, Any]] = [("enclosure.shell", shell)]
    if feature.feature_type != "hinge":
        bodies.append(("enclosure.lid", lid))
    bodies.append(("board.outline", _board_shape(lane)))
    plane_z = board_plane_z(lane.enclosure)
    for body in lane.component_bodies:
        if body.body_type != "none":
            bodies.append(
                (
                    body.node_id,
                    build_component_body_shape(
                        body,
                        plane_z,
                        lane.outline.width_mm,
                        lane.outline.depth_mm,
                    ),
                )
            )
    for other in lane.mechanism_features:
        if other.node_id != feature.node_id:
            bodies.append((other.node_id, build_mechanism_feature(other)))
    return tuple(bodies)


def check_motion_sweep(
    lane: MechanicalLane,
    shell: Any,
    lid: Any,
) -> tuple[MotionSweepFinding, ...]:
    """Check hinge and button discrete poses against static CAD bodies.

    The union of sampled poses under-approximates the continuous sweep.  Each
    moving solid is conservatively offset by its declared sweep margin.
    """
    findings: list[MotionSweepFinding] = []
    for feature in lane.mechanism_features:
        motion = feature.motion_check
        if motion is None:
            continue
        if feature.feature_type == "hinge":
            assert motion.step_deg is not None
            poses = _pose_values(feature.dimensions["swing_deg"], motion.step_deg)
        elif feature.feature_type == "button":
            assert motion.step_mm is not None
            poses = _pose_values(feature.dimensions["stroke_mm"], motion.step_mm)
        else:
            continue
        static_bodies = _static_bodies(lane, shell, lid, feature)
        worst = 0.0
        worst_pose: float | None = None
        colliding: set[str] = set()
        try:
            for pose in poses:
                moving = (
                    _hinge_pose(lid, feature, pose, lane)
                    if feature.feature_type == "hinge"
                    else _button_pose(feature, pose)
                )
                moving = _offset(moving, motion.sweep_margin_mm)
                if not moving.is_valid or moving.volume <= 0:
                    raise ValueError("moving motion solid is invalid")
                pose_collisions: set[str] = set()
                pose_worst = 0.0
                for body_id, static in static_bodies:
                    if body_id in motion.allowed_contact_ids:
                        continue
                    intersection = static & moving
                    volume = 0.0 if intersection is None else float(intersection.volume)
                    if volume > pose_worst:
                        pose_worst = volume
                    if volume > lane.enclosure.interference_tolerance_mm3:
                        pose_collisions.add(body_id)
                if pose_worst > worst:
                    worst = pose_worst
                    worst_pose = pose
                colliding.update(pose_collisions)
            status = "fail" if colliding else "pass"
        except Exception:
            findings.append(
                MotionSweepFinding(
                    feature_id=feature.node_id,
                    poses_checked=len(poses),
                    worst_pose=worst_pose,
                    worst_interference_mm3=round(worst, 6),
                    colliding_ids=tuple(sorted(colliding)),
                    status="unknown",
                )
            )
            continue
        findings.append(
            MotionSweepFinding(
                feature_id=feature.node_id,
                poses_checked=len(poses),
                worst_pose=worst_pose,
                worst_interference_mm3=round(worst, 6),
                colliding_ids=tuple(sorted(colliding)),
                status=status,
            )
        )
    return tuple(findings)
