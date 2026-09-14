# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@26bbeca6d58e18f3908790f202aa9daf7b1ed90a",
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
from contextvars import ContextVar
from pathlib import Path

from acd.core.electrical import ElectricalLane, extract_electrical_lane
from acd.core.firmware_lane import FirmwareLane, extract_firmware_lane
from acd.schema.design_graph import DesignGraph
from doc_inputs import (
    DocumentGenerationError,
    DocumentInput,
    DocumentTemplate,
    ProjectionFigure,
    ThemeSongFigure,
    format_number,
    int_attr,
    load_graph,
    load_projection_figures,
    load_template,
    load_theme_song,
    nodes_of_kind,
    number_attr,
    single_node_of_kind,
    text_attr,
    write_document,
)

DOCUMENT_NAME = "product-readme.md"
TEMPLATE_ID = "acd-product-readme-ja-v2"

_TEMPLATE: ContextVar[DocumentTemplate | None] = ContextVar(
    "product_readme_template", default=None
)


def t(key: str, **values: object) -> str:
    template = _TEMPLATE.get() or load_template("ja")
    return template.t(key, **values)


_FIGURE_TITLE_KEYS = {
    "schematic_view": "readme.literal_121",
    "layered_layout_view": "readme.literal_122",
    "placement_view": "readme.literal_123",
    "stackup_view": "readme.literal_124",
    "system_block_view": "readme.literal_125",
    "power_tree_view": "readme.literal_126",
    "firmware_state_view": "readme.literal_127",
    "firmware_sequence_view": "readme.literal_128",
    "rasterized_view": "readme.literal_129",
    "mechanical_section_view": "readme.literal_130",
    "mechanical_interference_view": "readme.literal_131",
}

_FIGURE_GUIDE_KEYS = {
    "schematic_view": "readme.literal_132",
    "layered_layout_view": "readme.literal_133",
    "placement_view": "readme.literal_134",
    "stackup_view": "readme.literal_135",
    "system_block_view": "readme.literal_136",
    "power_tree_view": "readme.literal_137",
    "firmware_state_view": "readme.literal_138",
    "firmware_sequence_view": "readme.literal_139",
    "rasterized_view": "readme.literal_140",
    "mechanical_section_view": "readme.literal_141",
    "mechanical_interference_view": "readme.literal_142",
}

# Projection domains are grouped into reader-facing areas: the board lane
# emits `electrical` and `system` domains, both shown under the  heading.
_DOMAIN_GROUP = {
    "electrical": "readme.literal_143",
    "system": "readme.literal_143",
    "firmware": "readme.literal_144",
    "mechanical": "readme.literal_145",
}
_DOMAIN_GROUP_ORDER = (
    "readme.literal_143",
    "readme.literal_144",
    "readme.literal_145",
)


def _domain_group(domain: str) -> str:
    return _DOMAIN_GROUP.get(domain, domain)

# Heading text -> GitHub anchor slug (letters/digits kept, punctuation dropped,
# spaces become hyphens; matches scripts/verify_docs.py github_slug).
_SECTION_HEADINGS = (
    ("readme.literal_148", "readme.literal_149"),
    ("readme.literal_150", "readme.literal_151"),
    ("readme.literal_152", "readme.literal_153"),
    ("readme.literal_154", "readme.literal_155"),
    ("readme.literal_156", "readme.literal_157"),
    ("readme.literal_158", "readme.literal_159"),
    ("readme.literal_160", "readme.literal_161"),
    ("readme.literal_162", "readme.literal_163"),
    ("readme.literal_164", "readme.literal_165"),
)
_THEME_HEADING = "readme.literal_162"


def _table_of_contents(has_theme: bool) -> list[str]:
    lines = [t("readme.literal_167"), ""]
    for heading_key, anchor_key in _SECTION_HEADINGS:
        if heading_key == _THEME_HEADING and not has_theme:
            continue
        lines.append(f"- [{t(heading_key)}](#{t(anchor_key)})")
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
        f"{graph.graph_id}（revision {graph.revision}"
        f"{t('readme.literal_104')}{mcu.mpn}{t('readme.literal_105')}"
        f"{t('readme.literal_106')}{format_number(number_attr(board, 'width_mm'))} × "
        f"{format_number(number_attr(board, 'height_mm'))} {unit}{t('readme.literal_107')}"
        f"{t('readme.literal_108')}{text_attr(safety, 'intended_use')}。"
    )


def _evidence_relation_section(
    inputs: Sequence[DocumentInput], theme: ThemeSongFigure | None
) -> list[str]:
    lines = [
        t("readme.literal_168"),
        "",
        t("readme.literal_169") + t("readme.literal_170") + t("readme.literal_171"),
        "",
    ]
    if theme is None:
        lines.append(t("readme.literal_172"))
        lines.append("")
    if inputs:
        lines += [t("readme.literal_173"), "", t("readme.literal_174"), "|---|---|"]
        for item in inputs:
            lines.append(f"| `{item.path.as_posix()}` | `{item.content_hash}` |")
        lines.append("")
    else:
        lines += [
            t("readme.literal_175") + t("readme.literal_176"),
            "",
        ]
    return lines


def _requirements_section(graph: DesignGraph) -> list[str]:
    requirements = nodes_of_kind(graph, "requirement")
    if not requirements:
        raise DocumentGenerationError("graph declares no requirement node")
    lines = [t("readme.literal_177"), "", t("readme.literal_178"), "|---|---|"]
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
        (t("readme.literal_179"), firmware.module.module_name),
        (
            t("readme.literal_180"),
            f"{format_number(number_attr(board, 'width_mm'))} × "
            f"{format_number(number_attr(board, 'height_mm'))} {unit}",
        ),
        (t("readme.literal_181"), str(int_attr(board, "layers"))),
        (t("readme.literal_182"), text_attr(board, "material")),
        (t("readme.literal_183"), f"{format_number(number_attr(board, 'thickness_mm'))} {unit}"),
        (t("readme.literal_184"), text_attr(board, "finish")),
        (t("readme.literal_185"), text_attr(board, "assembly_side")),
        (t("readme.literal_186"), f"{format_number(number_attr(safety, 'max_net_voltage_v'))} V"),
        (t("readme.literal_187"), f"{format_number(number_attr(safety, 'max_current_a'))} A"),
        (t("readme.literal_188"), text_attr(safety, "intended_use")),
    ]
    lines = [t("readme.literal_189"), "", t("readme.literal_190"), "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    return [*lines, ""]


def _power_interface_section(
    lane: ElectricalLane, firmware: FirmwareLane
) -> list[str]:
    lines = [
        t("readme.literal_191"),
        "",
        t("readme.literal_192"),
        "",
        t("readme.literal_193"),
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
    lines += ["", t("readme.literal_194"), "", t("readme.literal_195"), "|---|---|"]
    for assignment in sorted(firmware.pin_assignments, key=lambda item: item.net):
        lines.append(f"| {assignment.net} | IO{assignment.gpio} |")
    return [*lines, ""]


def _firmware_section(
    lane: ElectricalLane, firmware: FirmwareLane
) -> list[str]:
    mcu = lane.component_by_id(firmware.module.mcu_component)
    lines = [
        t("readme.literal_196"),
        "",
        f"{t('readme.literal_109')}{firmware.module.module_name}`"
        f"（node `{firmware.module.node_id}`）",
        f"- MCU: `{mcu.refdes}`",
        f"{t('readme.literal_110')}{firmware.module.entry_state}`",
        "",
        t("readme.literal_197"),
        "",
        t("readme.literal_198"),
        "|---|---|---|",
    ]
    for state in firmware.states:
        initial = "yes" if state.initial else ""
        lines.append(f"| {state.node_id} | {state.state_name} | {initial} |")
    lines += [
        "",
        t("readme.literal_199"),
        "",
        t("readme.literal_200"),
        "|---|---|",
    ]
    for transition in firmware.transitions:
        lines.append(
            f"| {transition.from_state} → {transition.to_state} "
            f"| {transition.trigger} |"
        )
    lines += [
        "",
        t("readme.literal_201"),
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
        t("readme.literal_202"),
        "",
        t("readme.literal_203"),
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
        t("readme.literal_204"),
        "",
        t("readme.literal_205"),
        "",
        t("readme.literal_206"),
        "|---|---|---|---|---|",
    ]
    for (mpn, value, lcsc, assembly), quantity in sorted(counts.items()):
        lines.append(f"| {mpn} | {value} | {lcsc} | {assembly} | {quantity} |")
    component_nodes = {
        node.id: node for node in nodes_of_kind(graph, "electrical.component")
    }
    lines += [
        "",
        t("readme.literal_207"),
        "",
        t("readme.literal_208"),
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
    domain_names = t("readme.literal_253").join(t(group) for group in groups)
    lines = [
        t("readme.literal_209"),
        "",
        f"{t('readme.literal_111')}{domain_names}。",
        t("readme.literal_210"),
        "",
    ]
    for group in groups:
        lines += [f"### {t(group)}", ""]
        for figure in figures:
            if _domain_group(figure.domain) != group:
                continue
            title = t(
                _FIGURE_TITLE_KEYS.get(figure.projection_type, "readme.literal_121")
            )
            guide = t(
                _FIGURE_GUIDE_KEYS.get(figure.projection_type, "readme.literal_132")
            )
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
                f"{t('readme.literal_112')}{figure.projection_type}`（{figure.domain} lane）",
                f"{t('readme.literal_113')}{figure.image_hash}`",
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
    lines = [
        t("readme.literal_212"),
        "",
        t("readme.literal_213"),
        "|---|---|",
        f"{t('readme.literal_114')}{theme.title} |",
        f"{t('readme.literal_115')}{theme.key} |",
        f"| BPM | {theme.bpm} |",
        f"{t('readme.literal_116')}{theme.bars} |",
        f"| composer | `{theme.composer_id}` |",
        f"{t('readme.literal_117')}{theme.source}` |",
        "",
        f"- artifact: [{theme.midi_path.name}]({link})",
        f"- artifact hash: `{theme.midi_hash}`",
        f"- regeneration check: `{theme.regeneration_status}`",
    ]
    if theme.mml_path is not None and theme.mml_hash is not None:
        mml_link = os.path.relpath(theme.mml_path.resolve(), out_dir.resolve()).replace(
            os.sep, "/"
        )
        lines.extend(
            [
                f"- artifact: [{theme.mml_path.name}]({mml_link})",
                f"- artifact hash: `{theme.mml_hash}`",
            ]
        )
    else:
        lines.append(f"{t('readme.literal_118')}{theme.mml_reason or t('readme.literal_119')}）")
    lines.extend(
        [
            "",
            t("readme.literal_214") + t("readme.literal_215"),
            "",
        ]
    )
    return lines


def _attribution_section(lane: ElectricalLane) -> list[str]:
    sources: set[tuple[str, str]] = set()
    for component in lane.components:
        sources.add((component.library.symbol_source, component.library.symbol_source_ref))
        sources.add(
            (component.library.footprint_source, component.library.footprint_source_ref)
        )
    lines = [
        t("readme.literal_216"),
        "",
        t("readme.literal_217") + t("readme.literal_218"),
        "",
        t("readme.literal_219"),
        "|---|---|",
    ]
    lines += [f"| {source} | {ref} |" for source, ref in sorted(sources)]
    lines += [
        "",
        t("readme.literal_220"),
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
    template: DocumentTemplate | None = None,
) -> str:
    """Render the product README body for a graph and its projections."""
    _TEMPLATE.set(template or load_template("ja"))
    lane = extract_electrical_lane(graph)
    firmware = extract_firmware_lane(graph)
    lines = [
        f"{t('readme.literal_120')}{graph.graph_id}",
        "",
        f"- Design Graph: `{graph.graph_id}`",
        f"- revision: `{graph.revision}`",
        "",
        t("readme.literal_221") + t("readme.literal_222"),
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
    parser.add_argument("--lang", choices=("ja", "en"), default="ja")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    template = load_template(args.lang)
    graph, graph_input = load_graph(args.graph)
    figures, projection_inputs = load_projection_figures(args.projections, graph.revision)
    theme = None
    theme_input: DocumentInput | None = None
    if args.theme_song_projection is not None:
        theme, theme_input = load_theme_song(args.theme_song_projection, graph)
    inputs: list[DocumentInput] = [graph_input, *projection_inputs]
    if theme_input is not None:
        inputs.append(theme_input)
    output_dir = args.out_dir if args.lang == "ja" else args.out_dir / args.lang
    body = render_readme(
        graph, figures, output_dir, theme=theme, inputs=inputs, template=template
    )
    document_path, provenance_path = write_document(
        document_kind="product_readme",
        body=body,
        out_dir=output_dir,
        document_name=DOCUMENT_NAME,
        template_id=f"acd-product-readme-{args.lang}-v2",
        generator=Path(__file__).resolve(),
        graph=graph,
        inputs=inputs,
        base_dir=args.base_dir,
        template=template,
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
