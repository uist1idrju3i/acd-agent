from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import acd.core.salvage_gate as salvage_gate
import workaround
from acd.core.design_predicates import PredicateResult
from check_workaround import main as check_workaround_main

ROOT = Path(__file__).resolve().parents[5]
GRAPH = ROOT / "fixtures/golden-design-1/graph.json"
DEFECTS = ROOT / "fixtures/defect/sample/defects.json"
REWORK = ROOT / "fixtures/rework/sample/rework.json"
DFA = ROOT / "fixtures/rework/sample/rework-dfa.json"
FIXTURE_DIR = ROOT / "fixtures/golden-design-1"
SAMPLE = ROOT / "fixtures/rework/sample"


def _proposal(tmp_path: Path, graph_path: Path = GRAPH) -> Path:
    proposal = workaround.build_proposal(graph_path, DEFECTS, "defect.r4-mpn")
    path = tmp_path / "workaround-candidates.json"
    workaround.write_json(path, proposal.model_dump(mode="json"))
    return path


def _graph_with_missing_footprint(tmp_path: Path) -> Path:
    payload = json.loads(GRAPH.read_text(encoding="utf-8"))
    component = next(
        node
        for node in payload["nodes"]
        if node["kind"] == "electrical.component"
        and node["id"] == "comp.c3"
    )
    component["attrs"]["footprint_file"] = "/definitely/missing/decoupling.kicad_mod"
    path = tmp_path / "graph-missing-footprint.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_sample_proposal_has_three_strategies_and_replace_template(tmp_path: Path) -> None:
    proposal = workaround.build_proposal(GRAPH, DEFECTS, "defect.r4-mpn")
    assert [candidate.strategy for candidate in proposal.candidates] == [
        "rework_only",
        "firmware_only",
        "combined",
    ]
    candidate = proposal.candidates[0]
    assert candidate.status == "proposed"
    assert candidate.anchor_node_ids == ["comp.r4"]
    assert candidate.rework_template is not None
    assert candidate.rework_template.operations[0].op == "replace"
    assert candidate.rework_template.operations[0].component_id == "comp.r4"
    first = json.dumps(proposal.model_dump(mode="json"), sort_keys=True)
    second = json.dumps(
        workaround.build_proposal(GRAPH, DEFECTS, "defect.r4-mpn").model_dump(mode="json"),
        sort_keys=True,
    )
    assert first == second
    assert proposal.provenance.script_sha256 == (
        "sha256:" + hashlib.sha256(Path(workaround.__file__).read_bytes()).hexdigest()
    )


def test_blocked_defect_emits_no_candidates(tmp_path: Path) -> None:
    payload = json.loads(DEFECTS.read_text(encoding="utf-8"))
    payload["records"][0]["root_cause_candidates"][0]["status"] = "unknown"
    payload["records"][0]["root_cause_candidates"][0].pop("node_ids")
    payload["records"][0]["root_cause_candidates"][0].pop("confidence")
    defects = tmp_path / "blocked.json"
    defects.write_text(json.dumps(payload), encoding="utf-8")
    proposal = workaround.build_proposal(GRAPH, defects, "defect.r4-mpn")
    assert proposal.defect_check_status == "blocked"
    assert proposal.candidates == []


def test_completed_sample_writes_not_salvageable_evaluation(tmp_path: Path) -> None:
    graph_path = _graph_with_missing_footprint(tmp_path)
    evaluation = workaround.evaluate_completed(
        graph_path=graph_path,
        defects_path=DEFECTS,
        proposal_path=_proposal(tmp_path, graph_path),
        candidate_id="WC-001",
        rework_path=REWORK,
        dfa_path=DFA,
        fixture_dir=FIXTURE_DIR,
        out_dir=tmp_path / "out",
        approval_path=SAMPLE / "safety-approval.json",
        erc_path=SAMPLE / "evidence/erc.json",
        drc_path=SAMPLE / "evidence/drc.json",
    )
    assert evaluation.salvage is not None
    assert evaluation.salvage.verdict == "not_salvageable"
    assert any("power_decoupling" in reason for reason in evaluation.salvage.reasons)
    assert set(evaluation.salvage.reasons) <= set(evaluation.rejection_reasons)
    assert (tmp_path / "out/workaround-evaluation.json").is_file()


def test_check_cli_returns_one_for_host_unknown_predicate(tmp_path: Path) -> None:
    graph_path = _graph_with_missing_footprint(tmp_path)
    proposal_path = _proposal(tmp_path, graph_path)
    exit_code = check_workaround_main(
        [
            "--graph",
            str(graph_path),
            "--defects",
            str(DEFECTS),
            "--candidates",
            str(proposal_path),
            "--candidate-id",
            "WC-001",
            "--rework",
            str(REWORK),
            "--dfa",
            str(DFA),
            "--fixture-dir",
            str(FIXTURE_DIR),
            "--approval",
            str(SAMPLE / "safety-approval.json"),
            "--erc-evidence",
            str(SAMPLE / "evidence/erc.json"),
            "--drc-evidence",
            str(SAMPLE / "evidence/drc.json"),
            "--out-dir",
            str(tmp_path / "cli-out"),
        ]
    )
    assert exit_code == 1
    assert (tmp_path / "cli-out/workaround-evaluation.json").is_file()


def test_completed_sample_is_salvageable_with_predicate_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def passing_predicates(*_args: object) -> tuple[PredicateResult, ...]:
        return (PredicateResult(name="usb_cc", status="pass", detail="pass"),)

    monkeypatch.setattr(salvage_gate, "evaluate_design_predicates", passing_predicates)
    assert not any("patch" in name.lower() for name in vars(workaround))
    evaluation = workaround.evaluate_completed(
        graph_path=GRAPH,
        defects_path=DEFECTS,
        proposal_path=_proposal(tmp_path),
        candidate_id="WC-001",
        rework_path=REWORK,
        dfa_path=DFA,
        fixture_dir=FIXTURE_DIR,
        out_dir=tmp_path / "out",
        approval_path=SAMPLE / "safety-approval.json",
        erc_path=SAMPLE / "evidence/erc.json",
        drc_path=SAMPLE / "evidence/drc.json",
    )
    assert evaluation.salvage is not None
    assert evaluation.salvage.verdict == "salvageable"


def test_rejects_placeholder_and_strategy_mismatch(tmp_path: Path) -> None:
    proposal_path = _proposal(tmp_path)
    payload = json.loads(REWORK.read_text(encoding="utf-8"))
    payload["workaround_id"] = "WA-000"
    placeholder = tmp_path / "placeholder.json"
    placeholder.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(workaround.WorkaroundError, match="WA-000"):
        workaround.evaluate_completed(
            graph_path=GRAPH,
            defects_path=DEFECTS,
            proposal_path=proposal_path,
            candidate_id="WC-001",
            rework_path=placeholder,
            dfa_path=DFA,
            fixture_dir=FIXTURE_DIR,
            out_dir=tmp_path / "placeholder-out",
        )

    payload = json.loads(REWORK.read_text(encoding="utf-8"))
    payload["firmware_changes"] = [
        {
            "change_id": "FW-001",
            "kind": "pin_reassignment",
            "description": "Reassign the pin.",
            "affected_functions": ["fw.pin.i2c_sda"],
        }
    ]
    mismatch = tmp_path / "mismatch.json"
    mismatch.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(workaround.WorkaroundError, match="rework_only"):
        workaround.evaluate_completed(
            graph_path=GRAPH,
            defects_path=DEFECTS,
            proposal_path=proposal_path,
            candidate_id="WC-001",
            rework_path=mismatch,
            dfa_path=DFA,
            fixture_dir=FIXTURE_DIR,
            out_dir=tmp_path / "mismatch-out",
        )


def test_rejects_defect_outside_candidate(tmp_path: Path) -> None:
    payload = json.loads(REWORK.read_text(encoding="utf-8"))
    payload["defect_ids"] = ["defect.other"]
    rework = tmp_path / "other-defect.json"
    rework.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(workaround.WorkaroundError, match="outside"):
        workaround.evaluate_completed(
            graph_path=GRAPH,
            defects_path=DEFECTS,
            proposal_path=_proposal(tmp_path),
            candidate_id="WC-001",
            rework_path=rework,
            dfa_path=DFA,
            fixture_dir=FIXTURE_DIR,
            out_dir=tmp_path / "out",
        )
