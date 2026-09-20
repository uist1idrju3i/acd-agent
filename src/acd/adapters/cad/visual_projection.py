"""Build123d mechanical visual projection renderer."""

from __future__ import annotations

import importlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from acd.adapters.cad.mechanical import (
    MechanicalGateError,
    MechanicalGateReport,
    board_plane_z,
    build_component_body_shape,
)
from acd.adapters.cad.project import CadProjection, cad_tool_version
from acd.adapters.svg.common import (
    COLOR_EDGE,
    COLOR_FRONT,
    COLOR_TEXT_MUTED,
    DIAGRAM_FONT_SIZE_RATIO,
    DIAGRAM_REFERENCE_WIDTH,
    footer_height,
    format_svg_number,
    header_height,
    legend,
    svg_document,
    svg_text,
    view_box_font_size,
)
from acd.core.electrical.visual_projection import (
    CAD_SVG_NORMALIZATION_RULE_ID,
    SvgNormalizationError,
    cad_view_geometry,
    measure_svg_resolution,
    raw_svg_parts,
)
from acd.core.knowledge.naming import artifact_prefix
from acd.core.mechanical.cad_normalize import normalize_step
from acd.core.mechanical.mechanical import SUPPORTED_OPENING_FACES, MechanicalLane
from acd.core.runtime.fileio import read_json
from acd.core.runtime.parallel import PipelineStageRunner
from acd.core.runtime.process import ExternalToolError, sha256_bytes
from acd.schema.visual_projection import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionSet,
    VisualProjectionType,
    VisualRegenerationCheck,
    VisualRendererProvenance,
    VisualResolution,
)

CAD_SVG_NORMALIZATION_RULE_DESCRIPTION = (
    "Build123d ExportSVG raw output is embedded verbatim as svg#cad-view "
    "inside an acd-svg document."
)

class MechanicalVisualProjectionError(ExternalToolError):
    """Raised when a mechanical visual projection cannot be trusted."""


@dataclass(frozen=True)
class _SectionGeometry:
    edges: tuple[Any, ...]
    wires: tuple[tuple[Any, ...], ...]


@dataclass(frozen=True)
class _CadAnnotations:
    graph_id: str
    view_name: Literal["section", "interference"]
    lane: MechanicalLane
    offset_mm: float
    interference_region_present: bool | None
    measured_max_interference_volume_mm3: float | None
    measured_min_clearance_mm: float | None


def _load_build123d() -> Any:
    try:
        return importlib.import_module("build123d")
    except (ImportError, ModuleNotFoundError) as exc:
        raise MechanicalVisualProjectionError("build123d renderer is unavailable") from exc


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
        manifest = read_json(manifest_path)
        artifacts = manifest["artifacts"]
        assembly = next(item for item in artifacts if item["role"] == "enclosure_assembly")
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
        raise MechanicalVisualProjectionError("section plane could not be evaluated") from exc
    if not wires:
        raise MechanicalVisualProjectionError(
            "section plane does not intersect the authoritative shape"
        )
    translation = build123d.Location((0, 0, -offset_mm))
    translated_wires = tuple(tuple(edge.moved(translation) for edge in wire) for wire in wires)
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
            raise MechanicalVisualProjectionError("mechanical section aperture interval is invalid")
        if not merged or (start > merged[-1][1] and not _close(start, merged[-1][1])):
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _expected_aperture_intervals(
    lane: MechanicalLane,
    section_offset_mm: float,
) -> dict[str, list[tuple[float, float]]]:
    intervals: dict[str, list[tuple[float, float]]] = {
        face: [] for face in SUPPORTED_OPENING_FACES
    }
    for opening in lane.connector_openings:
        if opening.face not in intervals:
            raise MechanicalVisualProjectionError(
                "mechanical section connector opening face is unsupported"
            )
        opening_min_z = opening.center_y_mm - (opening.height_mm / 2 + opening.margin_mm)
        opening_max_z = opening.center_y_mm + (opening.height_mm / 2 + opening.margin_mm)
        if opening_min_z < section_offset_mm < opening_max_z:
            if opening.face in {"left", "right"}:
                center = opening.center_x_mm - lane.outline.depth_mm / 2
            else:
                center = opening.center_x_mm - lane.outline.width_mm / 2
            half_width = (opening.width_mm + 2 * opening.margin_mm) / 2
            intervals[opening.face].append((center - half_width, center + half_width))
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


def _section_aperture_boundaries(
    geometry: _SectionGeometry,
    *,
    face: str,
    outer_width: float,
    outer_depth: float,
) -> list[float]:
    boundaries: list[float] = []
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
        if face in {"left", "right"}:
            if not _close(min_y, max_y):
                continue
            if _close(abs(min_y), outer_depth / 2):
                continue
            if face == "left":
                on_face = _close(min_x, -outer_width / 2) and max_x > -outer_width / 2
            else:
                on_face = _close(max_x, outer_width / 2) and min_x < outer_width / 2
            if on_face:
                boundaries.append(min_y)
        else:
            face_y = -outer_depth / 2 if face == "front" else outer_depth / 2
            if not _close(min_x, max_x):
                continue
            if _close(abs(min_x), outer_width / 2):
                continue
            if face == "front":
                on_face = _close(min_y, face_y) and max_y > face_y
            else:
                on_face = _close(max_y, face_y) and min_y < face_y
            if on_face:
                boundaries.append(min_x)
    return sorted(boundaries)


def _validate_section_features(
    geometry: _SectionGeometry,
    lane: MechanicalLane,
    section_offset_mm: float,
) -> None:
    if lane.mechanism_features:
        return
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
    if not lane.mechanism_features:
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
    expected_intervals = _expected_aperture_intervals(lane, section_offset_mm)
    outer_width, outer_depth = _expected_view_dimensions(lane)
    for face, intervals in expected_intervals.items():
        expected_boundaries = [boundary for interval in intervals for boundary in interval]
        actual_boundaries = _section_aperture_boundaries(
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

    has_inner_back = _inner_wall_is_covered(
        geometry,
        axis="y",
        wall=inner_y,
        inner_half=inner_x,
        apertures=expected_intervals["back"],
    )
    has_inner_front = _inner_wall_is_covered(
        geometry,
        axis="y",
        wall=-inner_y,
        inner_half=inner_x,
        apertures=expected_intervals["front"],
    )
    has_inner_left = _inner_wall_is_covered(
        geometry,
        axis="x",
        wall=-inner_x,
        inner_half=inner_y,
        apertures=expected_intervals["left"],
    )
    has_inner_right = _inner_wall_is_covered(
        geometry,
        axis="x",
        wall=inner_x,
        inner_half=inner_y,
        apertures=expected_intervals["right"],
    )
    if not (has_inner_left and has_inner_right and has_inner_back and has_inner_front):
        raise MechanicalVisualProjectionError(
            "mechanical section is missing the declared enclosure cavity"
        )


def _inner_wall_is_covered(
    geometry: _SectionGeometry,
    *,
    axis: Literal["x", "y"],
    wall: float,
    inner_half: float,
    apertures: list[tuple[float, float]],
) -> bool:
    """Inner wall segments plus declared apertures must span the full cavity.

    ``axis="y"`` checks a wall at a fixed Y spanning X; ``axis="x"`` checks a
    wall at a fixed X spanning Y. ``wall`` is the fixed coordinate and
    ``inner_half`` is the cavity half-extent along the wall's span axis.
    """
    segments: list[tuple[float, float]] = []
    for edge in geometry.edges:
        if not _edge_is(edge, "LINE"):
            continue
        bbox = edge.bounding_box()
        if axis == "y":
            if not (
                _close(float(bbox.min.Y), wall) and _close(float(bbox.max.Y), wall)
            ):
                continue
            span_min = float(bbox.min.X)
            span_max = float(bbox.max.X)
        else:
            if not (
                _close(float(bbox.min.X), wall) and _close(float(bbox.max.X), wall)
            ):
                continue
            span_min = float(bbox.min.Y)
            span_max = float(bbox.max.Y)
        clip_min = max(span_min, -inner_half)
        clip_max = min(span_max, inner_half)
        if clip_max > clip_min:
            segments.append((clip_min, clip_max))
    if not segments:
        return False
    clipped_apertures = [
        (max(start, -inner_half), min(end, inner_half))
        for start, end in apertures
        if min(end, inner_half) > max(start, -inner_half)
    ]
    covered = _merge_aperture_intervals([*segments, *clipped_apertures])
    return (
        len(covered) == 1
        and _close(covered[0][0], -inner_half)
        and _close(covered[0][1], inner_half)
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
        raise MechanicalVisualProjectionError("mechanical section offset declarations are invalid")
    return wall_thickness + standoff_height / 2


def _write_svg(
    *,
    output_path: Path,
    layers: list[tuple[str, list[Any], tuple[int, int, int] | None]],
    build123d: Any,
) -> bytes:
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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".raw",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        exporter.write(temporary_path)
        return temporary_path.read_bytes()
    except (OSError, ValueError) as exc:
        raise MechanicalVisualProjectionError(
            f"mechanical SVG could not be written: {output_path}"
        ) from exc
    finally:
        temporary_path.unlink(missing_ok=True)


def _raw_svg_parts(raw: bytes) -> tuple[str, str, float, float, str]:
    try:
        return raw_svg_parts(raw)
    except SvgNormalizationError as exc:
        raise MechanicalVisualProjectionError(str(exc)) from exc


def _wrap_cad_svg(raw: bytes, *, annotations: _CadAnnotations) -> bytes:
    raw_view_box, raw_attributes, raw_width, raw_height, raw_inner = _raw_svg_parts(raw)
    font_size = view_box_font_size(
        DIAGRAM_REFERENCE_WIDTH,
        ratio=DIAGRAM_FONT_SIZE_RATIO,
    )
    scale = DIAGRAM_REFERENCE_WIDTH * 0.55 / raw_width
    cad_width = raw_width * scale
    cad_height = raw_height * scale
    cad_x = font_size * 4
    cad_y = header_height(font_size) + font_size * 2
    dimension_y = cad_y + cad_height + font_size * 2
    dimension_x = cad_x + cad_width + font_size * 2
    scale_bar_y = dimension_y + font_size * 3.5
    legend_y = scale_bar_y + font_size * 3
    note_y = legend_y + font_size * 2
    outer_height = note_y + footer_height(font_size) + font_size * 3
    view_box_values = tuple(float(value) for value in raw_view_box.split())
    view_box_x, view_box_y = view_box_values[:2]

    def map_point(x: float, y: float) -> tuple[float, float]:
        return cad_x + (x - view_box_x) * scale, cad_y + (y - view_box_y) * scale

    outline_left, outline_top = map_point(
        -annotations.lane.outline.width_mm / 2,
        -annotations.lane.outline.depth_mm / 2,
    )
    outline_right, outline_bottom = map_point(
        annotations.lane.outline.width_mm / 2,
        annotations.lane.outline.depth_mm / 2,
    )
    dimension_stroke = max(font_size * 0.08, 0.1)
    tick = font_size * 0.6
    view_width, view_height = _expected_view_dimensions(annotations.lane)
    width_label = svg_text(
        f"{format_svg_number(view_width)} mm",
        x=cad_x + cad_width / 2,
        y=dimension_y + font_size * 1.5,
        font_size=font_size,
        element_id="dimension-width-label",
        anchor="middle",
    )
    depth_label_x = dimension_x + font_size * 1.4
    depth_label_y = cad_y + cad_height / 2
    depth_label = svg_text(
        f"{format_svg_number(view_height)} mm",
        x=depth_label_x,
        y=depth_label_y,
        font_size=font_size,
        element_id="dimension-depth-label",
        anchor="middle",
    )
    outline_width = outline_right - outline_left
    outline_height = outline_bottom - outline_top
    board_label = svg_text(
        "board outline (declared)",
        x=outline_left,
        y=outline_top - font_size * 0.6,
        font_size=font_size,
        fill=COLOR_FRONT,
    )
    scale_label = svg_text(
        "10 mm",
        x=cad_x + 5 * scale,
        y=scale_bar_y + font_size * 1.3,
        font_size=font_size,
        anchor="middle",
    )
    title = (
        f"{annotations.graph_id} mechanical {annotations.view_name} — "
        f"XY plane, z = {format_svg_number(annotations.offset_mm)} mm"
    )
    subtitle = (
        f"enclosure {format_svg_number(view_width)} × {format_svg_number(view_height)} mm "
        f"(outline {format_svg_number(annotations.lane.outline.width_mm)} × "
        f"{format_svg_number(annotations.lane.outline.depth_mm)} + 2×clearance "
        f"{format_svg_number(annotations.lane.enclosure.internal_clearance_mm)} + "
        f"2×wall {format_svg_number(annotations.lane.enclosure.wall_thickness_mm)}); "
        f"standoff {format_svg_number(annotations.lane.enclosure.standoff_height_mm)} mm"
    )
    body: list[str] = [
        (
            f'<svg id="cad-view" x="{format_svg_number(cad_x)}" '
            f'y="{format_svg_number(cad_y)}" width="{format_svg_number(cad_width)}" '
            f'height="{format_svg_number(cad_height)}" viewBox="{raw_view_box}"'
            f"{(' ' + raw_attributes) if raw_attributes else ''}>{raw_inner}</svg>"
        ),
        (
            f'<g id="dimension-width" fill="none" stroke="{COLOR_EDGE}" '
            f'stroke-width="{format_svg_number(dimension_stroke)}">'
            f'<line x1="{format_svg_number(cad_x)}" y1="{format_svg_number(dimension_y)}" '
            f'x2="{format_svg_number(cad_x + cad_width)}" y2="{format_svg_number(dimension_y)}"/>'
            f'<line x1="{format_svg_number(cad_x)}" y1="{format_svg_number(dimension_y - tick)}" '
            f'x2="{format_svg_number(cad_x)}" y2="{format_svg_number(dimension_y + tick)}"/>'
            f'<line x1="{format_svg_number(cad_x + cad_width)}" '
            f'y1="{format_svg_number(dimension_y - tick)}" '
            f'x2="{format_svg_number(cad_x + cad_width)}" '
            f'y2="{format_svg_number(dimension_y + tick)}"/>'
            f"</g>{width_label}"
        ),
        (
            f'<g id="dimension-depth" fill="none" stroke="{COLOR_EDGE}" '
            f'stroke-width="{format_svg_number(dimension_stroke)}">'
            f'<line x1="{format_svg_number(dimension_x)}" y1="{format_svg_number(cad_y)}" '
            f'x2="{format_svg_number(dimension_x)}" y2="{format_svg_number(cad_y + cad_height)}"/>'
            f'<line x1="{format_svg_number(dimension_x - tick)}" y1="{format_svg_number(cad_y)}" '
            f'x2="{format_svg_number(dimension_x + tick)}" y2="{format_svg_number(cad_y)}"/>'
            f'<line x1="{format_svg_number(dimension_x - tick)}" '
            f'y1="{format_svg_number(cad_y + cad_height)}" '
            f'x2="{format_svg_number(dimension_x + tick)}" '
            f'y2="{format_svg_number(cad_y + cad_height)}"/>'
            f"</g>{depth_label}"
        ),
        (
            f'<g id="board-outline"><rect x="{format_svg_number(outline_left)}" '
            f'y="{format_svg_number(outline_top)}" width="{format_svg_number(outline_width)}" '
            f'height="{format_svg_number(outline_height)}" fill="none" '
            f'stroke="{COLOR_FRONT}" stroke-width="{format_svg_number(dimension_stroke)}" '
            f'stroke-dasharray="{format_svg_number(font_size)} '
            f'{format_svg_number(font_size * 0.6)}"/>{board_label}</g>'
        ),
        (
            f'<g id="scale-bar"><line x1="{format_svg_number(cad_x)}" '
            f'y1="{format_svg_number(scale_bar_y)}" x2="{format_svg_number(cad_x + 10 * scale)}" '
            f'y2="{format_svg_number(scale_bar_y)}" stroke="{COLOR_EDGE}" '
            f'stroke-width="{format_svg_number(dimension_stroke * 2)}"/>'
            f"{scale_label}</g>"
        ),
    ]
    legend_items = [
        ("enclosure section (cut edges)", "#ffffff", COLOR_EDGE),
        ("board outline (declared)", "none", COLOR_FRONT),
    ]
    if (
        annotations.view_name == "interference"
        and annotations.interference_region_present
    ):
        legend_items.append(("interference region", "#ff0000", "#ff0000"))
    body.extend(legend(legend_items, x=cad_x, y=legend_y, font_size=font_size))
    if annotations.view_name == "interference":
        if annotations.interference_region_present:
            volume = annotations.measured_max_interference_volume_mm3
            if volume is None:
                raise MechanicalVisualProjectionError(
                    "interference volume annotation is missing gate measurement"
                )
            note = (
                f"interference present: max intersection volume "
                f"{format_svg_number(volume)} mm³ (gate measurement)"
            )
        else:
            clearance = annotations.measured_min_clearance_mm
            if clearance is None:
                raise MechanicalVisualProjectionError(
                    "clearance annotation is missing gate measurement"
                )
            note = (
                f"no interference: max intersection volume 0 mm³; measured min "
                f"clearance {format_svg_number(clearance)} mm (gate measurement)"
            )
        body.append(
            svg_text(
                note,
                x=cad_x,
                y=note_y,
                font_size=font_size,
                element_id="interference-note",
                fill=COLOR_TEXT_MUTED,
            )
        )
    return svg_document(
        width=DIAGRAM_REFERENCE_WIDTH,
        height=outer_height,
        title=title,
        subtitle=subtitle,
        body=body,
        font_size=font_size,
    )


def _image_hash(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise MechanicalVisualProjectionError(f"mechanical SVG could not be read: {path}") from exc


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
    lane: MechanicalLane,
    *,
    svg: bytes,
) -> None:
    expected_width, expected_height = _expected_view_dimensions(lane)
    try:
        _nested_width, _nested_height, view_box = cad_view_geometry(svg)
        width = float(view_box[2])
        height = float(view_box[3])
    except (ValueError, TypeError) as exc:
        raise MechanicalVisualProjectionError(
            "mechanical SVG cad-view dimensions could not be measured"
        ) from exc
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
        annotations: _CadAnnotations,
    ) -> VisualProjectionRecord:
        output = output_path.resolve()
        raw = _write_svg(
            output_path=output,
            layers=render_layers,
            build123d=self.build123d,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(_wrap_cad_svg(raw, annotations=annotations))
        first_hash = _image_hash(output)
        reproduction = output.parent / "reproduction" / (f"{output.stem}.reproduced{output.suffix}")
        reproduced_raw = _write_svg(
            output_path=reproduction,
            layers=render_layers,
            build123d=self.build123d,
        )
        reproduction.parent.mkdir(parents=True, exist_ok=True)
        reproduction.write_bytes(
            _wrap_cad_svg(reproduced_raw, annotations=annotations)
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
            raise MechanicalVisualProjectionError("only the declared XY section plane is supported")
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
            annotations=_CadAnnotations(
                graph_id=graph_id,
                view_name="section",
                lane=lane,
                offset_mm=section_offset_mm,
                interference_region_present=None,
                measured_max_interference_volume_mm3=None,
                measured_min_clearance_mm=None,
            ),
        )
        if not lane.mechanism_features:
            _validate_view_dimensions(lane, svg=output_path.read_bytes())
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
                float(interference.bounding_box().min.Z) + float(interference.bounding_box().max.Z)
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
            annotations=_CadAnnotations(
                graph_id=graph_id,
                view_name="interference",
                lane=lane,
                offset_mm=offset,
                interference_region_present=region_present,
                measured_max_interference_volume_mm3=(
                    gate_report.measured_max_interference_volume_mm3
                ),
                measured_min_clearance_mm=gate_report.measured_min_clearance_mm,
            ),
        )
        if not lane.mechanism_features:
            _validate_view_dimensions(lane, svg=output_path.read_bytes())
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
