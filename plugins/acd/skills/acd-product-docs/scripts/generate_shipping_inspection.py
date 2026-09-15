# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@dde03eda4f8825705ebbb8888a81ce8af5f485b5",
# ]
# ///
"""Generate a deterministic shipping inspection document."""

from __future__ import annotations

import argparse
import json
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.firmware_inspection import FirmwareInspectionSequence
from acd.schema.shipping_inspection import (
    CriterionSource,
    InspectionCategory,
    InspectionCriterion,
    InspectionItem,
    ShippingInspectionDocument,
)
from doc_inputs import (
    DocumentGenerationError,
    DocumentInput,
    DocumentTemplate,
    FirmwareConfigReport,
    ReportDevice,
    ReportPin,
    guard_devices,
    guard_pins,
    guard_report,
    guard_revision,
    load_firmware_config_report,
    load_firmware_inspection_sequence,
    load_graph,
    load_template,
    sha256_file,
    write_document,
)
from generate_instruction_manual import parse_pins_header

DOCUMENT_NAME = "shipping-inspection.md"
JSON_DOCUMENT_NAME = "shipping-inspection.json"
_TEMPLATE: ContextVar[DocumentTemplate | None] = ContextVar(
    "shipping_inspection_template", default=None
)
_CATEGORY_ORDER = (
    "visual",
    "continuity",
    "power",
    "flash_boot",
    "led",
    "sensor",
    "serial",
    "self_test",
)
_CATEGORY_TEMPLATE_KEYS = {
    "visual": "shipping.category.visual",
    "continuity": "shipping.category.continuity",
    "power": "shipping.category.power",
    "flash_boot": "shipping.category.flash_boot",
    "led": "shipping.category.led",
    "sensor": "shipping.category.sensor",
    "serial": "shipping.category.serial",
    "self_test": "shipping.category.self_test",
}
_UNKNOWN_REASON_TEMPLATE_KEYS = {
    "missing component mpn": "shipping.unknown.missing_component_mpn",
    "ground net is undeclared": "shipping.unknown.ground_net_undeclared",
    "missing nominal voltage": "shipping.unknown.missing_nominal_voltage",
    "missing safety voltage limit": "shipping.unknown.missing_safety_voltage_limit",
    "missing firmware boot declaration": "shipping.unknown.missing_firmware_boot",
    "blink behavior is not declared": "shipping.unknown.led_blink_undeclared",
    "serial output lines are not declared": "shipping.unknown.serial_output_undeclared",
    "firmware projection unavailable for this revision": (
        "shipping.unknown.firmware_projection_unavailable"
    ),
    "no self-measurement source declared in graph": (
        "shipping.unknown.no_self_measurement_source"
    ),
}


@dataclass(frozen=True)
class FirmwareProjectionInputs:
    """Revision-matched firmware inputs used by shipping inspection derivation."""

    report: FirmwareConfigReport
    macros: dict[str, str]
    pins: tuple[ReportPin, ...]
    devices: tuple[ReportDevice, ...]
    inspection_sequence: FirmwareInspectionSequence | None = None


def t(key: str, **values: object) -> str:
    template = _TEMPLATE.get() or load_template("ja")
    return template.t(key, **values)


def _text(node: GraphNode, key: str) -> str | None:
    value = node.attrs.get(key)
    return value if isinstance(value, str) and value else None


def _number(node: GraphNode, key: str) -> float | None:
    value = node.attrs.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _nodes(graph: DesignGraph, kind: str) -> list[GraphNode]:
    return sorted((node for node in graph.nodes if node.kind == kind), key=lambda n: n.id)


def _pins_for_component(graph: DesignGraph, component_id: str) -> list[GraphNode]:
    return [
        node
        for node in _nodes(graph, "electrical.pin")
        if node.attrs.get("component") == component_id
    ]


def _net_map(graph: DesignGraph) -> dict[str, GraphNode]:
    return {node.id: node for node in _nodes(graph, "electrical.net")}


def _is_led(component: GraphNode) -> bool:
    footprint = _text(component, "footprint") or ""
    return footprint.rsplit(":", 1)[-1].startswith("LED_")


def _connected_nets(graph: DesignGraph, start_nets: set[str]) -> set[str]:
    """Follow passive component connections to the nets driving an LED."""
    visited_nets = set(start_nets)
    changed = True
    while changed:
        changed = False
        for component in _nodes(graph, "electrical.component"):
            component_nets: set[str] = set()
            for pin in _pins_for_component(graph, component.id):
                net = pin.attrs.get("net")
                if isinstance(net, str):
                    component_nets.add(net)
            if component_nets & visited_nets:
                before = len(visited_nets)
                visited_nets.update(component_nets)
                changed |= len(visited_nets) != before
    return visited_nets


def _source(
    kind: Literal["graph", "gate_threshold", "firmware_projection"],
    ref: str,
) -> CriterionSource:
    return CriterionSource(kind=kind, ref=ref)


def _criterion(
    kind: Literal["value", "range", "string", "boolean", "unknown"],
    expected: str | float | int | bool | None,
    source: CriterionSource | None,
    *,
    unit: str | None = None,
    lower: float | None = None,
    upper: float | None = None,
) -> InspectionCriterion:
    return InspectionCriterion(
        kind=kind,
        expected=expected,
        unit=unit,
        lower=lower,
        upper=upper,
        source=source,
    )


def _item(
    index: int,
    category: InspectionCategory,
    subject_node_ids: list[str],
    method_key: str,
    criterion: InspectionCriterion,
) -> InspectionItem:
    return InspectionItem(
        item_id=f"SI-{index:03d}",
        category=category,
        subject_node_ids=subject_node_ids,
        method_key=method_key,
        criterion=criterion,
        manual_decision_required=criterion.kind == "unknown",
    )


def _unknown(reason: str) -> InspectionCriterion:
    return InspectionCriterion(
        kind="unknown",
        expected=None,
        source=None,
        unknown_reason=reason,
    )


def guarded_firmware_projection_inputs(
    graph: DesignGraph,
    report: FirmwareConfigReport,
    macros: dict[str, str],
    inspection_sequence: FirmwareInspectionSequence | None = None,
) -> FirmwareProjectionInputs:
    """Validate and package revision-matched firmware projection inputs."""
    guard_report(graph, report)
    guard_revision(graph, macros)
    return FirmwareProjectionInputs(
        report=report,
        macros=macros,
        pins=guard_pins(graph, report, macros),
        devices=guard_devices(report, macros),
        inspection_sequence=inspection_sequence,
    )


def build_shipping_inspection(
    graph: DesignGraph,
    firmware: FirmwareProjectionInputs | None,
) -> ShippingInspectionDocument:
    """Build the shipping inspection contract from governed inputs."""
    macros = firmware.macros if firmware is not None else {}
    devices = firmware.devices if firmware is not None else ()
    nets = _net_map(graph)
    board = next(iter(_nodes(graph, "electrical.board")), None)
    ground_name = _text(board, "ground_plane_net") if board is not None else None
    ground = next(
        (node for node in nets.values() if _text(node, "name") == ground_name),
        None,
    )
    boundary = next(iter(_nodes(graph, "safety.boundary")), None)
    items: list[InspectionItem] = []

    def add(
        category: InspectionCategory,
        subjects: list[str],
        method: str,
        criterion: InspectionCriterion,
    ) -> None:
        items.append(_item(len(items) + 1, category, subjects, method, criterion))

    for component in (
        node
        for node in _nodes(graph, "electrical.component")
        if node.attrs.get("assembly") == "fitted"
    ):
        refdes = _text(component, "refdes") or ""
        mpn = _text(component, "mpn") or ""
        footprint = _text(component, "footprint") or ""
        expected = f"{refdes} {mpn} {footprint}"
        criterion = (
            _criterion(
                "string",
                expected,
                _source("graph", f"{component.id}.attrs.mpn"),
            )
            if mpn
            else _unknown("missing component mpn")
        )
        add("visual", [component.id], "shipping.method.visual", criterion)

    power_nets = [
        node
        for node in _nodes(graph, "electrical.net")
        if node.attrs.get("power_rail") is True
    ]
    for net in power_nets:
        measurement_subject = next(
            (
                component.id
                for component in _nodes(graph, "electrical.component")
                if (_text(component, "footprint") or "").startswith("TestPoint:")
                and any(
                    pin.attrs.get("net") == net.id
                    for pin in _pins_for_component(graph, component.id)
                )
            ),
            _text(net, "power_source_pin") or net.id,
        )
        if ground is not None:
            add(
                "continuity",
                [net.id, ground.id],
                "shipping.method.continuity",
                _criterion(
                    "boolean",
                    False,
                    _source("graph", f"{net.id}.attrs.power_rail"),
                ),
            )
        else:
            add(
                "continuity",
                [net.id],
                "shipping.method.continuity",
                _unknown("ground net is undeclared"),
            )
        nominal = _number(net, "voltage_nominal_v")
        add(
            "power",
            [net.id, measurement_subject],
            "shipping.method.power_nominal",
            _criterion(
                "value",
                nominal,
                _source("graph", f"{net.id}.attrs.voltage_nominal_v"),
                unit="V",
            )
            if nominal is not None
            else _unknown("missing nominal voltage"),
        )
        limit = _number(boundary, "max_net_voltage_v") if boundary is not None else None
        source = (
            _source("gate_threshold", f"{boundary.id}.attrs.max_net_voltage_v")
            if boundary is not None and limit is not None
            else None
        )
        add(
            "power",
            [net.id, measurement_subject]
            + ([boundary.id] if boundary is not None else []),
            "shipping.method.power_upper",
            (
                _criterion("value", limit, source, unit="V")
                if limit is not None
                else _unknown("missing safety voltage limit")
            ),
        )

    module = next(iter(_nodes(graph, "firmware.module")), None)
    boot_message = _text(module, "boot_log_message") if module is not None else None
    if (
        firmware is not None
        and boot_message is not None
        and boot_message != firmware.report.boot_log_message
    ):
        raise DocumentGenerationError(
            "firmware config boot_log_message does not match graph firmware.module"
        )
    boot_expected = (
        firmware.report.boot_log_message.replace("%s", graph.revision)
        if firmware is not None and firmware.report.boot_log_message
        else None
    )
    add(
        "flash_boot",
        [module.id] if module is not None else [],
        "shipping.method.flash_boot",
        _criterion(
            "string",
            boot_expected,
            _source("firmware_projection", "firmware-config-report.json.settings.boot_log_message"),
        )
        if firmware is not None and module is not None and boot_expected is not None
        else _unknown(
            "missing firmware boot declaration"
            if firmware is not None
            else "firmware projection unavailable for this revision"
        ),
    )

    led_terminal_nets: set[str] = set()
    for component in _nodes(graph, "electrical.component"):
        if _is_led(component):
            led_terminal_nets.update(
                net
                for pin in _pins_for_component(graph, component.id)
                if (net := pin.attrs.get("net")) and isinstance(net, str)
            )
    led_nets = _connected_nets(graph, led_terminal_nets)
    assignment_nodes = [
        node
        for node in _nodes(graph, "firmware.pin_assignment")
        if node.attrs.get("net") in led_nets
    ]
    for assignment in assignment_nodes:
        pin_net = assignment.attrs.get("net")
        if not isinstance(pin_net, str):
            continue
        macro = "ACD_PIN_" + pin_net.removeprefix("net.").upper()
        gpio = int(macros[macro], 0) if firmware is not None else None
        led_subject = [assignment.id] + [
            component.id
            for component in _nodes(graph, "electrical.component")
            if any(
                p.attrs.get("net") == pin_net
                for p in _pins_for_component(graph, component.id)
            )
            and _is_led(component)
        ]
        add(
            "led",
            sorted(set(led_subject)),
            "shipping.method.led_gpio",
            _criterion("value", gpio, _source("firmware_projection", f"acd_pins.h:{macro}"))
            if firmware is not None
            else _unknown("firmware projection unavailable for this revision"),
        )
        add(
            "led",
            sorted(set(led_subject)),
            "shipping.method.led_behavior",
            _unknown(
                "blink behavior is not declared"
                if firmware is not None
                else "firmware projection unavailable for this revision"
            ),
        )

    if firmware is None:
        for component in _nodes(graph, "electrical.component"):
            if "sensor" not in (_text(component, "footprint") or "").lower():
                continue
            add(
                "sensor",
                [component.id],
                "shipping.method.sensor",
                _unknown("firmware projection unavailable for this revision"),
            )
    else:
        for device in devices:
            subject = next(
                (
                    component.id
                    for component in _nodes(graph, "electrical.component")
                    if _text(component, "mpn") == device.mpn
                ),
                device.driver_id,
            )
            add(
                "sensor",
                [subject],
                "shipping.method.sensor",
                _criterion(
                    "string",
                    f"ACK at 0x{device.i2c_address:02x}",
                    _source(
                        "firmware_projection",
                        "firmware-config-report.json.provenance.devices:"
                        f"{device.driver_id}",
                    ),
                ),
            )

    add(
        "serial",
        [module.id] if module is not None else ["serial"],
        "shipping.method.serial",
        _unknown(
            "serial output lines are not declared"
            if firmware is not None
            else "firmware projection unavailable for this revision"
        ),
    )
    sequence = firmware.inspection_sequence if firmware is not None else None
    if sequence is not None:
        if sequence.graph_id != graph.graph_id or sequence.target_revision != graph.revision:
            raise DocumentGenerationError(
                "firmware inspection sequence graph_id or target_revision does not match graph"
            )
        module_subject = [module.id] if module is not None else ["firmware.module"]
        add(
            "self_test",
            module_subject,
            "shipping.method.self_test_entry",
            _criterion(
                "string",
                sequence.entry_command,
                _source(
                    "firmware_projection",
                    "firmware-inspection-sequence.json#entry-command",
                ),
            ),
        )
        for sequence_item in sequence.items:
            if sequence_item.status == "unknown":
                criterion = _unknown(sequence_item.unknown_reason or "unknown")
            else:
                criterion = _criterion(
                    "string",
                    sequence_item.expected_line,
                    _source(
                        "firmware_projection",
                        f"firmware-inspection-sequence.json#{sequence_item.item_id}",
                    ),
                )
            add(
                "self_test",
                list(sequence_item.subject_node_ids),
                "shipping.method.self_test_item",
                criterion,
            )
    items.sort(
        key=lambda item: (
            _CATEGORY_ORDER.index(item.category),
            tuple(item.subject_node_ids),
            item.method_key,
        )
    )
    items = [
        item.model_copy(update={"item_id": f"SI-{index:03d}"})
        for index, item in enumerate(items, start=1)
    ]
    return ShippingInspectionDocument(
        schema_version="0.1",
        graph_id=graph.graph_id,
        revision=graph.revision,
        items=items,
        unknown_count=sum(item.manual_decision_required for item in items),
    )


def _subject_label(item: InspectionItem, graph: DesignGraph) -> str:
    nodes = {node.id: node for node in graph.nodes}
    labels: list[str] = []
    for node_id in item.subject_node_ids:
        node = nodes.get(node_id)
        if node is None:
            labels.append(node_id)
            continue
        labels.append(_text(node, "name") or _text(node, "refdes") or node.id)
    return ", ".join(labels)


def render_markdown(
    document: ShippingInspectionDocument,
    graph: DesignGraph,
    *,
    template: DocumentTemplate,
) -> str:
    _TEMPLATE.set(template)
    lines = [
        t("shipping.document_title", graph_id=document.graph_id),
        "",
        t("shipping.provenance_paragraph"),
        "",
    ]
    for category in _CATEGORY_ORDER:
        lines.extend(
            [
                t(_CATEGORY_TEMPLATE_KEYS[category]),
                "",
                t("shipping.header"),
                "|---|---|---|---|---|---|",
            ]
        )
        category_items = [item for item in document.items if item.category == category]
        for item in category_items:
            criterion = item.criterion
            expected = (
                "unknown"
                if criterion.kind == "unknown"
                else str(criterion.expected)
            )
            if criterion.unit is not None:
                expected = f"{expected} {criterion.unit}"
            source = (
                ""
                if criterion.source is None
                else f"{criterion.source.kind}: {criterion.source.ref}"
            )
            decision = (
                t(_UNKNOWN_REASON_TEMPLATE_KEYS[criterion.unknown_reason])
                if criterion.unknown_reason in _UNKNOWN_REASON_TEMPLATE_KEYS
                else criterion.unknown_reason or "unknown"
            )
            lines.append(
                t(
                    "shipping.row",
                    item_id=item.item_id,
                    subject=_subject_label(item, graph),
                    method=t(item.method_key, subject=_subject_label(item, graph)),
                    criterion=expected,
                    source=source,
                    decision=decision,
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
    document = build_shipping_inspection(graph, firmware)
    body = render_markdown(document, graph, template=template)
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
    document_path, provenance_path = write_document(
        document_kind="shipping_inspection",
        body=body,
        out_dir=output_dir,
        document_name=DOCUMENT_NAME,
        template_id=f"acd-shipping-inspection-{args.lang}-v1",
        generator=Path(__file__).resolve(),
        graph=graph,
        inputs=inputs,
        base_dir=args.base_dir,
        template=template,
    )
    json_body = json.dumps(
        document.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    json_path, json_provenance = write_document(
        document_kind="shipping_inspection_json",
        body=json_body,
        out_dir=output_dir,
        document_name=JSON_DOCUMENT_NAME,
        template_id=f"acd-shipping-inspection-{args.lang}-v1",
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
    except DocumentGenerationError as error:
        print(f"shipping inspection generation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
