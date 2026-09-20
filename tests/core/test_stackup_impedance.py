from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from acd.core.electrical.electrical import GraphExtractionError, extract_electrical_lane
from acd.core.knowledge.design_predicates import PredicateResult, evaluate_design_predicates
from acd.schema import DesignGraph

FIXTURE = Path(__file__).parents[2] / "fixtures/stackup/four-layer/graph.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _results(graph: DesignGraph) -> dict[str, PredicateResult]:
    lane = extract_electrical_lane(graph)
    return {
        result.name: result
        for result in evaluate_design_predicates(graph, lane, FIXTURE.parent)
    }


def test_four_layer_fixture_passes_pair_and_impedance() -> None:
    results = _results(_graph())
    assert results["differential_pair"].status == "pass"
    assert results["impedance_geometry"].status == "pass"
    assert "89.517" in results["impedance_geometry"].detail


def test_wider_trace_fails_impedance() -> None:
    graph = _graph()
    nodes = [
        node.model_copy(
            update={
                "attrs": {
                    **node.attrs,
                    "impedance_trace_width_mm": 0.30,
                }
            }
        )
        if node.id == "net.usb_dp"
        else node
        for node in graph.nodes
    ]
    result = _results(graph.model_copy(update={"nodes": nodes}))["impedance_geometry"]
    assert result.status == "fail"


def test_missing_negative_net_fails_pair() -> None:
    graph = _graph()
    nodes = [node for node in graph.nodes if node.id != "net.usb_dn"]
    result = _results(graph.model_copy(update={"nodes": nodes}))["differential_pair"]
    assert result.status == "fail"


def test_missing_stackup_fails_impedance() -> None:
    graph = _graph()
    nodes = [node for node in graph.nodes if node.id != "stackup.four-layer"]
    result = _results(graph.model_copy(update={"nodes": nodes}))["impedance_geometry"]
    assert result.status == "fail"
    assert result.detail == "stackup not declared"


def test_non_adjacent_reference_layer_fails_impedance() -> None:
    graph = _graph()
    nodes = [
        node.model_copy(
            update={
                "attrs": {
                    **node.attrs,
                    "impedance_reference_layer": "In2.Cu",
                }
            }
        )
        if node.id == "net.usb_dp"
        else node
        for node in graph.nodes
    ]
    result = _results(graph.model_copy(update={"nodes": nodes}))["impedance_geometry"]
    assert result.status == "fail"


def test_invalid_stackup_layer_is_fail_closed() -> None:
    graph = _graph()
    stackup = next(node for node in graph.nodes if node.id == "stackup.four-layer")
    layers = list(cast(list[dict[str, object]], stackup.attrs["layers"]))
    assert isinstance(layers, list)
    layers[0] = {"name": "B.Cu", "kind": "signal", "thickness_mm": 0.035, "copper_um": 35}
    bad = stackup.model_copy(update={"attrs": {**stackup.attrs, "layers": layers}})
    with pytest.raises(GraphExtractionError):
        extract_electrical_lane(
            graph.model_copy(
                update={"nodes": [bad if node.id == bad.id else node for node in graph.nodes]}
            )
        )
