"""Build123d enclosure projection without gate judgment."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acd.core.cad_normalize import normalize_3mf, normalize_step
from acd.core.mechanical import MechanicalLane
from acd.core.process import ToolRun, run_in_process


@dataclass(frozen=True)
class CadProjection:
    shell_step_path: Path
    lid_step_path: Path
    assembly_step_path: Path
    model_path: Path
    artifact_manifest_path: Path
    envelope: Any

    @property
    def step_path(self) -> Path:
        """Return the shell STEP for compatibility with mechanical gates."""
        return self.shell_step_path


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
    return shell, lid


def project_enclosure(
    lane: MechanicalLane,
    *,
    graph_path: Path,
    out_dir: Path,
    target_revision: str,
) -> CadProjection:
    out_dir.mkdir(parents=True, exist_ok=True)
    shell_step_path = out_dir / "enclosure-shell.step"
    lid_step_path = out_dir / "enclosure-lid.step"
    assembly_step_path = out_dir / "enclosure-assembly.step"
    model_path = out_dir / "enclosure.3mf"
    artifact_manifest_path = out_dir / "enclosure-artifacts.json"
    envelope_path = out_dir / "envelope-cad.json"
    config = json.dumps(
        {
            "adapter_revision": "p3-5-v3",
            "format": "step-parts+assembly+3mf+manifest",
            "linear_deflection": 0.01,
            "angular_deflection": 0.1,
            "part_number": "gd1-enclosure",
        },
        sort_keys=True,
    ).encode()

    def runner() -> None:
        build123d: Any = importlib.import_module("build123d")

        shell, lid = _build_shapes(lane)
        build123d.export_step(shell, shell_step_path)
        build123d.export_step(lid, lid_step_path)
        build123d.export_step(shell + lid, assembly_step_path)
        mesher = build123d.Mesher()
        mesher.add_shape(
            shell,
            linear_deflection=0.01,
            angular_deflection=0.1,
            part_number="gd1-enclosure-shell",
        )
        mesher.add_shape(
            lid,
            linear_deflection=0.01,
            angular_deflection=0.1,
            part_number="gd1-enclosure-lid",
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
        if path.suffix == ".json":
            return data
        raise ValueError(f"unsupported CAD output: {path}")

    run: ToolRun = run_in_process(
        tool_name="cad-kernel",
        tool_version=cad_tool_version(),
        format_version="STEP parts+assembly+3MF+manifest",
        input_paths=[graph_path],
        output_paths=[
            shell_step_path,
            lid_step_path,
            assembly_step_path,
            model_path,
            artifact_manifest_path,
        ],
        envelope_path=envelope_path,
        target_revision=target_revision,
        measurement_conditions=(
            "build123d box shell/lid, independent STEP parts, assembly STEP, "
            "Mesher 3MF, normalized artifact manifest and output hash"
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
        artifact_manifest_path=artifact_manifest_path,
        envelope=run.envelope,
    )


def _normalized_sha256(path: Path) -> str:
    normalized = normalize_step(path.read_bytes()) if path.suffix == ".step" else normalize_3mf(
        path.read_bytes()
    )
    return "sha256:" + hashlib.sha256(normalized).hexdigest()
