# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@78744de4cb56b3575bab87fe50cbdcffc267e408",
# ]
# ///
"""Generate a deterministic workaround work-instruction document."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Literal, cast

from acd.core.rework_diff import load_rework_diff
from acd.pipeline.graph_diff_projection import (
    GraphDiffProjectionError,
    run_graph_diff_projection,
)
from acd.schema.common import canonical_json_sha256
from acd.schema.defect_record import DefectDocument, DefectRecord
from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.rework_diff import (
    FirmwareChange,
    ReworkAdd,
    ReworkCut,
    ReworkOperation,
    ReworkRemove,
    ReworkReplace,
)
from acd.schema.salvage import ReworkDfaDeclaration, SalvageGateResult
from acd.schema.shipping_inspection import InspectionItem
from acd.schema.work_instruction import (
    PostWorkInspection,
    RequiredPart,
    RequiredTool,
    TargetUnits,
    WorkInstructionDocument,
    WorkStep,
)
from doc_inputs import (
    DocumentGenerationError,
    DocumentInput,
    DocumentTemplate,
    load_firmware_config_report,
    load_graph,
    load_template,
    sha256_file,
    write_document,
)
from generate_instruction_manual import parse_pins_header
from generate_shipping_inspection import (
    FirmwareProjectionInputs,
    build_shipping_inspection,
    guarded_firmware_projection_inputs,
)

DOCUMENT_NAME = "work-instruction.md"
JSON_DOCUMENT_NAME = "work-instruction.json"
_INSTRUCTION_TEMPLATE_KEYS = {
    "cut": "work.step.cut",
    "add": "work.step.add",
    "remove": "work.step.remove",
    "replace": "work.step.replace",
    "mechanical": "work.step.mechanical",
    "firmware": "work.step.firmware",
}


def _load_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DocumentGenerationError(f"{label} is not valid: {path}: {exc}") from exc


def _node_map(graph: DesignGraph) -> dict[str, GraphNode]:
    return {node.id: node for node in graph.nodes}


def _text(node: GraphNode | None, name: str) -> str | None:
    if node is None:
        return None
    value = node.attrs.get(name)
    return value if isinstance(value, str) and value else None


def _component_for_body(graph: DesignGraph, component_id: str) -> GraphNode | None:
    for node in graph.nodes:
        if node.kind == "mechanical.component_body" and component_id in node.depends_on:
            return node
    return None


def _position(graph: DesignGraph, component_id: str) -> tuple[float, float] | None:
    body = _component_for_body(graph, component_id)
    if body is None:
        return None
    x = body.attrs.get("x_mm")
    y = body.attrs.get("y_mm")
    if isinstance(x, (int, float)) and not isinstance(x, bool) and isinstance(
        y, (int, float)
    ) and not isinstance(y, bool):
        return (float(x), float(y))
    return None


def _subject_for_operation(operation: ReworkOperation) -> tuple[list[str], str | None]:
    if isinstance(operation, ReworkCut):
        return [operation.pin_id], None
    if isinstance(operation, ReworkAdd):
        return [operation.node.id, *operation.node.depends_on], None
    if isinstance(operation, ReworkRemove | ReworkReplace):
        return [operation.component_id], operation.component_id
    return [operation.target_id], operation.target_id


def _touched_nodes(graph: DesignGraph, operations: list[ReworkOperation]) -> set[str]:
    nodes = _node_map(graph)
    touched: set[str] = set()
    for operation in operations:
        subjects, _ = _subject_for_operation(operation)
        touched.update(subjects)
        if isinstance(operation, ReworkCut):
            pin = nodes.get(operation.pin_id)
            net = pin.attrs.get("net") if pin is not None else None
            if isinstance(net, str):
                touched.add(net)
        if isinstance(operation, ReworkAdd):
            touched.update(operation.node.depends_on)
    return touched


def _defects(
    path: Path, graph: DesignGraph, defect_ids: list[str]
) -> tuple[DefectRecord, ...]:
    try:
        document = DefectDocument.model_validate(_load_json(path, "defect document"))
    except ValueError as exc:
        raise DocumentGenerationError(f"defect document is invalid: {exc}") from exc
    if document.graph_id != graph.graph_id or document.revision != graph.revision:
        raise DocumentGenerationError("defect document does not match the base graph")
    records = {record.defect_id: record for record in document.records}
    missing = sorted(set(defect_ids) - set(records))
    if missing:
        raise DocumentGenerationError("rework references unknown defects: " + ", ".join(missing))
    return tuple(records[item] for item in defect_ids)


def _target_units(records: tuple[DefectRecord, ...]) -> TargetUnits:
    if any(record.affected_units.scope_status == "unknown" for record in records):
        return TargetUnits(scope_status="unknown")
    return TargetUnits(
        lots=sorted({lot for record in records for lot in record.affected_units.lots}),
        serials=sorted({serial for record in records for serial in record.affected_units.serials}),
        scope_status="declared",
    )


def _required_part(
    graph: DesignGraph, operation: ReworkAdd | ReworkReplace, index: int
) -> RequiredPart:
    if isinstance(operation, ReworkAdd):
        node = operation.node
    else:
        node = _node_map(graph).get(operation.component_id)
        if node is None:
            raise DocumentGenerationError(
                f"required part component is missing: {operation.component_id}"
            )
    refdes = _text(node, "refdes")
    if refdes is None:
        raise DocumentGenerationError(f"required part {node.id} has no refdes")
    mpn = _text(node, "mpn")
    return RequiredPart(
        refdes=refdes,
        mpn=mpn,
        value=_text(node, "value"),
        footprint=_text(node, "footprint"),
        source_op_index=index,
        unknown_reason=None if mpn else "missing component mpn",
    )


def _required_tools(
    dfa: ReworkDfaDeclaration, operation_count: int
) -> list[RequiredTool]:
    assessments = {item.operation_index: item for item in dfa.assessments}
    tools: list[RequiredTool] = []
    for index in range(operation_count):
        assessment = assessments.get(index)
        if assessment is None:
            raise DocumentGenerationError(f"DFA assessment is missing for operation {index}")
        tools.append(
            RequiredTool(
                op_index=index,
                tool_access=assessment.tool_access,
                hand_solderable=assessment.hand_solderable,
                enclosure_disassembly=assessment.enclosure_disassembly,
                basis=assessment.basis,
            )
        )
    return tools


def _steps(
    graph: DesignGraph,
    operations: list[ReworkOperation],
    changes: list[FirmwareChange],
) -> list[WorkStep]:
    nodes = _node_map(graph)
    result: list[WorkStep] = []
    for step_index, operation in enumerate(operations):
        subjects, component_id = _subject_for_operation(operation)
        node = nodes.get(component_id) if component_id is not None else None
        result.append(
            WorkStep(
                step_index=step_index,
                op_index=step_index,
                op=operation.op,
                subject_node_ids=subjects,
                refdes=_text(node, "refdes"),
                position_mm=_position(graph, component_id) if component_id else None,
                instruction_key=_INSTRUCTION_TEMPLATE_KEYS[operation.op],
                reason=operation.reason,
            )
        )
    offset = len(operations)
    for index, change in enumerate(changes):
        functions = ", ".join(change.affected_functions)
        result.append(
            WorkStep(
                step_index=offset + index,
                op_index=None,
                op="firmware",
                subject_node_ids=list(change.affected_functions),
                instruction_key=_INSTRUCTION_TEMPLATE_KEYS["firmware"],
                reason=f"{change.kind}: {change.description}; affected_functions: {functions}",
            )
        )
    return result


def _filtered_inspection(
    graph: DesignGraph,
    firmware: FirmwareProjectionInputs | None,
    touched: set[str],
) -> PostWorkInspection:
    inspection = build_shipping_inspection(graph, firmware)
    items: list[InspectionItem] = []
    firmware_categories = {"flash_boot", "led", "sensor", "serial"}
    for item in inspection.items:
        if item.category not in firmware_categories and (
            item.category != "power"
            and not set(item.subject_node_ids) & touched
        ):
            continue
        items.append(item)
    return PostWorkInspection(items=items)


def _highlight(
    graph_path: Path, derived_path: Path, out_dir: Path, project_name: str
) -> str:
    try:
        projection_path = run_graph_diff_projection(
            graph_path=derived_path,
            previous_graph_path=graph_path,
            out_dir=out_dir / "work-instruction-visual",
            project_name=project_name,
        )
        payload = json.loads(projection_path.read_text(encoding="utf-8"))
        image_path = payload["projections"][0]["image_path"]
        svg = projection_path.parent / image_path
        if not isinstance(image_path, str) or not svg.is_file():
            raise DocumentGenerationError("graph diff projection SVG is missing")
        return (Path("work-instruction-visual") / image_path).as_posix()
    except (GraphDiffProjectionError, OSError, KeyError, TypeError, ValueError) as exc:
        raise DocumentGenerationError(
            f"work-instruction highlight projection failed: {exc}"
        ) from exc


def build_work_instruction(
    *,
    graph: DesignGraph,
    defects_path: Path,
    rework_path: Path,
    dfa_path: Path,
    salvage_dir: Path,
    pins_header: Path,
    report_path: Path,
    out_dir: Path,
    graph_input: DocumentInput,
) -> tuple[WorkInstructionDocument, list[DocumentInput], Path]:
    loaded = load_rework_diff(rework_path)
    diff = loaded.diff
    if diff.graph_id != graph.graph_id or diff.base_revision != graph.revision:
        raise DocumentGenerationError("rework does not match the base graph")
    records = _defects(defects_path, graph, diff.defect_ids)
    try:
        dfa = ReworkDfaDeclaration.model_validate_json(
            dfa_path.read_text(encoding="utf-8")
        )
        salvage_path = salvage_dir / "salvage-gate.json"
        if not salvage_path.is_file():
            salvage_path = salvage_dir / "salvage-gate-result.json"
        salvage = SalvageGateResult.model_validate_json(
            salvage_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise DocumentGenerationError(f"salvage inputs are invalid: {exc}") from exc
    if salvage.verdict not in {"salvageable", "constrained_salvage"}:
        raise DocumentGenerationError("workaround is not salvageable")
    if (
        salvage.workaround_id != diff.workaround_id
        or salvage.graph_id != graph.graph_id
        or salvage.derived_revision != diff.derived_revision
        or dfa.workaround_id != diff.workaround_id
        or dfa.graph_id != graph.graph_id
        or dfa.base_revision != graph.revision
    ):
        raise DocumentGenerationError("salvage inputs do not match the rework")
    derived_path = salvage_dir / "derived-graph.json"
    provenance_path = salvage_dir / "derived-graph.provenance.json"
    derived_payload = _load_json(derived_path, "derived graph")
    provenance = _load_json(provenance_path, "derived graph provenance")
    if not isinstance(provenance, dict) or cast(dict[str, object], provenance).get(
        "derived_graph_sha256"
    ) != canonical_json_sha256(derived_payload):
        raise DocumentGenerationError("derived graph provenance hash mismatch")
    try:
        derived = DesignGraph.model_validate(derived_payload)
    except ValueError as exc:
        raise DocumentGenerationError(f"derived graph is invalid: {exc}") from exc
    if derived.graph_id != graph.graph_id or derived.revision != diff.derived_revision:
        raise DocumentGenerationError("derived graph does not match the rework")
    macros = parse_pins_header(pins_header)
    report = load_firmware_config_report(report_path)
    guarded_firmware_projection_inputs(graph, report, macros)
    required_parts = [
        _required_part(derived, operation, index)
        for index, operation in enumerate(diff.operations)
        if isinstance(operation, ReworkAdd | ReworkReplace)
    ]
    tools = _required_tools(dfa, len(diff.operations))
    steps = _steps(derived, diff.operations, diff.firmware_changes)
    touched = _touched_nodes(graph, diff.operations)
    post = _filtered_inspection(derived, None, touched)
    highlight = _highlight(
        graph_input.path,
        derived_path,
        out_dir,
        f"{graph.graph_id}-{diff.workaround_id}",
    )
    document = WorkInstructionDocument(
        graph_id=graph.graph_id,
        base_revision=graph.revision,
        derived_revision=derived.revision,
        workaround_id=diff.workaround_id,
        defect_ids=diff.defect_ids,
        salvage_verdict=cast(
            Literal["salvageable", "constrained_salvage"], salvage.verdict
        ),
        degraded_functions=salvage.degraded_functions,
        target_units=_target_units(records),
        required_parts=required_parts,
        required_tools=tools,
        steps=steps,
        highlight_projection=highlight,
        post_work_inspection=post,
    )
    inputs = [
        graph_input,
        DocumentInput(defects_path, sha256_file(defects_path)),
        DocumentInput(rework_path, sha256_file(rework_path)),
        DocumentInput(dfa_path, sha256_file(dfa_path)),
        DocumentInput(
            salvage_path,
            sha256_file(salvage_path),
        ),
        DocumentInput(derived_path, sha256_file(derived_path)),
        DocumentInput(provenance_path, sha256_file(provenance_path)),
        DocumentInput(pins_header, sha256_file(pins_header)),
        DocumentInput(report_path, sha256_file(report_path)),
    ]
    return document, inputs, derived_path


def _render(document: WorkInstructionDocument, template: DocumentTemplate) -> str:
    t = template.t
    lines = [
        t("work.document_title", graph_id=document.graph_id),
        t("work.provenance_paragraph"),
        t("work.target_heading"),
        t(
            "work.target_units",
            lots=", ".join(document.target_units.lots) or t("work.none"),
            serials=", ".join(document.target_units.serials) or t("work.none"),
            scope_status=document.target_units.scope_status,
        ),
        t("work.parts_heading"),
    ]
    for part in document.required_parts:
        lines.append(
            t(
                "work.part_row",
                refdes=part.refdes,
                mpn=part.mpn or t("work.unknown"),
                value=part.value or t("work.unknown"),
                footprint=part.footprint or t("work.unknown"),
                reason=part.unknown_reason or t("work.none"),
            )
        )
    if not document.required_parts:
        lines.append(t("work.none"))
    lines.append(t("work.tools_heading"))
    for tool in document.required_tools:
        lines.append(
            t(
                "work.tool_row",
                op_index=tool.op_index,
                tool_access=tool.tool_access,
                hand_solderable=tool.hand_solderable,
                enclosure_disassembly=tool.enclosure_disassembly,
                basis=tool.basis,
            )
        )
    if not document.required_tools:
        lines.append(t("work.none"))
    lines.append(t("work.steps_heading"))
    if document.salvage_verdict == "constrained_salvage":
        lines.append(
            t(
                "work.constrained_warning",
                functions=", ".join(document.degraded_functions),
            )
        )
    for step in document.steps:
        lines.append(
            t(
                "work.step_row",
                step_index=step.step_index + 1,
                op=step.op,
                subject=", ".join(step.subject_node_ids),
                instruction=t(step.instruction_key),
                reason=step.reason,
                refdes=step.refdes or t("work.none"),
                position=(
                    f"{step.position_mm[0]}, {step.position_mm[1]}"
                    if step.position_mm is not None
                    else t("work.none")
                ),
            )
        )
    lines.extend(
        [
            t("work.highlight_heading"),
            f"[{document.highlight_projection}]({document.highlight_projection})",
            t("work.inspection_heading"),
        ]
    )
    for item in document.post_work_inspection.items:
        criterion = item.criterion.unknown_reason or str(item.criterion.expected)
        lines.append(
            t(
                "work.inspection_row",
                item_id=item.item_id,
                category=item.category,
                criterion=criterion,
            )
        )
    return "\n".join(lines) + "\n"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--defects", type=Path, required=True)
    parser.add_argument("--rework", type=Path, required=True)
    parser.add_argument("--dfa", type=Path, required=True)
    parser.add_argument("--salvage-dir", type=Path, required=True)
    parser.add_argument("--pins-header", type=Path, required=True)
    parser.add_argument("--firmware-config-report", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    parser.add_argument("--lang", choices=("ja", "en"), default="ja")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    temp_dir = Path(tempfile.mkdtemp(prefix=".work-instruction-", dir=args.out_dir.parent))
    try:
        template = load_template(args.lang)
        graph, graph_input = load_graph(args.graph)
        document, inputs, _ = build_work_instruction(
            graph=graph,
            defects_path=args.defects,
            rework_path=args.rework,
            dfa_path=args.dfa,
            salvage_dir=args.salvage_dir,
            pins_header=args.pins_header,
            report_path=args.firmware_config_report,
            out_dir=temp_dir,
            graph_input=graph_input,
        )
        body = _render(document, template)
        output_dir = temp_dir if args.lang == "ja" else temp_dir / args.lang
        write_document(
            document_kind="work_instruction",
            body=body,
            out_dir=output_dir,
            document_name=DOCUMENT_NAME,
            template_id=f"acd-work-instruction-{args.lang}-v1",
            generator=Path(__file__).resolve(),
            graph=graph,
            inputs=inputs,
            base_dir=args.base_dir,
            template=template,
        )
        write_document(
            document_kind="work_instruction_json",
            body=(
                json.dumps(
                    document.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ),
            out_dir=output_dir,
            document_name=JSON_DOCUMENT_NAME,
            template_id=f"acd-work-instruction-{args.lang}-v1",
            generator=Path(__file__).resolve(),
            graph=graph,
            inputs=inputs,
            base_dir=args.base_dir,
            template=template,
        )
        args.out_dir.parent.mkdir(parents=True, exist_ok=True)
        if args.out_dir.exists():
            raise DocumentGenerationError(f"output directory already exists: {args.out_dir}")
        os.replace(temp_dir, args.out_dir)
        print(f"generated {args.out_dir / DOCUMENT_NAME}")
        return 0
    except (DocumentGenerationError, OSError, ValueError) as error:
        print(f"work instruction generation failed: {error}", file=sys.stderr)
        return 1
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
