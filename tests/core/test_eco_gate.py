"""Deterministic ECO close-gate tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from scripts.check_eco import main

ROOT = Path(__file__).resolve().parents[2]
ECO = ROOT / "fixtures/eco/sample/eco.json"
FROM_GRAPH = ROOT / "fixtures/golden-design-1/graph.json"
TO_GRAPH = ROOT / "fixtures/eco/sample/graph-r2.json"
DEFECTS = ROOT / "fixtures/defect/sample/defects.json"
EVIDENCE = ROOT / "fixtures/eco/sample/evidence"


def _args(out: Path, *, eco: Path = ECO, evidence: Path = EVIDENCE) -> list[str]:
    return [
        "--eco",
        str(eco),
        "--eco-id",
        "ECO-001",
        "--from-graph",
        str(FROM_GRAPH),
        "--to-graph",
        str(TO_GRAPH),
        "--defects",
        str(DEFECTS),
        "--evidence-dir",
        str(evidence),
        "--out-dir",
        str(out),
    ]


def _eco_record() -> dict[str, Any]:
    body = cast(dict[str, Any], json.loads(ECO.read_text(encoding="utf-8")))
    records: list[Any] = body["ecos"]
    assert isinstance(records, list)
    assert isinstance(records[0], dict)
    return cast(dict[str, Any], records[0])


def _write_eco(tmp_path: Path, record: dict[str, Any]) -> Path:
    path = tmp_path / "eco.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "artifact_kind": "eco_document",
                "ecos": [record],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_defects(tmp_path: Path, mutate: Any) -> Path:
    body = json.loads(DEFECTS.read_text(encoding="utf-8"))
    mutate(body)
    path = tmp_path / "defects.json"
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def test_sample_eco_is_closable(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert main(_args(out)) == 0
    result = json.loads((out / "eco-check.json").read_text(encoding="utf-8"))
    assert result["verdict"] == "closable"
    assert result["retires_workaround_ids"] == ["WA-001"]


def test_omitted_changed_node_is_mismatched(tmp_path: Path) -> None:
    record = _eco_record()
    record["impact"]["nodes_changed"] = []
    eco = _write_eco(tmp_path, record)
    out = tmp_path / "out"
    assert main(_args(out, eco=eco)) == 1
    result = json.loads((out / "eco-check.json").read_text(encoding="utf-8"))
    assert result["impact_status"] == "mismatched"


def test_revision_mismatched_evidence_is_unknown(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for source in EVIDENCE.glob("*.json"):
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["target_revision"] = "r1"
        (evidence / source.name).write_text(
            json.dumps(payload) + "\n", encoding="utf-8"
        )
    out = tmp_path / "out"
    assert main(_args(out, evidence=evidence)) == 1
    result = json.loads((out / "eco-check.json").read_text(encoding="utf-8"))
    assert result["gate_runs"][0]["status"] == "unknown"


def test_missing_drc_evidence_is_not_closable(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for source in EVIDENCE.glob("*.json"):
        if source.name != "drc.json":
            (evidence / source.name).write_text(
                source.read_text(encoding="utf-8"), encoding="utf-8"
            )
    out = tmp_path / "out"
    assert main(_args(out, evidence=evidence)) == 1
    result = json.loads((out / "eco-check.json").read_text(encoding="utf-8"))
    drc = next(run for run in result["gate_runs"] if run["gate"] == "drc")
    assert drc["status"] == "unknown"


def test_missing_horizontal_disposition_is_incomplete(tmp_path: Path) -> None:
    record = _eco_record()
    record["horizontal_dispositions"].pop()
    eco = _write_eco(tmp_path, record)
    out = tmp_path / "out"
    assert main(_args(out, eco=eco)) == 1
    result = json.loads((out / "eco-check.json").read_text(encoding="utf-8"))
    assert result["horizontal_status"] == "incomplete"


def test_fixed_node_outside_impact_is_rejected(tmp_path: Path) -> None:
    record = _eco_record()
    record["horizontal_dispositions"][0]["disposition"] = "fixed_in_eco"
    eco = _write_eco(tmp_path, record)
    out = tmp_path / "out"
    assert main(_args(out, eco=eco)) == 1
    result = json.loads((out / "eco-check.json").read_text(encoding="utf-8"))
    assert any("outside ECO impact" in reason for reason in result["reasons"])


def test_unsearched_horizontal_scope_is_unknown(tmp_path: Path) -> None:
    def mutate(body: dict[str, Any]) -> None:
        record = body["records"][0]
        for scope in record["horizontal_scopes"]:
            if scope["criterion"] == "same_profile":
                scope["search_status"] = "unsearched"
                scope["matched_node_ids"] = []
                scope["excluded"] = []

    defects = _write_defects(tmp_path, mutate)
    out = tmp_path / "out"
    arguments = _args(out)
    arguments[arguments.index("--defects") + 1] = str(defects)
    assert main(arguments) == 1
    result = json.loads((out / "eco-check.json").read_text(encoding="utf-8"))
    assert result["horizontal_status"] == "unknown"
