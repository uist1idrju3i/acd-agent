"""Build123d enclosure projection without gate judgment."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acd.adapters.cad.mechanical import (
    board_plane_z,
    build_board_edge_overhang_shape,
)
from acd.core.cad_normalize import normalize_3mf, normalize_step, normalize_stl
from acd.core.mechanical import MechanicalLane
from acd.core.naming import artifact_prefix
from acd.core.process import ToolRun, run_in_process
from acd.schema.design_graph import DesignGraph


@dataclass(frozen=True)
class CadProjection:
    shell_step_path: Path
    lid_step_path: Path
    assembly_step_path: Path
    model_path: Path
    mesh_stl_path: Path
    artifact_manifest_path: Path
    envelope: Any


def cad_tool_version() -> str:
    build123d_version = importlib.metadata.version("build123d")
    ocp_version = importlib.metadata.version("cadquery-ocp")
    return f"build123d={build123d_version};cadquery-ocp={ocp_version}"


def _build_shapes(lane: MechanicalLane) -> tuple[Any, Any]:
    build123d: Any = importlib.import_module("build123d")

    outline = lane.outline
    enclosure = lane.enclosure
    outer_width = (
        outline.width_mm
        + 2 * enclosure.internal_clearance_mm
        + 2 * enclosure.wall_thickness_mm
    )
    outer_depth = (
        outline.depth_mm
        + 2 * enclosure.internal_clearance_mm
        + 2 * enclosure.wall_thickness_mm
    )
    shell_height = (
        max((body.height_mm for body in lane.component_bodies), default=0.0)
        + enclosure.internal_clearance_mm
        + enclosure.standoff_height_mm
        + outline.thickness_mm
    )
    inner_width = outer_width - 2 * enclosure.wall_thickness_mm
    inner_depth = outer_depth - 2 * enclosure.wall_thickness_mm
    outer = build123d.Pos(0, 0, shell_height / 2) * build123d.Box(
        outer_width, outer_depth, shell_height
    )
    inner = build123d.Pos(0, 0, enclosure.wall_thickness_mm + shell_height / 2) * build123d.Box(
        inner_width, inner_depth, shell_height
    )
    shell = outer - inner

    for hole in outline.mount_holes:
        x = hole.x_mm - outline.width_mm / 2
        y = hole.y_mm - outline.depth_mm / 2
        standoff = build123d.Pos(
            x, y, enclosure.wall_thickness_mm + enclosure.standoff_height_mm / 2
        ) * build123d.Cylinder(enclosure.standoff_radius_mm, enclosure.standoff_height_mm)
        shell = shell + standoff
        pilot = build123d.Pos(
            x,
            y,
            enclosure.wall_thickness_mm + enclosure.standoff_height_mm / 2,
        ) * build123d.Cylinder(
            enclosure.standoff_pilot_hole_diameter_mm / 2,
            enclosure.standoff_height_mm,
        )
        shell = shell - pilot

    for overhang in lane.board_edge_overhangs:
        body = lane.body_for_component(overhang.component_id)
        cutter = build_board_edge_overhang_shape(
            overhang,
            body,
            outline.width_mm,
            outline.depth_mm,
            board_plane_z(enclosure),
            lateral_margin_mm=enclosure.internal_clearance_mm,
            top_margin_mm=enclosure.internal_clearance_mm,
            outward_extension_mm=enclosure.wall_thickness_mm * 3,
        )
        shell = shell - cutter

    for opening in lane.connector_openings:
        if opening.face != "front":
            raise ValueError(f"unsupported connector opening face: {opening.face}")
        x = opening.center_x_mm - outline.width_mm / 2
        z = opening.center_y_mm
        cutter = build123d.Pos(x, -outer_depth / 2, z) * build123d.Box(
            opening.width_mm + 2 * opening.margin_mm,
            enclosure.wall_thickness_mm * 3,
            opening.height_mm + 2 * opening.margin_mm,
        )
        shell = shell - cutter

    lid = build123d.Pos(
        0,
        0,
        shell_height + enclosure.lid_fit_gap_mm + enclosure.wall_thickness_mm / 2,
    ) * build123d.Box(outer_width, outer_depth, enclosure.wall_thickness_mm)
    for hole in outline.mount_holes:
        x = hole.x_mm - outline.width_mm / 2
        y = hole.y_mm - outline.depth_mm / 2
        cutter = build123d.Pos(
            x,
            y,
            shell_height
            + enclosure.lid_fit_gap_mm
            + enclosure.wall_thickness_mm / 2,
        ) * build123d.Cylinder(
            enclosure.lid_screw_hole_diameter_mm / 2,
            enclosure.wall_thickness_mm,
        )
        lid = lid - cutter
    return shell, lid


def project_enclosure(
    lane: MechanicalLane,
    *,
    graph_path: Path,
    out_dir: Path,
    target_revision: str,
    graph_id: str | None = None,
) -> CadProjection:
    out_dir.mkdir(parents=True, exist_ok=True)
    if graph_id is None:
        try:
            graph_id = DesignGraph.model_validate_json(
                graph_path.read_text(encoding="utf-8")
            ).graph_id
        except (OSError, ValueError) as exc:
            raise ValueError("enclosure graph_id is unknown (fail-closed)") from exc
    prefix = artifact_prefix(graph_id)
    shell_step_path = out_dir / "enclosure-shell.step"
    lid_step_path = out_dir / "enclosure-lid.step"
    assembly_step_path = out_dir / "enclosure-assembly.step"
    model_path = out_dir / "enclosure.3mf"
    mesh_stl_path = out_dir / "enclosure.stl"
    artifact_manifest_path = out_dir / "enclosure-artifacts.json"
    envelope_path = out_dir / "envelope-cad.json"
    config = json.dumps(
        {
            "adapter_revision": "p3-5-v5",
            "format": "step-parts+assembly+3mf+stl+manifest",
            "linear_deflection": 0.01,
            "angular_deflection": 0.1,
            "part_number": f"{prefix}-enclosure",
        },
        sort_keys=True,
    ).encode()

    def runner() -> None:
        build123d: Any = importlib.import_module("build123d")

        shell, lid = _build_shapes(lane)
        build123d.export_step(shell, shell_step_path)
        build123d.export_step(lid, lid_step_path)
        build123d.export_step(shell + lid, assembly_step_path)
        build123d.export_stl(
            shell + lid,
            mesh_stl_path,
            tolerance=0.01,
            angular_tolerance=0.1,
            ascii_format=True,
        )
        mesher = build123d.Mesher()
        mesher.add_shape(
            shell,
            linear_deflection=0.01,
            angular_deflection=0.1,
            part_number=f"{prefix}-enclosure-shell",
        )
        mesher.add_shape(
            lid,
            linear_deflection=0.01,
            angular_deflection=0.1,
            part_number=f"{prefix}-enclosure-lid",
        )
        mesher.write(model_path)
        manifest = {
            "schema_version": 1,
            "artifacts": [
                {
                    "path": shell_step_path.name,
                    "role": "enclosure_shell",
                    "format": "STEP",
                    "normalized_sha256": _normalized_sha256(shell_step_path),
                },
                {
                    "path": lid_step_path.name,
                    "role": "enclosure_lid",
                    "format": "STEP",
                    "normalized_sha256": _normalized_sha256(lid_step_path),
                },
                {
                    "path": assembly_step_path.name,
                    "role": "enclosure_assembly",
                    "format": "STEP",
                    "normalized_sha256": _normalized_sha256(assembly_step_path),
                },
                {
                    "path": model_path.name,
                    "role": "enclosure_model",
                    "format": "3MF",
                    "normalized_sha256": _normalized_sha256(model_path),
                },
                {
                    "path": mesh_stl_path.name,
                    "role": "enclosure_mesh_stl",
                    "format": "STL",
                    "normalized_sha256": _normalized_sha256(mesh_stl_path),
                },
            ],
        }
        artifact_manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def normalize(path: Path) -> bytes:
        data = path.read_bytes()
        if path.suffix == ".step":
            return normalize_step(data)
        if path.suffix == ".3mf":
            return normalize_3mf(data)
        if path.suffix == ".stl":
            return normalize_stl(data)
        if path.suffix == ".json":
            return data
        raise ValueError(f"unsupported CAD output: {path}")

    run: ToolRun = run_in_process(
        tool_name="cad-kernel",
        tool_version=cad_tool_version(),
        format_version="STEP parts+assembly+3MF+STL+manifest",
        input_paths=[graph_path],
        output_paths=[
            shell_step_path,
            lid_step_path,
            assembly_step_path,
            model_path,
            mesh_stl_path,
            artifact_manifest_path,
        ],
        envelope_path=envelope_path,
        target_revision=target_revision,
        measurement_conditions=(
            "build123d box shell/lid, independent STEP parts, assembly STEP, "
            "antenna overhang cutout, standoff pilot holes, lid screw holes, "
            "Mesher 3MF, ASCII STL mesh export, normalized artifact manifest "
            "and output hash"
        ),
        runner=runner,
        config=config,
        output_normalizer=normalize,
    )
    return CadProjection(
        shell_step_path=shell_step_path,
        lid_step_path=lid_step_path,
        assembly_step_path=assembly_step_path,
        model_path=model_path,
        mesh_stl_path=mesh_stl_path,
        artifact_manifest_path=artifact_manifest_path,
        envelope=run.envelope,
    )


def _normalized_sha256(path: Path) -> str:
    if path.suffix == ".step":
        normalized = normalize_step(path.read_bytes())
    elif path.suffix == ".3mf":
        normalized = normalize_3mf(path.read_bytes())
    elif path.suffix == ".stl":
        normalized = normalize_stl(path.read_bytes())
    else:
        raise ValueError(f"unsupported CAD output: {path}")
    return "sha256:" + hashlib.sha256(normalized).hexdigest()
