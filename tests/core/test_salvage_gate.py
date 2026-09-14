"""Deterministic salvageability gate tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts.check_salvageability import main

from acd.core import salvage_gate
from acd.core.rework_diff import apply_rework_diff, load_rework_diff
from acd.schema.design_graph import DesignGraph
from acd.schema.rework_diff import ReworkDiff
from acd.schema.salvage import ReworkDfaDeclaration, SafetyApproval

ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
SAMPLE = ROOT / "fixtures/rework/sample"
FW_SAMPLE = ROOT / "fixtures/rework/sample-fw-only"
_DEFAULT_APPROVAL = object()


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(GRAPH_PATH.read_text(encoding="utf-8"))


def _inputs(
    directory: Path = SAMPLE,
) -> tuple[ReworkDiff, ReworkDfaDeclaration, SafetyApproval | None]:
    diff = ReworkDiff.model_validate_json(
        (directory / "rework.json").read_text(encoding="utf-8")
    )
    dfa = ReworkDfaDeclaration.model_validate_json(
        (directory / "rework-dfa.json").read_text(encoding="utf-8")
    )
    approval_path = directory / "safety-approval.json"
    approval = (
        SafetyApproval.model_validate_json(approval_path.read_text(encoding="utf-8"))
        if approval_path.exists()
        else None
    )
    return diff, dfa, approval


def _patch_computed_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    def passing_predicates(*_args: object) -> tuple[SimpleNamespace]:
        return (SimpleNamespace(name="usb_cc", status="pass", detail="pass"),)

    def passing_preflight(*_args: object) -> SimpleNamespace:
        return SimpleNamespace(status="pass", findings=[])

    monkeypatch.setattr(
        salvage_gate,
        "evaluate_design_predicates",
        passing_predicates,
    )
    monkeypatch.setattr(
        salvage_gate,
        "check_mechanical_preflight",
        passing_preflight,
    )


def _evaluate(
    monkeypatch: pytest.MonkeyPatch,
    directory: Path = SAMPLE,
    *,
    approval: SafetyApproval | Any | None = _DEFAULT_APPROVAL,
    evidence: bool = True,
):
    _patch_computed_gates(monkeypatch)
    diff, dfa, declared_approval = _inputs(directory)
    approval_for_eval: SafetyApproval | None
    if approval is _DEFAULT_APPROVAL:
        approval_for_eval = declared_approval
    else:
        assert approval is None or isinstance(approval, SafetyApproval)
        approval_for_eval = approval
    external = {}
    if evidence:
        external = {
            "erc": directory / "evidence/erc.json",
            "drc": directory / "evidence/drc.json",
        }
    return salvage_gate.evaluate_salvage(
        base_graph=_graph(),
        diff=diff,
        dfa=dfa,
        approval=approval_for_eval,
        fixture_dir=ROOT / "fixtures/golden-design-1",
        external_evidence=external,
    )


def test_sample_is_salvageable_with_matching_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, result = _evaluate(monkeypatch)
    assert result.verdict == "salvageable"
    assert result.approval_status == "approved"


def test_missing_erc_is_not_salvageable(monkeypatch: pytest.MonkeyPatch) -> None:
    _, result = _evaluate(monkeypatch, evidence=False)
    assert result.verdict == "not_salvageable"
    assert any("erc" in reason for reason in result.reasons)


def test_base_revision_evidence_is_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_computed_gates(monkeypatch)
    diff, dfa, approval = _inputs()
    erc = tmp_path / "erc.json"
    erc.write_text(
        json.dumps(
            {
                "gate": "erc",
                "status": "pass",
                "message": "stale",
                "target_revision": "r1",
            }
        ),
        encoding="utf-8",
    )
    _, result = salvage_gate.evaluate_salvage(
        base_graph=_graph(),
        diff=diff,
        dfa=dfa,
        approval=approval,
        fixture_dir=ROOT / "fixtures/golden-design-1",
        external_evidence={
            "erc": erc,
            "drc": SAMPLE / "evidence/drc.json",
        },
    )
    erc_run = next(run for run in result.gate_runs if run.gate == "erc")
    assert erc_run.status == "unknown"
    assert result.verdict == "not_salvageable"


def test_unknown_dfa_tool_access_blocks_salvage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_computed_gates(monkeypatch)
    diff, dfa, approval = _inputs()
    dfa = dfa.model_copy(
        update={
            "assessments": [
                dfa.assessments[0].model_copy(update={"tool_access": "unknown"}),
                dfa.assessments[1],
            ]
        }
    )
    _, result = salvage_gate.evaluate_salvage(
        base_graph=_graph(),
        diff=diff,
        dfa=dfa,
        approval=approval,
        fixture_dir=ROOT / "fixtures/golden-design-1",
        external_evidence={
            "erc": SAMPLE / "evidence/erc.json",
            "drc": SAMPLE / "evidence/drc.json",
        },
    )
    assert result.verdict == "not_salvageable"
    assert result.dfa_blockers


def test_missing_safety_approval_is_not_salvageable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, result = _evaluate(monkeypatch, approval=None)
    assert result.approval_status == "missing"
    assert result.verdict == "not_salvageable"


def test_mismatched_safety_approval_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, approval = _inputs()
    assert approval is not None
    approval = approval.model_copy(update={"derived_revision": "r1+WA-999"})
    _, result = _evaluate(monkeypatch, approval=approval)
    assert result.approval_status == "invalid"
    assert result.verdict == "not_salvageable"


def test_firmware_only_workaround_is_constrained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    derived, result = _evaluate(monkeypatch, FW_SAMPLE)
    assert result.verdict == "constrained_salvage"
    assert result.degraded_functions == ["usb_c_cc_termination"]
    base = _graph()
    base_payload = base.model_dump(mode="json")
    derived_payload = derived.graph.model_dump(mode="json")
    derived_payload["revision"] = base_payload["revision"]
    assert derived_payload == base_payload


def test_cli_exit_codes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_computed_gates(monkeypatch)
    out = tmp_path / "pass"
    assert main(
        [
            "--graph",
            str(GRAPH_PATH),
            "--rework",
            str(SAMPLE / "rework.json"),
            "--dfa",
            str(SAMPLE / "rework-dfa.json"),
            "--fixture-dir",
            str(ROOT / "fixtures/golden-design-1"),
            "--approval",
            str(SAMPLE / "safety-approval.json"),
            "--erc-evidence",
            str(SAMPLE / "evidence/erc.json"),
            "--drc-evidence",
            str(SAMPLE / "evidence/drc.json"),
            "--out-dir",
            str(out),
        ]
    ) == 0
    assert (out / "derived-graph.json").is_file()
    assert (out / "gate-evidence/salvage-gate.json").is_file()
    assert main(
        [
            "--graph",
            str(GRAPH_PATH),
            "--rework",
            str(SAMPLE / "rework.json"),
            "--dfa",
            str(SAMPLE / "rework-dfa.json"),
            "--fixture-dir",
            str(ROOT / "fixtures/golden-design-1"),
            "--approval",
            str(SAMPLE / "safety-approval.json"),
            "--out-dir",
            str(tmp_path / "fail"),
        ]
    ) == 1
    assert main(
        [
            "--graph",
            str(tmp_path / "missing.json"),
            "--rework",
            str(SAMPLE / "rework.json"),
            "--dfa",
            str(SAMPLE / "rework-dfa.json"),
            "--fixture-dir",
            str(ROOT / "fixtures/golden-design-1"),
            "--out-dir",
            str(tmp_path / "error"),
        ]
    ) == 2


def test_derived_graph_is_deterministic() -> None:
    diff = load_rework_diff(SAMPLE / "rework.json").diff
    first = apply_rework_diff(_graph(), diff)
    second = apply_rework_diff(_graph(), diff)
    assert first.graph.model_dump(mode="json") == second.graph.model_dump(mode="json")
    assert first.derived_revision == second.derived_revision
