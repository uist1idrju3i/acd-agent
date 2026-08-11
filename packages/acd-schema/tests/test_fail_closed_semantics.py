"""Fail-closed semantics of the contract models."""

from __future__ import annotations

from datetime import UTC, datetime

from conftest import fixture_list, fixture_obj, load_fixture

from acd_schema import Evidence, GateMatrix, ReviewFinding, ToolEnvelope

NOW = datetime(2026, 8, 12, tzinfo=UTC)


def _envelope(**overrides: str) -> ToolEnvelope:
    data = load_fixture("valid", "tool-envelope.json")
    return ToolEnvelope.model_validate({**data, **overrides})


def test_envelope_unknown_version_is_flagged() -> None:
    assert not _envelope().has_unknown()
    assert _envelope(tool_version="unknown").has_unknown()
    assert _envelope(input_hash="unknown").has_unknown()
    assert _envelope(convergence_state="unknown").has_unknown()


def test_valid_evidence_supports_pass_only_on_matching_revision() -> None:
    evidence = Evidence.model_validate(load_fixture("valid", "evidence.json"))
    assert evidence.supports_pass("r3")
    assert not evidence.supports_pass("r4")


def test_stale_evidence_never_supports_pass() -> None:
    data = load_fixture("valid", "evidence.json")
    stale = Evidence.model_validate({**data, "status": "stale"})
    assert not stale.supports_pass("r3")
    unknown = Evidence.model_validate({**data, "status": "unknown"})
    assert not unknown.supports_pass("r3")


def test_evidence_with_unknown_provenance_never_supports_pass() -> None:
    data = load_fixture("valid", "evidence.json")
    envelope = dict(fixture_obj(data["envelope"]))
    envelope["tool_version"] = "unknown"
    evidence = Evidence.model_validate({**data, "envelope": envelope})
    assert not evidence.supports_pass("r3")


def test_gate_matrix_verdict_pass_with_live_waiver() -> None:
    matrix = GateMatrix.model_validate(load_fixture("valid", "gate-matrix.json"))
    assert matrix.verdict(NOW) == "pass"


def test_gate_matrix_verdict_fails_on_expired_waiver() -> None:
    matrix = GateMatrix.model_validate(load_fixture("valid", "gate-matrix.json"))
    assert matrix.verdict(datetime(2026, 10, 1, tzinfo=UTC)) == "fail"


def test_gate_matrix_verdict_fails_on_unknown_stale_or_not_run() -> None:
    data = load_fixture("valid", "gate-matrix.json")
    for status in ("unknown", "stale", "not_run"):
        gates = [dict(fixture_obj(g)) for g in fixture_list(data["gates"])]
        gates[0]["status"] = status
        gates[0].pop("waiver", None)
        matrix = GateMatrix.model_validate({**data, "gates": gates})
        assert matrix.verdict(NOW) == "fail", status


def test_gate_pass_without_evidence_fails() -> None:
    data = load_fixture("valid", "gate-matrix.json")
    gates = [dict(fixture_obj(g)) for g in fixture_list(data["gates"])]
    gates[0]["evidence_refs"] = []
    matrix = GateMatrix.model_validate({**data, "gates": gates})
    assert matrix.verdict(NOW) == "fail"


def test_open_high_severity_finding_blocks_pass() -> None:
    data = load_fixture("valid", "review-finding.json")
    disposed = ReviewFinding.model_validate(data)
    assert not disposed.blocks_pass()
    open_finding = ReviewFinding.model_validate(
        {**data, "disposition": "open", "disposition_reason": None, "disposed_at": None}
    )
    assert open_finding.blocks_pass()
