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
    missing_declaration_action,
    missing_declarations,
    run_lane_preflight,
)
from acd.schema.design_graph import DesignGraph
from acd.schema.lane_preflight import LanePreflightReport

FIXTURE = Path("fixtures/golden-design-1/graph.json")


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _without_kind(graph: DesignGraph, kind: str) -> DesignGraph:
    return graph.model_copy(update={"nodes": [node for node in graph.nodes if node.kind != kind]})


def _without_attr(graph: DesignGraph, kind: str, attr: str) -> DesignGraph:
    nodes = [
        (
            node.model_copy(
                update={
                    "attrs": {name: value for name, value in node.attrs.items() if name != attr}
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
    report = run_lane_preflight(_without_kind(_graph(), "firmware.module"), ("firmware-pipeline",))
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


def test_partial_stitch_via_basis_is_reported_as_incomplete() -> None:
    graph = _graph()
    for attr in (
        "stitch_via_max_frequency_hz",
        "stitch_via_dielectric_constant",
        "stitch_via_wavelength_fraction",
        "stitch_via_basis_source",
    ):
        graph = _without_attr(graph, "electrical.board", attr)
    assert run_lane_preflight(graph, ("board-pipeline",)).status == "declarations_complete"
    partial = _without_attr(_graph(), "electrical.board", "stitch_via_dielectric_constant")
    report = run_lane_preflight(partial, ("board-pipeline",))
    assert report.status == "declarations_incomplete"
    assert {item.attr for item in report.lanes[0].missing_attrs} == {
        "stitch_via_dielectric_constant"
    }


def test_all_lane_gaps_are_collected_in_one_result() -> None:
    graph = _without_kind(_without_kind(_graph(), "firmware.module"), "mechanical.outline")
    report = run_lane_preflight(graph)
    incomplete = {lane.lane for lane in report.lanes if lane.status == "declarations_incomplete"}
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


def test_missing_declarations_name_spec_path_count_and_attrs() -> None:
    graph = _without_kind(_graph(), "mechanical.silk_text")
    report = run_lane_preflight(graph, ("silkscreen-resolve",))
    entries = missing_declarations(report)
    assert [entry.model_dump(mode="json") for entry in entries] == [
        {
            "lane": "silkscreen-resolve",
            "kind": "mechanical.silk_text",
            "spec_path": "silk_texts[].attrs",
            "required_count": 1,
            "present_count": 0,
            "missing_count": 1,
            "required_attrs": [
                "layer",
                "role",
                "text",
                "stroke_width_mm",
                "height_mm",
                "placement_basis",
                "placement_search_order",
                "placement_reference",
                "rotation_deg",
                "placement_offset_step_mm",
                "placement_search_limit_mm",
                "placement_safety_margin_mm",
                "board_edge_margin_mm",
                "board_edge_margin_source",
            ],
            "missing_attrs": [],
        }
    ]
    action = missing_declaration_action(report)
    assert action is not None
    assert "never auto-completed" in action
    assert "`silk_texts[].attrs`" in action
    for attr in (
        "layer",
        "role",
        "text",
        "stroke_width_mm",
        "height_mm",
        "placement_basis",
        "placement_search_order",
        "placement_reference",
    ):
        assert f"mechanical.silk_text.{attr}" in action


def test_missing_attr_declarations_list_existing_node_ids() -> None:
    graph = _without_attr(_graph(), "mechanical.silk_text", "placement_reference")
    report = run_lane_preflight(graph, ("silkscreen-resolve",))
    (entry,) = missing_declarations(report)
    assert entry.missing_count == 0
    assert entry.present_count is None
    assert {item.attr for item in entry.missing_attrs} == {"placement_reference"}
    action = missing_declaration_action(report)
    assert action is not None
    assert "add attrs [mechanical.silk_text.placement_reference]" in action


def test_complete_declarations_have_no_action() -> None:
    report = run_lane_preflight(_graph())
    assert missing_declarations(report) == []
    assert missing_declaration_action(report) is None


def _with_attr(graph: DesignGraph, kind: str, attr: str, value: object) -> DesignGraph:
    nodes = [
        (
            node.model_copy(update={"attrs": {**node.attrs, attr: value}})
            if node.kind == kind
            else node
        )
        for node in graph.nodes
    ]
    return graph.model_copy(update={"nodes": nodes})


def _unsupported_codes(report: LanePreflightReport) -> list[str]:
    return [item.code for lane in report.lanes for item in lane.unsupported_values]


def test_safety_boundary_duplicate_reports_missing_code() -> None:
    graph = _graph()
    boundary = next(node for node in graph.nodes if node.kind == "safety.boundary")
    duplicate = boundary.model_copy(update={"id": "safety.boundary-2"})
    graph = graph.model_copy(update={"nodes": [*graph.nodes, duplicate]})
    report = run_lane_preflight(graph, ("board-pipeline",))
    assert report.status == "declarations_incomplete"
    (finding,) = report.lanes[0].unsupported_values
    assert finding.code == "safety.boundary.missing"
    assert "exactly 1" in finding.reason


def test_safety_boundary_intended_use_unsupported() -> None:
    graph = _with_attr(_graph(), "safety.boundary", "intended_use", "product")
    report = run_lane_preflight(graph, ("board-pipeline",))
    assert report.status == "declarations_incomplete"
    finding = next(
        item
        for lane in report.lanes
        for item in lane.unsupported_values
        if item.code == "safety.boundary.intended_use_unsupported"
    )
    assert "author_prototype" in finding.reason
    action = missing_declaration_action(report)
    assert action is not None
    assert "safety.boundary.intended_use_unsupported" in action


def test_safety_boundary_module_certified_unsupported() -> None:
    graph = _with_attr(_graph(), "safety.boundary", "module_certified", "pending")
    report = run_lane_preflight(graph, ("board-pipeline",))
    assert "safety.boundary.module_certified_unsupported" in _unsupported_codes(report)
    finding = next(
        item
        for lane in report.lanes
        for item in lane.unsupported_values
        if item.code == "safety.boundary.module_certified_unsupported"
    )
    assert "certified" in finding.reason


def test_safety_boundary_hazard_flag_non_bool_is_invalid() -> None:
    graph = _with_attr(_graph(), "safety.boundary", "battery", "no")
    report = run_lane_preflight(graph, ("board-pipeline",))
    finding = next(
        item
        for lane in report.lanes
        for item in lane.unsupported_values
        if item.code == "safety.boundary.hazard_flag_invalid"
    )
    assert finding.attr == "battery"
    assert "boolean" in finding.reason


def test_safety_boundary_hazard_flag_missing_is_invalid() -> None:
    graph = _without_attr(_graph(), "safety.boundary", "charger")
    report = run_lane_preflight(graph, ("board-pipeline",))
    finding = next(
        item
        for lane in report.lanes
        for item in lane.unsupported_values
        if item.code == "safety.boundary.hazard_flag_invalid"
    )
    assert finding.attr == "charger"


def test_net_width_basis_unsupported() -> None:
    graph = _with_attr(_graph(), "electrical.net", "width_basis", "hand_wavy")
    report = run_lane_preflight(graph, ("board-pipeline",))
    findings = [
        item
        for lane in report.lanes
        for item in lane.unsupported_values
        if item.code == "net.width_basis_unsupported"
    ]
    assert findings
    assert all(
        "current_ipc2221" in finding.reason and "manufacturing_minimum" in finding.reason
        for finding in findings
    )


def test_missing_safety_boundary_reports_missing_code_and_node() -> None:
    graph = _without_kind(_graph(), "safety.boundary")
    report = run_lane_preflight(graph, ("board-pipeline",))
    assert report.status == "declarations_incomplete"
    assert "safety.boundary.missing" in _unsupported_codes(report)
    assert any(
        item.kind == "safety.boundary" for item in report.lanes[0].missing_nodes
    )
    entries = missing_declarations(report)
    assert any(
        entry.kind == "safety.boundary" and entry.spec_path == "safety_boundary.attrs"
        for entry in entries
    )
