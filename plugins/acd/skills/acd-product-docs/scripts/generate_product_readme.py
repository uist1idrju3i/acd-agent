# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@cf1b2e58fce9573ae3bcb66b6300b9a4fd236c3e",
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
    "schematic_view": "readme.figure_title_schematic",
    "layered_layout_view": "readme.figure_title_layered_layout",
    "placement_view": "readme.figure_title_placement",
    "stackup_view": "readme.figure_title_stackup",
    "system_block_view": "readme.figure_title_system_block",
    "power_tree_view": "readme.figure_title_power_tree",
    "firmware_state_view": "readme.figure_title_firmware_state",
    "firmware_sequence_view": "readme.figure_title_firmware_sequence",
    "rasterized_view": "readme.figure_title_rasterized",
    "mechanical_section_view": "readme.figure_title_mechanical_section",
    "mechanical_interference_view": "readme.figure_title_mechanical_interference",
}

_FIGURE_GUIDE_KEYS = {
    "schematic_view": "readme.figure_guide_schematic",
    "layered_layout_view": "readme.figure_guide_layered_layout",
    "placement_view": "readme.figure_guide_placement",
    "stackup_view": "readme.figure_guide_stackup",
    "system_block_view": "readme.figure_guide_system_block",
    "power_tree_view": "readme.figure_guide_power_tree",
    "firmware_state_view": "readme.figure_guide_firmware_state",
    "firmware_sequence_view": "readme.figure_guide_firmware_sequence",
    "rasterized_view": "readme.figure_guide_rasterized",
    "mechanical_section_view": "readme.figure_guide_mechanical_section",
    "mechanical_interference_view": "readme.figure_guide_mechanical_interference",
}

# Projection domains are grouped into reader-facing areas: the board lane
# emits `electrical` and `system` domains, both shown under the  heading.
_DOMAIN_GROUP = {
    "electrical": "readme.domain_board",
    "system": "readme.domain_board",
    "firmware": "readme.domain_board_alias",
    "mechanical": "readme.domain_enclosure",
}
_DOMAIN_GROUP_ORDER = (
    "readme.domain_board",
    "readme.domain_board_alias",
    "readme.domain_enclosure",
)


def _domain_group(domain: str) -> str:
    return _DOMAIN_GROUP.get(domain, domain)

# Heading text -> GitHub anchor slug (letters/digits kept, punctuation dropped,
# spaces become hyphens; matches scripts/verify_docs.py github_slug).
_SECTION_HEADINGS = (
    ("readme.section_artifacts", "readme.anchor_artifacts"),
    ("readme.section_requirements", "readme.anchor_requirements"),
    ("readme.section_specifications", "readme.anchor_specifications"),
    ("readme.section_power_interfaces", "readme.anchor_power_interfaces"),
    ("readme.section_firmware", "readme.anchor_firmware"),
    ("readme.section_bom", "readme.anchor_bom"),
    ("readme.section_visual_projections", "readme.anchor_visual_projections"),
    ("readme.section_theme_song", "readme.anchor_theme_song"),
    ("readme.section_attribution", "readme.anchor_attribution"),
)
_THEME_HEADING = "readme.section_theme_song"


def _table_of_contents(has_theme: bool) -> list[str]:
    lines = [t("readme.contents_heading"), ""]
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
    return t(
        "readme.overview_sentence",
        graph_id=graph.graph_id,
        revision=graph.revision,
        mcu_mpn=mcu.mpn,
        width=format_number(number_attr(board, "width_mm")),
        height=format_number(number_attr(board, "height_mm")),
        unit=unit,
        intended_use=text_attr(safety, "intended_use"),
    )


def _evidence_relation_section(
    inputs: Sequence[DocumentInput], theme: ThemeSongFigure | None
) -> list[str]:
    lines = [
        t("readme.artifacts_heading"),
        "",
        t("readme.observation_paragraph"),
        "",
    ]
    if theme is None:
        lines.append(t("readme.inputs_header"))
        lines.append("")
    if inputs:
        lines += [
            t("readme.inputs_provenance_note"),
            "",
            t("readme.requirements_heading"),
            "|---|---|",
        ]
        for item in inputs:
            lines.append(f"| `{item.path.as_posix()}` | `{item.content_hash}` |")
        lines.append("")
    else:
        lines += [
            t("readme.provenance_location_note"),
            "",
        ]
    return lines


def _requirements_section(graph: DesignGraph) -> list[str]:
    requirements = nodes_of_kind(graph, "requirement")
    if not requirements:
        raise DocumentGenerationError("graph declares no requirement node")
    lines = [t("readme.board_outline_label"), "", t("readme.layer_count_label"), "|---|---|"]
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
        (t("readme.board_material_label"), firmware.module.module_name),
        (
            t("readme.board_thickness_label"),
            f"{format_number(number_attr(board, 'width_mm'))} × "
            f"{format_number(number_attr(board, 'height_mm'))} {unit}",
        ),
        (t("readme.surface_finish_label"), str(int_attr(board, "layers"))),
        (t("readme.assembly_side_label"), text_attr(board, "material")),
        (
            t("readme.max_voltage_label"),
            f"{format_number(number_attr(board, 'thickness_mm'))} {unit}",
        ),
        (t("readme.max_current_label"), text_attr(board, "finish")),
        (t("readme.intended_use_label"), text_attr(board, "assembly_side")),
        (
            t("readme.specifications_heading"),
            f"{format_number(number_attr(safety, 'max_net_voltage_v'))} V",
        ),
        (
            t("readme.specifications_header"),
            f"{format_number(number_attr(safety, 'max_current_a'))} A",
        ),
        (t("readme.power_interfaces_heading"), text_attr(safety, "intended_use")),
    ]
    lines = [
        t("readme.power_nets_heading"),
        "",
        t("readme.table.spec_header"),
        "|---|---|",
    ]
    lines += [t("readme.table.spec_row", name=name, value=value) for name, value in rows]
    return [*lines, ""]


def _power_interface_section(
    lane: ElectricalLane, firmware: FirmwareLane
) -> list[str]:
    lines = [
        t("readme.interface_assignments_heading"),
        "",
        t("readme.interface_assignments_header"),
        "",
        t("readme.firmware_heading"),
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
    lines += ["", t("readme.states_heading"), "", t("readme.states_header"), "|---|---|"]
    for assignment in sorted(firmware.pin_assignments, key=lambda item: item.net):
        lines.append(f"| {assignment.net} | IO{assignment.gpio} |")
    return [*lines, ""]


def _firmware_section(
    lane: ElectricalLane, firmware: FirmwareLane
) -> list[str]:
    mcu = lane.component_by_id(firmware.module.mcu_component)
    lines = [
        t("readme.transitions_heading"),
        "",
        t(
            "readme.firmware_module_sentence",
            module=firmware.module.module_name,
            node_id=firmware.module.node_id,
        ),
        f"- MCU: `{mcu.refdes}`",
        t(
            "readme.firmware_initial_sentence",
            state=firmware.module.entry_state,
        ),
        "",
        t("readme.transitions_header"),
        "",
        t("readme.sequence_heading"),
        "|---|---|---|",
    ]
    for state in firmware.states:
        initial = "yes" if state.initial else ""
        lines.append(f"| {state.node_id} | {state.state_name} | {initial} |")
    lines += [
        "",
        t("readme.pin_assignments_heading"),
        "",
        t("readme.pin_assignments_header"),
        "|---|---|",
    ]
    for transition in firmware.transitions:
        lines.append(
            f"| {transition.from_state} → {transition.to_state} "
            f"| {transition.trigger} |"
        )
    lines += [
        "",
        t("readme.bom_heading"),
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
        t("readme.bom_summary_heading"),
        "",
        t("readme.bom_summary_header"),
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
        t("readme.bom_details_heading"),
        "",
        t("readme.bom_details_header"),
        "",
        t("readme.figures_heading"),
        "|---|---|---|---|---|",
    ]
    for (mpn, value, lcsc, assembly), quantity in sorted(counts.items()):
        lines.append(f"| {mpn} | {value} | {lcsc} | {assembly} | {quantity} |")
    component_nodes = {
        node.id: node for node in nodes_of_kind(graph, "electrical.component")
    }
    lines += [
        "",
        t("readme.figures_missing"),
        "",
        t("readme.theme_heading"),
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
    domain_names = "/".join(t(group) for group in groups)
    lines = [
        t("readme.theme_header"),
        "",
        t("readme.figure_domain_sentence", domains=domain_names),
        t("readme.theme_intro"),
        "",
    ]
    for group in groups:
        lines += [f"### {t(group)}", ""]
        for figure in figures:
            if _domain_group(figure.domain) != group:
                continue
            title = t(
                _FIGURE_TITLE_KEYS.get(figure.projection_type, "readme.figure_title_schematic")
            )
            guide = t(
                _FIGURE_GUIDE_KEYS.get(figure.projection_type, "readme.figure_guide_schematic")
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
                t(
                    "readme.figure_type_sentence",
                    projection_type=figure.projection_type,
                    domain=figure.domain,
                ),
                t("readme.figure_hash_sentence", image_hash=figure.image_hash),
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
        t("readme.attribution_heading"),
        "",
        t("readme.attribution_intro"),
        "|---|---|",
        t("readme.theme_title_row", title=theme.title),
            t("readme.theme_key_row", theme_key=theme.key),
        t("readme.theme_bpm_row", bpm=theme.bpm),
        t("readme.theme_bars_row", bars=theme.bars),
        t("readme.theme_composer_row", composer_id=theme.composer_id),
        t("readme.theme_source_row", source=theme.source),
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
        lines.append(
            t(
                "readme.theme_mml_omitted",
                reason=theme.mml_reason or t("readme.legacy_reason"),
            )
        )
    lines.extend(
        [
            "",
            t("readme.theme_license_note"),
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
        t("readme.library_attribution_heading"),
        "",
        t("readme.library_attribution_intro"),
        "",
        t("readme.library_attribution_header"),
        "|---|---|",
    ]
    lines += [f"| {source} | {ref} |" for source, ref in sorted(sources)]
    lines += [
        "",
        t("readme.library_license_statement"),
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
        t("readme.document_title", graph_id=graph.graph_id),
        "",
        f"- Design Graph: `{graph.graph_id}`",
        f"- revision: `{graph.revision}`",
        "",
        t("readme.provenance_observation"),
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
