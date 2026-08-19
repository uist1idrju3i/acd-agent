"""Deterministic SVG writers for system and power-tree observations."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from pathlib import Path
from typing import ClassVar, Literal

from acd.adapters.svg.common import (
    ACD_SVG_RENDERER_VERSION,
    SvgVisualProjectionError,
    _escape,
    _fmt,
    _input_records,
    _slug,
    render_svg_projection,
)
from acd.core.electrical import ElectricalLane, NetView
from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.visual_projection import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionSet,
)

SystemVisualProjectionError = SvgVisualProjectionError

_KNOWN_NODE_KINDS = {
    "requirement",
    "electrical.net",
    "electrical.component",
    "electrical.pin",
    "electrical.board",
    "fab.order_intent",
    "fab.process_allowance",
    "mechanical.outline",
    "mechanical.component_body",
    "mechanical.connector_opening",
    "mechanical.board_edge_overhang",
    "mechanical.enclosure",
    "mechanical.silk_text",
    "mechanical.silk_graphic",
    "firmware.module",
    "firmware.pin_assignment",
    "safety.boundary",
    "evidence.anchor",
}
_BLOCK_DRAW_KINDS = {
    "electrical.board",
    "electrical.component",
    "electrical.net",
    "firmware.module",
    "safety.boundary",
}
_BLOCK_OMIT_KINDS = _KNOWN_NODE_KINDS - _BLOCK_DRAW_KINDS
_POWER_SOURCE_SYMBOLS = ("connector:usb_c", "regulator")


def _validate_node_kinds(graph: DesignGraph) -> None:
    unknown = sorted({str(node.kind) for node in graph.nodes} - _KNOWN_NODE_KINDS)
    if unknown:
        raise SystemVisualProjectionError(
            f"system block projection encountered unknown node kinds: {unknown}"
        )


def _block_edges(
    graph: DesignGraph,
    nodes: dict[str, GraphNode],
) -> list[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for node in nodes.values():
        for dependency in sorted(node.depends_on):
            target = graph.node_by_id(dependency)
            if target.kind in _BLOCK_DRAW_KINDS:
                edges.add((node.id, dependency))
            elif target.kind not in _BLOCK_OMIT_KINDS:
                raise SystemVisualProjectionError(
                    f"system block dependency has unknown node kind: {target.kind!r}"
                )
    if not edges:
        raise SystemVisualProjectionError(
            "system block projection requires at least one depends_on edge"
        )
    return sorted(edges)


def _block_svg(graph: DesignGraph) -> bytes:
    _validate_node_kinds(graph)
    nodes = {
        node.id: node
        for node in graph.nodes
        if node.kind in _BLOCK_DRAW_KINDS
    }
    if not nodes:
        raise SystemVisualProjectionError("system block projection has no drawable nodes")
    edges = _block_edges(graph, nodes)
    ordered = sorted(nodes.values(), key=lambda node: node.id)
    positions = {
        node.id: (20.0 + (index % 3) * 75.0, 25.0 + (index // 3) * 28.0)
        for index, node in enumerate(ordered)
    }
    height = max(70.0, 50.0 + math.ceil(len(ordered) / 3) * 28.0)
    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="240mm" height="{_fmt(height)}mm" '
        f'viewBox="0 0 240 {_fmt(height)}">',
        '<g id="system-block">',
    ]
    for source, target in edges:
        source_x, source_y = positions[source]
        target_x, target_y = positions[target]
        edge_id = f"block-edge-{_slug(source)}-{_slug(target)}"
        chunks.append(
            f'<line id="{edge_id}" x1="{_fmt(source_x + 22)}" '
            f'y1="{_fmt(source_y + 8)}" x2="{_fmt(target_x + 22)}" '
            f'y2="{_fmt(target_y + 8)}" stroke="#555"/>'
        )
    for kind in sorted({node.kind for node in ordered}):
        chunks.append(f'<g id="block-kind-{_slug(kind)}">')
        for node in ordered:
            if node.kind != kind:
                continue
            x, y = positions[node.id]
            identifier = _slug(node.id)
            chunks.extend(
                [
                    f'<g id="block-node-{identifier}">',
                    f'<rect id="block-box-{identifier}" x="{_fmt(x)}" y="{_fmt(y)}" '
                    'width="44" height="16" fill="none" stroke="#000"/>',
                    f'<text id="block-label-{identifier}" x="{_fmt(x + 2)}" '
                    f'y="{_fmt(y + 6)}">{_escape(node.id)}</text>',
                    f'<text id="block-kind-label-{identifier}" x="{_fmt(x + 2)}" '
                    f'y="{_fmt(y + 12)}">{_escape(node.kind)}</text>',
                    "</g>",
                ]
            )
        chunks.append("</g>")
    chunks.append("</g></svg>")
    return "".join(chunks).encode("utf-8")


def _power_source_candidates(
    net: NetView,
    lane: ElectricalLane,
) -> tuple[str, ...]:
    connected = {
        pin.component_id
        for pin in lane.pins
        if pin.net_id == net.node_id
    }
    if not connected:
        raise SystemVisualProjectionError(
            f"power net {net.node_id}: no connected pins are declared"
        )
    candidates_by_kind: dict[str, list[str]] = {marker: [] for marker in _POWER_SOURCE_SYMBOLS}
    for component_id in sorted(connected):
        component = lane.component_by_id(component_id)
        symbol = component.library.symbol.lower()
        for marker in _POWER_SOURCE_SYMBOLS:
            if marker in symbol:
                candidates_by_kind[marker].append(component_id)
    net_label = f"{net.node_id} {net.name}".lower()
    preferred_markers = (
        ("regulator",) if "3v3" in net_label else ("connector:usb_c",)
        if "vbus" in net_label or "gnd" in net_label
        else _POWER_SOURCE_SYMBOLS
    )
    candidates = [
        component_id
        for marker in preferred_markers
        for component_id in candidates_by_kind[marker]
    ]
    if len(candidates) != 1:
        raise SystemVisualProjectionError(
            f"power net {net.node_id}: supply source is not uniquely declared"
        )
    if len(connected) == 1:
        raise SystemVisualProjectionError(
            f"power net {net.node_id}: no load component is connected"
        )
    return tuple(candidates)


def _power_nets(lane: ElectricalLane) -> tuple[NetView, ...]:
    nets = tuple(
        net
        for net in lane.nets
        if net.voltage_nominal_v is not None
        and net.width_basis == "current_ipc2221"
    )
    if not nets:
        raise SystemVisualProjectionError(
            "power tree projection has no declared power nets"
        )
    for net in nets:
        voltage = net.voltage_nominal_v
        if voltage is None or not math.isfinite(voltage):
            raise SystemVisualProjectionError(
                f"power net {net.node_id}: voltage declaration is invalid"
            )
        _power_source_candidates(net, lane)
    return tuple(sorted(nets, key=lambda net: net.node_id))


def _power_tree_svg(lane: ElectricalLane) -> bytes:
    nets = _power_nets(lane)
    row_height = 30.0
    height = 30.0 + len(nets) * row_height
    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="240mm" height="{_fmt(height)}mm" '
        f'viewBox="0 0 240 {_fmt(height)}">',
        '<g id="power-tree">',
    ]
    for index, net in enumerate(nets):
        source_id = _power_source_candidates(net, lane)[0]
        connected = sorted(
            {
                pin.component_id
                for pin in lane.pins
                if pin.net_id == net.node_id
            }
        )
        load_ids = [component_id for component_id in connected if component_id != source_id]
        y = 20.0 + index * row_height
        net_identifier = _slug(net.node_id)
        source_identifier = _slug(source_id)
        chunks.extend(
            [
                f'<g id="power-net-{net_identifier}">',
                f'<rect id="power-source-box-{net_identifier}" x="10" y="{_fmt(y)}" '
                'width="46" height="14" fill="none" stroke="#000"/>',
                f'<text id="power-source-label-{net_identifier}" x="12" y="{_fmt(y + 8)}">'
                f'{_escape(source_id)}</text>',
                f'<rect id="power-net-box-{net_identifier}" x="92" y="{_fmt(y)}" '
                'width="56" height="14" fill="none" stroke="#000"/>',
                f'<text id="power-net-label-{net_identifier}" x="94" y="{_fmt(y + 6)}">'
                f'{_escape(net.name)}</text>',
                f'<text id="power-voltage-label-{net_identifier}" x="94" '
                f'y="{_fmt(y + 11)}">{net.voltage_nominal_v} V</text>',
                f'<line id="power-edge-source-{net_identifier}-{source_identifier}" '
                f'x1="56" y1="{_fmt(y + 7)}" x2="92" y2="{_fmt(y + 7)}" stroke="#555"/>',
            ]
        )
        for load_index, load_id in enumerate(load_ids):
            load_identifier = _slug(load_id)
            load_y = y + load_index * 16.0
            chunks.extend(
                [
                    f'<rect id="power-load-box-{net_identifier}-{load_identifier}" '
                    f'x="174" y="{_fmt(load_y)}" width="56" height="14" '
                    'fill="none" stroke="#000"/>',
                    f'<text id="power-load-label-{net_identifier}-{load_identifier}" '
                    f'x="176" y="{_fmt(load_y + 8)}">{_escape(load_id)}</text>',
                    f'<line id="power-edge-load-{net_identifier}-{load_identifier}" '
                    f'x1="148" y1="{_fmt(y + 7)}" x2="174" '
                    f'y2="{_fmt(load_y + 7)}" stroke="#555"/>',
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
            raise SystemVisualProjectionError("renderer version is unknown")
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
            else _power_tree_svg(lane)
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            output_path.write_bytes(content)
        except OSError as exc:
            raise SystemVisualProjectionError(
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
            raise SystemVisualProjectionError("unsupported system projection type")
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
        raise SystemVisualProjectionError("system graph revision does not match source revision")
    inputs = _input_records(authoritative_inputs, input_base_dir)
    renderer = renderer or SvgSystemRenderer()
    ids = projection_ids or (
        f"{_slug(project_name)}-system-block",
        f"{_slug(project_name)}-power-tree",
    )
    if len(ids) != 2:
        raise SystemVisualProjectionError("system projection identifiers are incomplete")
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
        raise SystemVisualProjectionError("system projection identifiers must be unique")
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
