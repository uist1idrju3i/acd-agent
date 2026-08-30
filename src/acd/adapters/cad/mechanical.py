"""Fail-closed mechanical gates over independently reloaded STEP geometry."""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from acd.core.mechanical import (
    BoardEdgeOverhangView,
    ComponentBodyView,
    EnclosureView,
    MechanicalLane,
)
from acd.core.parallel import PipelineStageRunner


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


@dataclass(frozen=True)
class EnclosureArtifactReport:
    shell_volume_mm3: float
    lid_volume_mm3: float
    assembly_volume_mm3: float
    shell_bbox_mm: tuple[float, float, float, float, float, float]
    lid_bbox_mm: tuple[float, float, float, float, float, float]
    assembly_bbox_mm: tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class _ArtifactMeasurement:
    role: str
    volume_mm3: float
    bbox_mm: tuple[float, float, float, float, float, float]


def _shape_bbox(shape: Any) -> tuple[float, float, float, float, float, float]:
    bbox = shape.bounding_box()
    return (
        float(bbox.min.X),
        float(bbox.min.Y),
        float(bbox.min.Z),
        float(bbox.max.X),
        float(bbox.max.Y),
        float(bbox.max.Z),
    )


def _bboxes_close(
    first: tuple[float, float, float, float, float, float],
    second: tuple[float, float, float, float, float, float],
    *,
    abs_tol: float = 1e-6,
) -> bool:
    return all(
        math.isclose(left, right, rel_tol=0.0, abs_tol=abs_tol)
        for left, right in zip(first, second, strict=True)
    )


def _measure_artifact(path: Path, role: str) -> _ArtifactMeasurement:
    build123d: Any = importlib.import_module("build123d")
    if not path.is_file():
        raise MechanicalGateError(f"{role} STEP is missing: {path}")
    try:
        shape = build123d.import_step(path)
        solids = list(shape.solids())
    except Exception as exc:
        raise MechanicalGateError(f"{role} STEP cannot be reloaded: {path}") from exc
    if role in {"shell", "lid"} and len(solids) != 1:
        raise MechanicalGateError(
            f"{role} STEP must contain exactly one solid, got {len(solids)}"
        )
    if role == "assembly" and len(solids) != 2:
        raise MechanicalGateError(
            f"assembly STEP must contain exactly two solids, got {len(solids)}"
        )
    return _ArtifactMeasurement(
        role=role,
        volume_mm3=float(shape.volume),
        bbox_mm=_shape_bbox(shape),
    )


def measure_enclosure_artifacts(
    *,
    shell_step_path: Path,
    lid_step_path: Path,
    assembly_step_path: Path,
    runner: PipelineStageRunner | None = None,
) -> EnclosureArtifactReport:
    """Reload and validate separated enclosure STEP artifacts."""
    stages = (
        ("shell", partial(_measure_artifact, shell_step_path, "shell")),
        ("lid", partial(_measure_artifact, lid_step_path, "lid")),
        ("assembly", partial(_measure_artifact, assembly_step_path, "assembly")),
    )
    measurements = (
        runner.run_ordered_stages(stages)
        if runner is not None
        else [stage() for _, stage in stages]
    )
    typed_measurements: list[_ArtifactMeasurement] = []
    for item in measurements:
        if not isinstance(item, _ArtifactMeasurement):
            raise MechanicalGateError("enclosure artifact measurements are unknown")
        typed_measurements.append(item)
    shell, lid, assembly = typed_measurements
    shell_bbox = shell.bbox_mm
    lid_bbox = lid.bbox_mm
    assembly_bbox = assembly.bbox_mm
    # GD1 currently uses a stacked shell/lid enclosure; nested designs need a different relation.
    if shell_bbox[5] >= lid_bbox[2]:
        raise MechanicalGateError(
            "current stacked GD1 enclosure requires shell/lid Z separation"
        )
    if not math.isclose(
        assembly.volume_mm3,
        shell.volume_mm3 + lid.volume_mm3,
        rel_tol=0.0,
        abs_tol=1e-4,
    ):
        raise MechanicalGateError(
            "assembly STEP volume does not equal separated shell/lid volumes"
        )
    expected_bbox = (
        min(shell_bbox[0], lid_bbox[0]),
        min(shell_bbox[1], lid_bbox[1]),
        min(shell_bbox[2], lid_bbox[2]),
        max(shell_bbox[3], lid_bbox[3]),
        max(shell_bbox[4], lid_bbox[4]),
        max(shell_bbox[5], lid_bbox[5]),
    )
    if not _bboxes_close(assembly_bbox, expected_bbox):
        raise MechanicalGateError(
            "assembly STEP bbox does not equal separated shell/lid bboxes"
        )
    return EnclosureArtifactReport(
        shell_volume_mm3=shell.volume_mm3,
        lid_volume_mm3=lid.volume_mm3,
        assembly_volume_mm3=assembly.volume_mm3,
        shell_bbox_mm=shell_bbox,
        lid_bbox_mm=lid_bbox,
        assembly_bbox_mm=assembly_bbox,
    )


def build_component_body_shape(
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


def board_plane_z(enclosure: EnclosureView) -> float:
    return enclosure.wall_thickness_mm + enclosure.internal_clearance_mm


def build_board_edge_overhang_shape(
    overhang: BoardEdgeOverhangView,
    body: ComponentBodyView,
    board_width_mm: float,
    board_depth_mm: float,
    board_plane_z_mm: float,
    lateral_margin_mm: float = 0.0,
    top_margin_mm: float = 0.0,
    outward_extension_mm: float = 0.0,
) -> Any:
    build123d: Any = importlib.import_module("build123d")
    if overhang.edge not in {"top", "bottom", "left", "right"}:
        raise ValueError(f"unsupported board edge overhang edge: {overhang.edge}")
    if any(
        not math.isfinite(value) or value < 0
        for value in (lateral_margin_mm, top_margin_mm, outward_extension_mm)
    ):
        raise ValueError("overhang margins must be finite and non-negative")
    x_center = body.x_mm - board_width_mm / 2
    y_center = body.y_mm - board_depth_mm / 2
    if overhang.edge in {"top", "bottom"}:
        x_min = x_center - body.width_mm / 2 - lateral_margin_mm
        x_max = x_center + body.width_mm / 2 + lateral_margin_mm
        y_min = -board_depth_mm / 2 - overhang.overhang_mm
        y_max = -board_depth_mm / 2
        if overhang.edge == "bottom":
            y_min, y_max = board_depth_mm / 2, board_depth_mm / 2 + overhang.overhang_mm
        if overhang.edge == "top":
            y_min -= outward_extension_mm
        else:
            y_max += outward_extension_mm
        return build123d.Pos(
            (x_min + x_max) / 2,
            (y_min + y_max) / 2,
            board_plane_z_mm + (body.height_mm + top_margin_mm) / 2,
        ) * build123d.Box(
            x_max - x_min,
            y_max - y_min,
            body.height_mm + top_margin_mm,
        )
    y_min = y_center - body.depth_mm / 2 - lateral_margin_mm
    y_max = y_center + body.depth_mm / 2 + lateral_margin_mm
    x_min = -board_width_mm / 2 - overhang.overhang_mm
    x_max = -board_width_mm / 2
    if overhang.edge == "right":
        x_min, x_max = board_width_mm / 2, board_width_mm / 2 + overhang.overhang_mm
    if overhang.edge == "left":
        x_min -= outward_extension_mm
    else:
        x_max += outward_extension_mm
    return build123d.Pos(
        (x_min + x_max) / 2,
        (y_min + y_max) / 2,
        board_plane_z_mm + (body.height_mm + top_margin_mm) / 2,
    ) * build123d.Box(
        x_max - x_min,
        y_max - y_min,
        body.height_mm + top_margin_mm,
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
    solids = list(shape.solids())
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

    def check_interference(candidate: Any) -> None:
        nonlocal interference, measured_max_interference_volume
        for solid in solids:
            intersection = solid & candidate
            intersection_volume = 0.0 if intersection is None else float(intersection.volume)
            measured_max_interference_volume = max(
                measured_max_interference_volume, intersection_volume
            )
            if (
                intersection is not None
                and intersection_volume > enclosure.interference_tolerance_mm3
            ):
                interference = False

    for body in lane.component_bodies:
        if body.body_type == "none":
            continue
        body_shape = build_component_body_shape(
            body,
            board_plane_z(enclosure),
            lane.outline.width_mm,
            lane.outline.depth_mm,
        )
        check_interference(body_shape)
        for solid in solids:
            standoff_area = math.pi * enclosure.standoff_radius_mm**2
            wall_faces = [
                face
                for face in solid.faces()
                if face.area > standoff_area and str(face.geom_type).endswith("PLANE")
            ]
            if not wall_faces:
                raise MechanicalGateError(
                    "reloaded STEP solid has no measurable inner wall faces"
                )
            measured_clearance = min(body_shape.distance_to(face) for face in wall_faces)
            measured_min_clearance = min(measured_min_clearance, measured_clearance)
            if measured_clearance < enclosure.internal_clearance_mm - enclosure.tolerance_mm:
                clearance = False

    for overhang in lane.board_edge_overhangs:
        body = lane.body_for_component(overhang.component_id)
        overhang_shape = build_board_edge_overhang_shape(
            overhang,
            body,
            lane.outline.width_mm,
            lane.outline.depth_mm,
            board_plane_z(enclosure),
        )
        check_interference(overhang_shape)

    measured_wall = min(
        _measured_wall_thickness(solid, enclosure.tolerance_mm) for solid in solids
    )
    if measured_min_clearance == float("inf"):
        raise MechanicalGateError("no solid component body has measurable clearance")
    wall_thickness = measured_wall + enclosure.tolerance_mm >= enclosure.min_wall_thickness_mm
    report = MechanicalGateReport(
        kernel_valid=True,
        interference=interference,
        clearance=clearance,
        wall_thickness=wall_thickness,
        measured_volume_mm3=float(sum(solid.volume for solid in solids)),
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
