"""Firmware projection determinism and pin-consistency check tests.

Uses the Golden Design #1 fixture graph, including a deliberate pin-mismatch
negative test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.electrical import ElectricalLane, extract_electrical_lane
from acd.schema.design_graph import DesignGraph
from fw_checks import (
    ESP32_C3_MINI_1_PAD_TO_GPIO,
    PinConsistencyError,
    assert_header_matches_lane,
    assert_pin_assignments_consistent,
)
from fw_graph import (
    FirmwareExtractionError,
    FirmwareLane,
    FirmwarePinView,
    extract_firmware_lane,
    extract_firmware_settings,
)
from fw_project import (
    FirmwareProjectionError,
    firmware_project_name,
    render_pins_header,
    write_firmware_project,
)

FIXTURE = Path(__file__).resolve().parents[5] / "fixtures" / "golden-design-1" / "graph.json"


@pytest.fixture(scope="module")
def graph() -> DesignGraph:
    return DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def fw_lane(graph: DesignGraph) -> FirmwareLane:
    return extract_firmware_lane(graph)


@pytest.fixture(scope="module")
def electrical(graph: DesignGraph) -> ElectricalLane:
    return extract_electrical_lane(graph)


def test_lane_extraction_matches_golden_design(fw_lane: FirmwareLane) -> None:
    assert fw_lane.gpio_for_net("net.led") == 7
    assert fw_lane.gpio_for_net("net.i2c_sda") == 4
    assert fw_lane.gpio_for_net("net.i2c_scl") == 5
    assert fw_lane.gpio_for_net("net.boot") == 9
    assert fw_lane.gpio_for_net("net.usb_dn") == 18
    assert fw_lane.gpio_for_net("net.usb_dp") == 19
    assert fw_lane.gpio_for_net("net.uart_rx") == 20
    assert fw_lane.gpio_for_net("net.uart_tx") == 21


def test_lane_extraction_fails_closed_on_duplicate_gpio() -> None:
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    nodes = [
        node.model_copy(update={"attrs": {**node.attrs, "gpio": 7}})
        if node.id == "fw.pin.boot"
        else node
        for node in graph.nodes
    ]
    broken = graph.model_copy(update={"nodes": nodes})
    with pytest.raises(FirmwareExtractionError, match="duplicate GPIO"):
        extract_firmware_lane(broken)


def test_pins_header_is_deterministic(fw_lane: FirmwareLane, tmp_path: Path) -> None:
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    settings = extract_firmware_settings(graph)
    first = write_firmware_project(
        fw_lane, "r1", tmp_path / "a", "golden-design-1", settings
    )
    second = write_firmware_project(
        fw_lane, "r1", tmp_path / "b", "golden-design-1", settings
    )
    assert first.pins_header.read_bytes() == second.pins_header.read_bytes()
    assert first.main_source.read_bytes() == second.main_source.read_bytes()
    header = first.pins_header.read_text(encoding="utf-8")
    assert "#define ACD_PIN_LED 7" in header
    assert "#define ACD_SHT40_I2C_ADDRESS 0x44" in header
    assert 'ACD_TARGET_REVISION "r1"' in header
    assert "ACD GD1 fw boot target_revision=%s" in (
        first.main_source.read_text(encoding="utf-8")
    )


def test_firmware_settings_default_and_declared_values(graph: DesignGraph) -> None:
    defaults = extract_firmware_settings(graph)
    assert defaults.led_blink_period_ms == 1000
    assert defaults.log_period_ms == 2000
    module = next(node for node in graph.nodes if node.kind == "firmware.module")
    assert defaults.boot_log_message == module.attrs.get(
        "boot_log_message",
        f"ACD {graph.graph_id} fw boot target_revision=%s",
    )
    changed = next(node for node in graph.nodes if node.kind == "firmware.module")
    declared = graph.model_copy(
        update={
            "nodes": [
                node.model_copy(
                    update={
                        "attrs": {
                            **node.attrs,
                            "led_blink_period_ms": 250,
                            "log_period_ms": 750,
                            "boot_log_message": "boot %s",
                        }
                    }
                )
                if node.id == changed.id
                else node
                for node in graph.nodes
            ]
        }
    )
    settings = extract_firmware_settings(declared)
    assert settings.led_blink_period_ms == 250
    assert settings.log_period_ms == 750
    assert settings.boot_log_message == "boot %s"


def test_firmware_settings_default_is_graph_derived(
    graph: DesignGraph, tmp_path: Path
) -> None:
    module = next(node for node in graph.nodes if node.kind == "firmware.module")
    nodes = [
        node.model_copy(
            update={
                "attrs": {
                    key: value
                    for key, value in node.attrs.items()
                    if key != "boot_log_message"
                }
            }
        )
        if node.id == module.id
        else node
        for node in graph.nodes
    ]
    arbitrary = graph.model_copy(update={"graph_id": "custom-design", "nodes": nodes})
    settings = extract_firmware_settings(arbitrary)
    assert settings.boot_log_message == "ACD custom-design fw boot target_revision=%s"
    project = write_firmware_project(
        extract_firmware_lane(arbitrary),
        "r1",
        tmp_path,
        arbitrary.graph_id,
    )
    assert "ACD custom-design fw boot target_revision=%s" in project.main_source.read_text(
        encoding="utf-8"
    )


def test_malformed_firmware_settings_fail_closed(graph: DesignGraph) -> None:
    module = next(node for node in graph.nodes if node.kind == "firmware.module")
    broken = graph.model_copy(
        update={
            "nodes": [
                node.model_copy(
                    update={"attrs": {**node.attrs, "log_period_ms": 0}}
                )
                if node.id == module.id
                else node
                for node in graph.nodes
            ]
        }
    )
    with pytest.raises(FirmwareExtractionError, match="log_period_ms"):
        extract_firmware_settings(broken)


def test_project_name_is_derived_from_the_graph_id(
    fw_lane: FirmwareLane, tmp_path: Path
) -> None:
    project = write_firmware_project(fw_lane, "r1", tmp_path, "golden-design-1")
    assert project.name == "acd_golden_design_1_fw"
    assert project.root.name == project.name
    assert project.app_binary.name == "acd_golden_design_1_fw.bin"
    assert 'project(acd_golden_design_1_fw)' in (
        project.root / "CMakeLists.txt"
    ).read_text(encoding="utf-8")
    assert 'TAG = "acd_golden_design_1"' in project.main_source.read_text(encoding="utf-8")


@pytest.mark.parametrize("graph_id", ["", "   ", "---", "///"])
def test_unusable_graph_id_fails_closed(graph_id: str) -> None:
    with pytest.raises(FirmwareProjectionError, match="firmware project name"):
        firmware_project_name(graph_id)


def test_generated_header_matches_lane(fw_lane: FirmwareLane) -> None:
    assert_header_matches_lane(render_pins_header(fw_lane, "r1"), fw_lane)


def test_header_check_rejects_tampered_gpio(fw_lane: FirmwareLane) -> None:
    header = render_pins_header(fw_lane, "r1").replace("ACD_PIN_LED 7", "ACD_PIN_LED 6")
    with pytest.raises(PinConsistencyError, match="ACD_PIN_LED"):
        assert_header_matches_lane(header, fw_lane)


def test_pin_check_passes_on_golden_design(
    fw_lane: FirmwareLane, electrical: ElectricalLane
) -> None:
    assert_pin_assignments_consistent(fw_lane, electrical, "U1", ESP32_C3_MINI_1_PAD_TO_GPIO)


def test_pin_check_rejects_deliberate_pin_shift(
    fw_lane: FirmwareLane, electrical: ElectricalLane
) -> None:
    """Negative test: shifting the LED assignment to another GPIO must fail."""
    shifted = FirmwareLane(
        pins=tuple(
            FirmwarePinView(node_id=p.node_id, gpio=6, net_id=p.net_id)
            if p.net_id == "net.led"
            else p
            for p in fw_lane.pins
        )
    )
    with pytest.raises(PinConsistencyError, match=r"net\.led"):
        assert_pin_assignments_consistent(shifted, electrical, "U1", ESP32_C3_MINI_1_PAD_TO_GPIO)


def test_pin_check_rejects_pad_outside_pinned_map(
    fw_lane: FirmwareLane, electrical: ElectricalLane
) -> None:
    partial_map = {k: v for k, v in ESP32_C3_MINI_1_PAD_TO_GPIO.items() if v != 7}
    with pytest.raises(PinConsistencyError, match="not in pinned pad map"):
        assert_pin_assignments_consistent(fw_lane, electrical, "U1", partial_map)


def test_pin_check_rejects_unknown_module(
    fw_lane: FirmwareLane, electrical: ElectricalLane
) -> None:
    with pytest.raises(PinConsistencyError, match="not found"):
        assert_pin_assignments_consistent(fw_lane, electrical, "U99", ESP32_C3_MINI_1_PAD_TO_GPIO)


def test_render_header_fails_closed_on_missing_net() -> None:
    lane = FirmwareLane(pins=(FirmwarePinView(node_id="fw.pin.led", gpio=7, net_id="net.led"),))
    with pytest.raises(Exception, match=r"net\.i2c_sda"):
        render_pins_header(lane, "r1")
