"""Deterministic SVG projection for graph revision differences."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from acd.adapters.svg.common import (
    ACD_SVG_RENDERER_VERSION,
    COLOR_EDGE_MUTED,
    SvgVisualProjectionError,
    arrow_marker_defs,
    diagram_font_size,
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
from acd.core.graph_diff import GraphDiffError, build_graph_diff
from acd.schema.design_graph import DesignGraph
from acd.schema.graph_diff import GraphDiff
from acd.schema.visual_projection import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionSet,
)

_WIDTH = 240.0
_MARGIN = 8.0
_BOX_HEIGHT = 10.0
_COLUMN_GAP = 4.0
_ROW_GAP = 4.0
_COLORS = {
    "added": "#2e7d32",
    "removed": "#c62828",
    "changed": "#ef6c00",
    "unchanged": "#9e9e9e",
}


def _node_status(diff: GraphDiff, node_id: str) -> str:
    if node_id in diff.nodes_added:
        return "added"
    if node_id in diff.nodes_removed:
        return "removed"
    if any(node.id == node_id for node in diff.nodes_changed):
        return "changed"
    return "unchanged"


def _edge_keys(graph: DesignGraph) -> set[str]:
    return {
        f"{node.id}->{dependency}"
        for node in graph.nodes
        for dependency in node.depends_on
    }


def _write_graph_diff_svg(
    *,
    previous: DesignGraph,
    current: DesignGraph,
    diff: GraphDiff,
    output_path: Path,
) -> None:
    font_size = diagram_font_size()
    small = font_size * 0.8
    nodes_by_id = {
        node.id: node for node in (*previous.nodes, *current.nodes)
    }
    kinds = sorted({node.kind for node in nodes_by_id.values()})
    if not kinds:
        raise SvgVisualProjectionError("graph diff requires at least one node")
    column_width = max(
        28.0,
        (_WIDTH - 2 * _MARGIN - _COLUMN_GAP * (len(kinds) - 1)) / len(kinds),
    )
    positions: dict[str, tuple[float, float]] = {}
    for column, kind in enumerate(kinds):
        nodes = sorted(
            (node for node in nodes_by_id.values() if node.kind == kind),
            key=lambda node: node.id,
        )
        x = _MARGIN + column * (column_width + _COLUMN_GAP)
        for row, node in enumerate(nodes):
            positions[node.id] = (
                x + column_width / 2,
                header_height(font_size) + font_size * 4 + row * (_BOX_HEIGHT + _ROW_GAP),
            )
    rows = max(
        len([node for node in nodes_by_id.values() if node.kind == kind])
        for kind in kinds
    )
    height = (
        header_height(font_size)
        + font_size * 5
        + max(1, rows) * (_BOX_HEIGHT + _ROW_GAP)
        + footer_height(font_size)
    )
    previous_edges = _edge_keys(previous)
    current_edges = _edge_keys(current)
    unchanged_edges = previous_edges & current_edges
    added_edges = current_edges - previous_edges
    removed_edges = previous_edges - current_edges
    body = [
        arrow_marker_defs(font_size),
        *legend(
            [
                ("added", _COLORS["added"], _COLORS["added"]),
                ("removed", _COLORS["removed"], _COLORS["removed"]),
                ("changed", _COLORS["changed"], _COLORS["changed"]),
                ("unchanged", _COLORS["unchanged"], _COLORS["unchanged"]),
            ],
            x=_MARGIN,
            y=header_height(font_size) + font_size * 1.2,
            font_size=small,
            element_id="graph-diff-legend",
        ),
        '<g id="graph-diff-edges">',
    ]
    for edge, color, dash in [
        *[(edge, _COLORS["added"], "") for edge in sorted(added_edges)],
        *[(edge, _COLORS["removed"], "stroke-dasharray=\"3 2\"") for edge in sorted(removed_edges)],
        *[(edge, COLOR_EDGE_MUTED, "") for edge in sorted(unchanged_edges)],
    ]:
        source, target = edge.split("->", 1)
        if source not in positions or target not in positions:
            raise SvgVisualProjectionError(f"graph diff edge references unknown node: {edge}")
        sx, sy = positions[source]
        tx, ty = positions[target]
        body.append(
            f'<line x1="{format_svg_number(sx)}" y1="{format_svg_number(sy)}" '
            f'x2="{format_svg_number(tx)}" y2="{format_svg_number(ty)}" '
            f'stroke="{color}" stroke-width="{format_svg_number(font_size * 0.16)}" '
            f'{dash} fill="none" marker-end="url(#arrow)"/>'
        )
    body.append("</g>")
    body.append('<g id="graph-diff-nodes">')
    for node_id in sorted(nodes_by_id):
        node = nodes_by_id[node_id]
        x, y = positions[node_id]
        status = _node_status(diff, node_id)
        color = _COLORS[status]
        dash = ' stroke-dasharray="3 2"' if status == "removed" else ""
        body.append(
            f'<rect x="{format_svg_number(x - column_width / 2)}" '
            f'y="{format_svg_number(y - _BOX_HEIGHT / 2)}" '
            f'width="{format_svg_number(column_width)}" '
            f'height="{format_svg_number(_BOX_HEIGHT)}" fill="{color}" '
            f'stroke="{color}"{dash}/>'
        )
        label = node_id
        if text_advance(label, small) > column_width - 2:
            label = node_id[: max(1, int((column_width - 2) / (small * 0.58)))] + "…"
        body.append(
            svg_text(
                label,
                x=x,
                y=y + small * 0.35,
                font_size=small,
                anchor="middle",
                fill="#ffffff",
                element_id=f"node-{slugify_identifier(node_id)}",
            )
        )
    body.append("</g>")
    body.append(
        svg_text(
            "Kinds: " + ", ".join(kinds),
            x=_MARGIN,
            y=height - footer_height(font_size),
            font_size=small,
            fill=COLOR_EDGE_MUTED,
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
        svg_document(
            width=_WIDTH,
            height=height,
            title=f"Graph diff {previous.revision} -> {current.revision}",
            subtitle=f"{current.graph_id} ({len(nodes_by_id)} nodes)",
            body=body,
            font_size=font_size,
        )
    )


class SvgGraphDiffRenderer:
    """Render graph revision differences without external tools."""

    renderer_type: ClassVar[str] = "acd-svg"
    tool_name: ClassVar[str] = "acd-svg"

    def __init__(self, *, tool_version: str = ACD_SVG_RENDERER_VERSION) -> None:
        if not tool_version or tool_version == "unknown":
            raise SvgVisualProjectionError("renderer version is unknown")
        self.tool_version = tool_version

    def render(
        self,
        *,
        projection_id: str,
        previous_graph: DesignGraph,
        current_graph: DesignGraph,
        input_files: list[VisualProjectionInput],
        output_path: Path,
        base_dir: Path,
    ) -> VisualProjectionRecord:
        try:
            diff = build_graph_diff(previous_graph, current_graph)
        except GraphDiffError as exc:
            raise SvgVisualProjectionError(str(exc)) from exc
        return render_svg_projection(
            projection_id=projection_id,
            projection_type="graph_diff_view",
            domain="system",
            source_revision=current_graph.revision,
            input_files=input_files,
            output_path=output_path,
            base_dir=base_dir,
            tool_version=self.tool_version,
            write_svg=lambda path: _write_graph_diff_svg(
                previous=previous_graph,
                current=current_graph,
                diff=diff,
                output_path=path,
            ),
        )


def generate_graph_diff_visual_projection(
    *,
    project_name: str,
    out_dir: Path,
    previous_graph: DesignGraph,
    current_graph: DesignGraph,
    authoritative_inputs: tuple[Path, ...],
    input_base_dir: Path,
    renderer: SvgGraphDiffRenderer | None = None,
    projection_id: str | None = None,
) -> VisualProjectionSet:
    if previous_graph.graph_id != current_graph.graph_id:
        raise SvgVisualProjectionError("graph diff graph IDs do not match")
    try:
        build_graph_diff(previous_graph, current_graph)
    except GraphDiffError as exc:
        raise SvgVisualProjectionError(str(exc)) from exc
    renderer = renderer or SvgGraphDiffRenderer()
    identifier = projection_id or f"{slugify_identifier(project_name)}-graph-diff"
    inputs = input_records(authoritative_inputs, input_base_dir)
    record = renderer.render(
        projection_id=identifier,
        previous_graph=previous_graph,
        current_graph=current_graph,
        input_files=inputs,
        output_path=out_dir / "visual" / f"{identifier}.svg",
        base_dir=out_dir,
    )
    result = VisualProjectionSet(
        source_revision=current_graph.revision,
        projections=[record],
    ).with_computed_hashes()
    (out_dir / "visual-projections-graph-diff.json").write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return result


__all__ = ["SvgGraphDiffRenderer", "generate_graph_diff_visual_projection"]
