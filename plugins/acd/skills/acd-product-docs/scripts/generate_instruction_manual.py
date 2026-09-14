# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@26bbeca6d58e18f3908790f202aa9daf7b1ed90a",
# ]
# ///
"""Generate the deterministic instruction manual from graph declarations.

Each section is rendered only when its inputs are declared by the graph and
pin projection. Undeclared items are listed as omissions; contradictions
between declarations and generated pins fail closed instead of estimating.
"""

from __future__ import annotations

import argparse
import re
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from acd.core.electrical import extract_electrical_lane
from acd.core.firmware_lane import FirmwareLane, extract_firmware_lane
from acd.schema.design_graph import DesignGraph
from doc_inputs import (
    DocumentGenerationError,
    DocumentInput,
    DocumentTemplate,
    format_number,
    load_graph,
    load_template,
    number_attr,
    sha256_file,
    single_node_of_kind,
    text_attr,
    write_document,
)

DOCUMENT_NAME = "instruction-manual.md"

_TEMPLATE: ContextVar[DocumentTemplate | None] = ContextVar(
    "instruction_manual_template", default=None
)


def t(key: str, **values: object) -> str:
    template = _TEMPLATE.get() or load_template("ja")
    return template.t(key, **values)

_DEFINE_PATTERN = re.compile(r"^#define\s+(?P<name>[A-Z0-9_]+)\s+(?P<value>\S+)\s*$")
_REQUIRED_MACROS = ("ACD_TARGET_REVISION",)


@dataclass(frozen=True)
class Omission:
    """One omitted section and the reason it was not rendered."""

    section: str
    reason: str


def parse_pins_header(path: Path) -> dict[str, str]:
    """Return the macro values of a generated ``acd_pins.h`` projection."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DocumentGenerationError(f"cannot read pin projection {path}: {exc}") from exc
    macros: dict[str, str] = {}
    for line in source.splitlines():
        match = _DEFINE_PATTERN.match(line)
        if match is not None:
            macros[match.group("name")] = match.group("value")
    missing = [name for name in _REQUIRED_MACROS if name not in macros]
    if missing:
        raise DocumentGenerationError(
            f"pin projection {path} is missing macros: {', '.join(sorted(missing))}"
        )
    return macros


def _require_macro(
    macros: dict[str, str], name: str, *, because: str
) -> None:
    if name not in macros:
        raise DocumentGenerationError(
            f"pin projection lacks {name} although the graph declares {because}"
        )


def _macro_int(macros: dict[str, str], name: str) -> int:
    raw = macros[name]
    try:
        return int(raw, 0)
    except ValueError as exc:
        raise DocumentGenerationError(
            f"pin projection macro {name} is not an integer: {raw!r}"
        ) from exc


def _required_macro_int(
    macros: dict[str, str], name: str, *, because: str
) -> int:
    _require_macro(macros, name, because=because)
    return _macro_int(macros, name)


def _revision_guard(graph: DesignGraph, macros: dict[str, str]) -> None:
    revision = macros["ACD_TARGET_REVISION"].strip('"')
    if revision != graph.revision:
        raise DocumentGenerationError(
            f"pin projection targets revision {revision!r}, not {graph.revision!r}"
        )


def _pin_macro(net: str) -> str:
    return "ACD_PIN_" + net.removeprefix("net.").upper()


def _declared_nets(firmware: FirmwareLane) -> set[str]:
    return {assignment.net for assignment in firmware.pin_assignments}


def _pin_pair(
    firmware: FirmwareLane,
    macros: dict[str, str],
    first_net: str,
    second_net: str,
    *,
    because: str,
) -> tuple[int, int] | None:
    declared = _declared_nets(firmware)
    if first_net not in declared or second_net not in declared:
        return None
    first_name = _pin_macro(first_net)
    second_name = _pin_macro(second_net)
    first = _required_macro_int(macros, first_name, because=because)
    second = _required_macro_int(macros, second_name, because=because)
    return first, second


def _function_section(
    graph: DesignGraph,
    macros: dict[str, str],
    omissions: list[Omission],
) -> list[str]:
    firmware = extract_firmware_lane(graph)
    lines = [t("manual.literal_085"), "", t("manual.literal_086"), ""]
    lines += [t("manual.literal_087"), "|---|---|"]
    for state in sorted(firmware.states, key=lambda item: item.state_name):
        initial = t("manual.literal_043") if state.initial else t("manual.literal_044")
        lines.append(f"| {state.state_name} | {initial} |")
    lines += ["", t("manual.literal_088"), "", t("manual.literal_089"), "|---|---|---|"]
    for step in sorted(firmware.sequence_steps, key=lambda item: item.step_index):
        lines.append(f"| {step.step_index} | {step.target} | {step.action} |")
    sensor_declared = any(
        step.action in {"read_temperature_humidity", "initialize_sht40"}
        for step in firmware.sequence_steps
    )
    if sensor_declared:
        address = _required_macro_int(
            macros,
            "ACD_SHT40_I2C_ADDRESS",
            because="temperature/humidity sensor step",
        )
        lines += [
            "",
            f"{t('manual.literal_045')}{address:02x}{t('manual.literal_046')}",
        ]
    else:
        omissions.append(
            Omission(t("manual.literal_090"), t("manual.literal_091"))
        )
    if any(step.action == "write_serial_log" for step in firmware.sequence_steps):
        log_period_ms = _required_macro_int(
            macros,
            "ACD_LOG_PERIOD_MS",
            because="write_serial_log step",
        )
        lines.append(f"{log_period_ms}{t('manual.literal_047')}")
    else:
        omissions.append(
            Omission(
                t("manual.literal_092"),
                t("manual.literal_093"),
            )
        )
    lines.append("")
    return lines


def _connection_section(
    graph: DesignGraph,
    macros: dict[str, str],
    omissions: list[Omission],
) -> list[str]:
    lane = extract_electrical_lane(graph)
    openings = sorted(
        (
            node
            for node in graph.nodes
            if node.kind == "mechanical.connector_opening"
        ),
        key=lambda node: node.id,
    )
    if not openings:
        omissions.append(
            Omission(t("manual.literal_094"), t("manual.literal_095"))
        )
        return []
    lines = [t("manual.literal_096"), ""]
    step = 1
    for opening in openings:
        connector_id = text_attr(opening, "connector")
        connector = next(
            (component for component in lane.components if component.node_id == connector_id),
            None,
        )
        if connector is None:
            raise DocumentGenerationError(
                f"connector component {connector_id!r} is missing"
            )
        lines += [
            f"{step}{t('manual.literal_048')}{text_attr(opening, 'face')}{t('manual.literal_049')}"
            f"{connector.refdes}（{connector.mpn}{t('manual.literal_050')}",
            f"{step + 1}{t('manual.literal_051')}",
            "",
            f"### {opening.id}",
            "",
            t("manual.literal_097"),
            "|---|---|",
            f"{t('manual.literal_052')}{format_number(number_attr(opening, 'width_mm'))} mm |",
            f"{t('manual.literal_053')}{format_number(number_attr(opening, 'height_mm'))} mm |",
            f"{t('manual.literal_054')}{format_number(number_attr(opening, 'margin_mm'))} mm |",
            "",
        ]
        step += 2
    firmware = extract_firmware_lane(graph)
    usb = _pin_pair(
        firmware,
        macros,
        "net.usb_dp",
        "net.usb_dn",
        because="pin role usb_dp/usb_dn",
    )
    if usb is None:
        omissions.append(
            Omission(
                t("manual.literal_098"),
                t("manual.literal_099"),
            )
        )
    else:
        lines += [
            f"{t('manual.literal_055')}{usb[0]}／IO{usb[1]}{t('manual.literal_056')}",
            "",
        ]
    return lines


def _led_section(
    graph: DesignGraph,
    macros: dict[str, str],
    omissions: list[Omission],
) -> list[str]:
    firmware = extract_firmware_lane(graph)
    toggles = [
        step for step in firmware.sequence_steps if step.action == "toggle_led"
    ]
    if not toggles:
        omissions.append(
            Omission(t("manual.literal_100"), t("manual.literal_101"))
        )
        return []
    period_ms = _required_macro_int(
        macros,
        "ACD_LED_BLINK_PERIOD_MS",
        because="toggle_led step",
    )
    gpio = _required_macro_int(
        macros,
        "ACD_PIN_LED",
        because="toggle_led step",
    )
    fault_states = sorted(
        state.state_name for state in firmware.states if state.state_name == "fault"
    )
    lines = [
        t("manual.literal_102"),
        "",
        t("manual.literal_103"),
        "|---|---|",
        (
            f"{t('manual.literal_057')}{period_ms}{t('manual.literal_058')}"
            f"{gpio}{t('manual.literal_059')}{t('manual.literal_104')}"
        ),
        t("manual.literal_105"),
    ]
    for state in fault_states:
        lines.append(
            f"{t('manual.literal_060')}{state}{t('manual.literal_061')}"
        )
    if any(step.action == "toggle_led2" for step in firmware.sequence_steps):
        gpio2 = _required_macro_int(
            macros,
            "ACD_PIN_LED2",
            because="toggle_led2 step",
        )
        lines.insert(
            6,
            f"{t('manual.literal_062')}{gpio2}{t('manual.literal_063')}",
        )
    lines.append("")
    return lines


def _operation_section(
    graph: DesignGraph,
    macros: dict[str, str],
    omissions: list[Omission],
) -> list[str]:
    firmware = extract_firmware_lane(graph)
    if not any(step.action == "read_button" for step in firmware.sequence_steps):
        omissions.append(Omission(t("manual.literal_106"), t("manual.literal_107")))
        return []
    button = _required_macro_int(
        macros,
        "ACD_PIN_BUTTON",
        because="read_button step",
    )
    lines = [t("manual.literal_108"), ""]
    for transition in sorted(firmware.transitions, key=lambda item: item.node_id):
        if transition.trigger == "button_pressed":
            lines.append(
                f"IO{button}{t('manual.literal_064')}{transition.from_state}{t('manual.literal_065')}"
                f"`{transition.to_state}{t('manual.literal_066')}"
            )
    lines.append("")
    return lines


def _flashing_section(
    graph: DesignGraph,
    macros: dict[str, str],
    omissions: list[Omission],
    *,
    led_written: bool,
) -> list[str]:
    firmware = extract_firmware_lane(graph)
    lane = extract_electrical_lane(graph)
    mcu = next(
        (c for c in lane.components if c.node_id == firmware.module.mcu_component), None
    )
    if mcu is None:
        raise DocumentGenerationError("MCU component is missing from the graph")
    lines = [t("manual.literal_109"), ""]
    step = 1
    usb = _pin_pair(
        firmware,
        macros,
        "net.usb_dp",
        "net.usb_dn",
        because="pin role usb_dp/usb_dn",
    )
    uart = _pin_pair(
        firmware,
        macros,
        "net.uart_tx",
        "net.uart_rx",
        because="pin role uart_tx/uart_rx",
    )
    if usb is not None:
        lines.append(
            f"{step}. `{mcu.mpn}{t('manual.literal_067')}{usb[0]}／IO"
            f"{usb[1]}{t('manual.literal_068')}"
        )
        step += 1
    elif uart is not None:
        lines.append(
            f"{step}. `{mcu.mpn}{t('manual.literal_069')}{uart[0]}／RX: "
            f"IO{uart[1]}{t('manual.literal_070')}"
        )
        step += 1
    else:
        lines.append(
            f"{step}{t('manual.literal_071')}" + t("manual.literal_110")
        )
        omissions.append(
            Omission(t("manual.literal_111"), t("manual.literal_112"))
        )
        step += 1
    if "net.boot" in _declared_nets(firmware):
        boot = _required_macro_int(
            macros,
            "ACD_PIN_BOOT",
            because="pin role boot",
        )
        lines.append(
            f"{step}{t('manual.literal_072')}{boot}{t('manual.literal_073')}"
            f"{t('manual.literal_113')}"
        )
        step += 1
    lines.append(f"{step}. revision`{graph.revision}{t('manual.literal_074')}")
    step += 1
    reset = t("manual.literal_114") if led_written else t("manual.literal_115")
    lines.append(f"{step}{t('manual.literal_075')}{reset}")
    lines.append("")
    return lines


def _safety_section(graph: DesignGraph) -> list[str]:
    safety = single_node_of_kind(graph, "safety.boundary")
    board = single_node_of_kind(graph, "electrical.board")
    max_voltage = format_number(number_attr(safety, "max_net_voltage_v"))
    max_current = format_number(number_attr(safety, "max_current_a"))
    antenna_keepout_text = (
        t("manual.literal_082")
        if board.attrs.get("antenna_keepout") is True
        else t("manual.literal_083")
    )
    lines = [
        t("manual.literal_116"),
        "",
        f"{t('manual.literal_076')}{max_voltage} V、"
        f"{t('manual.literal_077')}{max_current}{t('manual.literal_078')}",
        (
            f"{t('manual.literal_079')}{text_attr(safety, 'intended_use')}"
            f"{t('manual.literal_080')}{t('manual.literal_117')}"
        ),
        (
            f"{t('manual.literal_081')}"
            f"{antenna_keepout_text}"
            "）。"
        ),
        t("manual.literal_118"),
        "",
    ]
    return lines


def render_manual(
    graph: DesignGraph,
    macros: dict[str, str],
    *,
    template: DocumentTemplate | None = None,
) -> str:
    """Render the instruction manual body for a graph and its pin projection."""
    _TEMPLATE.set(template or load_template("ja"))
    _revision_guard(graph, macros)
    lines = [
        f"{t('manual.literal_084')}{graph.graph_id}",
        "",
        f"- Design Graph: `{graph.graph_id}`",
        f"- revision: `{graph.revision}`",
        "",
        t("manual.literal_119") + t("manual.literal_120"),
        "",
    ]
    omissions: list[Omission] = []
    lines += _function_section(graph, macros, omissions)
    lines += _connection_section(graph, macros, omissions)
    led_lines = _led_section(graph, macros, omissions)
    lines += led_lines
    lines += _operation_section(graph, macros, omissions)
    lines += _flashing_section(
        graph,
        macros,
        omissions,
        led_written=bool(led_lines),
    )
    lines += _safety_section(graph)
    lines += [t("manual.literal_121"), ""]
    if omissions:
        lines += [f"- {item.section}: {item.reason}" for item in omissions]
    else:
        lines.append(t("manual.literal_122"))
    lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument(
        "--pins-header",
        type=Path,
        required=True,
        help="generated acd_pins.h firmware pin projection",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    parser.add_argument("--lang", choices=("ja", "en"), default="ja")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    template = load_template(args.lang)
    graph, graph_input = load_graph(args.graph)
    macros = parse_pins_header(args.pins_header)
    body = render_manual(graph, macros, template=template)
    inputs: list[DocumentInput] = [
        graph_input,
        DocumentInput(path=args.pins_header, content_hash=sha256_file(args.pins_header)),
    ]
    document_path, provenance_path = write_document(
        document_kind="instruction_manual",
        body=body,
        out_dir=args.out_dir if args.lang == "ja" else args.out_dir / args.lang,
        document_name=DOCUMENT_NAME,
        template_id=f"acd-instruction-manual-{args.lang}-v2",
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
        print(f"instruction manual generation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
