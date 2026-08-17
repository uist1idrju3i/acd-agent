"""Firmware projection determinism and pin-consistency check tests.

Uses the Golden Design #1 fixture graph, including a deliberate pin-mismatch
negative test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd_core.electrical import ElectricalLane, extract_electrical_lane
from acd_schema.design_graph import DesignGraph
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
)
from fw_project import render_pins_header, write_firmware_project

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
    first = write_firmware_project(fw_lane, "r1", tmp_path / "a")
    second = write_firmware_project(fw_lane, "r1", tmp_path / "b")
    assert first.pins_header.read_bytes() == second.pins_header.read_bytes()
    assert first.main_source.read_bytes() == second.main_source.read_bytes()
    header = first.pins_header.read_text(encoding="utf-8")
    assert "#define ACD_PIN_LED 7" in header
    assert "#define ACD_SHT40_I2C_ADDRESS 0x44" in header
    assert 'ACD_TARGET_REVISION "r1"' in header


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
