"""Interface-spec projection determinism and fail-closed tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from doc_inputs import DocumentGenerationError, load_graph
from generate_instruction_manual import parse_pins_header
from generate_interface_spec import (
    build_interface_spec,
    load_firmware_config_report,
    render_markdown,
)
from generate_interface_spec import main as interface_main

REPO_ROOT = Path(__file__).resolve().parents[5]
GRAPH = REPO_ROOT / "fixtures" / "golden-design-1" / "graph.json"

_PINS = {
    "net.boot": 9,
    "net.i2c_scl": 5,
    "net.i2c_sda": 4,
    "net.led": 7,
    "net.uart_rx": 20,
    "net.uart_tx": 21,
    "net.usb_dn": 18,
    "net.usb_dp": 19,
}


def _graph_id() -> str:
    payload = cast(dict[str, object], json.loads(GRAPH.read_text(encoding="utf-8")))
    graph_id = payload["graph_id"]
    assert isinstance(graph_id, str)
    return graph_id


def _pins_header(directory: Path, revision: str = "r1") -> Path:
    lines = [
        "#pragma once",
        "",
        f'#define ACD_TARGET_REVISION "{revision}"',
        "",
    ]
    for net, gpio in sorted(_PINS.items()):
        macro = "ACD_PIN_" + net.removeprefix("net.").upper()
        lines.append(f"#define {macro} {gpio}")
    lines += [
        "",
        "#define ACD_SHT40_I2C_ADDRESS 0x44",
        "#define ACD_LED_BLINK_PERIOD_MS 1000",
        "#define ACD_LOG_PERIOD_MS 2000",
        "",
    ]
    path = directory / "acd_pins.h"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _config_report(
    directory: Path,
    *,
    graph_id: str | None = None,
    revision: str = "r1",
    pins: dict[str, int] | None = None,
    capabilities: tuple[str, ...] = (
        "led_blink",
        "i2c_sensor_init",
        "i2c_sensor_read",
    ),
    devices: tuple[tuple[str, str, int], ...] = (
        ("SHT40-AD1B-R3", "sht40", 0x44),
    ),
) -> Path:
    pin_map = _PINS if pins is None else pins
    report = {
        "schema_version": 1,
        "graph_id": _graph_id() if graph_id is None else graph_id,
        "target_revision": revision,
        "pins": [
            {"node_id": f"fw.pin.{net.removeprefix('net.')}", "gpio": gpio, "net": net}
            for net, gpio in sorted(pin_map.items())
        ],
        "settings": {
            "led_blink_period_ms": 1000,
            "log_period_ms": 2000,
            "boot_log_message": "ACD GD1 fw boot target_revision=%s",
        },
        "provenance": {
            "capabilities": [
                {"capability_id": cap, "action": "step", "step_index": index}
                for index, cap in enumerate(capabilities, start=1)
            ],
            "devices": [
                {"mpn": mpn, "driver_id": driver, "i2c_address": address}
                for mpn, driver, address in devices
            ],
        },
    }
    path = directory / "firmware-config-report.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _spec(
    tmp_path: Path,
    *,
    graph_id: str | None = None,
    revision: str = "r1",
    pins: dict[str, int] | None = None,
    capabilities: tuple[str, ...] = ("led_blink", "i2c_sensor_init", "i2c_sensor_read"),
    devices: tuple[tuple[str, str, int], ...] = (("SHT40-AD1B-R3", "sht40", 0x44),),
) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    header = _pins_header(tmp_path)
    report_path = _config_report(
        tmp_path,
        graph_id=graph_id,
        revision=revision,
        pins=pins,
        capabilities=capabilities,
        devices=devices,
    )
    graph, _ = load_graph(GRAPH)
    macros = parse_pins_header(header)
    report = load_firmware_config_report(report_path)
    return build_interface_spec(graph, report, macros)


def test_interface_spec_projects_gpio_i2c_and_uart(tmp_path: Path) -> None:
    spec = _spec(tmp_path)

    assert spec["artifact_kind"] == "interface_spec"
    assert spec["record_class"] == "L3"
    assert spec["pass_evidence"] is False
    gpio = cast(list[dict[str, object]], spec["gpio_assignments"])
    assert len(gpio) == len(_PINS)
    assert gpio[0]["net"] == "net.boot"
    devices = cast(list[dict[str, object]], spec["i2c_devices"])
    assert devices == [
        {
            "mpn": "SHT40-AD1B-R3",
            "driver_id": "sht40",
            "i2c_address": "0x44",
            "source": "firmware-config-report.json + acd_pins.h",
        }
    ]
    uart = cast(dict[str, object], spec["uart_log"])
    uart_lines = cast(list[dict[str, object]], uart["lines"])
    boot = uart_lines[0]
    assert boot["format"] == "ACD GD1 fw boot target_revision=r1"
    assert boot["template"] == "ACD GD1 fw boot target_revision=%s"
    measurement = uart_lines[1]
    assert measurement["line_id"] == "sht40_measurement"
    assert measurement["format"] == "SHT40 temp_c=<float> rh=<float>"
    assert measurement["emitted"] == "every 2000 ms"
    assert spec["unknown_fields"] == ["commands", "uart_log.transport"]


def test_interface_spec_json_is_deterministic(tmp_path: Path) -> None:
    first = _spec(tmp_path / "first")
    second = _spec(tmp_path / "second")
    assert first == second
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second, ensure_ascii=False, sort_keys=True
    )


def test_no_i2c_sensor_read_omits_measurement_line(tmp_path: Path) -> None:
    spec = _spec(tmp_path, capabilities=("led_blink", "i2c_sensor_init"))
    uart = cast(dict[str, object], spec["uart_log"])
    line_ids = [
        row["line_id"]
        for row in cast(list[dict[str, object]], uart["lines"])
    ]
    assert line_ids == ["boot"]


def test_empty_device_list_writes_no_devices(tmp_path: Path) -> None:
    spec = _spec(tmp_path, devices=())
    assert spec["i2c_devices"] == []
    uart = cast(dict[str, object], spec["uart_log"])
    line_ids = [
        row["line_id"]
        for row in cast(list[dict[str, object]], uart["lines"])
    ]
    assert line_ids == ["boot"]


def test_report_revision_mismatch_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(DocumentGenerationError, match="targets revision"):
        _spec(tmp_path, revision="r99")


def test_report_graph_id_mismatch_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(DocumentGenerationError, match="targets graph"):
        _spec(tmp_path, graph_id="other-design")


def test_report_pin_mismatch_fails_closed(tmp_path: Path) -> None:
    pins = dict(_PINS)
    pins["net.led"] = 8
    with pytest.raises(DocumentGenerationError, match="do not match"):
        _spec(tmp_path, pins=pins)


def test_header_gpio_mismatch_fails_closed(tmp_path: Path) -> None:
    header = _pins_header(tmp_path)
    content = header.read_text(encoding="utf-8").replace(
        "#define ACD_PIN_LED 7", "#define ACD_PIN_LED 8"
    )
    header.write_text(content, encoding="utf-8")
    report_path = _config_report(tmp_path)
    graph, _ = load_graph(GRAPH)
    macros = parse_pins_header(header)
    report = load_firmware_config_report(report_path)
    with pytest.raises(DocumentGenerationError, match="ACD_PIN_LED"):
        build_interface_spec(graph, report, macros)


def test_i2c_macro_mismatch_fails_closed(tmp_path: Path) -> None:
    header = _pins_header(tmp_path)
    content = header.read_text(encoding="utf-8").replace(
        "#define ACD_SHT40_I2C_ADDRESS 0x44", "#define ACD_SHT40_I2C_ADDRESS 0x45"
    )
    header.write_text(content, encoding="utf-8")
    report_path = _config_report(tmp_path)
    graph, _ = load_graph(GRAPH)
    macros = parse_pins_header(header)
    report = load_firmware_config_report(report_path)
    with pytest.raises(DocumentGenerationError, match="ACD_SHT40_I2C_ADDRESS"):
        build_interface_spec(graph, report, macros)


def test_missing_report_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(DocumentGenerationError, match="not valid"):
        load_firmware_config_report(tmp_path / "absent.json")


def test_main_writes_documents_and_provenance(tmp_path: Path) -> None:
    header = _pins_header(tmp_path)
    report_path = _config_report(tmp_path)
    out_dir = tmp_path / "out"

    assert (
        interface_main(
            [
                "--graph",
                str(GRAPH),
                "--pins-header",
                str(header),
                "--firmware-config-report",
                str(report_path),
                "--out-dir",
                str(out_dir),
                "--base-dir",
                str(tmp_path),
            ]
        )
        == 0
    )

    markdown = out_dir / "interface-spec.md"
    spec_json = out_dir / "interface-spec.json"
    assert markdown.is_file()
    assert spec_json.is_file()
    body = markdown.read_text(encoding="utf-8")
    assert "機器インターフェース仕様" in body
    assert "L3観測" in body
    provenance = json.loads(
        (out_dir / "interface-spec.md.provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["document_kind"] == "interface_spec"
    assert provenance["template_id"] == "acd-interface-spec-ja-v1"
    assert provenance["pass_evidence"] is False
    json_provenance = json.loads(
        (out_dir / "interface-spec.json.provenance.json").read_text(encoding="utf-8")
    )
    assert json_provenance["document_kind"] == "interface_spec_json"


def test_empty_i2c_markdown_sentence(tmp_path: Path) -> None:
    spec = _spec(tmp_path, devices=())
    body = render_markdown(spec)
    assert "I2Cデバイスは宣言されていない。" in body
