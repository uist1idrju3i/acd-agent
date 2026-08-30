"""Tests for the diagnostic lane preflight over declared graphs."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from acd.core.lane_preflight import (
    LANE_IDS,
    PREFLIGHT_CHECKED_PREDICATES,
    PREFLIGHT_UNCHECKED_PREDICATES,
    run_lane_preflight,
)
from acd.schema.design_graph import DesignGraph

FIXTURE = Path("fixtures/golden-design-1/graph.json")


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _without_kind(graph: DesignGraph, kind: str) -> DesignGraph:
    return graph.model_copy(
        update={"nodes": [node for node in graph.nodes if node.kind != kind]}
    )


def _without_attr(graph: DesignGraph, kind: str, attr: str) -> DesignGraph:
    nodes = [
        (
            node.model_copy(
                update={
                    "attrs": {
                        name: value
                        for name, value in node.attrs.items()
                        if name != attr
                    }
                }
            )
            if node.kind == kind
            else node
        )
        for node in graph.nodes
    ]
    return graph.model_copy(update={"nodes": nodes})


def test_declared_gd1_graph_has_complete_declarations_for_every_lane() -> None:
    report = run_lane_preflight(_graph())
    assert report.status == "declarations_complete"
    assert report.diagnostic_only is True
    assert report.record_class == "L3"
    assert report.checked_predicates == list(PREFLIGHT_CHECKED_PREDICATES)
    assert report.unchecked_predicates == list(PREFLIGHT_UNCHECKED_PREDICATES)
    assert tuple(lane.lane for lane in report.lanes) == LANE_IDS


def test_missing_required_node_is_reported_as_incomplete() -> None:
    report = run_lane_preflight(
        _without_kind(_graph(), "firmware.module"), ("firmware-pipeline",)
    )
    assert report.status == "declarations_incomplete"
    lane = report.lanes[0]
    assert lane.status == "declarations_incomplete"
    assert [item.kind for item in lane.missing_nodes] == ["firmware.module"]
    assert lane.missing_nodes[0].present_count == 0


def test_missing_required_attribute_is_reported_as_incomplete() -> None:
    report = run_lane_preflight(
        _without_attr(_graph(), "mechanical.silk_text", "placement_basis"),
        ("silkscreen-resolve",),
    )
    assert report.status == "declarations_incomplete"
    missing = report.lanes[0].missing_attrs
    assert missing
    assert {item.attr for item in missing} == {"placement_basis"}


def test_all_lane_gaps_are_collected_in_one_result() -> None:
    graph = _without_kind(
        _without_kind(_graph(), "firmware.module"), "mechanical.outline"
    )
    report = run_lane_preflight(graph)
    incomplete = {
        lane.lane
        for lane in report.lanes
        if lane.status == "declarations_incomplete"
    }
    assert incomplete == {"enclosure-pipeline", "firmware-pipeline"}


def test_unknown_lane_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown preflight lanes"):
        run_lane_preflight(_graph(), ("no-such-lane",))


def test_preflight_report_is_serializable_and_deterministic() -> None:
    first = run_lane_preflight(_graph()).model_dump(mode="json")
    second = run_lane_preflight(_graph()).model_dump(mode="json")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_preflight_predicate_documentation_matches_contract() -> None:
    documentation = Path("docs/operations.md").read_text(encoding="utf-8")
    rows = re.findall(
        r"^\s*\| `([^`]+)` \| (checked|unchecked) \|",
        documentation,
        flags=re.MULTILINE,
    )
    checked = tuple(predicate for predicate, kind in rows if kind == "checked")
    unchecked = tuple(predicate for predicate, kind in rows if kind == "unchecked")
    assert checked == PREFLIGHT_CHECKED_PREDICATES
    assert unchecked == PREFLIGHT_UNCHECKED_PREDICATES
