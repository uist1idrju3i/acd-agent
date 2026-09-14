# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@b251f797f6ce48cbc7bd338ec965113f84801d22",
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
from pathlib import Path
from typing import cast

from acd.schema.design_graph import DesignGraph
from doc_inputs import (
    DocumentGenerationError,
    DocumentInput,
    DocumentTemplate,
    FirmwareConfigReport,
    guard_devices,
    guard_pins,
    guard_report,
    guard_revision,
    load_firmware_config_report,
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


def build_interface_spec(
    graph: DesignGraph,
    report: FirmwareConfigReport,
    macros: dict[str, str],
) -> dict[str, object]:
    """Build the deterministic interface-spec JSON body."""
    guard_report(graph, report)
    guard_revision(graph, macros)
    pins = guard_pins(graph, report, macros)
    devices = guard_devices(report, macros)

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
