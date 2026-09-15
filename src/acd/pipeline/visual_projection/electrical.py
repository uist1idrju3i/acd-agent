"""Electrical (board) visual projections: SVG/PNG generation and crosscheck."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree

from acd.adapters.kicad.gates import GateError
from acd.adapters.kicad.layers import copper_layers_for_layer_count
from acd.adapters.kicad.visual_projection import KicadVisualRenderer
from acd.adapters.raster import CairoSvgRasterizer
from acd.core.board_model import BoardModel
from acd.core.electrical import ElectricalLane
from acd.core.visual_projection import (
    LayerViewAnnotations,
    nested_view_attributes,
    nested_view_geometry,
    svg_source_hash,
)
from acd.pipeline.visual_projection._common import (
    crosscheck_item,
    decimal_value,
    machine_input,
    node_id_fragment,
    status_for_items,
    svg_dimension,
    svg_root_geometry,
    svg_text,
)
from acd.schema.visual_crosscheck import (
    CrosscheckStatus,
    VisualCrosscheckItem,
    VisualCrosscheckReport,
    VisualProjectionCrosscheck,
    VisualReviewChecklistItem,
)
from acd.schema.visual_projection import (
    ElectricalVisualProjectionGates,
    VisualProjectionRecord,
    VisualProjectionSet,
)


def _assert_gates_passed(gates: ElectricalVisualProjectionGates) -> None:
    if gates.erc_errors != 0:
        raise GateError("visual projection gate erc_errors did not pass (fail-closed)")
    if gates.erc_unconnected != 0:
        raise GateError("visual projection gate erc_unconnected did not pass (fail-closed)")
    if not gates.routing_converged:
        raise GateError("visual projection gate routing_converged did not pass (fail-closed)")
    if gates.drc_errors != 0:
        raise GateError("visual projection gate drc_errors did not pass (fail-closed)")
    if gates.drc_unconnected != 0:
        raise GateError("visual projection gate drc_unconnected did not pass (fail-closed)")
    if not gates.independent_reload:
        raise GateError("visual projection gate independent_reload did not pass (fail-closed)")
    if gates.silkscreen_status != "measured_pass":
        raise GateError("visual projection gate silkscreen_status did not pass (fail-closed)")
    if gates.dfm_status != "pass":
        raise GateError("visual projection gate dfm_status did not pass (fail-closed)")
    if any(predicate.status != "pass" for predicate in gates.design_predicates):
        raise GateError("visual projection design predicates did not pass (fail-closed)")


def _declared_copper_layers(lane: ElectricalLane, board: BoardModel) -> tuple[str, ...]:
    if lane.board.layers != board.layers:
        raise ValueError("visual projection board layer count declarations differ")
    return copper_layers_for_layer_count(lane.board.layers)


def generate_electrical_visual_projections(
    *,
    project_name: str,
    out_dir: Path,
    source_revision: str,
    schematic: Path,
    routed_board: Path,
    lane: ElectricalLane,
    board: BoardModel,
    gates: ElectricalVisualProjectionGates,
    renderer: KicadVisualRenderer | None = None,
) -> VisualProjectionSet:
    """Generate the electrical visual projection set after passing all gates."""
    _assert_gates_passed(gates)
    layers = _declared_copper_layers(lane, board)
    visual_dir = out_dir / "visual"
    visual_dir.mkdir(parents=True, exist_ok=True)
    renderer = renderer or KicadVisualRenderer()
    project_fragment = node_id_fragment(project_name)
    records = [
        renderer.render(
            projection_id=f"{project_fragment}-schematic",
            projection_type="schematic_view",
            domain="electrical",
            source_revision=source_revision,
            source=schematic,
            output_path=visual_dir / f"{project_fragment}-schematic.svg",
            base_dir=out_dir,
        )
    ]
    for layer in layers:
        layer_fragment = node_id_fragment(layer)
        records.append(
            renderer.render(
                projection_id=f"{project_fragment}-{layer_fragment}",
                projection_type="layered_layout_view",
                domain="electrical",
                source_revision=source_revision,
                source=routed_board,
                output_path=visual_dir / f"{project_fragment}-{layer_fragment}.svg",
                layer=layer,
                layer_annotations=LayerViewAnnotations(
                    project_name=project_name,
                    layer=layer,
                    board_width_mm=board.width_mm,
                    board_height_mm=board.height_mm,
                    layer_count=len(layers),
                ),
                base_dir=out_dir,
            )
        )
    if not records:
        raise GateError("visual projection generation produced no records (fail-closed)")
    records.sort(key=lambda record: record.projection_id)
    projection_set = VisualProjectionSet(
        source_revision=source_revision,
        projections=records,
    )
    projection_set = projection_set.with_computed_hashes()
    output_path = out_dir / "visual-projections-electrical.json"
    output_path.write_text(
        projection_set.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return projection_set


def derive_png_visual_projections(
    projection_set: VisualProjectionSet,
    *,
    out_dir: Path,
    rasterizer: CairoSvgRasterizer | None = None,
    raster_set_path: Path | None = None,
) -> VisualProjectionSet:
    """Derive PNG projections from an existing SVG projection set."""
    rasterizer = rasterizer or CairoSvgRasterizer()
    derived = list(projection_set.projections)
    for projection in projection_set.projections:
        if projection.media_type != "image/svg+xml":
            raise ValueError("PNG derivation requires SVG source projections")
        derived.append(
            rasterizer.rasterize(
                source_record=projection,
                output_path=out_dir
                / "visual"
                / "png"
                / f"{projection.projection_id}.png",
                base_dir=out_dir,
            )
        )
    derived.sort(key=lambda record: record.projection_id)
    result = VisualProjectionSet(
        source_revision=projection_set.source_revision,
        projections=derived,
    ).with_computed_hashes()
    raster_output = (
        raster_set_path
        if raster_set_path is not None
        else out_dir / "visual-projections-electrical-raster.json"
    )
    raster_output.write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def _projection_crosscheck(
    *,
    projection: VisualProjectionRecord,
    expected_refdes: tuple[str, ...],
    declared_coordinate_system: tuple[str, str, str],
    base_dir: Path,
) -> VisualProjectionCrosscheck:
    path = (base_dir / projection.image_path).resolve()
    try:
        path.relative_to(base_dir.resolve())
    except ValueError as exc:
        raise ValueError("visual crosscheck image path is outside the workspace") from exc
    try:
        svg = path.read_bytes()
    except OSError as exc:
        raise ValueError("visual crosscheck SVG could not be read") from exc
    width, height, view_box = svg_root_geometry(svg)
    width_value, width_unit = svg_dimension(width, "width")
    height_value, height_unit = svg_dimension(height, "height")
    width_number = decimal_value(width_value, "width")
    height_number = decimal_value(height_value, "height")
    view_box_numbers = tuple(decimal_value(value, "viewBox") for value in view_box)
    is_layered = projection.projection_type == "layered_layout_view"
    nested_view_count = 0
    nested_width = nested_height = "missing"
    nested_view_box = ("missing", "missing", "missing", "missing")
    nested_attributes: dict[str, str] = {}
    nested_width_value = nested_height_value = "missing"
    nested_width_number = nested_height_number = None
    nested_raw_width = nested_raw_height = "missing"
    nested_raw_width_unit = nested_raw_height_unit = "missing"
    nested_raw_width_value = nested_raw_height_value = "missing"
    nested_raw_width_number = nested_raw_height_number = None
    nested_view_box_numbers: tuple[Decimal, ...] = ()
    if is_layered:
        try:
            nested_attributes = nested_view_attributes(svg, "layer-view")
            nested_raw_width = nested_attributes.get("data-raw-width", "missing")
            nested_raw_height = nested_attributes.get("data-raw-height", "missing")
            nested_raw_width_value, nested_raw_width_unit = svg_dimension(
                nested_raw_width, "layer-view data-raw-width"
            )
            nested_raw_height_value, nested_raw_height_unit = svg_dimension(
                nested_raw_height, "layer-view data-raw-height"
            )
            nested_raw_width_number = decimal_value(
                nested_raw_width_value, "layer-view data-raw-width"
            )
            nested_raw_height_number = decimal_value(
                nested_raw_height_value, "layer-view data-raw-height"
            )
        except ValueError:
            pass
        try:
            nested_width, nested_height, nested_view_box = nested_view_geometry(
                svg, "layer-view"
            )
            nested_width_value, _ = svg_dimension(
                nested_width, "layer-view width"
            )
            nested_height_value, _ = svg_dimension(
                nested_height, "layer-view height"
            )
            nested_width_number = decimal_value(nested_width_value, "layer-view width")
            nested_height_number = decimal_value(nested_height_value, "layer-view height")
            nested_view_box_numbers = tuple(
                decimal_value(value, "layer-view viewBox") for value in nested_view_box
            )
        except ValueError:
            pass
        try:
            root = ElementTree.fromstring(svg)
            nested_view_count = sum(
                1
                for element in root.iter()
                if element.tag.rsplit("}", 1)[-1] == "svg"
                and element.attrib.get("id") == "layer-view"
            )
        except ElementTree.ParseError:
            nested_view_count = 0
    text = svg_text(svg)
    files = tuple(re.findall(r"\bFile:\s*([^\s<]+)", text))
    versions = tuple(re.findall(r"\bKiCad E\.D\.A\.\s+([^\s<]+)", text))
    expected_file = Path(projection.input_files[0].path).name
    declared_unit, declared_origin, declared_y_axis = declared_coordinate_system
    items: list[VisualCrosscheckItem] = []
    items.append(
        crosscheck_item(
            check_id="svg-units",
            description=(
                "Outer SVG uses millimeters and nested KiCad dimensions preserve "
                "millimeter provenance"
                if is_layered
                else "SVG width and height use the declared board unit"
            ),
            expected=(
                (
                    "outer=mm; data-raw-width=mm; data-raw-height=mm; "
                    "nested width/height equal raw millimeter values"
                )
                if is_layered
                else (
                    f"declared_unit={declared_unit}; "
                    f"width={declared_unit}; height={declared_unit}"
                )
            ),
            actual=(
                (
                    f"outer width={width_unit}; outer height={height_unit}; "
                    f"nested width={nested_width}; nested height={nested_height}; "
                    f"data-raw-width={nested_raw_width}; "
                    f"data-raw-height={nested_raw_height}"
                )
                if is_layered
                else f"width={width_unit}; height={height_unit}"
            ),
            machine_field=(
                "ElectricalLane.board.unit; SVG.root.width/height; "
                "SVG.svg#layer-view.data-raw-width/data-raw-height"
                if is_layered
                else "ElectricalLane.board.unit"
            ),
            status=(
                "match"
                if declared_unit == "mm"
                and (
                    (
                        width_unit == declared_unit
                        and height_unit == declared_unit
                        and nested_raw_width_unit == declared_unit
                        and nested_raw_height_unit == declared_unit
                        and nested_width_number is not None
                        and nested_height_number is not None
                        and nested_raw_width_number == nested_width_number
                        and nested_raw_height_number == nested_height_number
                    )
                    if is_layered
                    else (width_unit == declared_unit and height_unit == declared_unit)
                )
                else "mismatch"
            ),
        )
    )
    items.append(
        crosscheck_item(
            check_id="svg-origin",
            description="SVG origin and y-axis match the declared board coordinate system",
            expected=f"origin={declared_origin}; y_axis={declared_y_axis}",
            actual=(
                f"viewBox_origin={nested_view_box[0]} {nested_view_box[1]}; y_axis=down"
                if is_layered
                else f"viewBox_origin={view_box[0]} {view_box[1]}; y_axis=down"
            ),
            machine_field=(
                "ElectricalLane.board.origin; ElectricalLane.board.y_axis; "
                "SVG.svg#layer-view.viewBox"
                if is_layered
                else "ElectricalLane.board.origin; ElectricalLane.board.y_axis"
            ),
            status=(
                "match"
                if declared_origin == "board_upper_left"
                and declared_y_axis == "down"
                and (
                    nested_view_box_numbers[:2] == (Decimal("0"), Decimal("0"))
                    if is_layered
                    else view_box_numbers[:2] == (Decimal("0"), Decimal("0"))
                )
                else "mismatch"
            ),
        )
    )
    items.append(
        crosscheck_item(
            check_id="svg-viewbox",
            description=(
                "Nested KiCad layer viewBox dimensions are self-consistent"
                if is_layered
                else "SVG viewBox dimensions are self-consistent with the SVG root"
            ),
            expected=(
                f"{nested_width_value} {nested_height_value}"
                if is_layered and nested_width_number is not None
                else f"{width_value} {height_value}"
            ),
            actual=(
                f"{nested_view_box[2]} {nested_view_box[3]}"
                if is_layered
                else f"{view_box[2]} {view_box[3]}"
            ),
            machine_field=(
                "SVG.svg#layer-view.width/height; SVG.svg#layer-view.viewBox"
                if is_layered
                else "SVG.root.width/height; SVG.root.viewBox"
            ),
            status=(
                "match"
                if (
                    nested_view_box_numbers[2:] == (nested_width_number, nested_height_number)
                    if is_layered
                    else view_box_numbers[2:] == (width_number, height_number)
                )
                else "mismatch"
            ),
        )
    )
    if is_layered:
        items.append(
            crosscheck_item(
                check_id="svg-outer-viewbox",
                description="Outer acd-svg viewBox is millimeter-based and self-consistent",
                expected=f"0 0 {width_value} {height_value}",
                actual=f"{view_box[0]} {view_box[1]} {view_box[2]} {view_box[3]}",
                machine_field="SVG.root.width/height; SVG.root.viewBox",
                status=(
                    "match"
                    if width_unit == "mm"
                    and height_unit == "mm"
                    and view_box_numbers == (
                        Decimal("0"),
                        Decimal("0"),
                        width_number,
                        height_number,
                    )
                    else "mismatch"
                ),
            )
        )
        items.append(
            crosscheck_item(
                check_id="svg-layer-view",
                description="Exactly one nested KiCad layer view is present",
                expected="1",
                actual=str(nested_view_count),
                machine_field="SVG.svg#layer-view",
                status="match" if nested_view_count == 1 else "mismatch",
            )
        )
    items.append(
        crosscheck_item(
            check_id="svg-input-file",
            description="SVG title block names the projection input file",
            expected=expected_file,
            actual=",".join(files) or "missing",
            machine_field="VisualProjectionRecord.input_files[0].path",
            status="match" if files and set(files) == {expected_file} else "mismatch",
        )
    )
    expected_version = projection.renderer.tool_version
    items.append(
        crosscheck_item(
            check_id="svg-renderer-version",
            description="SVG records the renderer version",
            expected=expected_version,
            actual=",".join(versions) or "missing",
            machine_field="VisualProjectionRecord.renderer.tool_version",
            status="match" if versions and set(versions) == {expected_version} else "mismatch",
        )
    )
    try:
        actual_hash = svg_source_hash(svg, projection.normalization_rule_id)
    except ValueError as exc:
        if is_layered:
            actual_hash = "normalization failed"
        else:
            raise ValueError("visual crosscheck SVG normalization failed") from exc
    items.append(
        crosscheck_item(
            check_id="svg-image-hash",
            description="SVG normalized image hash matches the projection record",
            expected=projection.image_hash,
            actual=actual_hash,
            machine_field="VisualProjectionRecord.image_hash",
            status="match" if actual_hash == projection.image_hash else "mismatch",
        )
    )
    if projection.projection_type == "schematic_view":
        missing_refdes = [
            refdes
            for refdes in expected_refdes
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(refdes)}(?![A-Za-z0-9_])", text)
            is None
        ]
        items.append(
            crosscheck_item(
                check_id="schematic-refdes",
                description="All electrical component reference designators are present",
                expected=",".join(expected_refdes) or "none",
                actual="missing:" + ",".join(missing_refdes) if missing_refdes else "all present",
                machine_field="ElectricalLane.components[*].refdes",
                status="match" if not missing_refdes else "mismatch",
            )
        )
    return VisualProjectionCrosscheck(
        projection_id=projection.projection_id,
        source_revision=projection.source_revision,
        image_hash=projection.image_hash,
        items=items,
        status=status_for_items(items),
    )


def crosscheck_electrical_visual_projections(
    *,
    project_name: str,
    source_revision: str,
    visual_projection_set: VisualProjectionSet,
    lane: ElectricalLane,
    board: BoardModel,
    base_dir: Path,
    machine_inputs: tuple[Path, ...],
    output_path: Path | None = None,
) -> VisualCrosscheckReport:
    """Cross-check electrical SVG projections against machine-readable inputs."""
    if visual_projection_set.source_revision != source_revision:
        raise ValueError("visual crosscheck source revisions do not match")
    if any(
        projection.source_revision != source_revision
        for projection in visual_projection_set.projections
    ):
        raise ValueError("visual crosscheck projection revisions do not match")
    expected_layers = _declared_copper_layers(lane, board)
    schematic = [
        projection
        for projection in visual_projection_set.projections
        if projection.projection_type == "schematic_view"
    ]
    layered = [
        projection
        for projection in visual_projection_set.projections
        if projection.projection_type == "layered_layout_view"
    ]
    expected_layer_ids = {
        f"{node_id_fragment(project_name)}-{node_id_fragment(layer)}"
        for layer in expected_layers
    }
    actual_layer_ids = {projection.projection_id for projection in layered}
    coverage_status: CrosscheckStatus = (
        "match"
        if len(schematic) == 1
        and actual_layer_ids == expected_layer_ids
        and len(layered) == len(expected_layers)
        else "mismatch"
    )
    coverage_item = crosscheck_item(
        check_id="projection-coverage",
        description="Projection set contains exactly the declared electrical views",
        expected=f"schematic=1; layers={','.join(expected_layers)}",
        actual=(
            f"schematic={len(schematic)}; "
            f"layered={','.join(sorted(actual_layer_ids)) or 'none'}"
        ),
        machine_field="ElectricalLane.board.layers",
        status=coverage_status,
    )
    records: list[VisualProjectionCrosscheck] = []
    for projection in visual_projection_set.projections:
        record = _projection_crosscheck(
            projection=projection,
            expected_refdes=tuple(component.refdes for component in lane.components),
            declared_coordinate_system=(
                lane.board.unit,
                lane.board.origin,
                lane.board.y_axis,
            ),
            base_dir=base_dir,
        )
        records.append(record)
    if not records:
        raise ValueError("visual crosscheck has no projection records")
    deterministic_items = {
        check_id: [item for record in records for item in record.items if item.check_id == check_id]
        for check_id in ("svg-units", "svg-origin", "svg-viewbox")
    }
    review_items = [
        VisualReviewChecklistItem(
            item_id="review-readability",
            aspect="readability",
            verification="observation_required",
            status="unknown",
            basis="SVG text and geometry cannot deterministically establish readability.",
        ),
        VisualReviewChecklistItem(
            item_id="review-design-intent",
            aspect="design_intent",
            verification="observation_required",
            status="unknown",
            basis="SVG bytes cannot deterministically establish design-intent fidelity.",
        ),
        VisualReviewChecklistItem(
            item_id="review-annotations",
            aspect="annotations",
            verification="observation_required",
            status="unknown",
            basis="Annotation legibility requires visual observation.",
        ),
        VisualReviewChecklistItem(
            item_id="review-units",
            aspect="units",
            verification="deterministic",
            status=status_for_items(deterministic_items["svg-units"]),
            basis="SVG root width and height unit checks.",
        ),
        VisualReviewChecklistItem(
            item_id="review-axis",
            aspect="axis",
            verification="observation_required",
            status="unknown",
            basis="Axis orientation beyond the SVG origin is not encoded deterministically.",
        ),
        VisualReviewChecklistItem(
            item_id="review-origin",
            aspect="origin",
            verification="deterministic",
            status=status_for_items(deterministic_items["svg-origin"]),
            basis="SVG viewBox origin check.",
        ),
        VisualReviewChecklistItem(
            item_id="review-occlusion",
            aspect="occlusion",
            verification="observation_required",
            status="unknown",
            basis="Overlapping or hidden visual elements require visual observation.",
        ),
        VisualReviewChecklistItem(
            item_id="review-signal-power",
            aspect="signal_power",
            verification="observation_required",
            status="unknown",
            basis="Signal and power-system readability requires visual observation.",
        ),
    ]
    report = VisualCrosscheckReport(
        source_revision=source_revision,
        visual_projection_set_identity_hash=visual_projection_set.identity_hash,
        machine_input_files=[
            machine_input(path, base_dir=base_dir)
            for path in machine_inputs
        ],
        set_items=[coverage_item],
        crosschecks=sorted(records, key=lambda record: record.projection_id),
        review_items=review_items,
        status=status_for_items(
            [coverage_item]
            + [
                item
                for record in records
                for item in record.items
            ]
        ),
        generated_at=datetime.now(UTC),
    ).with_computed_hashes()
    if output_path is None:
        output_path = base_dir / "visual-crosscheck-electrical.json"
    output_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report
