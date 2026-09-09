# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@12b25b697d3203d50c63a4dacd9b1704a009b850",
# ]
# ///
"""Generate the deterministic product description README for a design graph.

The generated document is an L3 observation: it presents specification values,
firmware behavior, a BOM, visual projections, an optional theme-song projection
and attribution notices that already exist in the design inputs. It cannot
approve a design and never introduces estimated values, so every table cell is
traced back to a graph attribute or a recorded projection.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from acd.core.electrical import ElectricalLane, extract_electrical_lane
from acd.core.firmware_lane import FirmwareLane, extract_firmware_lane
from acd.schema.design_graph import DesignGraph
from doc_inputs import (
    DocumentGenerationError,
    DocumentInput,
    ProjectionFigure,
    ThemeSongFigure,
    format_number,
    int_attr,
    load_graph,
    load_projection_figures,
    load_theme_song,
    nodes_of_kind,
    number_attr,
    single_node_of_kind,
    text_attr,
    write_document,
)

TEMPLATE_ID = "acd-product-readme-ja-v2"
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

_FIGURE_GUIDES = {
    "schematic_view": "回路図の投影。ネット名はgraph宣言の接続を示す。",
    "layered_layout_view": "基板1層分の銅箔投影。配線とviaの実配置を示す。",
    "placement_view": "基板外形内の部品配置。色はF/B面、refdesは部品参照名。",
    "stackup_view": "基板の層構成投影。誘電体・銅層・ソルダーマスクの積層順を示す。",
    "system_block_view": "機能ブロックと電源・信号の接続関係を示す系統図投影。",
    "power_tree_view": "電源ネットの供給元から負荷までのツリー投影。",
    "firmware_state_view": "FW状態機械の投影。初期状態と遷移はgraph宣言どおり。",
    "firmware_sequence_view": "FW起動シーケンスの投影。step順はgraph宣言どおり。",
    "rasterized_view": "SVG投影をPNGへラスタ化した投影。元SVGのhashと対応する。",
    "mechanical_section_view": "筐体の断面投影。基板・コネクタ開口の位置関係を示す。",
    "mechanical_interference_view": "筐体と部品の干渉確認投影。隙間・接触を示す。",
}

# Projection domains are grouped into reader-facing areas: the board lane
# emits `electrical` and `system` domains, both shown under the 基板 heading.
_DOMAIN_GROUP = {
    "electrical": "基板",
    "system": "基板",
    "firmware": "FW",
    "mechanical": "筐体",
}
_DOMAIN_GROUP_ORDER = ("基板", "FW", "筐体")


def _domain_group(domain: str) -> str:
    return _DOMAIN_GROUP.get(domain, domain)

# Heading text -> GitHub anchor slug (letters/digits kept, punctuation dropped,
# spaces become hyphens; matches scripts/verify_docs.py github_slug).
_SECTION_HEADINGS = (
    ("生成物と判定の関係", "生成物と判定の関係"),
    ("要求", "要求"),
    ("主要仕様", "主要仕様"),
    ("電源・インタフェース", "電源インタフェース"),
    ("ファームウェア動作", "ファームウェア動作"),
    ("部品と役割（BOM）", "部品と役割bom"),
    ("図解（視覚投影）", "図解視覚投影"),
    ("テーマソング（L3投影）", "テーマソングl3投影"),
    ("ライセンスと帰属", "ライセンスと帰属"),
)
_THEME_HEADING = "テーマソング（L3投影）"


def _table_of_contents(has_theme: bool) -> list[str]:
    lines = ["## 目次", ""]
    for heading, anchor in _SECTION_HEADINGS:
        if heading == _THEME_HEADING and not has_theme:
            continue
        lines.append(f"- [{heading}](#{anchor})")
    lines.append("")
    return lines


def _overview_sentence(graph: DesignGraph, lane: ElectricalLane) -> str:
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
    return (
        f"{graph.graph_id}（revision {graph.revision}）は、{mcu.mpn}を搭載し、"
        f"基板外形{format_number(number_attr(board, 'width_mm'))} × "
        f"{format_number(number_attr(board, 'height_mm'))} {unit}の設計である。"
        f"想定用途: {text_attr(safety, 'intended_use')}。"
    )


def _evidence_relation_section(
    inputs: Sequence[DocumentInput], theme: ThemeSongFigure | None
) -> list[str]:
    lines = [
        "## 生成物と判定の関係",
        "",
        "このREADMEはL3観測（`pass_evidence=false`）であり、設計の合格・"
        "order-readyの判定に一切作用しない。合格とorder-readyは決定論的ゲートと"
        "revision一致のauthoritative Evidenceのみが担う。",
        "",
    ]
    if theme is None:
        lines.append("テーマソング投影: 未入力（`--theme-song-projection`未指定）")
        lines.append("")
    if inputs:
        lines += ["入力ファイルとhash:", "", "| 入力 | content hash |", "|---|---|"]
        for item in inputs:
            lines.append(f"| `{item.path.as_posix()}` | `{item.content_hash}` |")
        lines.append("")
    else:
        lines += [
            "入力一覧は同ディレクトリの`product-readme.md.provenance.json`の"
            "`inputs`に記録される。",
            "",
        ]
    return lines


def _requirements_section(graph: DesignGraph) -> list[str]:
    requirements = nodes_of_kind(graph, "requirement")
    if not requirements:
        raise DocumentGenerationError("graph declares no requirement node")
    lines = ["## 要求", "", "| 要求ID | 内容 |", "|---|---|"]
    lines += [f"| {node.id} | {text_attr(node, 'text')} |" for node in requirements]
    return [*lines, ""]


def _specification_section(
    graph: DesignGraph, lane: ElectricalLane, firmware: FirmwareLane
) -> list[str]:
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
    return [*lines, ""]


def _power_interface_section(
    lane: ElectricalLane, firmware: FirmwareLane
) -> list[str]:
    lines = [
        "## 電源・インタフェース",
        "",
        "### 電源ネット",
        "",
        "| ネット | 公称電圧 |",
        "|---|---|",
    ]
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


def _firmware_section(
    lane: ElectricalLane, firmware: FirmwareLane
) -> list[str]:
    mcu = lane.component_by_id(firmware.module.mcu_component)
    lines = [
        "## ファームウェア動作",
        "",
        f"- モジュール: `{firmware.module.module_name}`（node `{firmware.module.node_id}`）",
        f"- MCU: `{mcu.refdes}`",
        f"- 初期状態: `{firmware.module.entry_state}`",
        "",
        "### 状態",
        "",
        "| node | 名称 | 初期状態 |",
        "|---|---|---|",
    ]
    for state in firmware.states:
        initial = "yes" if state.initial else ""
        lines.append(f"| {state.node_id} | {state.state_name} | {initial} |")
    lines += [
        "",
        "### 状態遷移",
        "",
        "| 遷移 | trigger |",
        "|---|---|",
    ]
    for transition in firmware.transitions:
        lines.append(
            f"| {transition.from_state} → {transition.to_state} "
            f"| {transition.trigger} |"
        )
    lines += [
        "",
        "### 起動シーケンス",
        "",
        "| index | actor | target | action |",
        "|---|---|---|---|",
    ]
    for step in sorted(firmware.sequence_steps, key=lambda item: item.step_index):
        lines.append(
            f"| {step.step_index} | {step.actor} | {step.target} | {step.action} |"
        )
    lines += [
        "",
        "### ピン割当（FWピン投影）",
        "",
        "| ネット | GPIO |",
        "|---|---|",
    ]
    for assignment in sorted(firmware.pin_assignments, key=lambda item: item.net):
        lines.append(f"| {assignment.net} | IO{assignment.gpio} |")
    return [*lines, ""]


def _bom_section(graph: DesignGraph, lane: ElectricalLane) -> list[str]:
    if not lane.components:
        raise DocumentGenerationError("graph declares no electrical component")
    counts = Counter(
        (component.mpn, component.value, component.lcsc, component.assembly)
        for component in lane.components
    )
    lines = [
        "## 部品と役割（BOM）",
        "",
        "### BOM要約",
        "",
        "| MPN | 値 | LCSC | 実装 | 数量 |",
        "|---|---|---|---|---|",
    ]
    for (mpn, value, lcsc, assembly), quantity in sorted(counts.items()):
        lines.append(f"| {mpn} | {value} | {lcsc} | {assembly} | {quantity} |")
    component_nodes = {
        node.id: node for node in nodes_of_kind(graph, "electrical.component")
    }
    lines += [
        "",
        "### 部品一覧",
        "",
        "| refdes | 値 | MPN | LCSC | 実装 | footprint | 役割 |",
        "|---|---|---|---|---|---|---|",
    ]
    for component in sorted(lane.components, key=lambda item: item.refdes):
        node = component_nodes.get(component.node_id)
        role_value = node.attrs.get("role") if node is not None else None
        if not isinstance(role_value, str):
            role_value = node.attrs.get("functional_block") if node is not None else None
        role = role_value if isinstance(role_value, str) and role_value else "—"
        lines.append(
            f"| {component.refdes} | {component.value} | {component.mpn} "
            f"| {component.lcsc} | {component.assembly} "
            f"| {component.library.footprint} | {role} |"
        )
    lines.append("")
    return lines


def _figures_section(figures: tuple[ProjectionFigure, ...], out_dir: Path) -> list[str]:
    groups = sorted(
        {_domain_group(figure.domain) for figure in figures},
        key=_domain_group_order,
    )
    domain_names = "・".join(groups)
    lines = [
        "## 図解（視覚投影）",
        "",
        f"供給された投影集合のdomain: {domain_names}。",
        "供給されなかった投影集合はこの文書に含まれない（欠落は未生成を意味しない）。",
        "",
    ]
    for group in groups:
        lines += [f"### {group}", ""]
        for figure in figures:
            if _domain_group(figure.domain) != group:
                continue
            title = _FIGURE_TITLES.get(figure.projection_type, figure.projection_type)
            guide = _FIGURE_GUIDES.get(figure.projection_type, "視覚投影。")
            link = os.path.relpath(
                figure.image_path.resolve(), out_dir.resolve()
            ).replace(os.sep, "/")
            lines += [
                f"#### {title}: {figure.projection_id}",
                "",
                guide,
                "",
                f"![{figure.projection_id}]({link})",
                "",
                f"- 投影種別: `{figure.projection_type}`（{figure.domain} lane）",
                f"- 画像hash: `{figure.image_hash}`",
                "",
            ]
    return lines


def _domain_group_order(group: str) -> int:
    try:
        return _DOMAIN_GROUP_ORDER.index(group)
    except ValueError:
        return len(_DOMAIN_GROUP_ORDER)


def _theme_song_section(theme: ThemeSongFigure, out_dir: Path) -> list[str]:
    link = os.path.relpath(theme.midi_path.resolve(), out_dir.resolve()).replace(
        os.sep, "/"
    )
    return [
        "## テーマソング（L3投影）",
        "",
        "| 項目 | 値 |",
        "|---|---|",
        f"| 題名 | {theme.title} |",
        f"| 調 | {theme.key} |",
        f"| BPM | {theme.bpm} |",
        f"| 小節数 | {theme.bars} |",
        f"| composer | `{theme.composer_id}` |",
        f"| 出所 | `{theme.source}` |",
        "",
        f"- artifact: [{theme.midi_path.name}]({link})",
        f"- artifact hash: `{theme.midi_hash}`",
        f"- regeneration check: `{theme.regeneration_status}`",
        "",
        "テーマソングはL3投影であり、`pass_evidence=false`を持ち、"
        "設計の判定に影響しない。",
        "",
    ]


def _attribution_section(lane: ElectricalLane) -> list[str]:
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
    graph: DesignGraph,
    figures: tuple[ProjectionFigure, ...],
    out_dir: Path,
    *,
    theme: ThemeSongFigure | None = None,
    inputs: Sequence[DocumentInput] = (),
) -> str:
    """Render the product README body for a graph and its projections."""
    lane = extract_electrical_lane(graph)
    firmware = extract_firmware_lane(graph)
    lines = [
        f"# 製品説明: {graph.graph_id}",
        "",
        f"- Design Graph: `{graph.graph_id}`",
        f"- revision: `{graph.revision}`",
        "",
        "この文書はDesign Graphと記録済み視覚投影から決定論的に生成された観測であり、"
        "設計の合否を判定しない。値はすべて入力由来で、推定値を含まない。",
        "",
        _overview_sentence(graph, lane),
        "",
    ]
    lines += _table_of_contents(has_theme=theme is not None)
    lines += _evidence_relation_section(inputs, theme)
    lines += _requirements_section(graph)
    lines += _specification_section(graph, lane, firmware)
    lines += _power_interface_section(lane, firmware)
    lines += _firmware_section(lane, firmware)
    lines += _bom_section(graph, lane)
    lines += _figures_section(figures, out_dir)
    if theme is not None:
        lines += _theme_song_section(theme, out_dir)
    lines += _attribution_section(lane)
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
    parser.add_argument(
        "--theme-song-projection",
        type=Path,
        default=None,
        help="recorded theme-song projection JSON (optional; MIDI must sit "
        "beside it at the declared artifact path)",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    graph, graph_input = load_graph(args.graph)
    figures, projection_inputs = load_projection_figures(args.projections, graph.revision)
    theme = None
    theme_input: DocumentInput | None = None
    if args.theme_song_projection is not None:
        theme, theme_input = load_theme_song(args.theme_song_projection, graph)
    inputs: list[DocumentInput] = [graph_input, *projection_inputs]
    if theme_input is not None:
        inputs.append(theme_input)
    body = render_readme(graph, figures, args.out_dir, theme=theme, inputs=inputs)
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
