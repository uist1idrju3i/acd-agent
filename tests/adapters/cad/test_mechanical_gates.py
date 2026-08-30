"""Mechanical gate positive and fail-closed negative tests."""

from __future__ import annotations

import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from acd.adapters.cad.mechanical import (
    MechanicalGateError,
    board_plane_z,
    build_board_edge_overhang_shape,
    run_mechanical_gates,
)
from acd.adapters.cad.project import project_enclosure
from acd.core.mechanical import extract_mechanical_lane
from acd.schema.design_graph import DesignGraph

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "golden-design-1" / "graph.json"


class KnownProbe:
    is_known = True


class UnknownProbe:
    is_known = False


def _projection(tmp_path: Path):
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    lane = extract_mechanical_lane(graph)
    projection = project_enclosure(
        lane,
        graph_path=FIXTURE,
        out_dir=tmp_path,
        target_revision=graph.revision,
    )
    return lane, projection


def test_mechanical_gates_pass_on_golden_projection(tmp_path: Path) -> None:
    lane, projection = _projection(tmp_path)
    report = run_mechanical_gates(
        step_path=projection.shell_step_path,
        lane=lane,
        kernel_probe=KnownProbe(),
    )
    assert report.interference
    assert report.clearance
    assert report.wall_thickness
    assert report.measured_min_wall_mm == pytest.approx(2.0, abs=0.1)
    assembly_report = run_mechanical_gates(
        step_path=projection.assembly_step_path,
        lane=lane,
        kernel_probe=KnownProbe(),
    )
    assert assembly_report.measured_volume_mm3 == pytest.approx(6695.121404, abs=1e-3)


def test_mechanical_gates_reject_interference(tmp_path: Path) -> None:
    lane, projection = _projection(tmp_path)
    body = replace(lane.component_bodies[0], x_mm=28.0, y_mm=12.5, height_mm=20.0)
    broken = replace(lane, component_bodies=(body, *lane.component_bodies[1:]))
    with pytest.raises(MechanicalGateError, match="interference"):
        run_mechanical_gates(
            step_path=projection.shell_step_path,
            lane=broken,
            kernel_probe=KnownProbe(),
        )


def test_mechanical_gates_reject_historical_undeclared_notch(
    tmp_path: Path,
) -> None:
    lane, _ = _projection(tmp_path / "declared")
    undeclared = replace(lane, board_edge_overhangs=())
    projection = project_enclosure(
        undeclared,
        graph_path=FIXTURE,
        out_dir=tmp_path / "undeclared",
        target_revision=DesignGraph.model_validate_json(
            FIXTURE.read_text(encoding="utf-8")
        ).revision,
    )
    with pytest.raises(MechanicalGateError, match="interference"):
        run_mechanical_gates(
            step_path=projection.shell_step_path,
            lane=lane,
            kernel_probe=KnownProbe(),
        )


def test_projected_enclosure_consumes_overhang_and_fastener_holes(
    tmp_path: Path,
) -> None:
    lane, projection = _projection(tmp_path)
    build123d = importlib.import_module("build123d")
    shell = build123d.import_step(projection.shell_step_path)
    lid = build123d.import_step(projection.lid_step_path)
    overhang = build_board_edge_overhang_shape(
        lane.board_edge_overhangs[0],
        lane.body_for_component("comp.u1"),
        lane.outline.width_mm,
        lane.outline.depth_mm,
        board_plane_z(lane.enclosure),
    )
    assert max(
        0.0 if (intersection := solid & overhang) is None else float(intersection.volume)
        for solid in shell.solids()
    ) == pytest.approx(
        0.0, abs=1e-3
    )
    for hole in lane.outline.mount_holes:
        x = hole.x_mm - lane.outline.width_mm / 2
        y = hole.y_mm - lane.outline.depth_mm / 2
        pilot = build123d.Pos(
            x, y, lane.enclosure.wall_thickness_mm + lane.enclosure.standoff_height_mm / 2
        ) * build123d.Cylinder(
            lane.enclosure.standoff_pilot_hole_diameter_mm / 2,
            lane.enclosure.standoff_height_mm,
        )
        clearance = build123d.Pos(
            x,
            y,
            (
                max(body.height_mm for body in lane.component_bodies)
                + lane.enclosure.internal_clearance_mm
                + lane.enclosure.standoff_height_mm
                + lane.outline.thickness_mm
            )
            + lane.enclosure.lid_fit_gap_mm
            + lane.enclosure.wall_thickness_mm / 2,
        ) * build123d.Cylinder(
            lane.enclosure.lid_screw_hole_diameter_mm / 2,
            lane.enclosure.wall_thickness_mm,
        )
        assert max(
            0.0 if (intersection := solid & pilot) is None else float(intersection.volume)
            for solid in shell.solids()
        ) == pytest.approx(
            0.0, abs=1e-3
        )
        assert max(
            0.0
            if (intersection := solid & clearance) is None
            else float(intersection.volume)
            for solid in lid.solids()
        ) == pytest.approx(
            0.0, abs=1e-3
        )


def test_mechanical_gates_reject_thin_wall(tmp_path: Path) -> None:
    lane, _ = _projection(tmp_path)
    broken = replace(
        lane,
        enclosure=replace(lane.enclosure, wall_thickness_mm=0.5),
    )
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    projection = project_enclosure(
        broken,
        graph_path=FIXTURE,
        out_dir=tmp_path / "thin",
        target_revision=graph.revision,
    )
    with pytest.raises(MechanicalGateError, match="wall_thickness"):
        run_mechanical_gates(
            step_path=projection.shell_step_path,
            lane=broken,
            kernel_probe=KnownProbe(),
        )


def test_mechanical_gates_reject_local_thin_wall(tmp_path: Path) -> None:
    lane, projection = _projection(tmp_path)
    build123d = importlib.import_module("build123d")
    imported = build123d.import_step(projection.shell_step_path)
    shell = max(imported.solids(), key=lambda solid: solid.volume)
    local_cutter = build123d.Pos(17.25, 0, 5) * build123d.Box(1.5, 8, 4)
    thin_shell = shell - local_cutter
    thin_step = tmp_path / "local-thin.step"
    build123d.export_step(thin_shell, thin_step)
    with pytest.raises(MechanicalGateError, match="wall_thickness"):
        run_mechanical_gates(
            step_path=thin_step,
            lane=lane,
            kernel_probe=KnownProbe(),
        )


def test_mechanical_gates_reject_unknown_kernel(tmp_path: Path) -> None:
    lane, projection = _projection(tmp_path)
    with pytest.raises(MechanicalGateError, match="unknown"):
        run_mechanical_gates(
            step_path=projection.shell_step_path,
            lane=lane,
            kernel_probe=UnknownProbe(),
        )
