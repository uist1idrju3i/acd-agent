"""Firmware requirement-to-sequence coverage check tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.firmware_capability import load_firmware_capability_registry
from acd.core.firmware_coverage import (
    FirmwareCoverageFinding,
    FirmwareCoverageReport,
    check_firmware_coverage,
)
from acd.pipeline.fixture_builder import build_design_fixture
from acd.schema import DesignFixtureSpec
from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.firmware_capability import FirmwareCapabilityRegistryDocument

REPO_ROOT = Path(__file__).resolve().parents[2]
GD1_FIXTURE = REPO_ROOT / "fixtures" / "golden-design-1" / "graph.json"
SENSOR_NODE_GRAPH = (
    REPO_ROOT / "examples" / "sensor-node-20260820" / "fixture" / "graph.json"
)
DUAL_BEACON_SPEC = (
    REPO_ROOT
    / "examples"
    / "dual-beacon-tag-vps-20260906"
    / "fixture"
    / "spec.json"
)


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(
        json.loads(GD1_FIXTURE.read_text(encoding="utf-8"))
    )


def _registry_document() -> FirmwareCapabilityRegistryDocument:
    return load_firmware_capability_registry().document


def _replace_node(graph: DesignGraph, node_id: str, **updates: object) -> DesignGraph:
    nodes = [
        node.model_copy(update=updates) if node.id == node_id else node
        for node in graph.nodes
    ]
    return graph.model_copy(update={"nodes": nodes})


def _replace_attrs(graph: DesignGraph, node_id: str, **attrs: object) -> DesignGraph:
    node = graph.node_by_id(node_id)
    return _replace_node(graph, node_id, attrs={**node.attrs, **attrs})


def _codes(report: FirmwareCoverageReport) -> list[tuple[str, str]]:
    return [(finding.code, finding.node_id) for finding in report.findings]


def test_gd1_graph_passes_coverage() -> None:
    report = check_firmware_coverage(_graph(), _registry_document())
    assert report.status == "pass"
    assert report.findings == ()


def test_sensor_node_example_passes_coverage() -> None:
    graph = DesignGraph.model_validate(
        json.loads(SENSOR_NODE_GRAPH.read_text(encoding="utf-8"))
    )
    report = check_firmware_coverage(graph, _registry_document())
    assert report.status == "pass"


def test_untargeted_led_indicator_fails_closed() -> None:
    graph = _replace_attrs(_graph(), "comp.sw1", led_indicator=True)
    report = check_firmware_coverage(graph, _registry_document())
    assert report.status == "fail"
    assert _codes(report) == [("led_indicator_untargeted", "comp.sw1")]
    finding = report.findings[0]
    assert "'comp.sw1'" in finding.message
    assert "toggle_led" in finding.message
    assert "remove the led_indicator declaration" in finding.message


def test_unemitted_trigger_fails_closed() -> None:
    graph = _replace_attrs(
        _graph(), "fw.transition.report_measure", trigger="unregistered_trigger"
    )
    report = check_firmware_coverage(graph, _registry_document())
    assert report.status == "fail"
    assert _codes(report) == [("trigger_unemitted", "fw.transition.report_measure")]
    message = report.findings[0].message
    assert "'unregistered_trigger'" in message
    assert "'fw.transition.report_measure'" in message
    assert "no registered capability emits this trigger" in message


def test_unemitted_trigger_names_registered_emitters() -> None:
    graph = _replace_attrs(
        _graph(), "fw.transition.report_measure", trigger="button_pressed"
    )
    report = check_firmware_coverage(graph, _registry_document())
    assert report.status == "fail"
    message = report.findings[0].message
    assert "registered emitters: button_input" in message


def test_unconsumed_pin_role_fails_closed() -> None:
    graph = _graph()
    net = GraphNode(
        id="net.user_btn",
        kind="electrical.net",
        attrs={
            "name": "USER_BTN",
            "width_basis": "manufacturing_minimum",
            "width_basis_source": "test coverage",
        },
        depends_on=[],
    )
    pin = GraphNode(
        id="fw.pin.user_btn",
        kind="firmware.pin_assignment",
        attrs={"gpio": 5, "net": "net.user_btn"},
        depends_on=["net.user_btn"],
    )
    graph = graph.model_copy(update={"nodes": [*graph.nodes, net, pin]})
    report = check_firmware_coverage(graph, _registry_document())
    assert report.status == "fail"
    assert _codes(report) == [("pin_role_unconsumed", "fw.pin.user_btn")]
    message = report.findings[0].message
    assert "'fw.pin.user_btn'" in message
    assert "'user_btn'" in message
    assert "registered:" in message
    assert "led2" in message
    assert "button" in message


def test_unregistered_action_fails_closed() -> None:
    graph = _replace_attrs(_graph(), "fw.sequence.003", action="self_destruct")
    report = check_firmware_coverage(graph, _registry_document())
    assert report.status == "fail"
    assert _codes(report) == [("action_unregistered", "fw.sequence.003")]
    assert "self_destruct" in report.findings[0].message
    assert "acd-firmware-capability-entry" in report.findings[0].message


def test_findings_order_is_deterministic() -> None:
    graph = _graph()
    net = GraphNode(
        id="net.user_btn",
        kind="electrical.net",
        attrs={
            "name": "USER_BTN",
            "width_basis": "manufacturing_minimum",
            "width_basis_source": "test coverage",
        },
        depends_on=[],
    )
    pin = GraphNode(
        id="fw.pin.user_btn",
        kind="firmware.pin_assignment",
        attrs={"gpio": 5, "net": "net.user_btn"},
        depends_on=["net.user_btn"],
    )
    mutated = _replace_attrs(
        _replace_attrs(graph, "comp.sw1", led_indicator=True),
        "fw.transition.report_measure",
        trigger="button_pressed",
    )
    mutated = mutated.model_copy(update={"nodes": [*mutated.nodes, net, pin]})
    first = check_firmware_coverage(mutated, _registry_document())
    second = check_firmware_coverage(mutated, _registry_document())
    assert first == second
    codes = _codes(first)
    assert codes == sorted(codes)


def test_dual_beacon_tag_spec_fails_closed(tmp_path: Path) -> None:
    spec = DesignFixtureSpec.model_validate_json(
        DUAL_BEACON_SPEC.read_text(encoding="utf-8")
    )
    graph = build_design_fixture(
        spec, tmp_path / "fixture", spec_dir=DUAL_BEACON_SPEC.parent
    )
    report = check_firmware_coverage(graph, _registry_document())
    assert report.status == "fail"
    assert _codes(report) == [
        ("led_indicator_untargeted", "comp.d2"),
        ("pin_role_unconsumed", "fw.pin.led_orange"),
        ("pin_role_unconsumed", "fw.pin.user_btn"),
        ("trigger_unemitted", "fw.transition.blink_paused"),
        ("trigger_unemitted", "fw.transition.paused_blink"),
    ]
    messages = [finding.message for finding in report.findings]
    assert any("'comp.d2'" in message and "toggle_led" in message for message in messages)
    assert any("'button_pressed'" in message for message in messages)


@pytest.mark.skipif(
    not Path("/usr/share/kicad/footprints/Capacitor_SMD.pretty").is_dir(),
    reason="pinned KiCad footprint library is not present in this environment",
)
def test_mini_blink_dongle_spec_passes_coverage(tmp_path: Path) -> None:
    spec_path = REPO_ROOT / "fixtures" / "mini-blink-dongle" / "spec.json"
    spec = DesignFixtureSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    graph = build_design_fixture(
        spec, tmp_path / "fixture", spec_dir=spec_path.parent
    )
    report = check_firmware_coverage(graph, _registry_document())
    assert report.status == "pass"


def test_report_serializes_to_dict() -> None:
    finding = FirmwareCoverageFinding(
        code="action_unregistered", node_id="fw.sequence.001", message="m"
    )
    report = FirmwareCoverageReport(status="fail", findings=(finding,))
    assert report.to_dict() == {
        "status": "fail",
        "findings": [
            {"code": "action_unregistered", "node_id": "fw.sequence.001", "message": "m"}
        ],
    }
