# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@69f7f426a1a4ad212b66797771e2995adefa70d6",
# ]
# ///
"""Project the device interface contract deterministically as JSON and Markdown.

The interface spec joins the firmware pin projection (``acd_pins.h``) and the
firmware config report with the design graph. Undeclared interface aspects
(UART transport parameters, host commands) are marked unknown; contradictions
between the report, the header, and the graph fail closed.
"""

from __future__ import annotations

import argparse
import json
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from acd.core.firmware_lane import extract_firmware_lane
from acd.schema.design_graph import DesignGraph
from doc_inputs import (
    DocumentGenerationError,
    DocumentInput,
    DocumentTemplate,
    load_graph,
    load_template,
    sha256_file,
    write_document,
)
from generate_instruction_manual import parse_pins_header

DOCUMENT_NAME = "interface-spec.md"
JSON_DOCUMENT_NAME = "interface-spec.json"

_TEMPLATE: ContextVar[DocumentTemplate | None] = ContextVar(
    "interface_spec_template", default=None
)


def t(key: str, **values: object) -> str:
    template = _TEMPLATE.get() or load_template("ja")
    return template.t(key, **values)

_UNKNOWN_TRANSPORT_REASON = (
    "UART parameters (baud rate, framing) are not declared in the graph or "
    "firmware projection"
)
_UNKNOWN_COMMANDS_REASON = (
    "no command interface is declared in the graph or firmware projection"
)


@dataclass(frozen=True)
class ReportPin:
    """One pin entry of the firmware config report."""

    node_id: str
    gpio: int
    net: str


@dataclass(frozen=True)
class ReportDevice:
    """One device entry of the firmware config report provenance."""

    mpn: str
    driver_id: str
    i2c_address: int


@dataclass(frozen=True)
class FirmwareConfigReport:
    """Parsed firmware config report written by the FW pipeline."""

    graph_id: str
    target_revision: str
    pins: tuple[ReportPin, ...]
    capabilities: tuple[str, ...]
    devices: tuple[ReportDevice, ...]
    led_blink_period_ms: int
    log_period_ms: int
    boot_log_message: str


def _require_object(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise DocumentGenerationError(f"report field {field!r} is not an object")
    return cast(dict[str, object], value)


def _require_str(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DocumentGenerationError(f"report field {field!r} is missing or not text")
    return value


def _require_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DocumentGenerationError(f"report field {field!r} is missing or not an int")
    return value


def _require_list(value: object, *, field: str) -> list[object]:
    if not isinstance(value, list):
        raise DocumentGenerationError(f"report field {field!r} is not a list")
    return cast(list[object], value)


def load_firmware_config_report(path: Path) -> FirmwareConfigReport:
    """Load the firmware config report, failing closed on any defect."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DocumentGenerationError(
            f"firmware config report {path} is not valid: {exc}"
        ) from exc
    report = _require_object(payload, field="report")
    pins = tuple(
        ReportPin(
            node_id=_require_str(item.get("node_id"), field="pins[].node_id"),
            gpio=_require_int(item.get("gpio"), field="pins[].gpio"),
            net=_require_str(item.get("net"), field="pins[].net"),
        )
        for item in (
            _require_object(item, field="pins[]")
            for item in _require_list(report.get("pins"), field="pins")
        )
    )
    settings = _require_object(report.get("settings"), field="settings")
    provenance = _require_object(report.get("provenance"), field="provenance")
    capabilities = tuple(
        sorted(
            _require_str(item.get("capability_id"), field="capabilities[].capability_id")
            for item in (
                _require_object(entry, field="capabilities[]")
                for entry in _require_list(
                    provenance.get("capabilities"), field="capabilities"
                )
            )
        )
    )
    devices = tuple(
        sorted(
            (
                ReportDevice(
                    mpn=_require_str(item.get("mpn"), field="devices[].mpn"),
                    driver_id=_require_str(
                        item.get("driver_id"), field="devices[].driver_id"
                    ),
                    i2c_address=_require_int(
                        item.get("i2c_address"), field="devices[].i2c_address"
                    ),
                )
                for item in (
                    _require_object(entry, field="devices[]")
                    for entry in _require_list(
                        provenance.get("devices"), field="devices"
                    )
                )
            ),
            key=lambda device: device.driver_id,
        )
    )
    return FirmwareConfigReport(
        graph_id=_require_str(report.get("graph_id"), field="graph_id"),
        target_revision=_require_str(
            report.get("target_revision"), field="target_revision"
        ),
        pins=pins,
        capabilities=capabilities,
        devices=devices,
        led_blink_period_ms=_require_int(
            settings.get("led_blink_period_ms"), field="settings.led_blink_period_ms"
        ),
        log_period_ms=_require_int(
            settings.get("log_period_ms"), field="settings.log_period_ms"
        ),
        boot_log_message=_require_str(
            settings.get("boot_log_message"), field="settings.boot_log_message"
        ),
    )


def _guard_report(graph: DesignGraph, report: FirmwareConfigReport) -> None:
    if report.graph_id != graph.graph_id:
        raise DocumentGenerationError(
            f"firmware config report targets graph {report.graph_id!r}, "
            f"not {graph.graph_id!r}"
        )
    if report.target_revision != graph.revision:
        raise DocumentGenerationError(
            f"firmware config report targets revision {report.target_revision!r}, "
            f"not {graph.revision!r}"
        )


def _guard_revision(graph: DesignGraph, macros: dict[str, str]) -> None:
    revision = macros["ACD_TARGET_REVISION"].strip('"')
    if revision != graph.revision:
        raise DocumentGenerationError(
            f"pin projection targets revision {revision!r}, not {graph.revision!r}"
        )


def _macro_int(macros: dict[str, str], name: str, *, because: str) -> int:
    raw = macros.get(name)
    if raw is None:
        raise DocumentGenerationError(
            f"pin projection lacks {name} although the report declares {because}"
        )
    try:
        return int(raw, 0)
    except ValueError as exc:
        raise DocumentGenerationError(
            f"pin projection macro {name} is not an integer: {raw!r}"
        ) from exc


def _guard_pins(
    graph: DesignGraph,
    report: FirmwareConfigReport,
    macros: dict[str, str],
) -> tuple[ReportPin, ...]:
    graph_pins = {
        assignment.net: assignment.gpio
        for assignment in extract_firmware_lane(graph).pin_assignments
    }
    report_pins = {pin.net: pin.gpio for pin in report.pins}
    if report_pins != graph_pins:
        raise DocumentGenerationError(
            "firmware config report pins do not match graph "
            f"firmware.pin_assignment nodes: report={sorted(report_pins.items())}, "
            f"graph={sorted(graph_pins.items())}"
        )
    for pin in report.pins:
        macro = "ACD_PIN_" + pin.net.removeprefix("net.").upper()
        header_gpio = _macro_int(macros, macro, because=f"pin {pin.net}")
        if header_gpio != pin.gpio:
            raise DocumentGenerationError(
                f"pin projection macro {macro}={header_gpio} does not match "
                f"report gpio {pin.gpio} for net {pin.net!r}"
            )
    return tuple(sorted(report.pins, key=lambda pin: pin.net))


def _guard_devices(
    report: FirmwareConfigReport, macros: dict[str, str]
) -> tuple[ReportDevice, ...]:
    seen_addresses: dict[int, str] = {}
    for device in report.devices:
        macro = f"ACD_{device.driver_id.upper()}_I2C_ADDRESS"
        header_address = _macro_int(
            macros, macro, because=f"device {device.driver_id}"
        )
        if header_address != device.i2c_address:
            raise DocumentGenerationError(
                f"pin projection macro {macro}=0x{header_address:02x} does not "
                f"match report i2c_address 0x{device.i2c_address:02x} for "
                f"driver {device.driver_id!r}"
            )
        owner = seen_addresses.get(device.i2c_address)
        if owner is not None:
            raise DocumentGenerationError(
                f"drivers {owner!r} and {device.driver_id!r} share I2C address "
                f"0x{device.i2c_address:02x}"
            )
        seen_addresses[device.i2c_address] = device.driver_id
    return report.devices


def build_interface_spec(
    graph: DesignGraph,
    report: FirmwareConfigReport,
    macros: dict[str, str],
) -> dict[str, object]:
    """Build the deterministic interface-spec JSON body."""
    _guard_report(graph, report)
    _guard_revision(graph, macros)
    pins = _guard_pins(graph, report, macros)
    devices = _guard_devices(report, macros)

    uart_lines: list[dict[str, str]] = [
        {
            "line_id": "boot",
            "format": report.boot_log_message.replace("%s", graph.revision),
            "template": report.boot_log_message,
            "emitted": "once at boot",
            "source": "firmware-config-report.json settings.boot_log_message",
        }
    ]
    device_capability = "i2c_sensor_read" in report.capabilities
    for device in devices:
        if not device_capability:
            break
        uart_lines.append(
            {
                "line_id": f"{device.driver_id}_measurement",
                "format": f"{device.driver_id.upper()} temp_c=<float> rh=<float>",
                "emitted": f"every {report.log_period_ms} ms",
                "source": (
                    "firmware-config-report.json provenance.devices + "
                    "settings.log_period_ms"
                ),
            }
        )

    unknown_fields = ["commands", "uart_log.transport"]
    return {
        "schema_version": 1,
        "artifact_kind": "interface_spec",
        "record_class": "L3",
        "pass_evidence": False,
        "graph_id": graph.graph_id,
        "target_revision": graph.revision,
        "gpio_assignments": [
            {
                "net": pin.net,
                "gpio": pin.gpio,
                "node_id": pin.node_id,
                "source": "graph:firmware.pin_assignment + acd_pins.h",
            }
            for pin in pins
        ],
        "i2c_devices": [
            {
                "mpn": device.mpn,
                "driver_id": device.driver_id,
                "i2c_address": f"0x{device.i2c_address:02x}",
                "source": "firmware-config-report.json + acd_pins.h",
            }
            for device in devices
        ],
        "uart_log": {
            "transport": {
                "status": "unknown",
                "reason": _UNKNOWN_TRANSPORT_REASON,
            },
            "lines": uart_lines,
        },
        "commands": {
            "status": "unknown",
            "reason": _UNKNOWN_COMMANDS_REASON,
            "entries": [],
        },
        "unknown_fields": unknown_fields,
    }


def render_markdown(
    spec: dict[str, object], *, template: DocumentTemplate | None = None
) -> str:
    """Render the Japanese Markdown body from the same spec data."""
    _TEMPLATE.set(template or load_template("ja"))
    gpio_rows = cast(list[dict[str, object]], spec["gpio_assignments"])
    devices = cast(list[dict[str, object]], spec["i2c_devices"])
    uart = cast(dict[str, object], spec["uart_log"])
    commands = cast(dict[str, object], spec["commands"])
    unknown_fields = cast(list[object], spec["unknown_fields"])

    lines = [
        t("interface.document_title", graph_id=spec["graph_id"]),
        "",
        f"- Design Graph: `{spec['graph_id']}`",
        f"- revision: `{spec['target_revision']}`",
        "",
        t("interface.provenance_paragraph"),
        "",
        t("interface.gpio_heading"),
        "",
        t("interface.gpio_header"),
        "|---|---|---|---|",
    ]
    for row in gpio_rows:
        lines.append(
            t(
                "interface.gpio_row",
                net=row["net"],
                gpio=row["gpio"],
                node_id=row["node_id"],
                source=row["source"],
            )
        )
    lines += ["", t("interface.i2c_heading"), ""]
    if devices:
        lines += [
            t("interface.i2c_header"),
            "|---|---|---|---|",
        ]
        for row in devices:
            lines.append(
                t(
                    "interface.i2c_row",
                    driver_id=row["driver_id"],
                    mpn=row["mpn"],
                    i2c_address=row["i2c_address"],
                    source=row["source"],
                )
            )
    else:
        lines.append(t("interface.no_i2c_devices"))
    uart_lines = cast(list[dict[str, object]], uart["lines"])
    uart_transport = cast(dict[str, object], uart["transport"])
    lines += [
        "",
        t("interface.uart_heading"),
        "",
        f"transport: **unknown** — {uart_transport['reason']}",
        "",
        t("interface.uart_header"),
        "|---|---|---|---|",
    ]
    for row in uart_lines:
        lines.append(
            t(
                "interface.uart_row",
                line_id=row["line_id"],
                format=row["format"],
                emitted=row["emitted"],
                source=row["source"],
            )
        )
    lines += [
        "",
        t("interface.commands_heading"),
        "",
        f"**unknown** — {commands['reason']}",
        "",
        t("interface.unknown_heading"),
        "",
    ]
    if unknown_fields:
        for field in sorted(str(item) for item in unknown_fields):
            lines.append(f"- `{field}`")
    else:
        lines.append(t("interface.no_unknown_fields"))
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
    parser.add_argument(
        "--firmware-config-report",
        type=Path,
        required=True,
        help="firmware-config-report.json written by the FW pipeline",
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
    report = load_firmware_config_report(args.firmware_config_report)
    spec = build_interface_spec(graph, report, macros)
    body = render_markdown(spec, template=template)
    output_dir = args.out_dir if args.lang == "ja" else args.out_dir / args.lang
    inputs: list[DocumentInput] = [
        graph_input,
        DocumentInput(path=args.pins_header, content_hash=sha256_file(args.pins_header)),
        DocumentInput(
            path=args.firmware_config_report,
            content_hash=sha256_file(args.firmware_config_report),
        ),
    ]
    document_path, provenance_path = write_document(
        document_kind="interface_spec",
        body=body,
        out_dir=output_dir,
        document_name=DOCUMENT_NAME,
        template_id=f"acd-interface-spec-{args.lang}-v1",
        generator=Path(__file__).resolve(),
        graph=graph,
        inputs=inputs,
        base_dir=args.base_dir,
        template=template,
    )
    json_body = (
        json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    json_document_path, json_provenance_path = write_document(
        document_kind="interface_spec_json",
        body=json_body,
        out_dir=output_dir,
        document_name=JSON_DOCUMENT_NAME,
        template_id=f"acd-interface-spec-{args.lang}-v1",
        generator=Path(__file__).resolve(),
        graph=graph,
        inputs=inputs,
        base_dir=args.base_dir,
        template=template,
    )
    print(f"generated {document_path}")
    print(f"provenance {provenance_path}")
    print(f"generated {json_document_path}")
    print(f"provenance {json_provenance_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DocumentGenerationError as error:
        print(f"interface spec generation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
