"""GD1 deterministic design predicate tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.design_predicates import (
    evaluate_gd1_predicates,
    evaluate_i2c_pullup,
    evaluate_pin_firmware_alignment,
    evaluate_power_boundary,
    evaluate_power_decoupling,
    evaluate_strapping_pin,
    evaluate_usb_cc,
)
from acd.core.electrical import extract_electrical_lane
from acd.schema import DesignGraph

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "fixtures" / "golden-design-1"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(
        json.loads((FIXTURE_DIR / "graph.json").read_text(encoding="utf-8"))
    )


def _update_node_attrs(graph: DesignGraph, node_id: str, **updates: object) -> DesignGraph:
    return graph.model_copy(
        update={
            "nodes": [
                node.model_copy(update={"attrs": {**node.attrs, **updates}})
                if node.id == node_id
                else node
                for node in graph.nodes
            ]
        }
    )


def _skip_if_gd1_geometry_library_is_missing(graph: DesignGraph) -> None:
    lane = extract_electrical_lane(graph)
    required_refs = {"C3", "C4", "C5", "U1", "U2", "U3"}
    for component in lane.components:
        if component.refdes not in required_refs:
            continue
        path = Path(component.library.footprint_file)
        if not path.is_absolute():
            path = FIXTURE_DIR / path
        if not path.is_file():
            pytest.skip(f"pinned KiCad library not present in this environment: {path}")


def test_gd1_predicates_pass_on_fixture() -> None:
    graph = _graph()
    _skip_if_gd1_geometry_library_is_missing(graph)
    lane = extract_electrical_lane(graph)
    results = evaluate_gd1_predicates(graph, lane, FIXTURE_DIR)
    assert [result.name for result in results] == [
        "usb_cc",
        "i2c_pullup",
        "strapping_pin",
        "pin_firmware_alignment",
        "power_decoupling",
        "power_boundary",
    ]
    assert [result.status for result in results] == [
        "pass",
        "pass",
        "pass",
        "pass",
        "pass",
        "pass",
    ]


def test_missing_cc_net_is_unknown() -> None:
    graph = _graph()
    graph = graph.model_copy(
        update={
            "nodes": [
                node.model_copy(update={"attrs": {**node.attrs, "name": "MISSING"}})
                if node.kind == "electrical.net" and node.attrs.get("name") == "CC1"
                else node
                for node in graph.nodes
            ]
        }
    )
    lane = extract_electrical_lane(graph)
    assert evaluate_usb_cc(graph, lane).status == "unknown"


def test_missing_safety_boundary_is_unknown() -> None:
    graph = _graph().model_copy(
        update={"nodes": [node for node in _graph().nodes if node.kind != "safety.boundary"]}
    )
    lane = extract_electrical_lane(graph)
    assert evaluate_power_boundary(graph, lane).status == "unknown"


def test_usb_cc_wrong_resistor_value_fails() -> None:
    graph = _update_node_attrs(_graph(), "comp.r1", value="1k")
    lane = extract_electrical_lane(graph)
    assert evaluate_usb_cc(graph, lane).status == "fail"


def test_i2c_pullup_wrong_resistor_value_fails() -> None:
    graph = _update_node_attrs(_graph(), "comp.r4", value="1k")
    lane = extract_electrical_lane(graph)
    assert evaluate_i2c_pullup(graph, lane).status == "fail"


def test_strapping_led_connection_fails() -> None:
    graph = _update_node_attrs(_graph(), "pin.u1.23", net="net.led", no_connect=False)
    lane = extract_electrical_lane(graph)
    assert evaluate_strapping_pin(graph, lane).status == "fail"


def test_pin_firmware_alignment_wrong_net_fails() -> None:
    graph = _update_node_attrs(_graph(), "fw.pin.i2c_sda", net="net.led")
    lane = extract_electrical_lane(graph)
    assert evaluate_pin_firmware_alignment(graph, lane).status == "fail"


def test_power_decoupling_distant_capacitor_fails() -> None:
    graph = _graph()
    _skip_if_gd1_geometry_library_is_missing(graph)
    graph = _update_node_attrs(
        graph,
        "comp.c4",
        placement_x_mm=100.0,
        placement_y_mm=100.0,
    )
    lane = extract_electrical_lane(graph)
    assert evaluate_power_decoupling(graph, lane, FIXTURE_DIR).status == "fail"


def test_power_boundary_unknown_certification_fails_closed() -> None:
    graph = _update_node_attrs(_graph(), "sb.gd1", module_certified="unknown")
    lane = extract_electrical_lane(graph)
    assert evaluate_power_boundary(graph, lane).status == "unknown"
