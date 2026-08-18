"""Fail-closed semantics of the contract models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import fixture_obj, load_fixture

from acd.schema import (
    Evidence,
    MeasuredQuantity,
    PhysicalEvidence,
    RationaleCoverageReport,
    RationaleUnclassified,
    ReceiptRecord,
    ToolEnvelope,
    canonical_sha256,
)

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
    assert evidence.supports_authoritative_pass("r3")
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


def test_physical_evidence_requires_measured_class_for_measured_claim() -> None:
    data = load_fixture("valid", "physical-evidence.json")
    measured = PhysicalEvidence.model_validate(data)
    assert measured.supports_pass("r3")
    assert measured.supports_measured_claim("r3")
    assert not measured.supports_authoritative_pass("r3")

    virtual = PhysicalEvidence.model_validate({**data, "measurement_class": "virtual"})
    assert virtual.supports_pass("r3")
    assert not virtual.supports_measured_claim("r3")


def test_unknown_physical_evidence_class_never_supports_pass() -> None:
    data = load_fixture("valid", "physical-evidence.json")
    evidence = PhysicalEvidence.model_validate({**data, "measurement_class": "unknown"})
    assert not evidence.supports_pass("r3")


def test_unknown_instrument_version_and_out_of_range_value_never_support_pass() -> None:
    unknown_instrument = PhysicalEvidence.model_validate(
        load_fixture("invalid", "physical-evidence-instrument-version-unknown.json")
    )
    assert not unknown_instrument.supports_pass("r3")

    out_of_range = PhysicalEvidence.model_validate(
        load_fixture("invalid", "physical-evidence-out-of-range.json")
    )
    assert not out_of_range.supports_pass("r3")


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_min": 4.0, "expected_max": 3.0},
        {"tolerance": -0.01},
        {"value": float("nan")},
        {"value": float("inf")},
    ],
)
def test_measured_quantity_rejects_invalid_numeric_contract(
    overrides: dict[str, float],
) -> None:
    data = {
        "name": "3v3_rail_voltage",
        "unit": "V",
        "value": 3.3,
        "expected_min": 3.0,
        "expected_max": 3.6,
        "tolerance": 0.05,
    }
    with pytest.raises(ValueError):
        MeasuredQuantity.model_validate({**data, **overrides})


def test_canonical_hash_is_stable_across_json_field_order() -> None:
    data = load_fixture("valid", "physical-evidence.json")
    evidence = PhysicalEvidence.model_validate(data)
    reordered = {
        "measurements": data["measurements"],
        "acquired_at": data["acquired_at"],
        "instrument": data["instrument"],
        "measurement_class": data["measurement_class"],
        "created_at": data["created_at"],
        "envelope": data["envelope"],
        "status": data["status"],
        "target_revision": data["target_revision"],
        "evidence_id": data["evidence_id"],
        "schema_version": data["schema_version"],
        "claims": data["claims"],
    }
    reordered_evidence = PhysicalEvidence.model_validate(reordered)
    assert evidence.canonical_hash() == reordered_evidence.canonical_hash()
    assert evidence.canonical_hash() == canonical_sha256(reordered_evidence)


def test_rationale_report_serializes_unclassified_attributes() -> None:
    report = RationaleCoverageReport(
        status="fail",
        graph_id="g",
        revision="r1",
        graph_id_match=False,
        revision_match=False,
        required_count=1,
        covered_count=0,
        unclassified=[
            RationaleUnclassified(
                node_id="node",
                node_kind="future.kind",
                attr="future_attr",
                reason="attribute is absent from both rationale classification tables",
            )
        ],
    )
    assert report.model_dump(mode="json")["unclassified"][0]["attr"] == "future_attr"


def test_receipt_requires_non_empty_inspection_reports_and_items() -> None:
    value = load_fixture("valid", "receipt.json")
    with pytest.raises(ValueError):
        ReceiptRecord.model_validate({**value, "inspection_reports": []})
    with pytest.raises(ValueError):
        ReceiptRecord.model_validate({**value, "received_items": []})


def test_receipt_timestamps_are_monotonic() -> None:
    value = load_fixture("valid", "receipt.json")
    with pytest.raises(ValueError):
        ReceiptRecord.model_validate({**value, "received_at": "2026-01-01T10:00:00Z"})
