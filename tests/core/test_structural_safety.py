"""Structural-safety predicate regression tests."""

from __future__ import annotations

import json
from pathlib import Path

from acd.core.electrical.electrical import extract_electrical_lane
from acd.core.mechanical.structural_safety import (
    evaluate_protection_selectivity,
    evaluate_signal_class_segregation,
    evaluate_single_point_of_failure,
    evaluate_sneak_path,
    evaluate_trapezoid_current_capacity,
)
from acd.schema import DesignGraph
from acd.schema.design_graph import GraphNode

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "fixtures" / "golden-design-1"
STRUCTURAL_FIXTURE_DIR = ROOT / "fixtures" / "structural-safety"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(
        json.loads((FIXTURE_DIR / "graph.json").read_text(encoding="utf-8"))
    )


def _structural_graph() -> DesignGraph:
    return DesignGraph.model_validate(
        json.loads(
            (STRUCTURAL_FIXTURE_DIR / "graph.json").read_text(encoding="utf-8")
        )
    )


def _update(graph: DesignGraph, node_id: str, **attrs: object) -> DesignGraph:
    return graph.model_copy(
        update={
            "nodes": [
                node.model_copy(update={"attrs": {**node.attrs, **attrs}})
                if node.id == node_id
                else node
                for node in graph.nodes
            ]
        }
    )


def _append(graph: DesignGraph, *nodes: GraphNode) -> DesignGraph:
    return graph.model_copy(update={"nodes": [*graph.nodes, *nodes]})


def test_single_point_of_failure_rejects_shared_connector() -> None:
    graph = _append(
        _graph(),
        GraphNode(
            id="safety.group",
            kind="safety.redundant_group",
            attrs={
                "members": ["net.usb_dp", "net.usb_dn"],
                "resources_shared_forbidden": ["connector"],
            },
        ),
    )
    result = evaluate_single_point_of_failure(graph, extract_electrical_lane(graph))
    assert result.status == "fail"
    assert "connector" in result.detail


def test_protection_selectivity_rejects_nonselective_downstream_trip() -> None:
    graph = _append(
        _graph(),
        GraphNode(
            id="comp.f1",
            kind="electrical.component",
            attrs={
                "refdes": "F1",
                "protection_role": "fuse",
                "trip_current_a": 1.0,
                "power_output_net": "net.p3v3",
            },
        ),
        GraphNode(
            id="comp.f2",
            kind="electrical.component",
            attrs={
                "refdes": "F2",
                "protection_role": "fuse",
                "trip_current_a": 1.0,
                "power_input_net": "net.p3v3",
            },
        ),
    )
    result = evaluate_protection_selectivity(graph, extract_electrical_lane(_graph()))
    assert result.status == "fail"
    assert "not below" in result.detail


def test_protection_selectivity_missing_trip_current_is_unknown() -> None:
    graph = _append(
        _graph(),
        GraphNode(
            id="comp.f1",
            kind="electrical.component",
            attrs={"refdes": "F1", "protection_role": "fuse"},
        ),
    )
    result = evaluate_protection_selectivity(graph, extract_electrical_lane(_graph()))
    assert result.status == "unknown"
    assert "trip_current_a" in result.detail


def test_signal_class_segregation_rejects_mains_and_selv_connector() -> None:
    graph = _update(
        _update(_graph(), "net.vbus_5v", signal_class="mains"),
        "net.gnd",
        signal_class="safety_extra_low_voltage",
    )
    result = evaluate_signal_class_segregation(graph, extract_electrical_lane(graph))
    assert result.status == "fail"
    assert "mains" in result.detail


def test_sneak_path_rejects_undeclared_passive_bridge() -> None:
    graph = _update(_graph(), "net.led", critical=True)
    result = evaluate_sneak_path(graph, extract_electrical_lane(graph))
    assert result.status == "fail"
    assert "intended_coupling" in result.detail


def test_trapezoid_current_capacity_rejects_thin_trace() -> None:
    graph = _update(
        _update(
            _update(
                _update(_graph(), "net.vbus_5v", min_trace_width_mm=0.1),
                "net.vbus_5v",
                max_temperature_rise_c=10.0,
            ),
            "board.gd1",
            copper_um=35,
            etch_factor=0.1,
        ),
        "net.vbus_5v",
        routing_layer="F.Cu",
    )
    result = evaluate_trapezoid_current_capacity(graph, extract_electrical_lane(graph))
    assert result.status == "fail"
    assert result.measurements


def test_trapezoid_current_capacity_missing_etch_factor_is_unknown() -> None:
    graph = _update(
        _update(_graph(), "net.vbus_5v", min_trace_width_mm=0.5),
        "net.vbus_5v",
        max_temperature_rise_c=10.0,
    )
    result = evaluate_trapezoid_current_capacity(graph, extract_electrical_lane(graph))
    assert result.status == "unknown"


def test_structural_safety_fixture_has_passing_new_predicates() -> None:
    graph = _structural_graph()
    lane = extract_electrical_lane(graph)
    results = {
        result.name: result
        for result in (
            evaluate_single_point_of_failure(graph, lane),
            evaluate_protection_selectivity(graph, lane),
            evaluate_signal_class_segregation(graph, lane),
            evaluate_sneak_path(graph, lane),
            evaluate_trapezoid_current_capacity(graph, lane),
        )
    }
    assert {name for name, result in results.items() if result.status == "pass"} == {
        "single_point_of_failure",
        "protection_selectivity",
        "signal_class_segregation",
        "sneak_path",
        "trapezoid_current_capacity",
    }
