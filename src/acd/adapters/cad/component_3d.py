"""Import and validate opt-in real component solids from KiCad STEP."""

from __future__ import annotations

import hashlib
import importlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from acd.adapters.cad.mechanical import board_plane_z
from acd.core.mechanical.cad_normalize import normalize_step
from acd.core.mechanical.mechanical import ComponentBodyView, MechanicalLane

Component3DStatus = Literal["pass", "fail", "unknown"]


@dataclass(frozen=True)
class Component3DFinding:
    rule_id: str
    status: Component3DStatus
    message: str
    refdes: str | None = None
    body_id: str | None = None


@dataclass(frozen=True)
class ComponentSolid:
    body_id: str
    component_id: str
    refdes: str
    shape: Any
    model_hash: str
    bbox_mm: tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class Component3DImport:
    board_solid: Any | None
    component_solids: tuple[ComponentSolid, ...]
    findings: tuple[Component3DFinding, ...]
    model_hash: str

    @property
    def status(self) -> Component3DStatus:
        if any(item.status == "fail" for item in self.findings):
            return "fail"
        if any(item.status == "unknown" for item in self.findings):
            return "unknown"
        return "pass"


@dataclass(frozen=True)
class AssemblyInterference3DReport:
    status: Component3DStatus
    findings: tuple[Component3DFinding, ...]


def _bbox(shape: Any) -> tuple[float, float, float, float, float, float]:
    box = shape.bounding_box()
    return (
        float(box.min.X),
        float(box.min.Y),
        float(box.min.Z),
        float(box.max.X),
        float(box.max.Y),
        float(box.max.Z),
    )


def _center(box: tuple[float, float, float, float, float, float]) -> tuple[float, float]:
    return ((box[0] + box[3]) / 2, (box[1] + box[4]) / 2)


def _body_box(
    body: ComponentBodyView,
    *,
    board_width_mm: float,
    board_depth_mm: float,
) -> tuple[float, float, float, float]:
    return (
        body.x_mm - board_width_mm / 2 - body.width_mm / 2,
        body.y_mm - board_depth_mm / 2 - body.depth_mm / 2,
        body.x_mm - board_width_mm / 2 + body.width_mm / 2,
        body.y_mm - board_depth_mm / 2 + body.depth_mm / 2,
    )


def _match_body(
    shape: Any,
    bodies: tuple[ComponentBodyView, ...],
    used: set[str],
    *,
    board_width_mm: float,
    board_depth_mm: float,
) -> ComponentBodyView | None:
    box = _bbox(shape)
    center = _center(box)
    candidates: list[tuple[float, ComponentBodyView]] = []
    for body in bodies:
        if body.body_type == "none" or body.node_id in used:
            continue
        expected = _body_box(
            body,
            board_width_mm=board_width_mm,
            board_depth_mm=board_depth_mm,
        )
        dx = center[0] - (expected[0] + expected[2]) / 2
        dy = center[1] - (expected[1] + expected[3]) / 2
        distance = math.hypot(dx, dy)
        tolerance = max(body.width_mm, body.depth_mm, 1.0)
        if distance <= tolerance:
            candidates.append((distance, body))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (round(item[0], 6), item[1].node_id))[1]


def import_component_step(
    step_path: Path,
    lane: MechanicalLane,
    *,
    refdes_by_component_id: Mapping[str, str],
) -> Component3DImport:
    """Import a STEP assembly and deterministically match solids to graph bodies."""
    model_hash = "unknown"
    try:
        model_hash = "sha256:" + hashlib.sha256(normalize_step(step_path.read_bytes())).hexdigest()
        build123d = importlib.import_module("build123d")
        shape = build123d.import_step(step_path)
        solids = sorted(
            list(shape.solids()),
            key=lambda item: (_bbox(item), round(float(item.volume), 6)),
        )
        if not solids:
            raise ValueError("component STEP contains no solids")
        board_z = board_plane_z(lane.enclosure)
        board_candidates = [
            solid
            for solid in solids
            if abs(_bbox(solid)[2] - board_z) <= 1.0
            and (_bbox(solid)[5] - _bbox(solid)[2]) <= lane.outline.thickness_mm * 2
        ]
        board = max(board_candidates or solids, key=lambda item: float(item.volume))
        used: set[str] = set()
        matched: list[ComponentSolid] = []
        findings: list[Component3DFinding] = []
        bodies = tuple(sorted(lane.component_bodies, key=lambda item: item.node_id))
        for solid in solids:
            if solid is board:
                continue
            body = _match_body(
                solid,
                bodies,
                used,
                board_width_mm=lane.outline.width_mm,
                board_depth_mm=lane.outline.depth_mm,
            )
            if body is None:
                findings.append(
                    Component3DFinding(
                        rule_id="unmatched_solid",
                        status="unknown",
                        message="imported solid did not match a declared component body",
                    )
                )
                continue
            used.add(body.node_id)
            matched.append(
                ComponentSolid(
                    body_id=body.node_id,
                    component_id=body.component_id,
                    refdes=refdes_by_component_id.get(body.component_id, body.component_id),
                    shape=solid,
                    model_hash=model_hash,
                    bbox_mm=_bbox(solid),
                )
            )
        for body in bodies:
            if body.node_id not in used:
                findings.append(
                    Component3DFinding(
                        rule_id="model_missing",
                        status="unknown",
                        message="declared component body has no matched KiCad solid",
                        refdes=refdes_by_component_id.get(body.component_id, body.component_id),
                        body_id=body.node_id,
                    )
                )
        return Component3DImport(board, tuple(matched), tuple(findings), model_hash)
    except (OSError, UnicodeError, ValueError, RuntimeError, ImportError) as exc:
        return Component3DImport(
            None,
            (),
            (
                Component3DFinding(
                    rule_id="component_step_import",
                    status="unknown",
                    message=f"component STEP import failed: {exc}",
                ),
            ),
            model_hash,
        )


def _status(findings: list[Component3DFinding]) -> Component3DStatus:
    if any(item.status == "fail" for item in findings):
        return "fail"
    if any(item.status == "unknown" for item in findings):
        return "unknown"
    return "pass"


def check_assembly_interference_3d(
    imported: Component3DImport,
    *,
    shell: Any,
    lid: Any,
    lane: MechanicalLane,
) -> AssemblyInterference3DReport:
    """Check real component solids against enclosure and declared envelopes."""
    findings = list(imported.findings)
    tolerance = lane.enclosure.interference_tolerance_mm3
    for component in imported.component_solids:
        for role, enclosure in (("shell", shell), ("lid", lid)):
            try:
                intersection = component.shape & enclosure
                volume = 0.0 if intersection is None else float(intersection.volume)
                if volume > tolerance:
                    findings.append(
                        Component3DFinding(
                            rule_id="enclosure_interference",
                            status="fail",
                            message=(
                                f"{role} intersection volume {volume:.3f} mm3 "
                                "exceeds tolerance"
                            ),
                            refdes=component.refdes,
                            body_id=component.body_id,
                        )
                    )
                clearance = float(component.shape.distance_to(enclosure))
                if clearance < lane.enclosure.internal_clearance_mm:
                    findings.append(
                        Component3DFinding(
                            rule_id="internal_clearance",
                            status="fail",
                            message=(
                                f"{role} clearance {clearance:.3f} mm is below "
                                f"{lane.enclosure.internal_clearance_mm:.3f} mm"
                            ),
                            refdes=component.refdes,
                            body_id=component.body_id,
                        )
                    )
            except Exception as exc:
                findings.append(
                    Component3DFinding(
                        rule_id="enclosure_interference",
                        status="unknown",
                        message=f"{role} boolean intersection failed: {exc}",
                        refdes=component.refdes,
                        body_id=component.body_id,
                    )
                )
        try:
            body = lane.body_for_component(component.component_id)
            expected = _body_box(
                body,
                board_width_mm=lane.outline.width_mm,
                board_depth_mm=lane.outline.depth_mm,
            )
            actual = component.bbox_mm
            plane_z = board_plane_z(lane.enclosure)
            expected_z = (
                (
                    plane_z + lane.outline.thickness_mm,
                    plane_z + lane.outline.thickness_mm + body.height_mm,
                )
                if body.mounting_side == "top"
                else (plane_z - body.height_mm, plane_z)
            )
            exceeds = (
                expected[0] - lane.enclosure.tolerance_mm > actual[0]
                or actual[3] > expected[2] + lane.enclosure.tolerance_mm
                or expected[1] - lane.enclosure.tolerance_mm > actual[1]
                or actual[4] > expected[3] + lane.enclosure.tolerance_mm
                or expected_z[0] - lane.enclosure.tolerance_mm > actual[2]
                or actual[5] > expected_z[1] + lane.enclosure.tolerance_mm
            )
            if exceeds:
                findings.append(
                    Component3DFinding(
                        rule_id="declared_envelope_exceeded",
                        status="fail",
                        message="KiCad model exceeds the declared component envelope",
                        refdes=component.refdes,
                        body_id=component.body_id,
                    )
                )
        except (KeyError, ValueError) as exc:
            findings.append(
                Component3DFinding(
                    rule_id="declared_envelope_exceeded",
                    status="unknown",
                    message=f"declared envelope comparison failed: {exc}",
                    refdes=component.refdes,
                    body_id=component.body_id,
                )
            )
    return AssemblyInterference3DReport(_status(findings), tuple(findings))
