"""DFA review Skill and contract tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from acd.schema.design_graph import DesignGraph
from acd.schema.dfa_review import DfaReviewReport
from dfa_review import load_graph, main, review_dfa

REPOSITORY = Path(__file__).resolve().parents[5]
GRAPH_PATH = REPOSITORY / "fixtures" / "golden-design-1" / "graph.json"


def _payload() -> dict[str, Any]:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def _graph(payload: dict[str, Any]) -> DesignGraph:
    return DesignGraph.model_validate(payload)


def test_gd1_report_covers_all_aspects_and_is_l2() -> None:
    report = review_dfa(load_graph(GRAPH_PATH))
    assert report.record_class == "L2"
    assert report.pass_evidence is False
    assert {
        finding.aspect for finding in report.findings
    } == {
        "orientation_uniformity",
        "single_side_assembly",
        "hand_solder_access",
        "connector_cable_order",
        "enclosure_assembly_effort",
        "fixture_required",
    }
    assert all(finding.severity != "stop_recommendation" for finding in report.findings)
    assert all(
        finding.unknown_reason is not None
        for finding in report.findings
        if finding.status == "unknown"
    )


def test_rotation_change_is_an_orientation_advisory() -> None:
    payload = _payload()
    for node in payload["nodes"]:
        if node["id"] == "comp.u1":
            node["attrs"]["placement_rotation_deg"] = 45.0
    report = review_dfa(_graph(payload))
    finding = next(
        item for item in report.findings if item.aspect == "orientation_uniformity"
    )
    assert finding.severity == "advisory"
    assert "comp.u1" in finding.subject_node_ids


def test_missing_connector_opening_is_advisory() -> None:
    payload = _payload()
    payload["nodes"] = [
        node
        for node in payload["nodes"]
        if node["id"] != "mechanical.connector_opening.j1"
    ]
    for node in payload["nodes"]:
        if node["id"] == "mechanical.enclosure.gd1":
            node["depends_on"] = [
                dependency
                for dependency in node["depends_on"]
                if dependency != "mechanical.connector_opening.j1"
            ]
    report = review_dfa(_graph(payload))
    finding = next(
        item for item in report.findings if item.aspect == "connector_cable_order"
    )
    assert finding.severity == "advisory"
    assert "comp.j1" in finding.subject_node_ids


def test_missing_connector_reference_is_stop_recommendation() -> None:
    payload = _payload()
    for node in payload["nodes"]:
        if node["id"] == "mechanical.connector_opening.j1":
            node["attrs"]["component_id"] = "comp.missing"
    report = review_dfa(_graph(payload))
    finding = next(
        item for item in report.findings if item.aspect == "connector_cable_order"
    )
    assert finding.severity == "stop_recommendation"
    assert "comp.missing" in finding.basis


def test_missing_assembly_attributes_are_unknown_for_hand_solder() -> None:
    payload = _payload()
    for node in payload["nodes"]:
        if node["kind"] == "electrical.component":
            node["attrs"].pop("assembly", None)
    report = review_dfa(_graph(payload))
    finding = next(
        item for item in report.findings if item.aspect == "hand_solder_access"
    )
    assert finding.status == "unknown"
    assert finding.unknown_reason == "component assembly method is not declared"


def test_hand_solder_clearance_below_rule_is_advisory() -> None:
    payload = _payload()
    for node in payload["nodes"]:
        if node["id"] == "comp.u1":
            node["attrs"]["assembly"] = "tht"
        if node["id"] == "comp.j1":
            node["attrs"]["placement_x_mm"] = 15.0
            node["attrs"]["placement_y_mm"] = 13.0
    report = review_dfa(_graph(payload))
    finding = next(
        item for item in report.findings if item.aspect == "hand_solder_access"
    )
    assert finding.severity == "advisory"
    assert "comp.u1" in finding.subject_node_ids


def test_cli_is_deterministic_and_writes_json_and_markdown(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert main(["--graph", str(GRAPH_PATH), "--out", str(first)]) == 0
    assert main(["--graph", str(GRAPH_PATH), "--out", str(second)]) == 0
    assert (first / "dfa-review.json").read_bytes() == (
        second / "dfa-review.json"
    ).read_bytes()
    assert (first / "dfa-review.md").read_bytes() == (second / "dfa-review.md").read_bytes()
    DfaReviewReport.model_validate(
        json.loads((first / "dfa-review.json").read_text(encoding="utf-8"))
    )


def test_malformed_graph_fails_without_output(tmp_path: Path) -> None:
    graph = tmp_path / "bad.json"
    graph.write_text("{not-json", encoding="utf-8")
    out = tmp_path / "out"
    assert main(["--graph", str(graph), "--out", str(out)]) == 1
    assert not out.exists()
