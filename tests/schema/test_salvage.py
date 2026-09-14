"""Schema validation tests for salvageability contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema.salvage import ReworkDfaDeclaration, SafetyApproval, SalvageGateResult


def _dfa_payload() -> dict[str, object]:
    return {
        "workaround_id": "WA-001",
        "graph_id": "golden-design-1",
        "base_revision": "r1",
        "assessments": [
            {
                "operation_index": 0,
                "tool_access": "yes",
                "hand_solderable": "yes",
                "enclosure_disassembly": "not_required",
                "basis": "DFA review",
            }
        ],
    }


def test_dfa_assessment_index_must_be_unique() -> None:
    payload = _dfa_payload()
    payload["assessments"] = [payload["assessments"][0], payload["assessments"][0]]
    with pytest.raises(ValidationError, match="operation_index"):
        ReworkDfaDeclaration.model_validate(payload)


def test_safety_approval_requires_derived_revision() -> None:
    with pytest.raises(ValidationError, match="derived revision"):
        SafetyApproval.model_validate(
            {
                "workaround_id": "WA-001",
                "graph_id": "golden-design-1",
                "derived_revision": "r1",
                "approver": "board",
                "approved_at": "2026-01-01T00:00:00Z",
                "scope": "safety boundary",
            }
        )


def test_salvageable_result_rejects_failing_gate() -> None:
    with pytest.raises(ValidationError, match="passing gate"):
        SalvageGateResult.model_validate(
            {
                "workaround_id": "WA-001",
                "graph_id": "golden-design-1",
                "base_revision": "r1",
                "derived_revision": "r1+WA-001",
                "verdict": "salvageable",
                "gate_runs": [
                    {
                        "gate": "erc",
                        "status": "fail",
                        "source": "computed",
                        "detail": "failed",
                    }
                ],
                "dfa_blockers": [],
                "safety_boundary_touched": False,
                "approval_status": "not_required",
                "degraded_functions": [],
                "reasons": [],
            }
        )


def test_not_salvageable_requires_reason() -> None:
    with pytest.raises(ValidationError, match="requires reasons"):
        SalvageGateResult.model_validate(
            {
                "workaround_id": "WA-001",
                "graph_id": "golden-design-1",
                "base_revision": "r1",
                "derived_revision": "r1+WA-001",
                "verdict": "not_salvageable",
                "gate_runs": [
                    {
                        "gate": "erc",
                        "status": "unknown",
                        "source": "missing",
                        "detail": "missing",
                    }
                ],
                "dfa_blockers": [],
                "safety_boundary_touched": False,
                "approval_status": "not_required",
                "degraded_functions": [],
                "reasons": [],
            }
        )
