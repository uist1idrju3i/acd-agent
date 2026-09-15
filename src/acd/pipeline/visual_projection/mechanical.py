"""Mechanical (enclosure) visual projection crosscheck."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from acd.adapters.cad.mechanical import MechanicalGateReport
from acd.adapters.cad.project import CadProjection, cad_tool_version
from acd.core.cad_normalize import normalize_3mf, normalize_step
from acd.core.mechanical import MechanicalLane
from acd.core.naming import artifact_prefix
from acd.core.process import sha256_bytes
from acd.core.visual_projection import (
    cad_view_geometry,
)
from acd.pipeline.visual_projection._common import (
    crosscheck_item,
    decimal_value,
    machine_input,
    status_for_items,
    svg_dimension,
    svg_root_geometry,
)
from acd.schema.visual_crosscheck import (
    VisualCrosscheckReport,
    VisualProjectionCrosscheck,
    VisualReviewChecklistItem,
)
from acd.schema.visual_projection import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionSet,
)


def _normalized_step_input(
    path: Path,
    *,
    base_dir: Path,
) -> VisualProjectionInput:
    input_record = machine_input(path, base_dir=base_dir)
    try:
        normalized_hash = sha256_bytes(normalize_step(path.read_bytes()))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("visual crosscheck assembly STEP cannot be normalized") from exc
    return input_record.model_copy(update={"content_hash": normalized_hash})


def _normalized_model_input(
    path: Path,
    *,
    base_dir: Path,
) -> VisualProjectionInput:
    input_record = machine_input(path, base_dir=base_dir)
    try:
        normalized_hash = sha256_bytes(normalize_3mf(path.read_bytes()))
    except (OSError, ValueError) as exc:
        raise ValueError("visual crosscheck model cannot be normalized") from exc
    return input_record.model_copy(update={"content_hash": normalized_hash})


def _svg_layer_ids(svg: bytes, scope_id: str | None = None) -> tuple[str, ...]:
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        raise ValueError("visual crosscheck SVG could not be parsed") from exc
    scope = root
    if scope_id is not None:
        matches = [
            element for element in root.iter() if element.attrib.get("id") == scope_id
        ]
        if len(matches) != 1:
            raise ValueError(f"visual crosscheck SVG scope is invalid: {scope_id}")
        scope = matches[0]
    return tuple(
        sorted(
            {
                element.attrib["id"]
                for element in scope.iter()
                if "id" in element.attrib
                and (scope_id is None or element is not scope)
            }
        )
    )


def _svg_outer_annotation_ids(svg: bytes) -> tuple[str, ...]:
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        raise ValueError("visual crosscheck SVG could not be parsed") from exc
    cad_views = [
        element for element in root.iter() if element.attrib.get("id") == "cad-view"
    ]
    if len(cad_views) != 1:
        raise ValueError("visual crosscheck SVG scope is invalid: cad-view")
    cad_view = cad_views[0]
    cad_view_element_ids = {id(element) for element in cad_view.iter()}
    ids: set[str] = {"cad-view"}
    for element in root.iter():
        if element is cad_view:
            continue
        if id(element) in cad_view_element_ids:
            continue
        element_id = element.attrib.get("id")
        if element_id is not None:
            ids.add(element_id)
    return tuple(sorted(ids))


def _mechanical_projection_crosscheck(
    *,
    projection: VisualProjectionRecord,
    lane: MechanicalLane,
    gate_report: MechanicalGateReport,
    base_dir: Path,
    declared_step_hash: str,
) -> VisualProjectionCrosscheck:
    if projection.projection_type not in {
        "mechanical_section_view",
        "mechanical_interference_view",
    }:
        raise ValueError("visual crosscheck contains a non-mechanical projection")
    path = (base_dir / projection.image_path).resolve()
    try:
        path.relative_to(base_dir.resolve())
        svg = path.read_bytes()
    except (OSError, ValueError) as exc:
        raise ValueError("visual crosscheck mechanical SVG could not be read") from exc
    width, height, _ = svg_root_geometry(svg)
    nested_width, nested_height, nested_view_box = cad_view_geometry(svg)
    _width_value, width_unit = svg_dimension(width, "width")
    _height_value, height_unit = svg_dimension(height, "height")
    nested_width_number = decimal_value(nested_width, "cad-view width")
    nested_height_number = decimal_value(nested_height, "cad-view height")
    view_box_numbers = tuple(decimal_value(value, "viewBox") for value in nested_view_box)
    expected_width = (
        lane.outline.width_mm
        + 2 * lane.enclosure.internal_clearance_mm
        + 2 * lane.enclosure.wall_thickness_mm
    )
    expected_height = (
        lane.outline.depth_mm
        + 2 * lane.enclosure.internal_clearance_mm
        + 2 * lane.enclosure.wall_thickness_mm
    )
    declared_offset = (
        lane.enclosure.wall_thickness_mm + lane.enclosure.standoff_height_mm / 2
    )
    expected_origin = (-expected_width / 2, -expected_height / 2)
    expected_layers = (
        ("section",)
        if projection.projection_type == "mechanical_section_view"
        else (
            ("enclosure", "interference")
            if projection.interference_region_present
            else ("enclosure",)
        )
    )
    actual_layers = _svg_layer_ids(svg, scope_id="cad-view")
    annotation_ids = _svg_outer_annotation_ids(svg)
    expected_annotations = [
        "board-outline",
        "cad-view",
        "dimension-depth",
        "dimension-width",
        "legend",
        "scale-bar",
    ]
    if projection.projection_type == "mechanical_interference_view":
        expected_annotations.append("interference-note")
    expected_annotation_set = tuple(sorted(expected_annotations))
    try:
        renderer_version = cad_tool_version()
    except (ImportError, ModuleNotFoundError, ValueError) as exc:
        raise ValueError("visual crosscheck CAD renderer version is unavailable") from exc
    if projection.renderer.tool_version == "unknown":
        raise ValueError("visual crosscheck CAD renderer version is unknown")
    input_files = projection.input_files
    if len(input_files) != 1:
        raise ValueError("visual crosscheck mechanical projection input is invalid")
    items = [
        crosscheck_item(
            check_id="svg-units",
            description="Mechanical SVG root dimensions use millimeter units",
            expected="width=mm; height=mm",
            actual=f"width={width_unit}; height={height_unit}",
            machine_field="SVG.root.width/height",
            status="match" if width_unit == "mm" and height_unit == "mm" else "mismatch",
        ),
        crosscheck_item(
            check_id="svg-origin",
            description="Mechanical SVG viewBox origin matches the centered CAD projection",
            expected=f"{expected_origin[0]} {expected_origin[1]}",
            actual=f"{nested_view_box[0]} {nested_view_box[1]}",
            machine_field="SVG.svg#cad-view.viewBox.origin",
            status=(
                "match"
                if math.isclose(float(view_box_numbers[0]), expected_origin[0], abs_tol=1e-6)
                and math.isclose(float(view_box_numbers[1]), expected_origin[1], abs_tol=1e-6)
                else "mismatch"
            ),
        ),
        crosscheck_item(
            check_id="svg-viewbox",
            description="Mechanical CAD viewBox and display dimensions use one scale",
            expected=(
                f"viewBox={expected_width} {expected_height}; "
                f"width={expected_width}*s; height={expected_height}*s"
            ),
            actual=(
                f"viewBox={nested_view_box[2]} {nested_view_box[3]}; "
                f"width={nested_width}; height={nested_height}"
            ),
            machine_field="SVG.svg#cad-view.width/height/viewBox",
            status=(
                "match" if (
                    lane.mechanism_features
                    or (
                    math.isclose(float(view_box_numbers[2]), expected_width, abs_tol=1e-6)
                    and math.isclose(float(view_box_numbers[3]), expected_height, abs_tol=1e-6)
                    and math.isclose(
                        float(nested_width_number) / float(view_box_numbers[2]),
                        float(nested_height_number) / float(view_box_numbers[3]),
                        abs_tol=1e-6,
                    )
                    )
                ) else "mismatch"
            ),
        ),
        crosscheck_item(
            check_id="svg-view-dimensions",
            description="Mechanical SVG viewBox dimensions match the declared enclosure",
            expected=f"{expected_width} {expected_height}",
            actual=f"{nested_view_box[2]} {nested_view_box[3]}",
            machine_field=(
                "SVG.svg#cad-view.viewBox; MechanicalLane.outline.width_mm/depth_mm; "
                "MechanicalLane.enclosure.internal_clearance_mm/wall_thickness_mm"
            ),
            status=(
                "match"
                if lane.mechanism_features
                or (
                    math.isclose(float(view_box_numbers[2]), expected_width, abs_tol=1e-6)
                and math.isclose(float(view_box_numbers[3]), expected_height, abs_tol=1e-6)
                )
                else "mismatch"
            ),
        ),
        crosscheck_item(
            check_id="svg-image-hash",
            description="Mechanical SVG raw-byte hash matches the projection record",
            expected=projection.image_hash,
            actual=sha256_bytes(svg),
            machine_field="VisualProjectionRecord.image_hash",
            status="match" if sha256_bytes(svg) == projection.image_hash else "mismatch",
        ),
        crosscheck_item(
            check_id="renderer-version",
            description="Mechanical SVG renderer version matches the installed CAD tool",
            expected=renderer_version,
            actual=projection.renderer.tool_version,
            machine_field="VisualProjectionRecord.renderer.tool_version; cad_tool_version()",
            status=(
                "match"
                if projection.renderer.tool_version == renderer_version
                else "mismatch"
            ),
        ),
        crosscheck_item(
            check_id="step-input-hash",
            description="Mechanical projection input matches the normalized assembly STEP",
            expected=declared_step_hash,
            actual=input_files[0].content_hash,
            machine_field="VisualProjectionRecord.input_files[0].content_hash",
            status="match" if input_files[0].content_hash == declared_step_hash else "mismatch",
        ),
        crosscheck_item(
            check_id="section-plane",
            description="Mechanical projection uses the declared XY section plane",
            expected="xy",
            actual=projection.section_plane_id or "missing",
            machine_field="VisualProjectionRecord.section_plane_id",
            status="match" if projection.section_plane_id == "xy" else "mismatch",
        ),
        crosscheck_item(
            check_id="section-offset",
            description="Mechanical projection section offset matches the declared offset",
            expected=str(declared_offset),
            actual=(
                str(projection.section_offset_mm)
                if projection.section_offset_mm is not None
                else "missing"
            ),
            machine_field=(
                "VisualProjectionRecord.section_offset_mm; "
                "MechanicalLane.enclosure.wall_thickness_mm/standoff_height_mm"
            ),
            status=(
                "match"
                if projection.section_offset_mm is not None
                and math.isclose(projection.section_offset_mm, declared_offset, abs_tol=1e-6)
                else "mismatch"
            ),
        ),
        crosscheck_item(
            check_id="svg-layer-names",
            description="Mechanical SVG layer identifiers match the declared view layers",
            expected=",".join(expected_layers),
            actual=",".join(actual_layers) or "none",
            machine_field="SVG.svg#cad-view.g[*].id",
            status="match" if actual_layers == expected_layers else "mismatch",
        ),
        crosscheck_item(
            check_id="svg-annotations",
            description="Mechanical SVG outer document carries declared annotations",
            expected=",".join(expected_annotation_set),
            actual=",".join(annotation_ids) or "none",
            machine_field="SVG.root.annotations[*].id",
            status=(
                "match"
                if set(expected_annotation_set).issubset(set(annotation_ids))
                else "mismatch"
            ),
        ),
    ]
    if projection.projection_type == "mechanical_interference_view":
        actual_volume = projection.interference_volume_mm3
        expected_volume = gate_report.measured_max_interference_volume_mm3
        items.extend(
            [
                crosscheck_item(
                    check_id="interference-volume",
                    description="Interference view volume matches the mechanical gate measurement",
                    expected=str(expected_volume),
                    actual=str(actual_volume) if actual_volume is not None else "missing",
                    machine_field=(
                        "VisualProjectionRecord.interference_volume_mm3; "
                        "MechanicalGateReport.measured_max_interference_volume_mm3"
                    ),
                    status=(
                        "match"
                        if actual_volume is not None
                        and math.isclose(actual_volume, expected_volume, abs_tol=1e-6)
                        else "mismatch"
                    ),
                ),
                crosscheck_item(
                    check_id="interference-region",
                    description="Interference region presence matches volume and gate status",
                    expected=(
                        f"volume>0={expected_volume > 0}; "
                        f"gate_interference_free={gate_report.interference}"
                    ),
                    actual=(
                        f"volume>0={actual_volume is not None and actual_volume > 0}; "
                        f"gate_interference_free={gate_report.interference}; "
                        f"region={projection.interference_region_present}"
                    ),
                    machine_field=(
                        "VisualProjectionRecord.interference_region_present; "
                        "MechanicalGateReport.interference"
                    ),
                    status=(
                        "match"
                        if actual_volume is not None
                        and projection.interference_region_present is not None
                        and (actual_volume > 0) == projection.interference_region_present
                        and gate_report.interference
                        == (expected_volume <= lane.enclosure.interference_tolerance_mm3)
                        else "mismatch"
                    ),
                ),
            ]
        )
    return VisualProjectionCrosscheck(
        projection_id=projection.projection_id,
        source_revision=projection.source_revision,
        image_hash=projection.image_hash,
        items=items,
        status=status_for_items(items),
    )


def crosscheck_mechanical_visual_projections(
    *,
    source_revision: str,
    visual_projection_set: VisualProjectionSet,
    lane: MechanicalLane,
    projection: CadProjection,
    gate_report: MechanicalGateReport,
    base_dir: Path,
    output_path: Path | None = None,
    graph_id: str = "golden-design-1",
) -> VisualCrosscheckReport:
    """Cross-check mechanical SVG projections against CAD and gate inputs."""
    if visual_projection_set.source_revision != source_revision:
        raise ValueError("visual crosscheck source revisions do not match")
    if any(
        item.source_revision != source_revision
        for item in visual_projection_set.projections
    ):
        raise ValueError("visual crosscheck projection revisions do not match")
    expected_types = {
        "mechanical_section_view",
        "mechanical_interference_view",
    }
    prefix = artifact_prefix(graph_id)
    expected_ids = {
        f"{prefix}-mechanical-section",
        f"{prefix}-mechanical-interference",
    }
    actual_types = [item.projection_type for item in visual_projection_set.projections]
    actual_ids = {item.projection_id for item in visual_projection_set.projections}
    coverage_item = crosscheck_item(
        check_id="projection-coverage",
        description="Projection set contains exactly the declared mechanical views",
        expected=(
            "mechanical_section_view=1; mechanical_interference_view=1; "
            f"projection_ids={prefix}-mechanical-section,{prefix}-mechanical-interference"
        ),
        actual=(
            f"types={','.join(sorted(actual_types)) or 'none'}; "
            f"projection_ids={','.join(sorted(actual_ids)) or 'none'}"
        ),
        machine_field="VisualProjectionSet.projections[*].projection_type/projection_id",
        status=(
            "match"
            if len(visual_projection_set.projections) == 2
            and set(actual_types) == expected_types
            and actual_ids == expected_ids
            else "mismatch"
        ),
    )
    declared_step = _normalized_step_input(
        projection.assembly_step_path,
        base_dir=base_dir,
    )
    records = [
        _mechanical_projection_crosscheck(
            projection=item,
            lane=lane,
            gate_report=gate_report,
            base_dir=base_dir,
            declared_step_hash=declared_step.content_hash,
        )
        for item in visual_projection_set.projections
    ]
    if not records:
        raise ValueError("visual crosscheck has no projection records")
    deterministic_items = {
        check_id: [
            item
            for record in records
            for item in record.items
            if item.check_id == check_id
        ]
        for check_id in ("svg-units", "svg-origin", "section-plane")
    }
    review_items = [
        VisualReviewChecklistItem(
            item_id="review-readability",
            aspect="readability",
            verification="observation_required",
            status="unknown",
            basis="Mechanical SVG geometry cannot deterministically establish readability.",
        ),
        VisualReviewChecklistItem(
            item_id="review-design-intent",
            aspect="design_intent",
            verification="observation_required",
            status="unknown",
            basis="Mechanical SVG bytes cannot deterministically establish design-intent fidelity.",
        ),
        VisualReviewChecklistItem(
            item_id="review-annotations",
            aspect="annotations",
            verification="observation_required",
            status="unknown",
            basis="Mechanical SVG annotations require visual observation.",
        ),
        VisualReviewChecklistItem(
            item_id="review-units",
            aspect="units",
            verification="deterministic",
            status=status_for_items(
                deterministic_items["svg-units"]
            ),
            basis="SVG root width and height unit checks.",
        ),
        VisualReviewChecklistItem(
            item_id="review-axis",
            aspect="axis",
            verification="observation_required",
            status="unknown",
            basis="Mechanical section axis orientation requires visual observation.",
        ),
        VisualReviewChecklistItem(
            item_id="review-origin",
            aspect="origin",
            verification="deterministic",
            status=status_for_items(deterministic_items["svg-origin"]),
            basis="Centered CAD SVG viewBox origin check.",
        ),
        VisualReviewChecklistItem(
            item_id="review-section-plane",
            aspect="section_plane",
            verification="deterministic",
            status=status_for_items(deterministic_items["section-plane"]),
            basis="Declared XY section plane check.",
        ),
        VisualReviewChecklistItem(
            item_id="review-occlusion",
            aspect="occlusion",
            verification="observation_required",
            status="unknown",
            basis="Overlapping or hidden mechanical visual elements require visual observation.",
        ),
        VisualReviewChecklistItem(
            item_id="review-interference-visibility",
            aspect="interference_visibility",
            verification="observation_required",
            status="unknown",
            basis="Interference visibility requires visual observation.",
        ),
    ]
    report = VisualCrosscheckReport(
        source_revision=source_revision,
        visual_projection_set_identity_hash=visual_projection_set.identity_hash,
        machine_input_files=[
            declared_step,
            _normalized_model_input(projection.model_path, base_dir=base_dir),
            machine_input(projection.artifact_manifest_path, base_dir=base_dir),
        ],
        set_items=[coverage_item],
        crosschecks=sorted(records, key=lambda record: record.projection_id),
        review_items=review_items,
        status=status_for_items(
            [coverage_item]
            + [item for record in records for item in record.items]
        ),
        generated_at=datetime.now(UTC),
    ).with_computed_hashes()
    if output_path is None:
        output_path = base_dir / "visual-crosscheck-mechanical.json"
    output_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report
