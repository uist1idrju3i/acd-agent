"""Electrical-lane visual projection wiring after deterministic gates."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

from acd.adapters.cad.mechanical import MechanicalGateReport
from acd.adapters.cad.project import CadProjection, cad_tool_version
from acd.adapters.kicad.gates import GateError
from acd.adapters.kicad.visual_projection import (
    KicadVisualRenderer,
    copper_layers_for_layer_count,
)
from acd.adapters.raster import CairoSvgRasterizer
from acd.core.board_model import BoardModel
from acd.core.cad_normalize import normalize_3mf, normalize_step
from acd.core.electrical import ElectricalLane
from acd.core.mechanical import MechanicalLane
from acd.core.process import sha256_bytes
from acd.core.visual_projection import normalized_svg_sha256
from acd.schema.visual_crosscheck import (
    CrosscheckStatus,
    VisualCrosscheckItem,
    VisualCrosscheckReport,
    VisualProjectionCrosscheck,
    VisualReviewChecklistItem,
)
from acd.schema.visual_projection import (
    ElectricalVisualProjectionGates,
    VisualProjectionInput,
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


def _node_id_fragment(value: str) -> str:
    fragment = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not fragment:
        raise ValueError("visual projection identifier declaration is invalid")
    return fragment


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
    project_fragment = _node_id_fragment(project_name)
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
        layer_fragment = _node_id_fragment(layer)
        records.append(
            renderer.render(
                projection_id=f"{project_fragment}-{layer_fragment}",
                projection_type="layered_layout_view",
                domain="electrical",
                source_revision=source_revision,
                source=routed_board,
                output_path=visual_dir / f"{project_fragment}-{layer_fragment}.svg",
                layer=layer,
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
    (out_dir / "visual-projections-electrical-raster.json").write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def _crosscheck_item(
    *,
    check_id: str,
    description: str,
    expected: str,
    actual: str,
    machine_field: str,
    status: CrosscheckStatus,
) -> VisualCrosscheckItem:
    return VisualCrosscheckItem(
        check_id=check_id,
        description=description,
        expected=expected,
        actual=actual,
        machine_field=machine_field,
        status=status,
    )


def _status_for_items(items: list[VisualCrosscheckItem]) -> CrosscheckStatus:
    if not items:
        raise ValueError("visual crosscheck cannot aggregate an empty item list")
    statuses = {item.status for item in items}
    if "mismatch" in statuses:
        return "mismatch"
    if "unknown" in statuses:
        return "unknown"
    return "match"


def _svg_root_geometry(svg: bytes) -> tuple[str, str, tuple[str, str, str, str]]:
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        raise ValueError("visual crosscheck SVG could not be parsed") from exc
    attributes = root.attrib
    width = attributes.get("width")
    height = attributes.get("height")
    view_box = attributes.get("viewBox")
    if width is None or height is None or view_box is None:
        raise ValueError("visual crosscheck SVG root geometry is incomplete")
    values = tuple(view_box.split())
    if len(values) != 4:
        raise ValueError("visual crosscheck SVG viewBox is malformed")
    return width, height, values


def _decimal(value: str, field_name: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"visual crosscheck {field_name} is not numeric") from exc
    if not parsed.is_finite():
        raise ValueError(f"visual crosscheck {field_name} is not finite")
    return parsed


def _svg_dimension(value: str, field_name: str) -> tuple[str, str]:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([A-Za-z]*)", value)
    if match is None:
        raise ValueError(f"visual crosscheck SVG {field_name} is malformed")
    return match.group(1), match.group(2)


def _svg_text(svg: bytes) -> str:
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        raise ValueError("visual crosscheck SVG could not be parsed") from exc
    return "\n".join(text.strip() for text in root.itertext() if text.strip())


def _machine_input(
    path: Path,
    *,
    base_dir: Path,
) -> VisualProjectionInput:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(base_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("visual crosscheck machine input is outside the workspace") from exc
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise ValueError("visual crosscheck machine input is missing or unreadable") from exc
    return VisualProjectionInput(path=relative, content_hash=sha256_bytes(content))


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
    width, height, view_box = _svg_root_geometry(svg)
    width_value, width_unit = _svg_dimension(width, "width")
    height_value, height_unit = _svg_dimension(height, "height")
    width_number = _decimal(width_value, "width")
    height_number = _decimal(height_value, "height")
    view_box_numbers = tuple(_decimal(value, "viewBox") for value in view_box)
    text = _svg_text(svg)
    files = tuple(re.findall(r"\bFile:\s*([^\s<]+)", text))
    versions = tuple(re.findall(r"\bKiCad E\.D\.A\.\s+([^\s<]+)", text))
    expected_file = Path(projection.input_files[0].path).name
    declared_unit, declared_origin, declared_y_axis = declared_coordinate_system
    items: list[VisualCrosscheckItem] = []
    items.append(
        _crosscheck_item(
            check_id="svg-units",
            description="SVG width and height use the declared board unit",
            expected=(
                f"declared_unit={declared_unit}; "
                f"width={declared_unit}; height={declared_unit}"
            ),
            actual=f"width={width_unit}; height={height_unit}",
            machine_field="ElectricalLane.board.unit",
            status=(
                "match"
                if declared_unit == "mm"
                and width_unit == declared_unit
                and height_unit == declared_unit
                else "mismatch"
            ),
        )
    )
    items.append(
        _crosscheck_item(
            check_id="svg-origin",
            description="SVG origin and y-axis match the declared board coordinate system",
            expected=f"origin={declared_origin}; y_axis={declared_y_axis}",
            actual=f"viewBox_origin={view_box[0]} {view_box[1]}; y_axis=down",
            machine_field="ElectricalLane.board.origin; ElectricalLane.board.y_axis",
            status=(
                "match"
                if declared_origin == "board_upper_left"
                and declared_y_axis == "down"
                and view_box_numbers[:2] == (Decimal("0"), Decimal("0"))
                else "mismatch"
            ),
        )
    )
    items.append(
        _crosscheck_item(
            check_id="svg-viewbox",
            description="SVG viewBox dimensions are self-consistent with the SVG root",
            expected=f"{width_value} {height_value}",
            actual=f"{view_box[2]} {view_box[3]}",
            machine_field="SVG.root.width/height; SVG.root.viewBox",
            status=(
                "match"
                if view_box_numbers[2:] == (width_number, height_number)
                else "mismatch"
            ),
        )
    )
    items.append(
        _crosscheck_item(
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
        _crosscheck_item(
            check_id="svg-renderer-version",
            description="SVG records the renderer version",
            expected=expected_version,
            actual=",".join(versions) or "missing",
            machine_field="VisualProjectionRecord.renderer.tool_version",
            status="match" if versions and set(versions) == {expected_version} else "mismatch",
        )
    )
    try:
        actual_hash = normalized_svg_sha256(svg)
    except ValueError as exc:
        raise ValueError("visual crosscheck SVG normalization failed") from exc
    items.append(
        _crosscheck_item(
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
            _crosscheck_item(
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
        status=_status_for_items(items),
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
        f"{_node_id_fragment(project_name)}-{_node_id_fragment(layer)}"
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
    coverage_item = _crosscheck_item(
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
            status=_status_for_items(deterministic_items["svg-units"]),
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
            status=_status_for_items(deterministic_items["svg-origin"]),
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
            _machine_input(path, base_dir=base_dir)
            for path in machine_inputs
        ],
        set_items=[coverage_item],
        crosschecks=sorted(records, key=lambda record: record.projection_id),
        review_items=review_items,
        status=_status_for_items(
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


def _normalized_step_input(
    path: Path,
    *,
    base_dir: Path,
) -> VisualProjectionInput:
    input_record = _machine_input(path, base_dir=base_dir)
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
    input_record = _machine_input(path, base_dir=base_dir)
    try:
        normalized_hash = sha256_bytes(normalize_3mf(path.read_bytes()))
    except (OSError, ValueError) as exc:
        raise ValueError("visual crosscheck model cannot be normalized") from exc
    return input_record.model_copy(update={"content_hash": normalized_hash})


def _svg_layer_ids(svg: bytes) -> tuple[str, ...]:
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        raise ValueError("visual crosscheck SVG could not be parsed") from exc
    return tuple(
        sorted(
            {
                element.attrib["id"]
                for element in root.iter()
                if "id" in element.attrib
            }
        )
    )


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
    width, height, view_box = _svg_root_geometry(svg)
    width_value, width_unit = _svg_dimension(width, "width")
    height_value, height_unit = _svg_dimension(height, "height")
    width_number = _decimal(width_value, "width")
    height_number = _decimal(height_value, "height")
    view_box_numbers = tuple(_decimal(value, "viewBox") for value in view_box)
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
    actual_layers = _svg_layer_ids(svg)
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
        _crosscheck_item(
            check_id="svg-units",
            description="Mechanical SVG root dimensions use millimeter units",
            expected="width=mm; height=mm",
            actual=f"width={width_unit}; height={height_unit}",
            machine_field="SVG.root.width/height",
            status="match" if width_unit == "mm" and height_unit == "mm" else "mismatch",
        ),
        _crosscheck_item(
            check_id="svg-origin",
            description="Mechanical SVG viewBox origin matches the centered CAD projection",
            expected=f"{expected_origin[0]} {expected_origin[1]}",
            actual=f"{view_box[0]} {view_box[1]}",
            machine_field="SVG.root.viewBox.origin",
            status=(
                "match"
                if math.isclose(float(view_box_numbers[0]), expected_origin[0], abs_tol=1e-6)
                and math.isclose(float(view_box_numbers[1]), expected_origin[1], abs_tol=1e-6)
                else "mismatch"
            ),
        ),
        _crosscheck_item(
            check_id="svg-viewbox",
            description="Mechanical SVG viewBox dimensions are self-consistent with the root",
            expected=f"{width_value} {height_value}",
            actual=f"{view_box[2]} {view_box[3]}",
            machine_field="SVG.root.width/height; SVG.root.viewBox",
            status=(
                "match"
                if view_box_numbers[2:] == (width_number, height_number)
                else "mismatch"
            ),
        ),
        _crosscheck_item(
            check_id="svg-view-dimensions",
            description="Mechanical SVG viewBox dimensions match the declared enclosure",
            expected=f"{expected_width} {expected_height}",
            actual=f"{view_box[2]} {view_box[3]}",
            machine_field=(
                "MechanicalLane.outline.width_mm/depth_mm; "
                "MechanicalLane.enclosure.internal_clearance_mm/wall_thickness_mm"
            ),
            status=(
                "match"
                if math.isclose(float(view_box_numbers[2]), expected_width, abs_tol=1e-6)
                and math.isclose(float(view_box_numbers[3]), expected_height, abs_tol=1e-6)
                else "mismatch"
            ),
        ),
        _crosscheck_item(
            check_id="svg-image-hash",
            description="Mechanical SVG raw-byte hash matches the projection record",
            expected=projection.image_hash,
            actual=sha256_bytes(svg),
            machine_field="VisualProjectionRecord.image_hash",
            status="match" if sha256_bytes(svg) == projection.image_hash else "mismatch",
        ),
        _crosscheck_item(
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
        _crosscheck_item(
            check_id="step-input-hash",
            description="Mechanical projection input matches the normalized assembly STEP",
            expected=declared_step_hash,
            actual=input_files[0].content_hash,
            machine_field="VisualProjectionRecord.input_files[0].content_hash",
            status="match" if input_files[0].content_hash == declared_step_hash else "mismatch",
        ),
        _crosscheck_item(
            check_id="section-plane",
            description="Mechanical projection uses the declared XY section plane",
            expected="xy",
            actual=projection.section_plane_id or "missing",
            machine_field="VisualProjectionRecord.section_plane_id",
            status="match" if projection.section_plane_id == "xy" else "mismatch",
        ),
        _crosscheck_item(
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
        _crosscheck_item(
            check_id="svg-layer-names",
            description="Mechanical SVG layer identifiers match the declared view layers",
            expected=",".join(expected_layers),
            actual=",".join(actual_layers) or "none",
            machine_field="SVG.root.g[*].id",
            status="match" if actual_layers == expected_layers else "mismatch",
        ),
    ]
    if projection.projection_type == "mechanical_interference_view":
        actual_volume = projection.interference_volume_mm3
        expected_volume = gate_report.measured_max_interference_volume_mm3
        items.extend(
            [
                _crosscheck_item(
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
                _crosscheck_item(
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
        status=_status_for_items(items),
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
    expected_ids = {
        "gd1-mechanical-section",
        "gd1-mechanical-interference",
    }
    actual_types = [item.projection_type for item in visual_projection_set.projections]
    actual_ids = {item.projection_id for item in visual_projection_set.projections}
    coverage_item = _crosscheck_item(
        check_id="projection-coverage",
        description="Projection set contains exactly the declared mechanical views",
        expected=(
            "mechanical_section_view=1; mechanical_interference_view=1; "
            "projection_ids=gd1-mechanical-section,gd1-mechanical-interference"
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
            status=_status_for_items(
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
            status=_status_for_items(deterministic_items["svg-origin"]),
            basis="Centered CAD SVG viewBox origin check.",
        ),
        VisualReviewChecklistItem(
            item_id="review-section-plane",
            aspect="section_plane",
            verification="deterministic",
            status=_status_for_items(deterministic_items["section-plane"]),
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
            _machine_input(projection.artifact_manifest_path, base_dir=base_dir),
        ],
        set_items=[coverage_item],
        crosschecks=sorted(records, key=lambda record: record.projection_id),
        review_items=review_items,
        status=_status_for_items(
            [coverage_item]
            + [item for record in records for item in record.items]
        ),
        generated_at=datetime.now(UTC),
    ).with_computed_hashes()
    if output_path is None:
        output_path = base_dir / "visual-crosscheck-mechanical.json"
    output_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report


__all__ = [
    "crosscheck_electrical_visual_projections",
    "crosscheck_mechanical_visual_projections",
    "derive_png_visual_projections",
    "generate_electrical_visual_projections",
]
