from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.check_defect_record import main

from acd.core.manufacturing.defect_records import (
    check_defect_records,
    compute_horizontal_scope,
    load_defect_document,
)
from acd.schema.design_graph import DesignGraph

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
DEFECT_PATH = ROOT / "fixtures/defect/sample/defects.json"


def _payload() -> dict[str, Any]:
    return json.loads(DEFECT_PATH.read_text(encoding="utf-8"))


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(GRAPH_PATH.read_text(encoding="utf-8"))


def test_sample_fixture_passes() -> None:
    graph = _graph()
    document = load_defect_document(DEFECT_PATH).document
    result = check_defect_records(graph, document)
    assert result.status == "pass"
    assert result.workaround_eligible == ["defect.r4-mpn"]
    assert result.blocked == []
    assert result.findings == []


def test_unsearched_scope_blocks_record(tmp_path: Path) -> None:
    payload = _payload()
    payload["records"][0]["horizontal_scopes"][0]["search_status"] = "unsearched"
    payload["records"][0]["horizontal_scopes"][0]["matched_node_ids"] = []
    path = tmp_path / "defects.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = check_defect_records(_graph(), load_defect_document(path).document)
    assert result.status == "fail"
    assert result.blocked == ["defect.r4-mpn"]
    assert any(item.code == "horizontal_unsearched" for item in result.findings)


def test_unknown_root_cause_blocks_record(tmp_path: Path) -> None:
    payload = _payload()
    candidate = payload["records"][0]["root_cause_candidates"][0]
    candidate.update(
        status="unknown",
        node_ids=[],
        confidence=None,
    )
    path = tmp_path / "defects.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = check_defect_records(_graph(), load_defect_document(path).document)
    assert result.status == "fail"
    assert any(item.code == "root_cause_unknown" for item in result.findings)


def test_unknown_node_blocks_record(tmp_path: Path) -> None:
    payload = _payload()
    candidate = payload["records"][0]["root_cause_candidates"][0]
    candidate["node_ids"] = ["comp.unknown"]
    path = tmp_path / "defects.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = check_defect_records(_graph(), load_defect_document(path).document)
    assert result.status == "fail"
    finding = next(item for item in result.findings if item.code == "unknown_node")
    assert finding.node_ids == ["comp.unknown"]


def test_missing_computed_node_is_incomplete(tmp_path: Path) -> None:
    payload = _payload()
    same_kind = next(
        scope
        for scope in payload["records"][0]["horizontal_scopes"]
        if scope["criterion"] == "same_node_kind"
    )
    same_kind["matched_node_ids"].remove("comp.c6")
    path = tmp_path / "defects.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = check_defect_records(_graph(), load_defect_document(path).document)
    assert result.status == "fail"
    finding = next(
        item for item in result.findings if item.code == "horizontal_incomplete"
    )
    assert finding.node_ids == ["comp.c6"]


def test_revision_mismatch_fails(tmp_path: Path) -> None:
    payload = _payload()
    payload["revision"] = "r2"
    path = tmp_path / "defects.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = check_defect_records(_graph(), load_defect_document(path).document)
    assert result.status == "fail"
    assert result.blocked == ["defect.r4-mpn"]
    assert any(item.code == "revision_mismatch" for item in result.findings)


def test_horizontal_scope_is_sorted_and_anchor_excluded() -> None:
    graph = _graph()
    document = load_defect_document(DEFECT_PATH).document
    record = document.records[0]
    assert compute_horizontal_scope(graph, record, "same_component_mpn") == ["comp.r5"]
    values = compute_horizontal_scope(graph, record, "same_node_kind")
    assert values == sorted(values)
    assert "comp.r4" not in values


def test_cli_exit_codes_and_outputs(tmp_path: Path) -> None:
    out_dir = tmp_path / "pass"
    assert (
        main(
            [
                "--graph",
                str(GRAPH_PATH),
                "--defects",
                str(DEFECT_PATH),
                "--out-dir",
                str(out_dir),
            ]
        )
        == 0
    )
    assert (out_dir / "defect-record-check.json").is_file()
    assert (out_dir / "gate-evidence/defect-record.json").is_file()

    payload = _payload()
    payload["revision"] = "r2"
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        main(
            [
                "--graph",
                str(GRAPH_PATH),
                "--defects",
                str(invalid),
                "--out-dir",
                str(tmp_path / "fail"),
            ]
        )
        == 1
    )
