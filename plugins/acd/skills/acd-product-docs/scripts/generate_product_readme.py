# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@194d14ab59ac245fb50b5f3bdaaa0b8dd55fafee",
# ]
# ///
"""Generate the deterministic product description README for a design graph.

The generated document is an L3 observation: it presents specification values,
a BOM summary, visual projections and attribution notices that already exist in
the design inputs. It cannot approve a design and never introduces estimated
values, so every table cell is traced back to a graph attribute.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from acd.core.electrical import extract_electrical_lane
from acd.core.firmware_lane import extract_firmware_lane
from acd.schema.design_graph import DesignGraph
from doc_inputs import (
    DocumentGenerationError,
    DocumentInput,
    ProjectionFigure,
    format_number,
    int_attr,
    load_graph,
    load_projection_figures,
    nodes_of_kind,
    number_attr,
    single_node_of_kind,
    text_attr,
    write_document,
)

TEMPLATE_ID = "acd-product-readme-ja-v1"
DOCUMENT_NAME = "product-readme.md"

_FIGURE_TITLES = {
    "schematic_view": "回路図投影",
    "layered_layout_view": "レイヤ別配線投影",
    "placement_view": "部品配置投影",
    "stackup_view": "層構成投影",
    "system_block_view": "システムブロック投影",
    "power_tree_view": "電源ツリー投影",
    "firmware_state_view": "FW状態遷移投影",
    "firmware_sequence_view": "FWシーケンス投影",
    "rasterized_view": "ラスタ化投影",
    "mechanical_section_view": "筐体断面投影",
    "mechanical_interference_view": "干渉確認投影",
}


def _requirements_section(graph: DesignGraph) -> list[str]:
    requirements = nodes_of_kind(graph, "requirement")
    if not requirements:
        raise DocumentGenerationError("graph declares no requirement node")
    lines = ["## 要求", "", "| 要求ID | 内容 |", "|---|---|"]
    lines += [f"| {node.id} | {text_attr(node, 'text')} |" for node in requirements]
    return [*lines, ""]


def _specification_section(graph: DesignGraph) -> list[str]:
    lane = extract_electrical_lane(graph)
    firmware = extract_firmware_lane(graph)
    board = single_node_of_kind(graph, "electrical.board")
    safety = single_node_of_kind(graph, "safety.boundary")
    mcu = next(
        (c for c in lane.components if c.node_id == firmware.module.mcu_component),
        None,
    )
    if mcu is None:
        raise DocumentGenerationError(
            f"MCU component {firmware.module.mcu_component!r} is missing from the graph"
        )
    unit = text_attr(board, "unit")
    rows = [
        ("MCU", f"{mcu.mpn}（{mcu.refdes}）"),
        ("FWモジュール", firmware.module.module_name),
        (
            "基板外形",
            f"{format_number(number_attr(board, 'width_mm'))} × "
            f"{format_number(number_attr(board, 'height_mm'))} {unit}",
        ),
        ("層数", str(int_attr(board, "layers"))),
        ("基板材質", text_attr(board, "material")),
        ("板厚", f"{format_number(number_attr(board, 'thickness_mm'))} {unit}"),
        ("表面処理", text_attr(board, "finish")),
        ("実装面", text_attr(board, "assembly_side")),
        ("最大ネット電圧", f"{format_number(number_attr(safety, 'max_net_voltage_v'))} V"),
        ("最大電流", f"{format_number(number_attr(safety, 'max_current_a'))} A"),
        ("想定用途", text_attr(safety, "intended_use")),
    ]
    lines = ["## 主要仕様", "", "| 項目 | 値 |", "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    lines += ["", "### 電源ネット", "", "| ネット | 公称電圧 |", "|---|---|"]
    powered = sorted(
        (net for net in lane.nets if net.voltage_nominal_v is not None),
        key=lambda net: net.name,
    )
    if not powered:
        raise DocumentGenerationError("graph declares no net with a nominal voltage")
    for net in powered:
        voltage = net.voltage_nominal_v
        if voltage is None:
            raise DocumentGenerationError(f"net {net.name!r} lost its nominal voltage")
        lines.append(f"| {net.name} | {format_number(voltage)} V |")
    lines += ["", "### インタフェース割当（FWピン投影）", "", "| ネット | GPIO |", "|---|---|"]
    for assignment in sorted(firmware.pin_assignments, key=lambda item: item.net):
        lines.append(f"| {assignment.net} | IO{assignment.gpio} |")
    return [*lines, ""]


def _bom_section(graph: DesignGraph) -> list[str]:
    lane = extract_electrical_lane(graph)
    if not lane.components:
        raise DocumentGenerationError("graph declares no electrical component")
    counts = Counter(
        (component.mpn, component.value, component.lcsc, component.assembly)
        for component in lane.components
    )
    lines = [
        "## BOM要約",
        "",
        "| MPN | 値 | LCSC | 実装 | 数量 |",
        "|---|---|---|---|---|",
    ]
    for (mpn, value, lcsc, assembly), quantity in sorted(counts.items()):
        lines.append(f"| {mpn} | {value} | {lcsc} | {assembly} | {quantity} |")
    lines.append("")
    return lines


def _figures_section(figures: tuple[ProjectionFigure, ...], out_dir: Path) -> list[str]:
    lines = ["## 図解（視覚投影）", ""]
    for figure in figures:
        title = _FIGURE_TITLES.get(figure.projection_type, figure.projection_type)
        link = os.path.relpath(figure.image_path.resolve(), out_dir.resolve()).replace(
            os.sep, "/"
        )
        lines += [
            f"### {title}: {figure.projection_id}",
            "",
            f"![{figure.projection_id}]({link})",
            "",
            f"- 投影種別: `{figure.projection_type}`（{figure.domain} lane）",
            f"- 画像hash: `{figure.image_hash}`",
            "",
        ]
    return lines


def _attribution_section(graph: DesignGraph) -> list[str]:
    lane = extract_electrical_lane(graph)
    sources: set[tuple[str, str]] = set()
    for component in lane.components:
        sources.add((component.library.symbol_source, component.library.symbol_source_ref))
        sources.add(
            (component.library.footprint_source, component.library.footprint_source_ref)
        )
    lines = [
        "## ライセンスと帰属",
        "",
        "回路図記号・フットプリントは以下の外部ライブラリ由来であり、"
        "各ライブラリのライセンス表示と帰属を保持する。",
        "",
        "| ライブラリ出典 | 参照 |",
        "|---|---|",
    ]
    lines += [f"| {source} | {ref} |" for source, ref in sorted(sources)]
    lines += [
        "",
        "生成物の設計データはこのリポジトリのライセンスに従う。",
        "",
    ]
    return lines


def render_readme(
    graph: DesignGraph, figures: tuple[ProjectionFigure, ...], out_dir: Path
) -> str:
    """Render the product README body for a graph and its projections."""
    lines = [
        f"# 製品説明: {graph.graph_id}",
        "",
        f"- Design Graph: `{graph.graph_id}`",
        f"- revision: `{graph.revision}`",
        "",
        "この文書はDesign Graphと記録済み視覚投影から決定論的に生成された観測であり、"
        "設計の合否を判定しない。値はすべて入力由来で、推定値を含まない。",
        "",
    ]
    lines += _requirements_section(graph)
    lines += _specification_section(graph)
    lines += _bom_section(graph)
    lines += _figures_section(figures, out_dir)
    lines += _attribution_section(graph)
    return "\n".join(lines).rstrip("\n") + "\n"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument(
        "--projections",
        type=Path,
        required=True,
        nargs="+",
        help="visual projection set files whose images are embedded",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    graph, graph_input = load_graph(args.graph)
    figures, projection_inputs = load_projection_figures(args.projections, graph.revision)
    body = render_readme(graph, figures, args.out_dir)
    inputs: list[DocumentInput] = [graph_input, *projection_inputs]
    document_path, provenance_path = write_document(
        document_kind="product_readme",
        body=body,
        out_dir=args.out_dir,
        document_name=DOCUMENT_NAME,
        template_id=TEMPLATE_ID,
        generator=Path(__file__).resolve(),
        graph=graph,
        inputs=inputs,
        base_dir=args.base_dir,
    )
    print(f"generated {document_path}")
    print(f"provenance {provenance_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DocumentGenerationError as error:
        print(f"product README generation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
