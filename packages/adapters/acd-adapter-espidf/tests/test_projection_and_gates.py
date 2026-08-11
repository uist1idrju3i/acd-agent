"""Firmware projection determinism and pin-consistency gate tests.

Uses the Golden Design #1 fixture graph. Includes the deliberate pin-mismatch
negative test required by the Phase 2 completion criteria.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd_adapter_espidf.build import fw_package_from_lane
from acd_adapter_espidf.gates import (
    ESP32_C3_MINI_1_PAD_TO_GPIO,
    PinGateError,
    assert_build_known,
    assert_pin_assignments_consistent,
)
from acd_adapter_espidf.project import render_pins_header, write_firmware_project
from acd_core.electrical import ElectricalLane, extract_electrical_lane
from acd_core.firmware import (
    FirmwareExtractionError,
    FirmwareLane,
    FirmwarePinView,
    extract_firmware_lane,
)
from acd_schema.design_graph import DesignGraph
from acd_schema.fw_package import BuildInfo, FwPackage

FIXTURE = Path(__file__).resolve().parents[4] / "fixtures" / "golden-design-1" / "graph.json"


@pytest.fixture(scope="module")
def graph() -> DesignGraph:
    return DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def fw_lane(graph: DesignGraph) -> FirmwareLane:
    return extract_firmware_lane(graph)


@pytest.fixture(scope="module")
def electrical(graph: DesignGraph) -> ElectricalLane:
    return extract_electrical_lane(graph)


def _build() -> BuildInfo:
    zero_hash = "sha256:" + "0" * 64
    return BuildInfo(
        toolchain_version="esp-idf v6.0.2", source_hash=zero_hash, artifact_hash=zero_hash
    )


def _package(fw_lane: FirmwareLane, revision: str) -> FwPackage:
    return fw_package_from_lane(
        fw_lane, package_id="fw.gd1", target_revision=revision, build=_build()
    )


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


def test_pin_gate_passes_on_golden_design(
    fw_lane: FirmwareLane, electrical: ElectricalLane, graph: DesignGraph
) -> None:
    package = _package(fw_lane, graph.revision)
    assert_pin_assignments_consistent(
        package, fw_lane, electrical, "U1", ESP32_C3_MINI_1_PAD_TO_GPIO
    )


def test_pin_gate_rejects_deliberate_pin_shift(
    fw_lane: FirmwareLane, electrical: ElectricalLane, graph: DesignGraph
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
    package = _package(shifted, graph.revision)
    with pytest.raises(PinGateError, match=r"net\.led"):
        assert_pin_assignments_consistent(
            package, shifted, electrical, "U1", ESP32_C3_MINI_1_PAD_TO_GPIO
        )


def test_pin_gate_rejects_package_graph_mismatch(
    fw_lane: FirmwareLane, electrical: ElectricalLane, graph: DesignGraph
) -> None:
    """Negative test: a package pin diverging from the graph must fail."""
    package = _package(fw_lane, graph.revision)
    assignments = [
        a.model_copy(update={"pin": "IO6"}) if a.net == "net.led" else a
        for a in package.pin_assignments
    ]
    tampered = package.model_copy(update={"pin_assignments": assignments})
    with pytest.raises(PinGateError, match=r"net\.led"):
        assert_pin_assignments_consistent(
            tampered, fw_lane, electrical, "U1", ESP32_C3_MINI_1_PAD_TO_GPIO
        )


def test_pin_gate_rejects_pad_outside_pinned_map(
    fw_lane: FirmwareLane, electrical: ElectricalLane, graph: DesignGraph
) -> None:
    package = _package(fw_lane, graph.revision)
    partial_map = {k: v for k, v in ESP32_C3_MINI_1_PAD_TO_GPIO.items() if v != 7}
    with pytest.raises(PinGateError, match="not in pinned pad map"):
        assert_pin_assignments_consistent(package, fw_lane, electrical, "U1", partial_map)


def test_build_gate_rejects_unknown_hashes(fw_lane: FirmwareLane, graph: DesignGraph) -> None:
    unknown_build = BuildInfo(
        toolchain_version="esp-idf v6.0.2", source_hash="unknown", artifact_hash="unknown"
    )
    package = fw_package_from_lane(
        fw_lane, package_id="fw.gd1", target_revision=graph.revision, build=unknown_build
    )
    with pytest.raises(PinGateError, match="unknown"):
        assert_build_known(package)


def test_render_header_fails_closed_on_missing_net() -> None:
    lane = FirmwareLane(pins=(FirmwarePinView(node_id="fw.pin.led", gpio=7, net_id="net.led"),))
    with pytest.raises(Exception, match=r"net\.i2c_sda"):
        render_pins_header(lane, "r1")
