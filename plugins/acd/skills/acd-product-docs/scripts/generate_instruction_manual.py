# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@850b4f10a9106ea478df45ed0f78d64241be66b6",
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
from dataclasses import dataclass
from pathlib import Path

from acd.core.electrical import extract_electrical_lane
from acd.core.firmware_lane import FirmwareLane, extract_firmware_lane
from acd.schema.design_graph import DesignGraph
from doc_inputs import (
    DocumentGenerationError,
    DocumentInput,
    format_number,
    load_graph,
    number_attr,
    sha256_file,
    single_node_of_kind,
    text_attr,
    write_document,
)

TEMPLATE_ID = "acd-instruction-manual-ja-v2"
DOCUMENT_NAME = "instruction-manual.md"

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
    lines = ["## 機能説明", "", "起動後のFWは次の状態を遷移する。", ""]
    lines += ["| 状態 | 初期状態 |", "|---|---|"]
    for state in sorted(firmware.states, key=lambda item: item.state_name):
        lines.append(f"| {state.state_name} | {'はい' if state.initial else 'いいえ'} |")
    lines += ["", "動作順序は次のとおり。", "", "| 手順 | 対象 | 動作 |", "|---|---|---|"]
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
            f"温湿度センサはI2Cアドレス`0x{address:02x}`で読み出す。",
        ]
    else:
        omissions.append(
            Omission("機能説明（センサ）", "graphにセンサ読み出しstepの宣言が無い")
        )
    if any(step.action == "write_serial_log" for step in firmware.sequence_steps):
        log_period_ms = _required_macro_int(
            macros,
            "ACD_LOG_PERIOD_MS",
            because="write_serial_log step",
        )
        lines.append(f"{log_period_ms} msごとにシリアルログへ出力する。")
    else:
        omissions.append(
            Omission(
                "機能説明（シリアルログ）",
                "graphにwrite_serial_log stepの宣言が無い",
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
            Omission("接続手順", "mechanical.connector_openingの宣言が無い")
        )
        return []
    lines = ["## 接続手順", ""]
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
            f"{step}. 筐体{text_attr(opening, 'face')}面の開口部から、"
            f"{connector.refdes}（{connector.mpn}）へケーブルを挿入する。",
            f"{step + 1}. ケーブルの他端をPCまたは電源へ接続する。",
            "",
            f"### {opening.id}",
            "",
            "| 開口部項目 | 値 |",
            "|---|---|",
            f"| 幅 | {format_number(number_attr(opening, 'width_mm'))} mm |",
            f"| 高さ | {format_number(number_attr(opening, 'height_mm'))} mm |",
            f"| 余裕 | {format_number(number_attr(opening, 'margin_mm'))} mm |",
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
                "接続手順（USBシリアル）",
                "pin role usb_dp/usb_dn の宣言が無い",
            )
        )
    else:
        lines += [
            f"USBシリアル（IO{usb[0]}／IO{usb[1]}）経由でログを確認できる。",
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
            Omission("LED表示の意味", "graphにtoggle_led stepの宣言が無い")
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
        "## LED表示の意味",
        "",
        "| 表示 | 意味 |",
        "|---|---|",
        f"| 周期{period_ms} msの点滅 | IO{gpio}のLEDが点滅し、"
        "計測ループが動作していることを示す |",
        "| 消灯のまま | 給電またはFW書き込みが完了していない |",
    ]
    for state in fault_states:
        lines.append(
            f"| 点滅停止 | FWが`{state}`状態であり、センサ読み出しに失敗している |"
        )
    if any(step.action == "toggle_led2" for step in firmware.sequence_steps):
        gpio2 = _required_macro_int(
            macros,
            "ACD_PIN_LED2",
            because="toggle_led2 step",
        )
        lines.insert(
            6,
            f"| 逆相の点滅 | IO{gpio2}のLEDが逆相で点滅する |",
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
        omissions.append(Omission("操作", "graphにread_button stepの宣言が無い"))
        return []
    button = _required_macro_int(
        macros,
        "ACD_PIN_BUTTON",
        because="read_button step",
    )
    lines = ["## 操作", ""]
    for transition in sorted(firmware.transitions, key=lambda item: item.node_id):
        if transition.trigger == "button_pressed":
            lines.append(
                f"IO{button}のボタンを押すと`{transition.from_state}`から"
                f"`{transition.to_state}`へ遷移する。"
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
    lines = ["## 書き込み手順", ""]
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
            f"{step}. `{mcu.mpn}`のUSBシリアルJTAG（IO{usb[0]}／IO{usb[1]}）でPCへ接続する。"
        )
        step += 1
    elif uart is not None:
        lines.append(
            f"{step}. `{mcu.mpn}`のUART（TX: IO{uart[0]}／RX: IO{uart[1]}）でPCへ接続する。"
        )
        step += 1
    else:
        lines.append(
            f"{step}. 書き込み経路（USB／UART）の宣言が無いため、"
            "MCUのデータシートに従って接続する。"
        )
        omissions.append(
            Omission("書き込み経路", "graphにUSB／UART書き込み経路の宣言が無い")
        )
        step += 1
    if "net.boot" in _declared_nets(firmware):
        boot = _required_macro_int(
            macros,
            "ACD_PIN_BOOT",
            because="pin role boot",
        )
        lines.append(
            f"{step}. 書き込みに失敗する場合はIO{boot}の"
            "BOOT信号をGNDへ落として再接続する。"
        )
        step += 1
    lines.append(f"{step}. revision`{graph.revision}`のFWイメージを書き込む。")
    step += 1
    reset = "LED点滅とシリアルログが再開する。" if led_written else "FWが再開する。"
    lines.append(f"{step}. 書き込み後にリセットすると、{reset}")
    lines.append("")
    return lines


def _safety_section(graph: DesignGraph) -> list[str]:
    safety = single_node_of_kind(graph, "safety.boundary")
    board = single_node_of_kind(graph, "electrical.board")
    max_voltage = format_number(number_attr(safety, "max_net_voltage_v"))
    max_current = format_number(number_attr(safety, "max_current_a"))
    lines = [
        "## 安全上の注意",
        "",
        f"- 電源はUSBのみとし、最大ネット電圧{max_voltage} V、"
        f"最大電流{max_current} Aを超える使用をしない。",
        f"- 想定用途は`{text_attr(safety, 'intended_use')}`であり、"
        "バッテリ、充電回路、モータ・アクチュエータ・レーザを接続しない。",
        f"- アンテナ部（基板端）を金属で覆わない（アンテナkeepout: "
        f"{'宣言あり' if board.attrs.get('antenna_keepout') is True else '宣言なし'}）。",
        "- 筐体を開けた状態で通電しない。",
        "",
    ]
    return lines


def render_manual(graph: DesignGraph, macros: dict[str, str]) -> str:
    """Render the instruction manual body for a graph and its pin projection."""
    _revision_guard(graph, macros)
    lines = [
        f"# 取扱説明書: {graph.graph_id}",
        "",
        f"- Design Graph: `{graph.graph_id}`",
        f"- revision: `{graph.revision}`",
        "",
        "この文書はDesign GraphとFWピン投影（`acd_pins.h`）から決定論的に生成された観測であり、"
        "設計や製品の合否を判定しない。記載値はすべて入力由来で、推定値を含まない。",
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
    lines += ["## 省略した項目", ""]
    if omissions:
        lines += [f"- {item.section}: {item.reason}" for item in omissions]
    else:
        lines.append("省略した項目はない。")
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    graph, graph_input = load_graph(args.graph)
    macros = parse_pins_header(args.pins_header)
    body = render_manual(graph, macros)
    inputs: list[DocumentInput] = [
        graph_input,
        DocumentInput(path=args.pins_header, content_hash=sha256_file(args.pins_header)),
    ]
    document_path, provenance_path = write_document(
        document_kind="instruction_manual",
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
        print(f"instruction manual generation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
