"""Deterministic SVG writers for system and power-tree observations."""

from __future__ import annotations

import math
from pathlib import Path
from typing import ClassVar, Literal, get_args

from acd.adapters.svg.common import (
    ACD_SVG_RENDERER_VERSION,
    DIAGRAM_FONT_SIZE_RATIO,
    SvgVisualProjectionError,
    escape_xml,
    format_svg_number,
    input_records,
    render_svg_projection,
    slugify_identifier,
    view_box_font_size,
)
from acd.core.electrical import ElectricalLane, NetView
from acd.schema.design_graph import DesignGraph, GraphNode, NodeKind
from acd.schema.visual_projection import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionSet,
)

# Both system projections are laid out on a fixed 240-unit wide viewBox.
_DIAGRAM_VIEW_BOX_WIDTH = 240.0

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


def _block_svg(graph: DesignGraph) -> bytes:
    _validate_node_kinds(graph)
    nodes = {
        node.id: node for node in graph.nodes if node.kind in _BLOCK_DRAW_KINDS
    }
    if not nodes:
        raise SvgVisualProjectionError("system block projection has no drawable nodes")
    edges = _block_edges(graph, nodes)
    ordered = sorted(nodes.values(), key=lambda node: node.id)
    positions = {
        node.id: (20.0 + (index % 3) * 75.0, 25.0 + (index // 3) * 28.0)
        for index, node in enumerate(ordered)
    }
    height = max(70.0, 50.0 + math.ceil(len(ordered) / 3) * 28.0)
    font_size = view_box_font_size(_DIAGRAM_VIEW_BOX_WIDTH, ratio=DIAGRAM_FONT_SIZE_RATIO)
    chunks = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="240mm" '
        f'height="{format_svg_number(height)}mm" '
        f'viewBox="0 0 240 {format_svg_number(height)}">',
        '<g id="system-block">',
    ]
    for source, target in edges:
        source_x, source_y = positions[source]
        target_x, target_y = positions[target]
        edge_id = (
            f"block-edge-{slugify_identifier(source)}-"
            f"{slugify_identifier(target)}"
        )
        chunks.append(
            f'<line id="{edge_id}" x1="{format_svg_number(source_x + 22)}" '
            f'y1="{format_svg_number(source_y + 8)}" '
            f'x2="{format_svg_number(target_x + 22)}" '
            f'y2="{format_svg_number(target_y + 8)}" stroke="#555"/>'
        )
    for kind in sorted({node.kind for node in ordered}):
        chunks.append(f'<g id="block-kind-{slugify_identifier(kind)}">')
        for node in ordered:
            if node.kind != kind:
                continue
            x, y = positions[node.id]
            identifier = slugify_identifier(node.id)
            chunks.extend(
                [
                    f'<g id="block-node-{identifier}">',
                    f'<rect id="block-box-{identifier}" '
                    f'x="{format_svg_number(x)}" y="{format_svg_number(y)}" '
                    'width="44" height="16" fill="none" stroke="#000"/>',
                    f'<text id="block-label-{identifier}" '
                    f'x="{format_svg_number(x + 2)}" '
                    f'y="{format_svg_number(y + 6)}" '
                    f'font-size="{format_svg_number(font_size)}">'
                    f"{escape_xml(node.id)}</text>",
                    f'<text id="block-kind-label-{identifier}" '
                    f'x="{format_svg_number(x + 2)}" '
                    f'y="{format_svg_number(y + 12)}" '
                    f'font-size="{format_svg_number(font_size)}">'
                    f"{escape_xml(node.kind)}</text>",
                    "</g>",
                ]
            )
        chunks.append("</g>")
    chunks.append("</g></svg>")
    return "".join(chunks).encode("utf-8")


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


def _power_tree_svg(lane: ElectricalLane, graph: DesignGraph) -> bytes:
    nets = _power_nets(lane)
    row_height = 30.0
    height = 30.0 + len(nets) * row_height
    font_size = view_box_font_size(_DIAGRAM_VIEW_BOX_WIDTH, ratio=DIAGRAM_FONT_SIZE_RATIO)
    chunks = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="240mm" '
        f'height="{format_svg_number(height)}mm" '
        f'viewBox="0 0 240 {format_svg_number(height)}">',
        '<g id="power-tree">',
    ]
    for index, net in enumerate(nets):
        source_id, load_ids = _power_connections(net, lane, graph)
        y = 20.0 + index * row_height
        net_identifier = slugify_identifier(net.node_id)
        source_identifier = slugify_identifier(source_id)
        chunks.extend(
            [
                f'<g id="power-net-{net_identifier}">',
                f'<rect id="power-source-box-{net_identifier}" '
                f'x="10" y="{format_svg_number(y)}" width="46" height="14" '
                'fill="none" stroke="#000"/>',
                f'<text id="power-source-label-{net_identifier}" x="12" '
                f'y="{format_svg_number(y + 8)}" '
                f'font-size="{format_svg_number(font_size)}">'
                f"{escape_xml(source_id)}</text>",
                f'<rect id="power-net-box-{net_identifier}" x="92" '
                f'y="{format_svg_number(y)}" width="56" height="14" '
                'fill="none" stroke="#000"/>',
                f'<text id="power-net-label-{net_identifier}" x="94" '
                f'y="{format_svg_number(y + 6)}" '
                f'font-size="{format_svg_number(font_size)}">'
                f"{escape_xml(net.name)}</text>",
                f'<text id="power-voltage-label-{net_identifier}" x="94" '
                f'y="{format_svg_number(y + 11)}" '
                f'font-size="{format_svg_number(font_size)}">'
                f"{net.voltage_nominal_v} V</text>",
                f'<line id="power-edge-source-{net_identifier}-'
                f'{source_identifier}" x1="56" '
                f'y1="{format_svg_number(y + 7)}" x2="92" '
                f'y2="{format_svg_number(y + 7)}" stroke="#555"/>',
            ]
        )
        for load_index, load_id in enumerate(load_ids):
            load_identifier = slugify_identifier(load_id)
            load_y = y + load_index * 16.0
            chunks.extend(
                [
                    f'<rect id="power-load-box-{net_identifier}-'
                    f'{load_identifier}" x="174" '
                    f'y="{format_svg_number(load_y)}" width="56" height="14" '
                    'fill="none" stroke="#000"/>',
                    f'<text id="power-load-label-{net_identifier}-'
                    f'{load_identifier}" x="176" '
                    f'y="{format_svg_number(load_y + 8)}" '
                    f'font-size="{format_svg_number(font_size)}">'
                    f"{escape_xml(load_id)}</text>",
                    f'<line id="power-edge-load-{net_identifier}-'
                    f'{load_identifier}" x1="148" '
                    f'y1="{format_svg_number(y + 7)}" x2="174" '
                    f'y2="{format_svg_number(load_y + 7)}" stroke="#555"/>',
                ]
            )
        chunks.append("</g>")
    chunks.append("</g></svg>")
    return "".join(chunks).encode("utf-8")


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
            _block_svg(graph)
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
