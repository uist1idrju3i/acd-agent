"""Build123d mechanical visual projection renderer."""

from __future__ import annotations

import importlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from acd.adapters.cad.mechanical import (
    MechanicalGateError,
    MechanicalGateReport,
    board_plane_z,
    build_component_body_shape,
)
from acd.adapters.cad.project import CadProjection, cad_tool_version
from acd.core.cad_normalize import normalize_step
from acd.core.mechanical import MechanicalLane
from acd.core.naming import artifact_prefix
from acd.core.parallel import PipelineStageRunner
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


@dataclass(frozen=True)
class _SectionGeometry:
    edges: tuple[Any, ...]
    wires: tuple[tuple[Any, ...], ...]


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


def _edge_sort_key(edge: Any) -> tuple[str, float, float, float, float, float, float, float]:
    bbox = edge.bounding_box()
    return (
        str(edge.geom_type),
        round(float(bbox.min.X), 9),
        round(float(bbox.min.Y), 9),
        round(float(bbox.max.X), 9),
        round(float(bbox.max.Y), 9),
        round(float(edge.length), 9),
        round(float(edge.center().X), 9),
        round(float(edge.center().Y), 9),
    )


def _section_geometry(shape: Any, offset_mm: float, build123d: Any) -> _SectionGeometry:
    try:
        plane = build123d.Plane.XY.offset(offset_mm)
        wires: list[tuple[Any, ...]] = []
        for solid in shape.solids():
            section = solid & plane
            if section is None:
                continue
            for face in section.faces():
                for wire in face.wires():
                    wire_edges = tuple(wire.edges())
                    if wire_edges:
                        wires.append(wire_edges)
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        raise MechanicalVisualProjectionError(
            "section plane could not be evaluated"
        ) from exc
    if not wires:
        raise MechanicalVisualProjectionError(
            "section plane does not intersect the authoritative shape"
        )
    translation = build123d.Location((0, 0, -offset_mm))
    translated_wires = tuple(
        tuple(edge.moved(translation) for edge in wire) for wire in wires
    )
    edges = tuple(sorted((edge for wire in translated_wires for edge in wire), key=_edge_sort_key))
    return _SectionGeometry(edges=edges, wires=translated_wires)


def _edge_is(edge: Any, geometry_type: str) -> bool:
    return str(edge.geom_type).endswith(geometry_type)


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-6)


def _merge_aperture_intervals(
    intervals: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    ordered = sorted(intervals)
    merged: list[tuple[float, float]] = []
    for start, end in ordered:
        if not math.isfinite(start) or not math.isfinite(end) or start > end:
            raise MechanicalVisualProjectionError(
                "mechanical section aperture interval is invalid"
            )
        if not merged or (
            start > merged[-1][1] and not _close(start, merged[-1][1])
        ):
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _expected_aperture_intervals(
    lane: MechanicalLane,
    section_offset_mm: float,
) -> dict[str, list[tuple[float, float]]]:
    intervals: dict[str, list[tuple[float, float]]] = {"front": [], "back": []}
    for opening in lane.connector_openings:
        if opening.face not in intervals:
            raise MechanicalVisualProjectionError(
                "mechanical section connector opening face is unsupported"
            )
        opening_min_z = opening.center_y_mm - (
            opening.height_mm / 2 + opening.margin_mm
        )
        opening_max_z = opening.center_y_mm + (
            opening.height_mm / 2 + opening.margin_mm
        )
        if opening_min_z < section_offset_mm < opening_max_z:
            center_x = opening.center_x_mm - lane.outline.width_mm / 2
            half_width = (opening.width_mm + 2 * opening.margin_mm) / 2
            intervals[opening.face].append(
                (center_x - half_width, center_x + half_width)
            )
    for overhang in lane.board_edge_overhangs:
        face = {"top": "front", "bottom": "back"}.get(overhang.edge)
        if face is None:
            continue
        body = lane.body_for_component(overhang.component_id)
        overhang_min_z = board_plane_z(lane.enclosure)
        overhang_max_z = overhang_min_z + body.height_mm
        if overhang_min_z < section_offset_mm < overhang_max_z:
            center_x = body.x_mm - lane.outline.width_mm / 2
            half_width = body.width_mm / 2 + lane.enclosure.internal_clearance_mm
            intervals[face].append((center_x - half_width, center_x + half_width))
    return {
        face: _merge_aperture_intervals(face_intervals)
        for face, face_intervals in intervals.items()
    }


def _section_aperture_boundary_xs(
    geometry: _SectionGeometry,
    *,
    face: str,
    outer_width: float,
    outer_depth: float,
) -> list[float]:
    face_y = -outer_depth / 2 if face == "front" else outer_depth / 2
    boundary_xs: list[float] = []
    for edge in geometry.edges:
        if not _edge_is(edge, "LINE"):
            continue
        try:
            bbox = edge.bounding_box()
            min_x = float(bbox.min.X)
            max_x = float(bbox.max.X)
            min_y = float(bbox.min.Y)
            max_y = float(bbox.max.Y)
        except (AttributeError, TypeError, ValueError) as exc:
            raise MechanicalVisualProjectionError(
                "mechanical section aperture boundary geometry is unreadable"
            ) from exc
        if not _close(min_x, max_x):
            continue
        if _close(abs(min_x), outer_width / 2):
            continue
        if face == "front":
            on_face = _close(min_y, face_y) and max_y > face_y
        else:
            on_face = _close(max_y, face_y) and min_y < face_y
        if on_face:
            boundary_xs.append(min_x)
    return sorted(boundary_xs)


def _validate_section_features(
    geometry: _SectionGeometry,
    lane: MechanicalLane,
    section_offset_mm: float,
) -> None:
    circles = [edge for edge in geometry.edges if _edge_is(edge, "CIRCLE")]
    holes = lane.outline.mount_holes
    if not circles and holes:
        raise MechanicalVisualProjectionError(
            "mechanical section is missing declared standoff features"
        )
    expected_features = [
        (
            hole.x_mm - lane.outline.width_mm / 2,
            hole.y_mm - lane.outline.depth_mm / 2,
            radius,
        )
        for hole in holes
        for radius in (
            lane.enclosure.standoff_radius_mm,
            lane.enclosure.standoff_pilot_hole_diameter_mm / 2,
        )
    ]
    measured_features: list[tuple[float, float, float]] = []
    for edge in circles:
        try:
            radius = float(edge.radius)
            center = edge.arc_center
            center_x = float(center.X)
            center_y = float(center.Y)
        except (AttributeError, TypeError, ValueError) as exc:
            raise MechanicalVisualProjectionError(
                "mechanical section circular edge geometry is unreadable"
            ) from exc
        if not all(math.isfinite(value) for value in (center_x, center_y, radius)):
            raise MechanicalVisualProjectionError(
                "mechanical section circular edge geometry is non-finite"
            )
        measured_features.append((center_x, center_y, radius))
    for expected_x, expected_y, expected_radius in expected_features:
        if not any(
            _close(center_x, expected_x)
            and _close(center_y, expected_y)
            and _close(radius, expected_radius)
            for center_x, center_y, radius in measured_features
        ):
            raise MechanicalVisualProjectionError(
                "mechanical section standoff geometry does not match MechanicalLane"
            )
    for center_x, center_y, radius in measured_features:
        if not any(
            _close(center_x, expected_x)
            and _close(center_y, expected_y)
            and _close(radius, expected_radius)
            for expected_x, expected_y, expected_radius in expected_features
        ):
            raise MechanicalVisualProjectionError(
                "mechanical section contains an undeclared circular feature"
            )

    inner_width = lane.outline.width_mm + 2 * lane.enclosure.internal_clearance_mm
    inner_depth = lane.outline.depth_mm + 2 * lane.enclosure.internal_clearance_mm
    inner_x = inner_width / 2
    inner_y = inner_depth / 2
    has_inner_left = any(
        _edge_is(edge, "LINE")
        and _close(float(edge.bounding_box().min.X), -inner_x)
        and _close(float(edge.bounding_box().max.X), -inner_x)
        and _close(float(edge.bounding_box().min.Y), -inner_y)
        and _close(float(edge.bounding_box().max.Y), inner_y)
        for edge in geometry.edges
    )
    has_inner_right = any(
        _edge_is(edge, "LINE")
        and _close(float(edge.bounding_box().min.X), inner_x)
        and _close(float(edge.bounding_box().max.X), inner_x)
        and _close(float(edge.bounding_box().min.Y), -inner_y)
        and _close(float(edge.bounding_box().max.Y), inner_y)
        for edge in geometry.edges
    )
    has_inner_top = any(
        _edge_is(edge, "LINE")
        and _close(float(edge.bounding_box().min.X), -inner_x)
        and _close(float(edge.bounding_box().max.X), inner_x)
        and _close(float(edge.bounding_box().min.Y), inner_y)
        and _close(float(edge.bounding_box().max.Y), inner_y)
        for edge in geometry.edges
    )
    if not (has_inner_left and has_inner_right and has_inner_top):
        raise MechanicalVisualProjectionError(
            "mechanical section is missing the declared enclosure cavity"
        )

    outer_width, outer_depth = _expected_view_dimensions(lane)
    expected_intervals = _expected_aperture_intervals(lane, section_offset_mm)
    for face, intervals in expected_intervals.items():
        expected_boundaries = [
            boundary
            for interval in intervals
            for boundary in interval
        ]
        actual_boundaries = _section_aperture_boundary_xs(
            geometry,
            face=face,
            outer_width=outer_width,
            outer_depth=outer_depth,
        )
        missing_boundaries = [
            boundary
            for boundary in expected_boundaries
            if not any(_close(boundary, actual) for actual in actual_boundaries)
        ]
        if missing_boundaries:
            raise MechanicalVisualProjectionError(
                f"mechanical section {face} aperture is missing a declared boundary"
            )
        unexpected_boundaries = [
            boundary
            for boundary in actual_boundaries
            if not any(_close(boundary, expected) for expected in expected_boundaries)
        ]
        if unexpected_boundaries:
            raise MechanicalVisualProjectionError(
                f"mechanical section {face} aperture contains an undeclared boundary"
            )


def _declared_section_offset_mm(lane: MechanicalLane) -> float:
    wall_thickness = lane.enclosure.wall_thickness_mm
    standoff_height = lane.enclosure.standoff_height_mm
    if (
        not math.isfinite(wall_thickness)
        or not math.isfinite(standoff_height)
        or wall_thickness <= 0
        or standoff_height <= 0
    ):
        raise MechanicalVisualProjectionError(
            "mechanical section offset declarations are invalid"
        )
    return wall_thickness + standoff_height / 2


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
        graph_id: str = "golden-design-1",
        output_path: Path,
        section_plane_id: str,
    ) -> VisualProjectionRecord:
        if section_plane_id != "xy":
            raise MechanicalVisualProjectionError(
                "only the declared XY section plane is supported"
            )
        section_offset_mm = _declared_section_offset_mm(lane)
        input_file = _assembly_input(
            projection, base_dir=self.base_dir, target_revision=target_revision
        )
        shape = self.build123d.import_step(projection.assembly_step_path)
        section = _section_geometry(shape, section_offset_mm, self.build123d)
        _validate_section_features(section, lane, section_offset_mm)
        record = self._render(
            output_path=output_path,
            projection_id=f"{artifact_prefix(graph_id)}-mechanical-section",
            projection_type="mechanical_section_view",
            input_file=input_file,
            render_layers=[("section", list(section.edges), None)],
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
        graph_id: str = "golden-design-1",
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
            offset = float(shell_bbox.min.Z) + _declared_section_offset_mm(lane)
        shell_section = _section_geometry(assembly, offset, self.build123d)
        interference_edges: list[Any] = (
            list(_section_geometry(interference, offset, self.build123d).edges)
            if interference is not None
            else []
        )
        record = self._render(
            output_path=output_path,
            projection_id=f"{artifact_prefix(graph_id)}-mechanical-interference",
            projection_type="mechanical_interference_view",
            input_file=input_file,
            render_layers=[
                ("enclosure", list(shell_section.edges), None),
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


def _render_mechanical_section(
    *,
    projection: CadProjection,
    lane: MechanicalLane,
    target_revision: str,
    graph_id: str,
    out_dir: Path,
) -> VisualProjectionRecord:
    renderer = MechanicalVisualRenderer(base_dir=out_dir)
    return renderer.render_section(
        projection=projection,
        lane=lane,
        target_revision=target_revision,
        graph_id=graph_id,
        output_path=out_dir / f"visual/{artifact_prefix(graph_id)}-mechanical-section.svg",
        section_plane_id="xy",
    )


def _render_mechanical_interference(
    *,
    projection: CadProjection,
    lane: MechanicalLane,
    target_revision: str,
    graph_id: str,
    gate_report: MechanicalGateReport,
    out_dir: Path,
) -> VisualProjectionRecord:
    renderer = MechanicalVisualRenderer(base_dir=out_dir)
    return renderer.render_interference(
        projection=projection,
        lane=lane,
        target_revision=target_revision,
        graph_id=graph_id,
        gate_report=gate_report,
        output_path=out_dir / f"visual/{artifact_prefix(graph_id)}-mechanical-interference.svg",
    )


def generate_mechanical_visual_projections(
    *,
    projection: CadProjection,
    lane: MechanicalLane,
    target_revision: str,
    gate_report: MechanicalGateReport,
    out_dir: Path,
    runner: PipelineStageRunner | None = None,
    graph_id: str = "golden-design-1",
) -> VisualProjectionSet:
    """Generate mechanical SVG projections after mechanical gates pass."""
    if not gate_report.kernel_valid or not gate_report.clearance or not gate_report.wall_thickness:
        raise MechanicalGateError("mechanical visual projections require passing gates")
    stages = (
        (
            "mechanical-section",
            partial(
                _render_mechanical_section,
                projection=projection,
                lane=lane,
                target_revision=target_revision,
                graph_id=graph_id,
                out_dir=out_dir,
            ),
        ),
        (
            "mechanical-interference",
            partial(
                _render_mechanical_interference,
                projection=projection,
                lane=lane,
                target_revision=target_revision,
                graph_id=graph_id,
                gate_report=gate_report,
                out_dir=out_dir,
            ),
        ),
    )
    records = (
        runner.run_ordered_stages(stages)
        if runner is not None
        else [stage() for _, stage in stages]
    )
    typed_records: list[VisualProjectionRecord] = []
    for record in records:
        if not isinstance(record, VisualProjectionRecord):
            raise MechanicalGateError("mechanical visual projections are unknown")
        typed_records.append(record)
    typed_records.sort(key=lambda record: record.projection_id)
    result = VisualProjectionSet(
        source_revision=target_revision,
        projections=typed_records,
    ).with_computed_hashes()
    (out_dir / "visual-projections-mechanical.json").write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return result
