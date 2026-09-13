"""KiCad CLI adapter for reproducible visual projection records."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from acd.adapters.kicad.cli import KicadCli
from acd.adapters.svg.common import (
    COLOR_COPPER,
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
from acd.core.process import DEFAULT_TOOL_TIMEOUT_S, ExternalToolError, run_tool, sha256_bytes
from acd.core.visual_projection import (
    KICAD_LAYER_SVG_NORMALIZATION_RULE_DESCRIPTION,
    KICAD_LAYER_SVG_NORMALIZATION_RULE_ID,
    SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION,
    SVG_TITLE_NORMALIZATION_RULE_ID,
    LayerViewAnnotations,
    measure_svg_resolution,
    raw_svg_parts,
    svg_source_hash,
)
from acd.pipeline.repository import repository_root
from acd.schema.visual_projection import (
    VisualProjectionDomain,
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionType,
    VisualRegenerationCheck,
    VisualRendererProvenance,
    VisualResolution,
)


def _layer_orientation(layer: str) -> str:
    if layer == "F.Cu":
        return "front copper (component side), viewed from top"
    if layer == "B.Cu":
        return "back copper (solder side), viewed from top, not mirrored"
    if layer.startswith("In") and layer.endswith(".Cu"):
        number = layer[2:-3]
        if number.isdigit() and int(number) > 0:
            return f"inner copper layer {int(number)}, viewed from top"
    raise ExternalToolError(f"unsupported KiCad copper layer: {layer}")


def wrap_kicad_layer_svg(raw: bytes, annotations: LayerViewAnnotations) -> bytes:
    """Wrap a raw KiCad copper SVG in an annotated acd-svg document."""
    orientation = _layer_orientation(annotations.layer)
    if (
        not annotations.project_name.strip()
        or not annotations.layer.strip()
        or annotations.layer_count <= 0
        or annotations.board_width_mm <= 0
        or annotations.board_height_mm <= 0
    ):
        raise ExternalToolError("KiCad layer annotations are invalid")
    try:
        measured = measure_svg_resolution(raw)
        raw_view_box, raw_attributes, raw_width, _raw_height, raw_inner = raw_svg_parts(raw)
    except ValueError as exc:
        raise ExternalToolError("raw KiCad layer SVG is invalid") from exc
    if (
        measured.width[-2:] != "mm"
        or measured.height[-2:] != "mm"
        or measured.view_box[2] <= 0
        or measured.view_box[3] <= 0
    ):
        raise ExternalToolError(
            "raw KiCad layer SVG requires positive millimeter dimensions"
        )
    raw_width_mm = float(measured.width[:-2])
    raw_height_mm = float(measured.height[:-2])
    scale = raw_width_mm / raw_width
    font_size = view_box_font_size(
        DIAGRAM_REFERENCE_WIDTH,
        ratio=DIAGRAM_FONT_SIZE_RATIO,
    )
    layer_x = font_size * 4
    layer_y = header_height(font_size) + font_size * 2
    layer_width = raw_width_mm
    layer_height = raw_height_mm
    dimension_y = layer_y + layer_height + font_size * 2
    dimension_x = layer_x + layer_width + font_size * 2
    scale_bar_y = dimension_y + font_size * 3.5
    legend_y = scale_bar_y + font_size * 3
    note_y = legend_y + font_size * 2
    outer_height = note_y + footer_height(font_size) + font_size * 3
    stroke = max(font_size * 0.08, 0.1)
    tick = font_size * 0.6
    width_label = svg_text(
        f"{format_svg_number(annotations.board_width_mm)} mm",
        x=layer_x + annotations.board_width_mm * scale / 2,
        y=dimension_y + font_size * 1.5,
        font_size=font_size,
        element_id="dimension-width-label",
        anchor="middle",
    )
    height_label_x = dimension_x + font_size * 1.4
    height_label = svg_text(
        f"{format_svg_number(annotations.board_height_mm)} mm",
        x=height_label_x,
        y=layer_y + annotations.board_height_mm * scale / 2,
        font_size=font_size,
        element_id="dimension-height-label",
        extra=(
            f'transform="rotate(90 {format_svg_number(height_label_x)} '
            f'{format_svg_number(layer_y + annotations.board_height_mm * scale / 2)})"'
        ),
    )
    board_width = annotations.board_width_mm * scale
    board_height = annotations.board_height_mm * scale
    outline_label = svg_text(
        "declared board outline",
        x=layer_x,
        y=layer_y - font_size * 0.6,
        font_size=font_size,
        fill=COLOR_FRONT,
    )
    scale_label = svg_text(
        "10 mm",
        x=layer_x + 5 * scale,
        y=scale_bar_y + font_size * 1.3,
        font_size=font_size,
        anchor="middle",
    )
    body: list[str] = [
        (
            f'<svg id="layer-view" x="{format_svg_number(layer_x)}" '
            f'y="{format_svg_number(layer_y)}" width="{measured.width}" '
            f'height="{measured.height}" viewBox="{raw_view_box}"'
            f"{(' ' + raw_attributes) if raw_attributes else ''}>{raw_inner}</svg>"
        ),
        (
            f'<g id="board-outline" fill="none" stroke="{COLOR_FRONT}" '
            f'stroke-width="{format_svg_number(stroke)}" '
            f'stroke-dasharray="{format_svg_number(font_size)} '
            f'{format_svg_number(font_size * 0.6)}">'
            f'<rect x="{format_svg_number(layer_x)}" y="{format_svg_number(layer_y)}" '
            f'width="{format_svg_number(board_width)}" height="{format_svg_number(board_height)}"/>'
            f"{outline_label}"
            "</g>"
        ),
        (
            f'<g id="dimension-width" fill="none" stroke="{COLOR_EDGE}" '
            f'stroke-width="{format_svg_number(stroke)}">'
            f'<line x1="{format_svg_number(layer_x)}" y1="{format_svg_number(dimension_y)}" '
            f'x2="{format_svg_number(layer_x + board_width)}" '
            f'y2="{format_svg_number(dimension_y)}"/>'
            f'<line x1="{format_svg_number(layer_x)}" y1="{format_svg_number(dimension_y - tick)}" '
            f'x2="{format_svg_number(layer_x)}" y2="{format_svg_number(dimension_y + tick)}"/>'
            f'<line x1="{format_svg_number(layer_x + board_width)}" '
            f'y1="{format_svg_number(dimension_y - tick)}" '
            f'x2="{format_svg_number(layer_x + board_width)}" '
            f'y2="{format_svg_number(dimension_y + tick)}"/>'
            f"</g>{width_label}"
        ),
        (
            f'<g id="dimension-height" fill="none" stroke="{COLOR_EDGE}" '
            f'stroke-width="{format_svg_number(stroke)}">'
            f'<line x1="{format_svg_number(dimension_x)}" y1="{format_svg_number(layer_y)}" '
            f'x2="{format_svg_number(dimension_x)}" '
            f'y2="{format_svg_number(layer_y + board_height)}"/>'
            f'<line x1="{format_svg_number(dimension_x - tick)}" y1="{format_svg_number(layer_y)}" '
            f'x2="{format_svg_number(dimension_x + tick)}" y2="{format_svg_number(layer_y)}"/>'
            f'<line x1="{format_svg_number(dimension_x - tick)}" '
            f'y1="{format_svg_number(layer_y + board_height)}" '
            f'x2="{format_svg_number(dimension_x + tick)}" '
            f'y2="{format_svg_number(layer_y + board_height)}"/>'
            f"</g>{height_label}"
        ),
        (
            f'<g id="scale-bar"><line x1="{format_svg_number(layer_x)}" '
            f'y1="{format_svg_number(scale_bar_y)}" '
            f'x2="{format_svg_number(layer_x + 10 * scale)}" '
            f'y2="{format_svg_number(scale_bar_y)}" stroke="{COLOR_EDGE}" '
            f'stroke-width="{format_svg_number(stroke * 2)}"/>'
            f"{scale_label}"
            "</g>"
        ),
    ]
    body.extend(
        legend(
            [
                ("copper (this layer)", COLOR_COPPER, COLOR_COPPER),
                ("declared board outline", "none", COLOR_FRONT),
            ],
            x=layer_x,
            y=legend_y,
            font_size=font_size,
        )
    )
    body.append(
        svg_text(
            orientation,
            x=layer_x,
            y=note_y,
            font_size=font_size,
            element_id="orientation-note",
            fill=COLOR_TEXT_MUTED,
        )
    )
    return svg_document(
        width=DIAGRAM_REFERENCE_WIDTH,
        height=outer_height,
        title=f"{annotations.project_name} — {annotations.layer}",
        subtitle=(
            f"{orientation}; {annotations.layer_count}-layer board, "
            f"{format_svg_number(annotations.board_width_mm)} × "
            f"{format_svg_number(annotations.board_height_mm)} mm"
        ),
        body=body,
        font_size=font_size,
    )


class KicadVisualRenderer:
    """Render supported KiCad visual projections and verify regeneration."""

    def __init__(self, kicad: KicadCli | None = None) -> None:
        self.kicad = kicad or KicadCli()

    def _export(
        self,
        projection_type: VisualProjectionType,
        source: Path,
        output: Path,
        envelope: Path,
        target_revision: str,
        layer: str | None,
    ) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        export_dir: Path | None = None
        if projection_type == "schematic_view":
            # Isolate KiCad sheet output from sibling visual exports.
            export_dir = output.parent / f".{output.stem}.kicad-export"
            export_dir.mkdir(parents=True, exist_ok=True)
            for existing_output in export_dir.glob("*.svg"):
                existing_output.unlink()
            generated_output = export_dir / f"{source.stem}.svg"
            command = [
                self.kicad.executable,
                "sch",
                "export",
                "svg",
                "-o",
                str(export_dir),
                str(source),
            ]
        else:
            if layer is None or not layer.strip():
                raise ExternalToolError("layered layout view requires a layer")
            generated_output = output
            command = [
                self.kicad.executable,
                "pcb",
                "export",
                "svg",
                "--layers",
                layer,
                "--page-size-mode",
                "2",
                "-o",
                str(output),
                str(source),
            ]
        try:
            run_tool(
                tool_name="kicad-cli",
                tool_version=self.kicad.version(),
                format_version="SVG",
                command=command,
                input_paths=[source],
                output_paths=[generated_output],
                envelope_path=envelope,
                target_revision=target_revision,
                measurement_conditions="single SVG export; measured root dimensions",
                timeout_s=DEFAULT_TOOL_TIMEOUT_S,
            )
            if projection_type == "schematic_view":
                assert export_dir is not None
                unexpected_outputs = set(export_dir.glob("*.svg")) - {generated_output}
                if unexpected_outputs:
                    raise ExternalToolError(
                        "kicad-cli schematic export produced multiple SVG outputs"
                    )
                try:
                    generated_output.replace(output)
                except OSError as exc:
                    raise ExternalToolError(
                        "kicad-cli schematic SVG output could not be normalized to target path"
                    ) from exc
        finally:
            if export_dir is not None:
                shutil.rmtree(export_dir)

    @staticmethod
    def _resolve_within_base(path: Path, base_dir: Path, field_name: str) -> Path:
        candidate = path if path.is_absolute() else base_dir / path
        resolved = candidate.resolve()
        try:
            resolved.relative_to(base_dir)
        except ValueError as exc:
            raise ExternalToolError(
                f"visual projection {field_name} must stay within base directory"
            ) from exc
        return resolved

    def render(
        self,
        *,
        projection_id: str,
        projection_type: VisualProjectionType,
        domain: VisualProjectionDomain,
        source_revision: str,
        source: Path,
        output_path: Path,
        layer: str | None = None,
        layer_annotations: LayerViewAnnotations | None = None,
        base_dir: Path | None = None,
    ) -> VisualProjectionRecord:
        if projection_type == "layered_layout_view" and layer_annotations is None:
            raise ExternalToolError("layered layout view requires layer annotations")
        if projection_type == "schematic_view" and layer_annotations is not None:
            raise ExternalToolError("schematic view does not accept layer annotations")
        if projection_type == "layered_layout_view":
            assert layer_annotations is not None
        layer_annotations_value = layer_annotations
        root = (base_dir or repository_root()).resolve()
        source_path = self._resolve_within_base(source, root, "source")
        output = self._resolve_within_base(output_path, root, "output")
        reproduction_path = output.parent / "reproduction" / (
            f"{output.stem}.reproduced{output.suffix}"
        )
        reproduction_path.parent.mkdir(parents=True, exist_ok=True)
        normalization_rule_id = (
            KICAD_LAYER_SVG_NORMALIZATION_RULE_ID
            if projection_type == "layered_layout_view"
            else SVG_TITLE_NORMALIZATION_RULE_ID
        )
        normalization_rule_description = (
            KICAD_LAYER_SVG_NORMALIZATION_RULE_DESCRIPTION
            if projection_type == "layered_layout_view"
            else SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION
        )

        def export_final(destination: Path) -> None:
            if projection_type != "layered_layout_view":
                self._export(
                    projection_type,
                    source_path,
                    destination,
                    destination.with_suffix(destination.suffix + ".envelope.json"),
                    source_revision,
                    layer,
                )
                return
            with NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".raw",
                delete=False,
            ) as temporary:
                raw_path = Path(temporary.name)
            try:
                self._export(
                    projection_type,
                    source_path,
                    raw_path,
                    destination.with_suffix(destination.suffix + ".envelope.json"),
                    source_revision,
                    layer,
                )
                if layer_annotations_value is None:
                    raise ExternalToolError(
                        "layered layout view requires layer annotations"
                    )
                destination.write_bytes(
                    wrap_kicad_layer_svg(
                        raw_path.read_bytes(), layer_annotations_value
                    )
                )
            finally:
                raw_path.unlink(missing_ok=True)

        export_final(output)
        first = output.read_bytes()
        first_hash = svg_source_hash(first, normalization_rule_id)
        measured = measure_svg_resolution(first)
        export_final(reproduction_path)
        second_hash = svg_source_hash(reproduction_path.read_bytes(), normalization_rule_id)
        if first_hash != second_hash:
            raise ExternalToolError("visual projection regeneration hash mismatch")
        source_record_path = source_path.relative_to(root).as_posix()
        output_record_path = output.relative_to(root).as_posix()
        return VisualProjectionRecord(
            projection_id=projection_id,
            projection_type=projection_type,
            domain=domain,
            source_revision=source_revision,
            input_files=[
                VisualProjectionInput(
                    path=source_record_path,
                    content_hash=sha256_bytes(source_path.read_bytes()),
                )
            ],
            renderer=VisualRendererProvenance(tool_version=self.kicad.version()),
            resolution=VisualResolution(
                width=measured.width,
                height=measured.height,
                view_box=measured.view_box,
            ),
            normalization_rule_id=normalization_rule_id,
            normalization_rule_description=normalization_rule_description,
            image_hash=first_hash,
            generated_at=datetime.now(UTC),
            regeneration_check=VisualRegenerationCheck(
                status="reproduced",
                first_image_hash=first_hash,
                second_image_hash=second_hash,
            ),
            image_path=output_record_path,
        )
