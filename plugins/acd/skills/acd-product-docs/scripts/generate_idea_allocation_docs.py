# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@e8d0307410666e9ed11f794b9e46d0595a3528f3",
# ]
# ///
"""Project idea refinement and responsibility allocation into L3 documents.

The generator joins the IdeaRecord, the estimate catalog, and the
responsibility declaration with the design graph and renders the idea record,
the rough estimate, the responsibility allocation, and a cross-domain block
diagram. All outputs are L3 observations; open items are rendered as ``open``
and never guessed. The dialogue history (idea-dialogue.json) is internal and
is never read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.idea_dialogue import load_idea_record
from acd.core.idea_estimate import estimate_idea, load_estimate_catalog
from acd.core.responsibility_gate import (
    check_responsibility,
    load_responsibility_declaration,
)
from acd.schema.design_graph import DesignGraph
from acd.schema.idea import IdeaField, IdeaRecord
from acd.schema.idea_estimate import IdeaEstimateCatalog, IdeaRoughEstimate
from acd.schema.responsibility import (
    ResponsibilityDeclaration,
    ResponsibilityDomain,
    ResponsibilityGateResult,
)
from doc_inputs import (
    DocumentGenerationError,
    DocumentInput,
    DocumentTemplate,
    load_graph,
    load_template,
    sha256_file,
    write_document,
)

TEMPLATE_ID = "acd-idea-allocation-ja-v1"
IDEA_DOCUMENT_NAME = "idea-record.md"
ESTIMATE_DOCUMENT_NAME = "rough-estimate.md"
ESTIMATE_JSON_NAME = "rough-estimate.json"
ALLOCATION_DOCUMENT_NAME = "responsibility-allocation.md"
ALLOCATION_JSON_NAME = "responsibility-allocation.json"
SVG_DOCUMENT_NAME = "cross-domain-block-diagram.svg"

_DOMAIN_ORDER: tuple[ResponsibilityDomain, ...] = (
    "mechanism",
    "mechanical",
    "electrical",
    "firmware",
    "pc_software",
    "server",
    "mobile_app",
)


def _load_inputs(
    args: argparse.Namespace,
) -> tuple[
    DesignGraph,
    IdeaRecord,
    IdeaEstimateCatalog,
    ResponsibilityDeclaration,
    list[DocumentInput],
]:
    graph, graph_input = load_graph(args.graph)
    inputs = [graph_input]
    for path in (args.idea, args.estimate_catalog, args.responsibility):
        inputs.append(
            DocumentInput(path=path, content_hash=sha256_file(path))
        )
    try:
        idea = load_idea_record(args.idea)
        catalog = load_estimate_catalog(args.estimate_catalog)
        declaration = load_responsibility_declaration(args.responsibility)
    except ValueError as exc:
        raise DocumentGenerationError(str(exc)) from exc
    if (
        declaration.graph_id != graph.graph_id
        or declaration.revision != graph.revision
    ):
        raise DocumentGenerationError(
            "responsibility declaration does not match the design graph "
            f"{graph.graph_id}@{graph.revision}"
        )
    declared_idea_functions = {item.function_id for item in idea.functions}
    referenced = {item.function_id for item in declaration.functions}
    for node in graph.nodes:
        if node.kind == "design.responsibility":
            function_id = node.attrs.get("function_id")
            if isinstance(function_id, str):
                referenced.add(function_id)
    unknown = sorted(referenced - declared_idea_functions)
    if unknown:
        raise DocumentGenerationError(
            "function ids are not declared in the idea record: "
            + ", ".join(unknown)
        )
    return graph, idea, catalog, declaration, inputs


def _field_value(field: IdeaField) -> str:
    if field.status == "open" or field.value is None:
        return "open"
    value = str(field.value)
    return f"{value} {field.unit}" if field.unit else value


def _field_sources(field: IdeaField) -> str:
    return ", ".join(f"{s.kind}:{s.ref}" for s in field.sources) or "-"


def _scalar_rows(idea: IdeaRecord) -> list[tuple[str, IdeaField]]:
    return [
        ("purpose", idea.purpose),
        ("target_users", idea.target_users),
        ("experience", idea.experience),
        ("environment", idea.environment),
        ("constraints.cost", idea.constraints.cost),
        ("constraints.dimensions", idea.constraints.dimensions),
        ("constraints.power", idea.constraints.power),
        ("constraints.communication", idea.constraints.communication),
        ("constraints.regulatory", idea.constraints.regulatory),
    ]


def _render_idea_record(idea: IdeaRecord, template: DocumentTemplate) -> str:
    lines = [
        template.t("idea.record_title", title=idea.title),
        "",
        f"idea_id: `{idea.idea_id}` / revision: `{idea.revision}`",
        "",
        template.t("idea.record_fields_heading"),
        "",
        "| path | status | value | sources |",
        "|---|---|---|---|",
    ]
    for path, field in _scalar_rows(idea):
        lines.append(
            f"| {path} | {field.status} | {_field_value(field)} "
            f"| {_field_sources(field)} |"
        )
    lines += ["", template.t("idea.record_success_heading"), ""]
    if idea.success_criteria:
        lines += ["| criterion | status | value | sources |", "|---|---|---|---|"]
        for item in idea.success_criteria:
            field = item.statement
            lines.append(
                f"| {item.criterion_id} | {field.status} "
                f"| {_field_value(field)} | {_field_sources(field)} |"
            )
    else:
        lines.append("success_criteria: open")
    lines += ["", template.t("idea.record_functions_heading"), ""]
    if idea.functions:
        lines += [
            "| function | priority | function_class | status | value |",
            "|---|---|---|---|---|",
        ]
        for item in idea.functions:
            field = item.description
            lines.append(
                f"| {item.function_id} | {item.priority} "
                f"| {item.function_class or '-'} | {field.status} "
                f"| {_field_value(field)} |"
            )
    else:
        lines.append("functions: open")
    lines += [
        "",
        "---",
        "This is a projection of the idea record; open items block "
        "requirement promotion.",
        "",
    ]
    return "\n".join(lines)


def _render_estimate_markdown(
    estimate: IdeaRoughEstimate, template: DocumentTemplate
) -> str:
    lines = [
        template.t("idea.estimate_title"),
        "",
        "This document is an estimate. Totals exclude functions without a "
        "catalog entry; findings are L3 observations, not approvals.",
        "",
        "## Lines",
        "",
        "| function | class | typical part | unit cost JPY | power mW | "
        "footprint mm2 |",
        "|---|---|---|---|---|---|",
    ]
    for line in estimate.lines:
        lines.append(
            f"| {line.function_id} | {line.function_class} "
            f"| {line.typical_part} "
            f"| {line.unit_cost_jpy.min}301c{line.unit_cost_jpy.max} "
            f"| {line.power_mw.min}301c{line.power_mw.max} "
            f"| {line.footprint_mm2} |"
        )
    if estimate.unknown_functions:
        lines += [
            "",
            template.t("idea.estimate_unknown_heading"),
            "",
            "| function | reason |",
            "|---|---|",
        ]
        for item in estimate.unknown_functions:
            lines.append(f"| {item.function_id} | {item.reason} |")
    totals = estimate.totals
    lines += [
        "",
        template.t("idea.estimate_total_heading"),
        "",
        f"- cost_jpy: {totals.cost_jpy.min}301c{totals.cost_jpy.max}",
        f"- power_mw: {totals.power_mw.min}301c{totals.power_mw.max}",
        f"- footprint_mm2: {totals.footprint_mm2}",
        f"- covers_all_functions: {str(totals.covers_all_functions).lower()}",
        "",
        "## Findings",
        "",
        "| constraint | status | detail |",
        "|---|---|---|",
    ]
    for finding in estimate.findings:
        lines.append(
            f"| {finding.constraint} | {finding.status} | {finding.detail} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_allocation_markdown(
    declaration: ResponsibilityDeclaration,
    result: ResponsibilityGateResult,
    template: DocumentTemplate,
) -> str:
    lines = [
        template.t("idea.allocation_title"),
        "",
        f"gate status: **{result.status}** (L3 observation; it does not grant "
        "approval)",
        "",
        template.t("idea.allocation_heading"),
        "",
        "| function | domain | node | criteria |",
        "|---|---|---|---|",
    ]
    for assignment in result.assignments:
        lines.append(
            f"| {assignment.function_id} | {assignment.domain} "
            f"| {assignment.node_id} | {', '.join(assignment.criteria)} |"
        )
    lines += [
        "",
        "## Domain capabilities",
        "",
        "| domain | gpio_count | communication | memory_kb | power_sources | "
        "motion |",
        "|---|---|---|---|---|---|",
    ]
    for capability in declaration.capabilities:
        lines.append(
            f"| {capability.domain} | {capability.gpio_count} "
            f"| {capability.communication} | {capability.memory_kb} "
            f"| {capability.power_sources} | {capability.motion} |"
        )
    lines += [
        "",
        "## Cross-domain interfaces",
        "",
        "| interface | domains | signal | protocol | power | declared_by | "
        "one_sided |",
        "|---|---|---|---|---|---|---|",
    ]
    for interface in declaration.interfaces:
        one_sided = set(interface.declared_by) != set(interface.domains)
        lines.append(
            f"| {interface.interface_id} | {'/'.join(interface.domains)} "
            f"| {interface.signal} | {interface.protocol} | {interface.power} "
            f"| {', '.join(interface.declared_by)} "
            f"| {str(one_sided).lower()} |"
        )
    lines += [
        "",
        "## Gate findings",
        "",
        "| code | subject | detail |",
        "|---|---|---|",
    ]
    for finding in result.findings:
        lines.append(
            f"| {finding.code} | {finding.subject} | {finding.detail} |"
        )
    if not result.findings:
        lines.append("| - | - | no findings |")
    lines.append("")
    return "\n".join(lines)


def _render_block_svg(
    declaration: ResponsibilityDeclaration, result: ResponsibilityGateResult
) -> str:
    used_domains = [
        domain
        for domain in _DOMAIN_ORDER
        if any(c.domain == domain for c in declaration.capabilities)
        or any(a.domain == domain for a in result.assignments)
    ]
    box_w, box_h, gap, top, left = 170, 140, 40, 40, 20
    positions = {
        domain: (left + index * (box_w + gap), top)
        for index, domain in enumerate(used_domains)
    }
    width = left * 2 + len(used_domains) * box_w + max(
        0, len(used_domains) - 1
    ) * gap
    height = top * 2 + box_h
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">',
    ]
    functions_by_domain: dict[str, list[str]] = {}
    for assignment in result.assignments:
        functions_by_domain.setdefault(assignment.domain, []).append(
            assignment.function_id
        )
    for interface in declaration.interfaces:
        if interface.domains[0] in positions and interface.domains[1] in positions:
            x1 = positions[interface.domains[0]][0] + box_w
            y1 = positions[interface.domains[0]][1] + box_h // 2
            x2 = positions[interface.domains[1]][0]
            y2 = positions[interface.domains[1]][1] + box_h // 2
            dashed = set(interface.declared_by) != set(interface.domains)
            dash = ' stroke-dasharray="6 4"' if dashed else ""
            label = f"{interface.signal}/{interface.protocol}"
            parts.append(
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                f'stroke="black"{dash}/>'
            )
            mid_x, mid_y = (x1 + x2) // 2, (y1 + y2) // 2 - 4
            parts.append(
                f'<text x="{mid_x}" y="{mid_y}" font-size="10" '
                f'text-anchor="middle">{_escape(label)}</text>'
            )
    for domain in used_domains:
        x, y = positions[domain]
        parts.append(
            f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" '
            f'fill="white" stroke="black"/>'
        )
        parts.append(
            f'<text x="{x + box_w // 2}" y="{y + 18}" font-size="12" '
            f'text-anchor="middle" font-weight="bold">{domain}</text>'
        )
        for index, function_id in enumerate(
            sorted(functions_by_domain.get(domain, []))
        ):
            parts.append(
                f'<text x="{x + 8}" y="{y + 40 + index * 16}" '
                f'font-size="10">{_escape(function_id)}</text>'
            )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--idea", type=Path, required=True)
    parser.add_argument("--estimate-catalog", type=Path, required=True)
    parser.add_argument("--responsibility", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        graph, idea, catalog, declaration, inputs = _load_inputs(args)
        estimate = estimate_idea(idea, catalog)
    except DocumentGenerationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    result = check_responsibility(graph, declaration)
    generator = Path(__file__).resolve()
    template = load_template("ja")

    documents = [
        (
            "idea_record",
            _render_idea_record(idea, template),
            IDEA_DOCUMENT_NAME,
        ),
        (
            "rough_estimate",
            _render_estimate_markdown(estimate, template),
            ESTIMATE_DOCUMENT_NAME,
        ),
        (
            "rough_estimate_json",
            json.dumps(
                estimate.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            ESTIMATE_JSON_NAME,
        ),
        (
            "responsibility_allocation",
            _render_allocation_markdown(declaration, result, template),
            ALLOCATION_DOCUMENT_NAME,
        ),
        (
            "responsibility_allocation_json",
            json.dumps(
                result.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            ALLOCATION_JSON_NAME,
        ),
        (
            "cross_domain_block_diagram",
            _render_block_svg(declaration, result),
            SVG_DOCUMENT_NAME,
        ),
    ]
    for kind, body, name in documents:
        document_path, provenance_path = write_document(
            document_kind=kind,
            body=body,
            out_dir=args.out_dir,
            document_name=name,
            template_id=TEMPLATE_ID,
            generator=generator,
            graph=graph,
            inputs=inputs,
            base_dir=args.base_dir,
            template=template,
        )
        print(f"generated {document_path}")
        print(f"provenance {provenance_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
