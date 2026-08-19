"""Build123d mechanical visual projection renderer."""

from __future__ import annotations

import importlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from acd.adapters.cad.mechanical import (
    MechanicalGateError,
    MechanicalGateReport,
    build_component_body_shape,
)
from acd.adapters.cad.project import CadProjection, cad_tool_version
from acd.core.cad_normalize import normalize_step
from acd.core.mechanical import MechanicalLane
from acd.core.process import ExternalToolError, sha256_bytes
from acd.core.visual_projection import measure_svg_resolution
from acd.schema.visual_projection import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionSet,
    VisualProjectionType,
    VisualRegenerationCheck,
    VisualRendererProvenance,
    VisualResolution,
)

CAD_SVG_NORMALIZATION_RULE_ID = "build123d-svg-v1"
CAD_SVG_NORMALIZATION_RULE_DESCRIPTION = (
    "Build123d ExportSVG with millimeter units, fixed precision, zero margin, "
    "and fit_to_stroke disabled."
)


class MechanicalVisualProjectionError(ExternalToolError):
    """Raised when a mechanical visual projection cannot be trusted."""


def _load_build123d() -> Any:
    try:
        return importlib.import_module("build123d")
    except (ImportError, ModuleNotFoundError) as exc:
        raise MechanicalVisualProjectionError(
            "build123d renderer is unavailable"
        ) from exc


def _relative_path(path: Path, base_dir: Path, field_name: str) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(base_dir.resolve()).as_posix()
    except ValueError as exc:
        raise MechanicalVisualProjectionError(
            f"{field_name} must stay within the output directory"
        ) from exc


def _normalized_step_hash(path: Path) -> str:
    try:
        return sha256_bytes(normalize_step(path.read_bytes()))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise MechanicalVisualProjectionError(
            f"assembly STEP cannot be normalized: {path}"
        ) from exc


def _assembly_input(
    projection: CadProjection,
    *,
    base_dir: Path,
    target_revision: str,
) -> VisualProjectionInput:
    path = projection.assembly_step_path
    if not path.is_file():
        raise MechanicalVisualProjectionError(f"assembly STEP is missing: {path}")
    if projection.envelope.target_revision != target_revision:
        raise MechanicalVisualProjectionError("assembly STEP revision does not match target")
    manifest_path = projection.artifact_manifest_path
    if not manifest_path.is_file():
        raise MechanicalVisualProjectionError("CAD artifact manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifacts = manifest["artifacts"]
        assembly = next(
            item for item in artifacts if item["role"] == "enclosure_assembly"
        )
        expected_hash = assembly["normalized_sha256"]
    except (KeyError, StopIteration, TypeError, json.JSONDecodeError) as exc:
        raise MechanicalVisualProjectionError(
            "CAD artifact manifest has no valid assembly entry"
        ) from exc
    actual_hash = _normalized_step_hash(path)
    if actual_hash != expected_hash:
        raise MechanicalVisualProjectionError("assembly STEP input hash mismatch")
    return VisualProjectionInput(
        path=_relative_path(path, base_dir, "assembly STEP"),
        content_hash=actual_hash,
    )


def _section_edges(shape: Any, offset_mm: float, build123d: Any) -> list[Any]:
    try:
        section = shape & build123d.Plane.XY.offset(offset_mm)
        edges = list(section.edges())
    except (TypeError, ValueError, RuntimeError) as exc:
        raise MechanicalVisualProjectionError(
            "section plane could not be evaluated"
        ) from exc
    if not edges:
        raise MechanicalVisualProjectionError(
            "section plane does not intersect the authoritative shape"
        )
    translation = build123d.Location((0, 0, -offset_mm))
    return [edge.moved(translation) for edge in edges]


def _write_svg(
    *,
    output_path: Path,
    layers: list[tuple[str, list[Any], tuple[int, int, int] | None]],
    build123d: Any,
) -> None:
    exporter = build123d.ExportSVG(
        unit=build123d.Unit.MM,
        margin=0,
        fit_to_stroke=False,
        precision=6,
    )
    for name, shapes, fill_color in layers:
        exporter.add_layer(name, fill_color=fill_color, line_color=(180, 0, 0))
        if shapes:
            exporter.add_shape(shapes, layer=name)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        exporter.write(output_path)
    except MechanicalVisualProjectionError:
        raise
    except (OSError, ValueError) as exc:
        raise MechanicalVisualProjectionError(
            f"mechanical SVG could not be written: {output_path}"
        ) from exc


def _image_hash(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise MechanicalVisualProjectionError(
            f"mechanical SVG could not be read: {path}"
        ) from exc


def _expected_view_dimensions(lane: MechanicalLane) -> tuple[float, float]:
    return (
        lane.outline.width_mm
        + 2 * lane.enclosure.internal_clearance_mm
        + 2 * lane.enclosure.wall_thickness_mm,
        lane.outline.depth_mm
        + 2 * lane.enclosure.internal_clearance_mm
        + 2 * lane.enclosure.wall_thickness_mm,
    )


def _validate_view_dimensions(
    record: VisualProjectionRecord,
    lane: MechanicalLane,
) -> None:
    expected_width, expected_height = _expected_view_dimensions(lane)
    width = record.resolution.view_box[2]
    height = record.resolution.view_box[3]
    if not math.isclose(width, expected_width, abs_tol=1e-6) or not math.isclose(
        height, expected_height, abs_tol=1e-6
    ):
        raise MechanicalVisualProjectionError(
            "mechanical SVG dimensions do not match MechanicalLane enclosure dimensions"
        )


def _record(
    *,
    projection_id: str,
    projection_type: VisualProjectionType,
    target_revision: str,
    input_file: VisualProjectionInput,
    output_path: Path,
    base_dir: Path,
    tool_version: str,
    first_hash: str,
    second_hash: str,
    section_plane_id: str | None,
    offset_mm: float | None,
    interference_volume_mm3: float | None,
    interference_region_present: bool | None,
) -> VisualProjectionRecord:
    try:
        measured = measure_svg_resolution(output_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise MechanicalVisualProjectionError(
            "mechanical SVG resolution could not be measured"
        ) from exc
    if measured.view_box[2] <= 0 or measured.view_box[3] <= 0:
        raise MechanicalVisualProjectionError("mechanical SVG has empty dimensions")
    if first_hash != second_hash:
        raise MechanicalVisualProjectionError("mechanical visual regeneration hash mismatch")
    return VisualProjectionRecord(
        projection_id=projection_id,
        projection_type=projection_type,
        domain="mechanical",
        source_revision=target_revision,
        input_files=[input_file],
        renderer=VisualRendererProvenance(
            renderer_type="build123d",
            tool_name="build123d",
            tool_version=tool_version,
        ),
        resolution=VisualResolution(
            width=measured.width,
            height=measured.height,
            view_box=measured.view_box,
        ),
        normalization_rule_id=CAD_SVG_NORMALIZATION_RULE_ID,
        normalization_rule_description=CAD_SVG_NORMALIZATION_RULE_DESCRIPTION,
        image_hash=first_hash,
        generated_at=datetime.now(UTC),
        regeneration_check=VisualRegenerationCheck(
            status="reproduced",
            first_image_hash=first_hash,
            second_image_hash=second_hash,
        ),
        image_path=_relative_path(output_path, base_dir, "image"),
        section_plane_id=section_plane_id,
        section_offset_mm=offset_mm,
        interference_volume_mm3=interference_volume_mm3,
        interference_region_present=interference_region_present,
    )


class MechanicalVisualRenderer:
    """Render authoritative CAD sections and interference observations."""

    def __init__(self, *, base_dir: Path) -> None:
        self.base_dir = base_dir.resolve()
        self.build123d = _load_build123d()
        try:
            self.tool_version = cad_tool_version()
        except (ImportError, ModuleNotFoundError, ValueError) as exc:
            raise MechanicalVisualProjectionError(
                "CAD renderer tool version is unavailable"
            ) from exc

    def _render(
        self,
        *,
        output_path: Path,
        projection_id: str,
        projection_type: VisualProjectionType,
        input_file: VisualProjectionInput,
        render_layers: list[tuple[str, list[Any], tuple[int, int, int] | None]],
        section_plane_id: str,
        offset_mm: float | None,
        interference_volume_mm3: float | None,
        interference_region_present: bool | None,
        target_revision: str,
    ) -> VisualProjectionRecord:
        output = output_path.resolve()
        _write_svg(output_path=output, layers=render_layers, build123d=self.build123d)
        first_hash = _image_hash(output)
        reproduction = output.parent / "reproduction" / (
            f"{output.stem}.reproduced{output.suffix}"
        )
        _write_svg(
            output_path=reproduction,
            layers=render_layers,
            build123d=self.build123d,
        )
        second_hash = _image_hash(reproduction)
        return _record(
            projection_id=projection_id,
            projection_type=projection_type,
            target_revision=target_revision,
            input_file=input_file,
            output_path=output,
            base_dir=self.base_dir,
            tool_version=self.tool_version,
            first_hash=first_hash,
            second_hash=second_hash,
            section_plane_id=section_plane_id,
            offset_mm=offset_mm,
            interference_volume_mm3=interference_volume_mm3,
            interference_region_present=interference_region_present,
        )

    def render_section(
        self,
        *,
        projection: CadProjection,
        lane: MechanicalLane,
        target_revision: str,
        output_path: Path,
        section_plane_id: str,
        section_offset_mm: float,
    ) -> VisualProjectionRecord:
        if section_plane_id != "xy":
            raise MechanicalVisualProjectionError(
                "only the declared XY section plane is supported"
            )
        if not math.isfinite(section_offset_mm):
            raise MechanicalVisualProjectionError("section offset must be finite")
        input_file = _assembly_input(
            projection, base_dir=self.base_dir, target_revision=target_revision
        )
        shape = self.build123d.import_step(projection.assembly_step_path)
        edges = _section_edges(shape, section_offset_mm, self.build123d)
        record = self._render(
            output_path=output_path,
            projection_id="gd1-mechanical-section",
            projection_type="mechanical_section_view",
            input_file=input_file,
            render_layers=[("section", edges, None)],
            section_plane_id=section_plane_id,
            offset_mm=section_offset_mm,
            interference_volume_mm3=None,
            interference_region_present=None,
            target_revision=target_revision,
        )
        _validate_view_dimensions(record, lane)
        return record

    def render_interference(
        self,
        *,
        projection: CadProjection,
        lane: MechanicalLane,
        target_revision: str,
        gate_report: MechanicalGateReport,
        output_path: Path,
    ) -> VisualProjectionRecord:
        input_file = _assembly_input(
            projection, base_dir=self.base_dir, target_revision=target_revision
        )
        assembly = self.build123d.import_step(projection.assembly_step_path)
        solids = list(assembly.solids())
        if not solids:
            raise MechanicalVisualProjectionError("assembly STEP contains no solids")
        intersections: list[tuple[Any, float]] = []
        for body in lane.component_bodies:
            if body.body_type == "none":
                continue
            body_shape = build_component_body_shape(
                body,
                lane.enclosure.wall_thickness_mm + lane.enclosure.internal_clearance_mm,
                lane.outline.width_mm,
                lane.outline.depth_mm,
            )
            for solid in solids:
                intersection = solid & body_shape
                volume = 0.0 if intersection is None else float(intersection.volume)
                if volume > 0:
                    intersections.append((intersection, volume))
        actual_volume = max((volume for _shape, volume in intersections), default=0.0)
        if not math.isclose(
            actual_volume,
            gate_report.measured_max_interference_volume_mm3,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise MechanicalVisualProjectionError(
                "interference volume does not match mechanical gate measurement"
            )
        region_present = actual_volume > 0
        if region_present:
            interference = max(intersections, key=lambda item: item[1])[0]
            offset = (
                float(interference.bounding_box().min.Z)
                + float(interference.bounding_box().max.Z)
            ) / 2
        else:
            interference = None
            shell_bbox = max(solids, key=lambda solid: solid.volume).bounding_box()
            offset = float(shell_bbox.min.Z) + lane.enclosure.wall_thickness_mm
        shell_edges = _section_edges(assembly, offset, self.build123d)
        interference_edges = (
            _section_edges(interference, offset, self.build123d)
            if interference is not None
            else []
        )
        record = self._render(
            output_path=output_path,
            projection_id="gd1-mechanical-interference",
            projection_type="mechanical_interference_view",
            input_file=input_file,
            render_layers=[
                ("enclosure", shell_edges, None),
                ("interference", interference_edges, (255, 0, 0)),
            ],
            section_plane_id="xy",
            offset_mm=offset,
            interference_volume_mm3=actual_volume,
            interference_region_present=region_present,
            target_revision=target_revision,
        )
        _validate_view_dimensions(record, lane)
        return record


def generate_mechanical_visual_projections(
    *,
    projection: CadProjection,
    lane: MechanicalLane,
    target_revision: str,
    gate_report: MechanicalGateReport,
    out_dir: Path,
) -> VisualProjectionSet:
    """Generate mechanical SVG projections after mechanical gates pass."""
    if not gate_report.kernel_valid or not gate_report.clearance or not gate_report.wall_thickness:
        raise MechanicalGateError("mechanical visual projections require passing gates")
    visual_dir = out_dir / "visual"
    renderer = MechanicalVisualRenderer(base_dir=out_dir)
    records = [
        renderer.render_section(
            projection=projection,
            lane=lane,
            target_revision=target_revision,
            output_path=visual_dir / "gd1-mechanical-section.svg",
            section_plane_id="xy",
            section_offset_mm=lane.enclosure.wall_thickness_mm,
        ),
        renderer.render_interference(
            projection=projection,
            lane=lane,
            target_revision=target_revision,
            gate_report=gate_report,
            output_path=visual_dir / "gd1-mechanical-interference.svg",
        ),
    ]
    records.sort(key=lambda record: record.projection_id)
    result = VisualProjectionSet(
        source_revision=target_revision,
        projections=records,
    ).with_computed_hashes()
    (out_dir / "visual-projections-mechanical.json").write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return result
