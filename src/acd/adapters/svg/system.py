"""Deterministic SVG writers for system and power-tree observations."""

from __future__ import annotations

import math
from pathlib import Path
from typing import ClassVar, Literal, get_args

from acd.adapters.svg.common import (
    ACD_SVG_RENDERER_VERSION,
    COLOR_EDGE,
    COLOR_EDGE_MUTED,
    COLOR_HEADER_RULE,
    COLOR_TEXT_MUTED,
    DIAGRAM_REFERENCE_WIDTH,
    KIND_FILL,
    KIND_STROKE,
    SMALL_FONT_SCALE,
    SvgVisualProjectionError,
    arrow_marker_defs,
    diagram_font_size,
    escape_xml,
    footer_height,
    format_svg_number,
    header_height,
    input_records,
    legend,
    render_svg_projection,
    slugify_identifier,
    svg_document,
    svg_text,
    text_advance,
)
from acd.core.electrical import ElectricalLane, NetView
from acd.schema.design_graph import DesignGraph, GraphNode, NodeKind
from acd.schema.visual_projection import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionSet,
)

# Both system projections are laid out on a fixed 240-unit wide viewBox.
_DIAGRAM_VIEW_BOX_WIDTH = DIAGRAM_REFERENCE_WIDTH

_KNOWN_NODE_KINDS = frozenset(get_args(NodeKind))
_BLOCK_DRAW_KINDS = frozenset(
    {
        "electrical.board",
        "electrical.component",
        "electrical.net",
        "firmware.module",
        "safety.boundary",
    }
)
_BLOCK_OMIT_KINDS = frozenset(
    {
        # Pin-level electrical nodes are represented through component blocks.
        "electrical.pin",
        # Requirements and manufacturing intents are not system blocks.
        "requirement",
        # Functional-block declarations select contracts but are not system blocks.
        "design.functional_block",
        "electrical.placement_group",
        "fab.order_intent",
        "fab.process_allowance",
        # Mechanical geometry and graphics belong to mechanical projections.
        "mechanical.outline",
        "mechanical.component_body",
        "mechanical.connector_opening",
        "mechanical.board_edge_overhang",
        "mechanical.enclosure",
        "mechanical.silk_text",
        "mechanical.silk_graphic",
        # Firmware pin assignments are not firmware module blocks.
        "firmware.pin_assignment",
        # Firmware state and sequence nodes belong to dedicated FW projections.
        "firmware.state",
        "firmware.state_transition",
        "firmware.sequence_step",
        # Evidence anchors are provenance references, not system blocks.
        "evidence.anchor",
    }
)


def validate_block_node_kind_partition() -> None:
    """Reject a renderer classification that is out of sync with NodeKind."""
    if (
        _BLOCK_DRAW_KINDS & _BLOCK_OMIT_KINDS
        or _BLOCK_DRAW_KINDS | _BLOCK_OMIT_KINDS != _KNOWN_NODE_KINDS
    ):
        raise SvgVisualProjectionError(
            "system block node-kind classification is incomplete"
        )


def _validate_node_kinds(graph: DesignGraph) -> None:
    validate_block_node_kind_partition()
    unknown = sorted({str(node.kind) for node in graph.nodes} - _KNOWN_NODE_KINDS)
    if unknown:
        raise SvgVisualProjectionError(
            f"system block projection encountered unknown node kinds: {unknown}"
        )


def _block_edges(
    graph: DesignGraph,
    nodes: dict[str, GraphNode],
) -> list[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for node in nodes.values():
        for dependency in sorted(node.depends_on):
            try:
                target = graph.node_by_id(dependency)
            except KeyError as exc:
                raise SvgVisualProjectionError(
                    f"system block dependency does not exist: {dependency!r}"
                ) from exc
            if target.kind in _BLOCK_DRAW_KINDS:
                edges.add((node.id, dependency))
            elif target.kind not in _BLOCK_OMIT_KINDS:
                raise SvgVisualProjectionError(
                    f"system block dependency has unknown node kind: {target.kind!r}"
                )
    if not edges:
        raise SvgVisualProjectionError(
            "system block projection requires at least one depends_on edge"
        )
    return sorted(edges)


# Swimlane order (top to bottom) and human-facing lane titles.
_BLOCK_LANE_ORDER: tuple[str, ...] = (
    "safety.boundary",
    "electrical.board",
    "firmware.module",
    "electrical.component",
    "electrical.net",
)
_BLOCK_LANE_TITLES = {
    "safety.boundary": "Safety boundary",
    "electrical.board": "Board",
    "firmware.module": "Firmware",
    "electrical.component": "Components",
    "electrical.net": "Nets",
}


def _block_human_label(node: GraphNode, lane: ElectricalLane) -> str:
    """Human-facing primary label; the node id is always shown as secondary."""
    if node.kind == "electrical.component":
        component = next(
            (item for item in lane.components if item.node_id == node.id), None
        )
        if component is not None:
            return f"{component.refdes} {component.value}".strip()
    elif node.kind == "electrical.net":
        net = next((item for item in lane.nets if item.node_id == node.id), None)
        if net is not None:
            return net.name
    elif node.kind == "firmware.module":
        module_name = node.attrs.get("module_name")
        if isinstance(module_name, str) and module_name:
            return module_name
    return _BLOCK_LANE_TITLES[node.kind]


def _block_svg(graph: DesignGraph, lane: ElectricalLane) -> bytes:
    _validate_node_kinds(graph)
    nodes = {
        node.id: node for node in graph.nodes if node.kind in _BLOCK_DRAW_KINDS
    }
    if not nodes:
        raise SvgVisualProjectionError("system block projection has no drawable nodes")
    edges = _block_edges(graph, nodes)
    ordered = sorted(nodes.values(), key=lambda node: node.id)
    font_size = diagram_font_size()
    small = font_size * SMALL_FONT_SCALE
    width = _DIAGRAM_VIEW_BOX_WIDTH
    margin = font_size * 2
    lane_label_width = font_size * 12
    grid_left = margin + lane_label_width
    grid_width = width - grid_left - margin
    box_height = font_size * 4.2
    gap = font_size * 1.6
    row_pitch = box_height + gap

    labels = {node.id: _block_human_label(node, lane) for node in ordered}
    lanes = [
        (kind, [node for node in ordered if node.kind == kind])
        for kind in _BLOCK_LANE_ORDER
        if any(node.kind == kind for node in ordered)
    ]
    positions: dict[str, tuple[float, float, float]] = {}
    lane_bands: list[tuple[str, float, float]] = []
    band_by_kind: dict[str, tuple[float, float]] = {}
    y = header_height(font_size) + font_size * 3.5
    for kind, lane_nodes in lanes:
        longest = max(
            max(
                text_advance(labels[node.id], font_size, bold=True),
                text_advance(node.id, small),
            )
            for node in lane_nodes
        )
        box_width = min(max(longest + font_size * 1.5, font_size * 12), grid_width)
        columns = max(1, int((grid_width + gap) // (box_width + gap)))
        rows = math.ceil(len(lane_nodes) / columns)
        band_top = y - gap / 2
        for index, node in enumerate(lane_nodes):
            column = index % columns
            row = index // columns
            positions[node.id] = (
                grid_left + column * (box_width + gap),
                y + row * row_pitch,
                box_width,
            )
        y += rows * row_pitch
        lane_bands.append((kind, band_top, y - gap / 2))
        band_by_kind[kind] = (band_top, y - gap / 2)
        y += gap
    height = y + footer_height(font_size)

    body = [arrow_marker_defs(font_size), '<g id="system-block">']
    body += legend(
        [
            (_BLOCK_LANE_TITLES[kind], KIND_FILL[kind], KIND_STROKE[kind])
            for kind, _ in lanes
        ],
        x=margin,
        y=header_height(font_size) + font_size * 1.2,
        font_size=small,
        element_id="block-legend",
    )
    body.append('<g id="block-lanes">')
    for kind, top, bottom in lane_bands:
        body.append(
            f'<rect x="{format_svg_number(margin)}" y="{format_svg_number(top)}" '
            f'width="{format_svg_number(width - 2 * margin)}" '
            f'height="{format_svg_number(bottom - top)}" fill="{KIND_FILL[kind]}" '
            f'fill-opacity="0.35" stroke="none"/>'
        )
        body.append(
            svg_text(
                _BLOCK_LANE_TITLES[kind],
                x=margin + font_size * 0.6,
                y=top + font_size * 2.2,
                font_size=font_size,
                weight="bold",
                fill=KIND_STROKE[kind],
            )
        )
        body.append(
            svg_text(
                kind,
                x=margin + font_size * 0.6,
                y=top + font_size * 3.6,
                font_size=small,
                fill=COLOR_TEXT_MUTED,
            )
        )
    body.append("</g>")
    body.append('<g id="block-edges">')
    # Orthogonal bus routing that never crosses a box: leave the source box
    # vertically to a bus just outside its lane band, run to the trunk left of
    # the grid, travel to a bus just outside the target band, drop down the
    # channel left of the target column and enter the target from its left.
    trunk_x = grid_left - gap * 0.4
    for source, target in edges:
        sx, sy, sw = positions[source]
        tx, ty, _ = positions[target]
        source_top, source_bottom = band_by_kind[nodes[source].kind]
        target_top, target_bottom = band_by_kind[nodes[target].kind]
        downward = ty >= sy
        start_y = sy + box_height if downward else sy
        source_bus_y = (
            source_bottom + gap * 0.25 if downward else source_top - gap * 0.25
        )
        target_bus_y = (
            target_top - gap * 0.25 if downward else target_bottom + gap * 0.25
        )
        channel_x = tx - gap / 2
        end_y = ty + box_height / 2
        edge_id = (
            f"block-edge-{slugify_identifier(source)}-"
            f"{slugify_identifier(target)}"
        )
        body.append(
            f'<path id="{edge_id}" d="M {format_svg_number(sx + sw / 2)} '
            f"{format_svg_number(start_y)} V {format_svg_number(source_bus_y)} "
            f"H {format_svg_number(trunk_x)} V {format_svg_number(target_bus_y)} "
            f"H {format_svg_number(channel_x)} V {format_svg_number(end_y)} "
            f'H {format_svg_number(tx)}" '
            f'fill="none" stroke="{COLOR_EDGE_MUTED}" '
            f'stroke-width="{format_svg_number(font_size * 0.15)}" '
            'marker-end="url(#arrow)"/>'
        )
    body.append("</g>")
    for kind, lane_nodes in lanes:
        body.append(f'<g id="block-kind-{slugify_identifier(kind)}">')
        for node in lane_nodes:
            x, node_y, box_width = positions[node.id]
            identifier = slugify_identifier(node.id)
            body.extend(
                [
                    f'<g id="block-node-{identifier}" data-node-id="{escape_xml(node.id)}" '
                    f'data-node-kind="{escape_xml(node.kind)}">',
                    f'<rect id="block-box-{identifier}" '
                    f'x="{format_svg_number(x)}" y="{format_svg_number(node_y)}" '
                    f'width="{format_svg_number(box_width)}" '
                    f'height="{format_svg_number(box_height)}" '
                    f'rx="{format_svg_number(font_size * 0.4)}" '
                    f'fill="{KIND_FILL[kind]}" stroke="{KIND_STROKE[kind]}" '
                    f'stroke-width="{format_svg_number(font_size * 0.18)}"/>',
                    svg_text(
                        labels[node.id],
                        x=x + font_size * 0.7,
                        y=node_y + font_size * 1.7,
                        font_size=font_size,
                        element_id=f"block-label-{identifier}",
                        weight="bold",
                    ),
                    svg_text(
                        node.id,
                        x=x + font_size * 0.7,
                        y=node_y + font_size * 3.4,
                        font_size=small,
                        element_id=f"block-kind-label-{identifier}",
                        fill=COLOR_TEXT_MUTED,
                    ),
                    "</g>",
                ]
            )
        body.append("</g>")
    body.append("</g>")
    return svg_document(
        width=width,
        height=height,
        title="System block diagram",
        subtitle=(
            f"{graph.graph_id} {graph.revision} - {len(ordered)} blocks, "
            f"{len(edges)} dependency edges (arrow points to the dependency)"
        ),
        body=body,
        font_size=font_size,
    )


def _power_connections(
    net: NetView,
    lane: ElectricalLane,
    graph: DesignGraph,
) -> tuple[str, list[str]]:
    if net.voltage_nominal_v is None or not math.isfinite(net.voltage_nominal_v):
        raise SvgVisualProjectionError(
            f"power rail {net.node_id}: voltage declaration is missing or invalid"
        )
    source_pin_id = net.power_source_pin
    if not source_pin_id:
        raise SvgVisualProjectionError(
            f"power rail {net.node_id}: power_source_pin is undeclared"
        )
    try:
        source_pin_node = graph.node_by_id(source_pin_id)
    except KeyError as exc:
        raise SvgVisualProjectionError(
            f"power rail {net.node_id}: power_source_pin does not exist"
        ) from exc
    if source_pin_node.kind != "electrical.pin":
        raise SvgVisualProjectionError(
            f"power rail {net.node_id}: power_source_pin is not an electrical.pin"
        )
    source_pin = next(
        (pin for pin in lane.pins if pin.node_id == source_pin_id),
        None,
    )
    if source_pin is None or source_pin.net_id != net.node_id:
        raise SvgVisualProjectionError(
            f"power rail {net.node_id}: power_source_pin is not connected to the rail"
        )
    try:
        lane.component_by_id(source_pin.component_id)
    except KeyError as exc:
        raise SvgVisualProjectionError(
            f"power rail {net.node_id}: source component does not exist"
        ) from exc
    connected_components = sorted(
        {
            pin.component_id
            for pin in lane.pins
            if pin.net_id == net.node_id
        }
    )
    load_ids = [
        component_id
        for component_id in connected_components
        if component_id != source_pin.component_id
    ]
    if not load_ids:
        raise SvgVisualProjectionError(
            f"power rail {net.node_id}: no load pin is connected"
        )
    return source_pin.component_id, load_ids


def _power_nets(lane: ElectricalLane) -> tuple[NetView, ...]:
    nets = tuple(net for net in lane.nets if net.power_rail)
    if not nets:
        raise SvgVisualProjectionError(
            "power tree projection has no declared power rails"
        )
    return tuple(sorted(nets, key=lambda net: net.node_id))


def _component_caption(lane: ElectricalLane, component_id: str) -> tuple[str, str]:
    """Return `(refdes value, mpn)` for a component node id."""
    component = lane.component_by_id(component_id)
    return f"{component.refdes} {component.value}".strip(), component.mpn


def _power_tree_svg(lane: ElectricalLane, graph: DesignGraph) -> bytes:
    nets = _power_nets(lane)
    font_size = diagram_font_size()
    small = font_size * SMALL_FONT_SCALE
    width = _DIAGRAM_VIEW_BOX_WIDTH
    margin = font_size * 2
    box_height = font_size * 4.2
    load_pitch = box_height + font_size * 0.8
    row_gap = font_size * 3.0
    rows: list[tuple[NetView, str, list[str], float, float]] = []
    y = header_height(font_size) + font_size * 3.0
    captions: list[str] = []
    for net in nets:
        source_id, load_ids = _power_connections(net, lane, graph)
        row_height = max(box_height, len(load_ids) * load_pitch - font_size * 0.8)
        rows.append((net, source_id, load_ids, y, row_height))
        y += row_height + row_gap
        captions.append(net.name)
        for component_id in (source_id, *load_ids):
            label, mpn = _component_caption(lane, component_id)
            captions.append(label)
            captions.append(f"{mpn} ({component_id})")
    longest = max(
        max(text_advance(text, font_size, bold=True), text_advance(text, small))
        for text in captions
    )
    connector_gap = font_size * 6
    column_width = (width - 2 * margin - 2 * connector_gap) / 3
    # Widen the sheet instead of clipping when a caption does not fit.
    box_width = max(column_width, longest + font_size * 1.5)
    width = max(width, 2 * margin + 3 * box_width + 2 * connector_gap)
    source_x = margin
    net_x = source_x + box_width + connector_gap
    load_x = net_x + box_width + connector_gap
    height = y - row_gap + font_size * 2 + footer_height(font_size)

    body = [arrow_marker_defs(font_size), '<g id="power-tree">']
    column_title_y = header_height(font_size) + font_size * 1.2
    for label, x in (("Source", source_x), ("Power rail", net_x), ("Loads", load_x)):
        body.append(
            svg_text(
                label,
                x=x + box_width / 2,
                y=column_title_y,
                font_size=font_size,
                anchor="middle",
                weight="bold",
                fill=COLOR_TEXT_MUTED,
            )
        )
    for index, (net, source_id, load_ids, row_y, row_height) in enumerate(rows):
        net_identifier = slugify_identifier(net.node_id)
        source_identifier = slugify_identifier(source_id)
        center_y = row_y + row_height / 2
        source_label, source_mpn = _component_caption(lane, source_id)
        if index > 0:
            separator_y = row_y - row_gap / 2
            body.append(
                f'<line x1="{format_svg_number(margin)}" y1="{format_svg_number(separator_y)}" '
                f'x2="{format_svg_number(width - margin)}" y2="{format_svg_number(separator_y)}" '
                f'stroke="{COLOR_HEADER_RULE}" '
                f'stroke-width="{format_svg_number(font_size * 0.08)}" '
                f'stroke-dasharray="{format_svg_number(font_size)} '
                f'{format_svg_number(font_size)}"/>'
            )
        body.extend(
            [
                f'<g id="power-net-{net_identifier}" data-node-id="{escape_xml(net.node_id)}">',
                f'<rect id="power-source-box-{net_identifier}" '
                f'x="{format_svg_number(source_x)}" '
                f'y="{format_svg_number(center_y - box_height / 2)}" '
                f'width="{format_svg_number(box_width)}" height="{format_svg_number(box_height)}" '
                f'rx="{format_svg_number(font_size * 0.4)}" '
                f'fill="{KIND_FILL["electrical.component"]}" '
                f'stroke="{KIND_STROKE["electrical.component"]}" '
                f'stroke-width="{format_svg_number(font_size * 0.18)}"/>',
                svg_text(
                    source_label,
                    x=source_x + font_size * 0.7,
                    y=center_y - box_height / 2 + font_size * 1.7,
                    font_size=font_size,
                    element_id=f"power-source-label-{net_identifier}",
                    weight="bold",
                ),
                svg_text(
                    f"{source_mpn} ({source_id})",
                    x=source_x + font_size * 0.7,
                    y=center_y - box_height / 2 + font_size * 3.4,
                    font_size=small,
                    fill=COLOR_TEXT_MUTED,
                ),
                f'<rect id="power-net-box-{net_identifier}" '
                f'x="{format_svg_number(net_x)}" '
                f'y="{format_svg_number(center_y - box_height / 2)}" '
                f'width="{format_svg_number(box_width)}" height="{format_svg_number(box_height)}" '
                f'rx="{format_svg_number(font_size * 0.4)}" fill="{KIND_FILL["electrical.net"]}" '
                f'stroke="{KIND_STROKE["electrical.net"]}" '
                f'stroke-width="{format_svg_number(font_size * 0.18)}"/>',
                svg_text(
                    net.name,
                    x=net_x + font_size * 0.7,
                    y=center_y - box_height / 2 + font_size * 1.7,
                    font_size=font_size,
                    element_id=f"power-net-label-{net_identifier}",
                    weight="bold",
                ),
                svg_text(
                    f"{net.voltage_nominal_v} V nominal",
                    x=net_x + font_size * 0.7,
                    y=center_y - box_height / 2 + font_size * 3.4,
                    font_size=small,
                    element_id=f"power-voltage-label-{net_identifier}",
                ),
                f'<line id="power-edge-source-{net_identifier}-{source_identifier}" '
                f'x1="{format_svg_number(source_x + box_width)}" '
                f'y1="{format_svg_number(center_y)}" '
                f'x2="{format_svg_number(net_x)}" y2="{format_svg_number(center_y)}" '
                f'stroke="{COLOR_EDGE}" stroke-width="{format_svg_number(font_size * 0.2)}" '
                'marker-end="url(#arrow)"/>',
            ]
        )
        for load_index, load_id in enumerate(load_ids):
            load_identifier = slugify_identifier(load_id)
            load_y = row_y + load_index * load_pitch
            load_center = load_y + box_height / 2
            load_label, load_mpn = _component_caption(lane, load_id)
            bend_x = net_x + box_width + font_size * 3
            body.extend(
                [
                    f'<rect id="power-load-box-{net_identifier}-{load_identifier}" '
                    f'x="{format_svg_number(load_x)}" y="{format_svg_number(load_y)}" '
                    f'width="{format_svg_number(box_width)}" '
                    f'height="{format_svg_number(box_height)}" '
                    f'rx="{format_svg_number(font_size * 0.4)}" '
                    f'fill="{KIND_FILL["electrical.component"]}" '
                    f'stroke="{KIND_STROKE["electrical.component"]}" '
                    f'stroke-width="{format_svg_number(font_size * 0.18)}"/>',
                    svg_text(
                        load_label,
                        x=load_x + font_size * 0.7,
                        y=load_y + font_size * 1.7,
                        font_size=font_size,
                        element_id=f"power-load-label-{net_identifier}-{load_identifier}",
                        weight="bold",
                    ),
                    svg_text(
                        f"{load_mpn} ({load_id})",
                        x=load_x + font_size * 0.7,
                        y=load_y + font_size * 3.4,
                        font_size=small,
                        fill=COLOR_TEXT_MUTED,
                    ),
                    f'<path id="power-edge-load-{net_identifier}-{load_identifier}" '
                    f'd="M {format_svg_number(net_x + box_width)} {format_svg_number(center_y)} '
                    f"H {format_svg_number(bend_x)} V {format_svg_number(load_center)} "
                    f'H {format_svg_number(load_x)}" fill="none" stroke="{COLOR_EDGE}" '
                    f'stroke-width="{format_svg_number(font_size * 0.2)}" '
                    'marker-end="url(#arrow)"/>'
                ]
            )
        body.append("</g>")
    body.append("</g>")
    return svg_document(
        width=width,
        height=height,
        title="Power tree",
        subtitle=(
            f"{graph.graph_id} {graph.revision} - {len(nets)} declared power rails "
            "(source pin from power_source_pin, loads from connected pins)"
        ),
        body=body,
        font_size=font_size,
    )


class SvgSystemRenderer:
    """Render system block and power-tree SVGs without external tools."""

    renderer_type: ClassVar[Literal["acd-svg"]] = "acd-svg"
    tool_name: ClassVar[Literal["acd-svg"]] = "acd-svg"

    def __init__(self, *, tool_version: str = ACD_SVG_RENDERER_VERSION) -> None:
        if not tool_version or tool_version == "unknown":
            raise SvgVisualProjectionError("renderer version is unknown")
        self.tool_version = tool_version

    def _write_svg(
        self,
        *,
        projection_type: Literal["system_block_view", "power_tree_view"],
        graph: DesignGraph,
        lane: ElectricalLane,
        output_path: Path,
    ) -> None:
        content = (
            _block_svg(graph, lane)
            if projection_type == "system_block_view"
            else _power_tree_svg(lane, graph)
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            output_path.write_bytes(content)
        except OSError as exc:
            raise SvgVisualProjectionError(
                f"system SVG could not be written: {output_path}"
            ) from exc

    def render(
        self,
        *,
        projection_id: str,
        projection_type: Literal["system_block_view", "power_tree_view"],
        source_revision: str,
        graph: DesignGraph,
        lane: ElectricalLane,
        input_files: list[VisualProjectionInput],
        output_path: Path,
        base_dir: Path,
    ) -> VisualProjectionRecord:
        if projection_type not in {"system_block_view", "power_tree_view"}:
            raise SvgVisualProjectionError("unsupported system projection type")
        return render_svg_projection(
            projection_id=projection_id,
            projection_type=projection_type,
            domain="system",
            source_revision=source_revision,
            input_files=input_files,
            output_path=output_path,
            base_dir=base_dir,
            tool_version=self.tool_version,
            write_svg=lambda path: self._write_svg(
                projection_type=projection_type,
                graph=graph,
                lane=lane,
                output_path=path,
            ),
        )


def generate_system_visual_projections(
    *,
    project_name: str,
    out_dir: Path,
    source_revision: str,
    graph: DesignGraph,
    lane: ElectricalLane,
    authoritative_inputs: tuple[Path, ...],
    input_base_dir: Path,
    renderer: SvgSystemRenderer | None = None,
    projection_ids: tuple[str, str] | None = None,
) -> VisualProjectionSet:
    """Generate the system block and power-tree projection collection."""
    if graph.revision != source_revision:
        raise SvgVisualProjectionError(
            "system graph revision does not match source revision"
        )
    inputs = input_records(authoritative_inputs, input_base_dir)
    renderer = renderer or SvgSystemRenderer()
    ids = projection_ids or (
        f"{slugify_identifier(project_name)}-system-block",
        f"{slugify_identifier(project_name)}-power-tree",
    )
    if len(ids) != 2:
        raise SvgVisualProjectionError(
            "system projection identifiers are incomplete"
        )
    records = [
        renderer.render(
            projection_id=ids[0],
            projection_type="system_block_view",
            source_revision=source_revision,
            graph=graph,
            lane=lane,
            input_files=inputs,
            output_path=out_dir / "visual" / f"{ids[0]}.svg",
            base_dir=out_dir,
        ),
        renderer.render(
            projection_id=ids[1],
            projection_type="power_tree_view",
            source_revision=source_revision,
            graph=graph,
            lane=lane,
            input_files=inputs,
            output_path=out_dir / "visual" / f"{ids[1]}.svg",
            base_dir=out_dir,
        ),
    ]
    if len({record.projection_id for record in records}) != len(records):
        raise SvgVisualProjectionError(
            "system projection identifiers must be unique"
        )
    records.sort(key=lambda record: record.projection_id)
    result = VisualProjectionSet(
        source_revision=source_revision,
        projections=records,
    ).with_computed_hashes()
    (out_dir / "visual-projections-system.json").write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return result
