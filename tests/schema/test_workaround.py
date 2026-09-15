from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema.salvage import GateRun, SalvageGateResult
from acd.schema.workaround import (
    SkillProvenance,
    WorkaroundCandidate,
    WorkaroundEvaluation,
    WorkaroundProposalSet,
)


def _provenance() -> SkillProvenance:
    digest = "sha256:" + "a" * 64
    return SkillProvenance(
        script_sha256=digest,
        acd_version="0.0.2",
        graph_sha256=digest,
        defects_sha256=digest,
    )


def _candidate(**overrides: object) -> WorkaroundCandidate:
    payload: dict[str, object] = {
        "candidate_id": "WC-001",
        "strategy": "rework_only",
        "defect_ids": ["defect.r4-mpn"],
        "anchor_node_ids": ["comp.r4"],
        "rationale": "replace the root-cause component",
        "status": "not_applicable",
        "not_applicable_reason": "no applicable anchor",
    }
    payload.update(overrides)
    return WorkaroundCandidate.model_validate(payload)


def test_candidate_id_and_defect_uniqueness() -> None:
    with pytest.raises(ValidationError):
        _candidate(candidate_id="WC-01")
    with pytest.raises(ValidationError):
        _candidate(defect_ids=["defect.r4-mpn", "defect.r4-mpn"])


def test_not_applicable_reason_is_exact() -> None:
    with pytest.raises(ValidationError):
        _candidate(not_applicable_reason=None)
    with pytest.raises(ValidationError):
        _candidate(status="proposed", not_applicable_reason="reason")


def test_proposal_status_and_candidate_uniqueness() -> None:
    candidate = _candidate()
    with pytest.raises(ValidationError):
        WorkaroundProposalSet(
            graph_id="golden-design-1",
            revision="r1",
            defect_id="defect.r4-mpn",
            defect_check_status="blocked",
            candidates=[candidate],
            provenance=_provenance(),
        )
    with pytest.raises(ValidationError):
        WorkaroundProposalSet(
            graph_id="golden-design-1",
            revision="r1",
            defect_id="defect.r4-mpn",
            defect_check_status="workaround_eligible",
            candidates=[],
            provenance=_provenance(),
        )


def test_evaluation_rejection_reason_invariant() -> None:
    salvage = SalvageGateResult(
        workaround_id="WA-001",
        graph_id="golden-design-1",
        base_revision="r1",
        derived_revision="r1+WA-001",
        verdict="not_salvageable",
        gate_runs=[
            GateRun(
                gate="erc",
                status="fail",
                source="computed",
                detail="erc failed",
            )
        ],
        dfa_blockers=[],
        safety_boundary_touched=False,
        approval_status="not_required",
        degraded_functions=[],
        reasons=["erc failed"],
    )
    with pytest.raises(ValidationError):
        WorkaroundEvaluation(
            candidate_id="WC-001",
            workaround_id="WA-001",
            graph_id="golden-design-1",
            base_revision="r1",
            derived_revision="r1+WA-001",
            defect_check_status="workaround_eligible",
            salvage=salvage,
            rejection_reasons=[],
            provenance=_provenance(),
        )
