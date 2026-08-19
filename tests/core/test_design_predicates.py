"""GD1 deterministic design predicate tests."""

from __future__ import annotations

import json
from pathlib import Path

from acd.core.design_predicates import (
    evaluate_gd1_predicates,
    evaluate_power_boundary,
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


def test_gd1_predicates_pass_on_fixture() -> None:
    graph = _graph()
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
