"""Electrical-lane visual projection wiring after deterministic gates."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

from acd.adapters.kicad.gates import GateError
from acd.adapters.kicad.visual_projection import (
    KicadVisualRenderer,
    copper_layers_for_layer_count,
)
from acd.adapters.raster import CairoSvgRasterizer
from acd.core.board_model import BoardModel
from acd.core.electrical import ElectricalLane
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
    return VisualProjectionInput(
        path=relative,
        content_hash=sha256_bytes(resolved.read_bytes()),
    )


def _projection_crosscheck(
    *,
    projection: object,
    expected_refdes: tuple[str, ...],
    base_dir: Path,
) -> VisualProjectionCrosscheck:
    from acd.schema.visual_projection import VisualProjectionRecord

    if not isinstance(projection, VisualProjectionRecord):
        raise ValueError("visual crosscheck projection record is invalid")
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
    items: list[VisualCrosscheckItem] = []
    items.append(
        _crosscheck_item(
            check_id="svg-units",
            description="SVG width and height use millimetres",
            expected="width=mm; height=mm",
            actual=f"width={width_unit}; height={height_unit}",
            machine_field="VisualProjectionRecord.resolution.width/height",
            status="match" if width_unit == "mm" and height_unit == "mm" else "mismatch",
        )
    )
    items.append(
        _crosscheck_item(
            check_id="svg-origin",
            description="SVG viewBox origin is zero",
            expected="0 0",
            actual=f"{view_box[0]} {view_box[1]}",
            machine_field="ElectricalLane.board.origin",
            status="match" if view_box_numbers[:2] == (Decimal("0"), Decimal("0")) else "mismatch",
        )
    )
    items.append(
        _crosscheck_item(
            check_id="svg-viewbox",
            description="SVG viewBox dimensions match root dimensions",
            expected=f"{width_value} {height_value}",
            actual=f"{view_box[2]} {view_box[3]}",
            machine_field="ElectricalLane.board.width_mm/height_mm",
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
            base_dir=base_dir,
        )
        record = record.model_copy(
            update={
                "items": [coverage_item, *record.items],
                "status": _status_for_items([coverage_item, *record.items]),
            }
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
        crosschecks=sorted(records, key=lambda record: record.projection_id),
        review_items=review_items,
        status=_status_for_items(
            [
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


__all__ = [
    "crosscheck_electrical_visual_projections",
    "derive_png_visual_projections",
    "generate_electrical_visual_projections",
]
