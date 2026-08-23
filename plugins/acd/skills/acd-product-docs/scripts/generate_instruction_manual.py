# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@fdde02c0485e5dedd25ecd2f93201eac62f42bd4",
# ]
# ///
"""Generate the deterministic instruction manual for a design graph.

Function descriptions, connection steps, LED semantics, flashing steps and
safety notes are derived from the design graph and from the generated firmware
pin projection (``acd_pins.h``). No value is estimated: when an input macro or
graph node is missing, generation stops instead of guessing a number.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from acd.core.electrical import extract_electrical_lane
from acd.core.firmware_lane import extract_firmware_lane
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

TEMPLATE_ID = "acd-instruction-manual-ja-v1"
DOCUMENT_NAME = "instruction-manual.md"

_DEFINE_PATTERN = re.compile(r"^#define\s+(?P<name>[A-Z0-9_]+)\s+(?P<value>\S+)\s*$")
_REQUIRED_MACROS = (
    "ACD_TARGET_REVISION",
    "ACD_PIN_LED",
    "ACD_PIN_I2C_SDA",
    "ACD_PIN_I2C_SCL",
    "ACD_PIN_UART_TX",
    "ACD_PIN_UART_RX",
    "ACD_PIN_USB_DP",
    "ACD_PIN_USB_DN",
    "ACD_PIN_BOOT",
    "ACD_SHT40_I2C_ADDRESS",
    "ACD_LED_BLINK_PERIOD_MS",
    "ACD_LOG_PERIOD_MS",
)


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


def _macro_int(macros: dict[str, str], name: str) -> int:
    raw = macros[name]
    try:
        return int(raw, 0)
    except ValueError as exc:
        raise DocumentGenerationError(
            f"pin projection macro {name} is not an integer: {raw!r}"
        ) from exc


def _revision_guard(graph: DesignGraph, macros: dict[str, str]) -> None:
    revision = macros["ACD_TARGET_REVISION"].strip('"')
    if revision != graph.revision:
        raise DocumentGenerationError(
            f"pin projection targets revision {revision!r}, not {graph.revision!r}"
        )


def _function_section(graph: DesignGraph, macros: dict[str, str]) -> list[str]:
    firmware = extract_firmware_lane(graph)
    lines = ["## 機能説明", "", "起動後のFWは次の状態を遷移する。", ""]
    lines += ["| 状態 | 初期状態 |", "|---|---|"]
    for state in sorted(firmware.states, key=lambda item: item.state_name):
        lines.append(f"| {state.state_name} | {'はい' if state.initial else 'いいえ'} |")
    lines += ["", "動作順序は次のとおり。", "", "| 手順 | 対象 | 動作 |", "|---|---|---|"]
    for step in sorted(firmware.sequence_steps, key=lambda item: item.step_index):
        lines.append(f"| {step.step_index} | {step.target} | {step.action} |")
    address = _macro_int(macros, "ACD_SHT40_I2C_ADDRESS")
    log_period_ms = _macro_int(macros, "ACD_LOG_PERIOD_MS")
    lines += [
        "",
        f"温湿度センサはI2Cアドレス`0x{address:02x}`で読み出し、"
        f"{log_period_ms} msごとにシリアルログへ出力する。",
        "",
    ]
    return lines


def _connection_section(graph: DesignGraph, macros: dict[str, str]) -> list[str]:
    lane = extract_electrical_lane(graph)
    opening = single_node_of_kind(graph, "mechanical.connector_opening")
    connector_id = text_attr(opening, "connector")
    connector = next((c for c in lane.components if c.node_id == connector_id), None)
    if connector is None:
        raise DocumentGenerationError(f"connector component {connector_id!r} is missing")
    lines = [
        "## 接続手順",
        "",
        f"1. 筐体{text_attr(opening, 'face')}面の開口部から、{connector.refdes}"
        f"（{connector.mpn}）へUSBケーブルを挿入する。",
        "2. USBケーブルの他端をPCまたはUSB電源へ接続する。",
        f"3. シリアルモニタを開くと、USBシリアル（IO{_macro_int(macros, 'ACD_PIN_USB_DP')}／"
        f"IO{_macro_int(macros, 'ACD_PIN_USB_DN')}）経由でログを確認できる。",
        "",
        "| 開口部項目 | 値 |",
        "|---|---|",
        f"| 幅 | {format_number(number_attr(opening, 'width_mm'))} mm |",
        f"| 高さ | {format_number(number_attr(opening, 'height_mm'))} mm |",
        f"| 余裕 | {format_number(number_attr(opening, 'margin_mm'))} mm |",
        "",
    ]
    return lines


def _led_section(graph: DesignGraph, macros: dict[str, str]) -> list[str]:
    firmware = extract_firmware_lane(graph)
    period_ms = _macro_int(macros, "ACD_LED_BLINK_PERIOD_MS")
    gpio = _macro_int(macros, "ACD_PIN_LED")
    toggles = [
        step for step in firmware.sequence_steps if step.action == "toggle_led"
    ]
    if not toggles:
        raise DocumentGenerationError("firmware sequence declares no LED action")
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
    lines.append("")
    return lines


def _flashing_section(graph: DesignGraph, macros: dict[str, str]) -> list[str]:
    firmware = extract_firmware_lane(graph)
    lane = extract_electrical_lane(graph)
    mcu = next(
        (c for c in lane.components if c.node_id == firmware.module.mcu_component), None
    )
    if mcu is None:
        raise DocumentGenerationError("MCU component is missing from the graph")
    return [
        "## 書き込み手順",
        "",
        f"1. `{mcu.mpn}`のUSBシリアルJTAG（IO{_macro_int(macros, 'ACD_PIN_USB_DP')}／"
        f"IO{_macro_int(macros, 'ACD_PIN_USB_DN')}）でPCへ接続する。",
        f"2. 書き込みに失敗する場合はIO{_macro_int(macros, 'ACD_PIN_BOOT')}の"
        "BOOT信号をGNDへ落として再接続する。",
        f"3. revision`{graph.revision}`のFWイメージを書き込む。",
        "4. 書き込み後にリセットすると、LED点滅とシリアルログが再開する。",
        "",
    ]


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
    lines += _function_section(graph, macros)
    lines += _connection_section(graph, macros)
    lines += _led_section(graph, macros)
    lines += _flashing_section(graph, macros)
    lines += _safety_section(graph)
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
