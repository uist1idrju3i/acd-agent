# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@cd8b09b0a49991197029be72448e91ac7b041219",
# ]
# ///
"""Generate a deterministic bring-up test plan from shipping inspection."""

from __future__ import annotations

import argparse
import json
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Literal, cast

from acd.schema.bringup_plan import (
    BringUpItem,
    BringUpTestPlan,
    MeasurementTemplate,
)
from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.feedback import FeedbackPolicy
from acd.schema.shipping_inspection import CriterionSource, InspectionItem
from doc_inputs import (
    DocumentGenerationError,
    DocumentInput,
    DocumentTemplate,
    load_firmware_config_report,
    load_firmware_inspection_sequence,
    load_graph,
    load_json_object,
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

DOCUMENT_NAME = "bringup-test-plan.md"
JSON_DOCUMENT_NAME = "bringup-test-plan.json"
_TEMPLATE: ContextVar[DocumentTemplate | None] = ContextVar(
    "bringup_plan_template", default=None
)
_PHASE_ORDER = {
    "unpowered": 0,
    "power_up": 1,
    "flash_boot": 2,
    "peripheral": 3,
    "self_test": 4,
}
_PHASE_LABELS = {
    "visual": ("unpowered", "visual"),
    "continuity": ("unpowered", "multimeter"),
    "power": ("power_up", "multimeter"),
    "flash_boot": ("flash_boot", "serial_console"),
    "led": ("peripheral", "visual"),
    "sensor": ("peripheral", "serial_console"),
    "serial": ("peripheral", "serial_console"),
    "self_test": ("self_test", "serial_console"),
}
_PHASE_TEMPLATE_KEYS = {
    "unpowered": "bringup.phase.unpowered",
    "power_up": "bringup.phase.power_up",
    "flash_boot": "bringup.phase.flash_boot",
    "peripheral": "bringup.phase.peripheral",
    "self_test": "bringup.phase.self_test",
}
_METHOD_TEMPLATE_KEYS = {
    "unpowered": "bringup.method.unpowered",
    "power_up": "bringup.method.power_up",
    "flash_boot": "bringup.method.flash_boot",
    "peripheral": "bringup.method.peripheral",
    "self_test": "bringup.method.self_test",
}


def t(key: str, **values: object) -> str:
    template = _TEMPLATE.get() or load_template("ja")
    return template.t(key, **values)


def _load_feedback_policy(path: Path) -> tuple[FeedbackPolicy, DocumentInput]:
    data = load_json_object(path, label="feedback policy")
    try:
        policy = FeedbackPolicy.model_validate(data)
    except ValueError as exc:
        raise DocumentGenerationError(f"feedback policy {path} is not valid: {exc}") from exc
    return policy, DocumentInput(path, sha256_file(path))


def _probe_points(graph: DesignGraph, subjects: list[str]) -> list[str]:
    nodes = {node.id: node for node in graph.nodes}
    reachable: set[str] = set(subjects)
    frontier = list(subjects)
    while frontier:
        current = frontier.pop()
        for node in graph.nodes:
            if current in node.depends_on and node.id not in reachable:
                reachable.add(node.id)
                frontier.append(node.id)
            if node.id == current:
                for dependency in node.depends_on:
                    if dependency not in reachable:
                        reachable.add(dependency)
                        frontier.append(dependency)
    probe_kinds = {
        "electrical.test_point",
        "electrical.connector",
        "mechanical.connector_opening",
    }
    return sorted(
        node_id
        for node_id in reachable
        if node_id not in subjects
        and node_id in nodes
        and nodes[node_id].kind in probe_kinds
    )


def _current_limit(graph: DesignGraph) -> tuple[GraphNode, str, float] | None:
    candidates: list[tuple[int, GraphNode, str, float]] = []
    for node in graph.nodes:
        attrs = (
            ("max_input_current_a", 0),
            ("current_limit_a", 1),
            ("max_current_a", 2),
        )
        for attr, priority in attrs:
            value = node.attrs.get(attr)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if attr == "max_current_a" and node.kind != "safety.boundary":
                    power_rail = node.attrs.get("power_rail")
                    if power_rail is not True:
                        continue
                candidates.append((priority, node, attr, float(value)))
                break
    if not candidates:
        return None
    _, node, attr, value = sorted(
        candidates, key=lambda candidate: (candidate[0], candidate[1].id)
    )[0]
    return node, attr, value


def _criterion_fields(
    item: InspectionItem,
) -> tuple[MeasurementTemplate | None, str | None, str | None]:
    criterion = item.criterion
    if criterion.kind == "unknown":
        return None, None, criterion.unknown_reason
    if criterion.kind == "range":
        if criterion.lower is None or criterion.upper is None or criterion.unit is None:
            raise DocumentGenerationError(
                f"inspection item {item.item_id} has incomplete range criterion"
            )
        return (
            MeasurementTemplate(
                name=item.item_id,
                unit=criterion.unit,
                expected_min=criterion.lower,
                expected_max=criterion.upper,
                tolerance=0.0,
            ),
            None,
            None,
        )
    if criterion.kind == "value" and isinstance(
        criterion.expected, (int, float)
    ) and not isinstance(criterion.expected, bool):
        if criterion.unit is None:
            return None, str(criterion.expected), None
        expected = float(criterion.expected)
        return (
            MeasurementTemplate(
                name=item.item_id,
                unit=criterion.unit,
                expected_min=expected,
                expected_max=expected,
                tolerance=0.0,
            ),
            None,
            None,
        )
    if criterion.expected is None:
        raise DocumentGenerationError(
            f"inspection item {item.item_id} has no expected criterion"
        )
    return None, str(criterion.expected), None


def _build_items(
    graph: DesignGraph,
    inspection_items: list[InspectionItem],
) -> list[BringUpItem]:
    built: list[BringUpItem] = []
    for index, inspection in enumerate(inspection_items):
        phase_name, instrument = _PHASE_LABELS[inspection.category]
        measurement, expected_text, unknown_reason = _criterion_fields(inspection)
        built.append(
            BringUpItem(
                item_id=f"BU-{index + 1:03d}",
                phase=cast(
                    Literal[
                        "unpowered",
                        "power_up",
                        "flash_boot",
                        "peripheral",
                        "self_test",
                    ],
                    phase_name,
                ),
                order=index,
                source_inspection_item_id=inspection.item_id,
                subject_node_ids=list(inspection.subject_node_ids),
                probe_points=_probe_points(graph, inspection.subject_node_ids),
                instrument=cast(
                    Literal[
                        "multimeter",
                        "current_limited_supply",
                        "serial_console",
                        "visual",
                        "unknown",
                    ],
                    instrument,
                ),
                procedure_key=_METHOD_TEMPLATE_KEYS[phase_name],
                measurement=measurement,
                expected_text=expected_text,
                criterion_source=inspection.criterion.source,
                unknown_reason=unknown_reason,
                stop_on_fail=phase_name in {"power_up", "flash_boot"},
            )
        )
    return built


def build_bringup_plan(
    graph: DesignGraph,
    firmware: FirmwareProjectionInputs | None,
    *,
    feedback_policy: FeedbackPolicy | None = None,
) -> BringUpTestPlan:
    inspection = build_shipping_inspection(graph, firmware)
    items = _build_items(graph, inspection.items)
    power_item = next(
        (item for item in inspection.items if item.category == "power"), None
    )
    current_limit = _current_limit(graph)
    if power_item is not None:
        node, limit_attr, limit = (
            current_limit if current_limit is not None else (None, None, None)
        )
        if node is not None and limit_attr is not None and limit is not None:
            extra = BringUpItem(
                item_id="BU-input-current-limit",
                phase="power_up",
                order=-1,
                source_inspection_item_id=power_item.item_id,
                subject_node_ids=[node.id],
                probe_points=_probe_points(graph, [node.id]),
                instrument="current_limited_supply",
                procedure_key="bringup.method.power_up_current_limit",
                measurement=MeasurementTemplate(
                    name="BU-input-current-limit",
                    unit="A",
                    expected_min=0.0,
                    expected_max=limit,
                    tolerance=0.0,
                ),
                criterion_source=CriterionSource(
                    kind="graph",
                    ref=f"{node.id}.attrs.{limit_attr}",
                ),
                stop_on_fail=True,
            )
        else:
            extra = BringUpItem(
                item_id="BU-input-current-limit",
                phase="power_up",
                order=-1,
                source_inspection_item_id=power_item.item_id,
                subject_node_ids=list(power_item.subject_node_ids),
                probe_points=_probe_points(graph, power_item.subject_node_ids),
                instrument="current_limited_supply",
                procedure_key="bringup.method.power_up_current_limit",
                unknown_reason="no input current limit declared",
                stop_on_fail=True,
            )
        items.append(extra)
    items.sort(key=lambda item: (_PHASE_ORDER[item.phase], item.order))
    uncovered: list[str] = []
    if feedback_policy is not None:
        measurements = {
            item.measurement.name
            for item in items
            if item.measurement is not None
        }
        for rule in feedback_policy.rules:
            if rule.measurement_name not in measurements:
                uncovered.append(rule.rule_id)
            else:
                for item in items:
                    if (
                        item.measurement is not None
                        and item.measurement.name == rule.measurement_name
                    ):
                        item.feeds_feedback_rule_ids.append(rule.rule_id)
    return BringUpTestPlan(
        schema_version="0.1",
        graph_id=graph.graph_id,
        target_revision=graph.revision,
        items=items,
        uncovered_feedback_rules=uncovered,
    )


def render_markdown(plan: BringUpTestPlan, *, template: DocumentTemplate) -> str:
    _TEMPLATE.set(template)
    lines = [
        t("bringup.document_title", graph_id=plan.graph_id),
        t("bringup.provenance_paragraph"),
        "",
    ]
    if plan.uncovered_feedback_rules:
        lines.extend(
            [
                t(
                    "bringup.uncovered_feedback",
                    rules=", ".join(plan.uncovered_feedback_rules),
                ),
                "",
            ]
        )
    for phase in ("unpowered", "power_up", "flash_boot", "peripheral", "self_test"):
        lines.extend(
            [
                t(_PHASE_TEMPLATE_KEYS[phase]),
                "",
                t("bringup.header"),
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for item in plan.items:
            if item.phase != phase:
                continue
            if item.measurement is not None:
                expected = (
                    f"{item.measurement.expected_min}.."
                    f"{item.measurement.expected_max} {item.measurement.unit} "
                    f"(tolerance {item.measurement.tolerance})"
                )
                fields = (
                    f"{item.measurement.name}: value, expected_min, expected_max, "
                    f"tolerance"
                )
            else:
                expected = item.expected_text or item.unknown_reason or "unknown"
                fields = ""
            lines.append(
                t(
                    "bringup.row",
                    item_id=item.item_id,
                    source=item.source_inspection_item_id,
                    procedure=t(item.procedure_key),
                    instrument=item.instrument,
                    expected=expected,
                    measurement_fields=fields,
                    reading="",
                    stop_on_fail=str(item.stop_on_fail),
                )
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--pins-header", type=Path, required=True)
    parser.add_argument("--firmware-config-report", type=Path, required=True)
    parser.add_argument("--inspection-sequence", type=Path)
    parser.add_argument("--feedback-policy", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    parser.add_argument("--lang", choices=("ja", "en"), default="ja")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    template = load_template(args.lang)
    graph, graph_input = load_graph(args.graph)
    macros = parse_pins_header(args.pins_header)
    report = load_firmware_config_report(args.firmware_config_report)
    sequence = (
        load_firmware_inspection_sequence(args.inspection_sequence)
        if args.inspection_sequence is not None
        else None
    )
    firmware = guarded_firmware_projection_inputs(
        graph, report, macros, inspection_sequence=sequence
    )
    policy = None
    policy_input = None
    if args.feedback_policy is not None:
        policy, policy_input = _load_feedback_policy(args.feedback_policy)
        if policy.graph_id != graph.graph_id or policy.revision != graph.revision:
            raise DocumentGenerationError(
                "feedback policy graph_id or revision does not match graph"
            )
    plan = build_bringup_plan(graph, firmware, feedback_policy=policy)
    body = render_markdown(plan, template=template)
    output_dir = args.out_dir if args.lang == "ja" else args.out_dir / args.lang
    inputs = [
        graph_input,
        DocumentInput(args.pins_header, sha256_file(args.pins_header)),
        DocumentInput(args.firmware_config_report, sha256_file(args.firmware_config_report)),
    ]
    if args.inspection_sequence is not None:
        inputs.append(
            DocumentInput(
                args.inspection_sequence,
                sha256_file(args.inspection_sequence),
            )
        )
    if policy_input is not None:
        inputs.append(policy_input)
    document_path, provenance_path = write_document(
        document_kind="bringup_plan",
        body=body,
        out_dir=output_dir,
        document_name=DOCUMENT_NAME,
        template_id=f"acd-bringup-plan-{args.lang}-v1",
        generator=Path(__file__).resolve(),
        graph=graph,
        inputs=inputs,
        base_dir=args.base_dir,
        template=template,
    )
    json_path, json_provenance = write_document(
        document_kind="bringup_plan_json",
        body=json.dumps(
            plan.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        out_dir=output_dir,
        document_name=JSON_DOCUMENT_NAME,
        template_id=f"acd-bringup-plan-{args.lang}-v1",
        generator=Path(__file__).resolve(),
        graph=graph,
        inputs=inputs,
        base_dir=args.base_dir,
        template=template,
    )
    print(f"generated {document_path}")
    print(f"provenance {provenance_path}")
    print(f"generated {json_path}")
    print(f"provenance {json_provenance}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DocumentGenerationError, ValueError) as error:
        print(f"bring-up plan generation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
