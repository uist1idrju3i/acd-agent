"""GD1 deterministic design predicate tests."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from acd.adapters.kicad.library import FootprintLibrary
from acd.core.design_predicates import (
    PREDICATE_CATALOG,
    PREDICATE_EVALUATION_STAGE,
    _component_pad_positions,
    _minimum_pad_pair,
    evaluate_design_predicates,
    evaluate_i2c_pullup,
    evaluate_led_series_element,
    evaluate_pin_firmware_alignment,
    evaluate_power_boundary,
    evaluate_power_decoupling,
    evaluate_strapping_pin,
    evaluate_usb_cc,
    validate_predicate_stage_coverage,
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
    results = evaluate_design_predicates(graph, lane, FIXTURE_DIR)
    assert [result.name for result in results] == [
        "usb_cc",
        "i2c_pullup",
        "strapping_pin",
        "pin_firmware_alignment",
        "power_decoupling",
        "power_boundary",
        "led_series_element",
    ]
    assert [result.status for result in results] == [
        "pass",
        "pass",
        "pass",
        "pass",
        "pass",
        "pass",
        "not_applicable",
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


def test_power_decoupling_failure_has_structured_measurement_and_remediation() -> None:
    graph = _graph()
    _skip_if_gd1_geometry_library_is_missing(graph)
    graph = _update_node_attrs(graph, "comp.c5", placement_x_mm=19.516)
    lane = extract_electrical_lane(graph)
    result = next(
        item
        for item in evaluate_design_predicates(graph, lane, FIXTURE_DIR)
        if item.name == "power_decoupling"
    )
    assert result.status == "fail"
    assert result.detail == "C5 distance 3.319 mm exceeds 3.0 mm"
    assert len(result.measurements) == 1
    measurement = result.measurements[0]
    assert measurement.measured == pytest.approx(3.319, abs=0.0005)
    assert measurement.limit == 3.0
    assert measurement.quantity == "pad_distance_mm"
    assert measurement.comparison == "<="
    assert measurement.unit == "mm"
    assert measurement.margin == pytest.approx(-0.319, abs=0.0005)
    assert measurement.excess == pytest.approx(0.319, abs=0.0005)
    assert measurement.subject is not None
    assert measurement.subject.refdes == "C5"
    assert measurement.subject.target_refdes == "U3"
    assert measurement.subject.net == "+3V3"
    assert result.remediation is not None
    assert result.remediation.change_dimensions == ("component_placement_xy",)
    assert result.remediation.dimensions_source == "registry"
    assert result.remediation.source_block_ids == ("single_ldo_power_tree",)
    assert result.remediation.margin == pytest.approx(-0.319, abs=0.0005)
    assert result.remediation.excess == pytest.approx(0.319, abs=0.0005)
    assert result.remediation.message == (
        "move C5 within 3.000 mm of U3; measured 3.319 mm, exceeds by 0.319 mm"
    )


def test_power_decoupling_pad_pair_preserves_duplicate_shape_pad_numbers() -> None:
    graph = _graph()
    _skip_if_gd1_geometry_library_is_missing(graph)
    lane = extract_electrical_lane(graph)
    capacitor = next(component for component in lane.components if component.refdes == "C3")
    target = next(component for component in lane.components if component.refdes == "U2")
    net_id = next(
        pin.net_id
        for pin in lane.pins_of_component(capacitor.node_id)
        if pin.net_id is not None
    )
    library = FootprintLibrary()
    capacitor_entries = _component_pad_positions(
        graph, lane, capacitor, net_id, FIXTURE_DIR, library
    )
    target_entries = _component_pad_positions(graph, lane, target, net_id, FIXTURE_DIR, library)
    assert [pad for pad, _ in target_entries] == ["2", "2"]
    expected = min(
        (
            math.dist(cap_position, target_position),
            cap_pad,
            target_pad,
        )
        for cap_pad, cap_position in capacitor_entries
        for target_pad, target_position in target_entries
    )
    assert _minimum_pad_pair(graph, lane, capacitor, target, net_id, FIXTURE_DIR) == expected


def test_predicate_evaluation_stage_catalog_is_complete_and_fail_closed() -> None:
    validate_predicate_stage_coverage(PREDICATE_CATALOG, PREDICATE_EVALUATION_STAGE)
    with pytest.raises(ValueError, match="missing evaluation stage"):
        validate_predicate_stage_coverage(PREDICATE_CATALOG, {})
    with pytest.raises(ValueError, match="unknown predicates"):
        validate_predicate_stage_coverage(
            PREDICATE_CATALOG,
            {**PREDICATE_EVALUATION_STAGE, "unknown": "pre_router"},
        )
    with pytest.raises(ValueError, match="invalid"):
        validate_predicate_stage_coverage(
            PREDICATE_CATALOG,
            {**PREDICATE_EVALUATION_STAGE, "usb_cc": "during_router"},
        )


def test_power_boundary_unknown_certification_fails_closed() -> None:
    graph = _update_node_attrs(_graph(), "sb.gd1", module_certified="unknown")
    lane = extract_electrical_lane(graph)
    assert evaluate_power_boundary(graph, lane).status == "unknown"


def _drop_nodes(graph: DesignGraph, node_ids: set[str]) -> DesignGraph:
    return graph.model_copy(
        update={"nodes": [node for node in graph.nodes if node.id not in node_ids]}
    )


def _led_declared_graph() -> DesignGraph:
    return _update_node_attrs(
        _graph(),
        "comp.d1",
        led_indicator=True,
        led_drive_net="net.led",
        led_series_net="net.led_a",
    )


def test_led_series_element_accepts_the_declared_gd1_topology() -> None:
    graph = _led_declared_graph()
    lane = extract_electrical_lane(graph)
    result = evaluate_led_series_element(graph, lane)
    assert result.status == "pass"
    assert [subject.refdes for subject in result.subjects] == ["R6"]


def test_led_series_element_is_unknown_without_declarations() -> None:
    graph = _graph()
    lane = extract_electrical_lane(graph)
    assert evaluate_led_series_element(graph, lane).status == "unknown"


def test_led_series_element_is_unknown_for_partial_declarations() -> None:
    graph = _update_node_attrs(_graph(), "comp.d1", led_indicator=True)
    lane = extract_electrical_lane(graph)
    assert evaluate_led_series_element(graph, lane).status == "unknown"


def test_led_series_element_rejects_a_missing_series_element() -> None:
    graph = _drop_nodes(_led_declared_graph(), {"comp.r6", "pin.r6.1", "pin.r6.2"})
    lane = extract_electrical_lane(graph)
    result = evaluate_led_series_element(graph, lane)
    assert result.status == "fail"
    assert "0 series elements" in result.detail


def test_led_series_element_rejects_a_direct_drive_connection() -> None:
    graph = _update_node_attrs(
        _led_declared_graph(), "comp.d1", led_series_net="net.led"
    )
    graph = graph.model_copy(
        update={
            "nodes": [
                node.model_copy(update={"attrs": {**node.attrs, "net": "net.led"}})
                if node.id == "pin.d1.2"
                else node
                for node in graph.nodes
            ]
        }
    )
    lane = extract_electrical_lane(graph)
    result = evaluate_led_series_element(graph, lane)
    assert result.status == "fail"
