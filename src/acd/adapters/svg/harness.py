"""Deterministic SVG projection for a declared wire harness."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Literal

from acd.adapters.svg.common import (
    ACD_SVG_RENDERER_VERSION,
    COLOR_EDGE,
    COLOR_FRONT,
    COLOR_TEXT_MUTED,
    DIAGRAM_REFERENCE_WIDTH,
    SvgVisualProjectionError,
    diagram_font_size,
    footer_height,
    format_svg_number,
    header_height,
    input_records,
    render_svg_projection,
    slugify_identifier,
    svg_document,
    svg_text,
    text_advance,
)
from acd.core.electrical import ElectricalLane
from acd.schema.harness import HarnessContract
from acd.schema.visual_projection import (
    VisualProjectionInput,
    VisualProjectionRecord,
)

HarnessProjectionType = Literal["harness_view"]


def _harness_svg(contract: HarnessContract, lane: ElectricalLane) -> bytes:
    font_size = diagram_font_size()
    small = font_size * 0.8
    margin = font_size * 2
    connectors = sorted(contract.connectors, key=lambda item: item.connector_id)
    wires = sorted(contract.wires, key=lambda item: item.wire_id)
    if not connectors or not wires:
        raise SvgVisualProjectionError("harness projection requires connectors and wires")
    box_width = max(
        font_size * 8,
        max(text_advance(item.connector_id, font_size, bold=True) for item in connectors)
        + font_size * 2,
    )
    box_height = font_size * (3 + max(
        len(
            {
                endpoint.cavity
                for wire in wires
                for endpoint in (wire.from_, wire.to)
                if endpoint.connector_id == connector.connector_id
            }
        )
        for connector in connectors
    ))
    gap = font_size * 25
    left_x = margin
    right_x = left_x + box_width + gap
    top_y = header_height(font_size) + font_size * 2
    connector_positions = {
        connector.connector_id: (
            left_x if index == 0 else right_x,
            top_y,
        )
        for index, connector in enumerate(connectors)
    }
    if len(connectors) > 2:
        connector_positions = {
            connector.connector_id: (
                left_x + index * (box_width + gap),
                top_y,
            )
            for index, connector in enumerate(connectors)
        }
    cavity_order = {
        connector.connector_id: sorted(
            {
                endpoint.cavity
                for wire in wires
                for endpoint in (wire.from_, wire.to)
                if endpoint.connector_id == connector.connector_id
            }
        )
        for connector in connectors
    }
    cavity_y = {
        connector_id: {
            cavity: top_y + font_size * (2.5 + index)
            for index, cavity in enumerate(cavities)
        }
        for connector_id, cavities in cavity_order.items()
    }
    body: list[str] = []
    for connector in connectors:
        x, y = connector_positions[connector.connector_id]
        body.extend(
            [
                f'<g id="connector-{slugify_identifier(connector.connector_id)}">',
                f'<rect x="{format_svg_number(x)}" y="{format_svg_number(y)}" '
                f'width="{format_svg_number(box_width)}" '
                f'height="{format_svg_number(box_height)}" '
                f'rx="{format_svg_number(font_size * 0.3)}" '
                f'fill="#e0ecf8" stroke="{COLOR_FRONT}" '
                f'stroke-width="{format_svg_number(font_size * 0.15)}"/>',
                svg_text(
                    connector.connector_id,
                    x=x + box_width / 2,
                    y=y + font_size * 1.4,
                    font_size=font_size,
                    anchor="middle",
                    weight="bold",
                ),
            ]
        )
        for cavity in cavity_order[connector.connector_id]:
            cy = cavity_y[connector.connector_id][cavity]
            body.append(
                svg_text(
                    cavity,
                    x=x + font_size,
                    y=cy,
                    font_size=small,
                    fill=COLOR_TEXT_MUTED,
                )
            )
        body.append("</g>")
    for index, wire in enumerate(wires):
        source = (
            connector_positions[wire.from_.connector_id][0] + box_width,
            cavity_y[wire.from_.connector_id][wire.from_.cavity],
        )
        target = (
            connector_positions[wire.to.connector_id][0],
            cavity_y[wire.to.connector_id][wire.to.cavity],
        )
        y_offset = (1 - index % 3) * font_size * 0.35
        mid_x = (source[0] + target[0]) / 2
        label = f"{wire.wire_id} / {wire.net_id} / {wire.wire_type_id}"
        body.extend(
            [
                f'<path id="wire-{slugify_identifier(wire.wire_id)}" '
                f'd="M {format_svg_number(source[0])} {format_svg_number(source[1])} '
                f'H {format_svg_number(mid_x)} V {format_svg_number(source[1] + y_offset)} '
                f'H {format_svg_number(target[0])} V {format_svg_number(target[1])}" '
                f'fill="none" stroke="{COLOR_EDGE}" '
                f'stroke-width="{format_svg_number(font_size * 0.13)}"/>',
                svg_text(
                    label,
                    x=mid_x,
                    y=top_y + box_height + font_size * (1.5 + index * 1.2),
                    font_size=small,
                    anchor="middle",
                ),
            ]
        )
    title = f"Harness — {contract.harness_id}"
    subtitle = f"{len(connectors)} connectors, {len(wires)} wires, graph {contract.graph_id}"
    width = max(
        DIAGRAM_REFERENCE_WIDTH,
        max(x for x, _ in connector_positions.values()) + box_width + margin,
        text_advance(title, font_size * 1.8, bold=True) + margin * 2,
    )
    height = top_y + box_height + font_size * 7 + footer_height(font_size)
    return svg_document(
        width=width,
        height=height,
        title=title,
        subtitle=subtitle,
        body=body,
        font_size=font_size,
    )


class SvgHarnessRenderer:
    """Render harness SVG without external tools."""

    renderer_type: ClassVar[Literal["acd-svg"]] = "acd-svg"
    tool_name: ClassVar[Literal["acd-svg"]] = "acd-svg"

    def __init__(self, *, tool_version: str = ACD_SVG_RENDERER_VERSION) -> None:
        if not tool_version or tool_version == "unknown":
            raise SvgVisualProjectionError("renderer version is unknown")
        self.tool_version = tool_version

    def render(
        self,
        *,
        projection_id: str,
        source_revision: str,
        graph: object,
        lane: ElectricalLane,
        contract: HarnessContract,
        input_files: list[VisualProjectionInput],
        output_path: Path,
        base_dir: Path,
    ) -> VisualProjectionRecord:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return render_svg_projection(
            projection_id=projection_id,
            projection_type="harness_view",
            domain="electrical",
            source_revision=source_revision,
            input_files=input_files,
            output_path=output_path,
            base_dir=base_dir,
            tool_version=self.tool_version,
            write_svg=lambda path: _write_harness_svg(path, contract, lane),
        )


def _write_harness_svg(path: Path, contract: HarnessContract, lane: ElectricalLane) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_harness_svg(contract, lane))


def generate_harness_visual_projection(
    *,
    out_dir: Path,
    source_revision: str,
    graph: object,
    lane: ElectricalLane,
    contract: HarnessContract,
    authoritative_inputs: tuple[Path, ...],
    input_base_dir: Path,
    renderer: SvgHarnessRenderer | None = None,
) -> VisualProjectionRecord:
    if getattr(graph, "revision", None) != source_revision:
        raise SvgVisualProjectionError("harness graph revision does not match source revision")
    inputs = input_records(authoritative_inputs, input_base_dir)
    renderer = renderer or SvgHarnessRenderer()
    return renderer.render(
        projection_id=f"{slugify_identifier(contract.harness_id)}-harness",
        source_revision=source_revision,
        graph=graph,
        lane=lane,
        contract=contract,
        input_files=inputs,
        output_path=out_dir / "harness.svg",
        base_dir=out_dir,
    )
