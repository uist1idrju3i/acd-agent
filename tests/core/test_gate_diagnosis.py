"""Tests for the L3 gate-failure diagnosis summary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from acd.core.gate_diagnosis import GateDiagnosisError, diagnose_gate_failure
from acd.schema.common import canonical_json_sha256

FIXTURE_DIR = Path("fixtures/golden-design-1")


def _hashed(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "content_sha256": canonical_json_sha256(payload)}


def _write_predicates(out_dir: Path, predicates: list[dict[str, Any]]) -> Path:
    evidence_dir = out_dir / "gate-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / "design-predicates.json"
    path.write_text(
        json.dumps(
            _hashed(
                {
                    "artifact_kind": "design_predicate_report",
                    "target_revision": "r1",
                    "observation": {
                        "predicates": predicates,
                        "unconnected_nets": ["net.sda"],
                    },
                }
            )
        ),
        encoding="utf-8",
    )
    return path


def _failing_predicate() -> dict[str, Any]:
    return {
        "name": "power_decoupling",
        "status": "fail",
        "detail": "C2 is 5.2mm from U1 pin 1",
        "remediation": {
            "change_dimensions": ["component_placement_xy"],
            "refdes": "C2",
            "target_refdes": "U1",
            "net": "net.3v3",
        },
    }


def test_failed_subjects_are_machine_readable(tmp_path: Path) -> None:
    _write_predicates(tmp_path, [_failing_predicate()])

    diagnosis = diagnose_gate_failure(tmp_path)

    assert diagnosis["record_class"] == "L3"
    assert diagnosis["pass_evidence"] is False
    assert diagnosis["failed_predicates"] == ["power_decoupling"]
    assert diagnosis["remediation_change_dimensions"] == ["component_placement_xy"]
    assert diagnosis["failed_subjects"] == [
        {
            "predicate": "power_decoupling",
            "status": "fail",
            "change_dimensions": ["component_placement_xy"],
            "refdes": "C2",
            "target_refdes": "U1",
            "net": "net.3v3",
        }
    ]
    assert diagnosis["unconnected_nets"] == ["net.sda"]


def test_fixture_reports_rationale_coverage_and_preflight(tmp_path: Path) -> None:
    _write_predicates(tmp_path, [_failing_predicate()])

    diagnosis = diagnose_gate_failure(tmp_path, FIXTURE_DIR)

    coverage = diagnosis["rationale_coverage"]
    assert coverage["status"] == "pass"
    assert coverage["graph_id_match"] is True
    assert coverage["unclassified"] == []
    assert diagnosis["lane_preflight"]["status"]


def test_supported_lane_reports_declared_dimensions(tmp_path: Path) -> None:
    _write_predicates(tmp_path, [_failing_predicate()])

    diagnosis = diagnose_gate_failure(tmp_path, None, "board-pipeline")

    recovery = diagnosis["lane_recovery"]
    assert recovery["recovery_supported"] is True
    assert "component_placement_xy" in recovery["recovery_dimensions"]
    assert diagnosis["required_declarations"] == []


def test_unsupported_lane_reports_required_declaration(tmp_path: Path) -> None:
    _write_predicates(tmp_path, [_failing_predicate()])

    diagnosis = diagnose_gate_failure(tmp_path, None, "order-readiness")

    assert diagnosis["lane_recovery"]["recovery_supported"] is False
    assert diagnosis["required_declarations"][0]["lane_id"] == "order-readiness"
    assert diagnosis["required_declarations"][0]["next_step_action"]


def test_undeclared_lane_is_reported_as_unsupported(tmp_path: Path) -> None:
    _write_predicates(tmp_path, [_failing_predicate()])

    diagnosis = diagnose_gate_failure(tmp_path, None, "unknown-lane")

    assert diagnosis["lane_recovery"]["recovery_supported"] is False
    assert diagnosis["required_declarations"][0]["reason"]


def test_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    path = _write_predicates(tmp_path, [_failing_predicate()])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["observation"]["predicates"][0]["detail"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GateDiagnosisError, match="hash mismatch"):
        diagnose_gate_failure(tmp_path)


def test_malformed_remediation_dimensions_fail_closed(tmp_path: Path) -> None:
    predicate = _failing_predicate()
    predicate["remediation"]["change_dimensions"] = [3]
    _write_predicates(tmp_path, [predicate])

    with pytest.raises(GateDiagnosisError, match="remediation dimensions"):
        diagnose_gate_failure(tmp_path)


def test_missing_fixture_inputs_fail_closed(tmp_path: Path) -> None:
    _write_predicates(tmp_path, [_failing_predicate()])

    with pytest.raises(GateDiagnosisError, match="rationale inputs"):
        diagnose_gate_failure(tmp_path, tmp_path / "missing-fixture")


def test_missing_artifacts_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(GateDiagnosisError, match="no diagnostic artifacts"):
        diagnose_gate_failure(tmp_path)
