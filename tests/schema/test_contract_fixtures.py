"""Pydantic validation of retained contract fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import fixture_obj, load_fixture
from pydantic import ValidationError

from acd.schema import (
    AcdModel,
    DesignFreedomDeclarationDocument,
    DesignGraph,
    Evidence,
    FunctionalBlockRegistryDocument,
    OrderPolicy,
    OrderScope,
    PhysicalEvidence,
    QuoteRecord,
    RationaleDocument,
    ReceiptRecord,
    ToolEnvelope,
    VisualProjectionSet,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (DesignGraph, "design-graph.json"),
        (Evidence, "evidence.json"),
        (PhysicalEvidence, "physical-evidence.json"),
        (ToolEnvelope, "tool-envelope.json"),
        (RationaleDocument, "rationale.json"),
        (ReceiptRecord, "receipt.json"),
        (QuoteRecord, "quote.json"),
        (QuoteRecord, "quote-order.json"),
        (OrderScope, "order-scope.json"),
        (OrderPolicy, "order-policy.json"),
        (VisualProjectionSet, "visual-projection-set.json"),
        (VisualProjectionSet, "visual-projection-mechanical.json"),
    ],
)
def test_valid_contract_fixtures(model: type[AcdModel], name: str) -> None:
    model.model_validate(load_fixture("valid", name))


def test_design_freedom_contract() -> None:
    path = ROOT / "contracts" / "design-freedom-declaration.json"
    DesignFreedomDeclarationDocument.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (DesignGraph, "design-graph-unknown-field.json"),
        (DesignFreedomDeclarationDocument, "design-freedom-unknown-dimension-id.json"),
        (DesignFreedomDeclarationDocument, "design-freedom-missing-dimension.json"),
        (DesignFreedomDeclarationDocument, "design-freedom-unknown-field.json"),
        (DesignFreedomDeclarationDocument, "design-freedom-bound-without-basis.json"),
        (
            DesignFreedomDeclarationDocument,
            "design-freedom-disabled-without-reason.json",
        ),
        (FunctionalBlockRegistryDocument, "functional-block-registry-duplicate.json"),
        (
            FunctionalBlockRegistryDocument,
            "functional-block-registry-empty-predicates.json",
        ),
        (FunctionalBlockRegistryDocument, "functional-block-registry-unknown-field.json"),
        (Evidence, "evidence-bad-status.json"),
        (PhysicalEvidence, "physical-evidence-missing-classification.json"),
        (PhysicalEvidence, "physical-evidence-missing-unit.json"),
        (PhysicalEvidence, "physical-evidence-revision-mismatch.json"),
        (PhysicalEvidence, "physical-evidence-time-reversed.json"),
        (PhysicalEvidence, "physical-evidence-no-measurements.json"),
        (ToolEnvelope, "tool-envelope-missing-input-hash.json"),
        (RationaleDocument, "rationale-bad-alternatives.json"),
        (ReceiptRecord, "receipt-inspection-reports-missing.json"),
        (ReceiptRecord, "receipt-time-reversed.json"),
        (ReceiptRecord, "receipt-zero-items.json"),
        (ReceiptRecord, "receipt-manifest-hash-unknown.json"),
        (QuoteRecord, "quote-expired-before-fetch.json"),
        (QuoteRecord, "quote-sources-missing.json"),
        (QuoteRecord, "quote-source-index-out-of-range.json"),
        (QuoteRecord, "quote-unknown-value.json"),
        (QuoteRecord, "quote-currency-mismatch.json"),
        (QuoteRecord, "quote-duplicate-item-id.json"),
        (QuoteRecord, "quote-time-reversed.json"),
        (QuoteRecord, "quote-negative-amount.json"),
        (QuoteRecord, "quote-assembly-capability-missing.json"),
        (QuoteRecord, "quote-declared-total-mismatch.json"),
        (OrderScope, "order-scope-suppliers-empty.json"),
        (OrderScope, "order-scope-required-board-missing.json"),
        (OrderScope, "order-scope-mechanical-undeclared.json"),
        (OrderScope, "order-scope-unknown-value.json"),
        (OrderPolicy, "order-policy-missing-limit.json"),
        (OrderPolicy, "order-policy-unknown-limit.json"),
        (OrderPolicy, "order-policy-electrical-missing.json"),
        (OrderPolicy, "order-policy-negative-limit.json"),
        (OrderPolicy, "order-policy-missing-currency.json"),
        (OrderPolicy, "order-policy-extra-field.json"),
        (ReceiptRecord, "receipt-revision-unknown.json"),
        (VisualProjectionSet, "visual-projection-renderer-version-unknown.json"),
        (VisualProjectionSet, "visual-projection-resolution-missing.json"),
        (VisualProjectionSet, "visual-projection-image-hash-unknown.json"),
        (VisualProjectionSet, "visual-projection-absolute-image-path.json"),
        (VisualProjectionSet, "visual-projection-duplicate-identifier.json"),
        (VisualProjectionSet, "visual-projection-pass-evidence.json"),
        (
            VisualProjectionSet,
            "visual-projection-interference-region-mismatch.json",
        ),
    ],
)
def test_invalid_contract_fixtures(model: type[AcdModel], name: str) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(load_fixture("invalid", name))


def test_rationale_requires_alternative_decision_record() -> None:
    value = load_fixture("valid", "rationale.json")
    records = value["records"]
    assert isinstance(records, list)
    record = fixture_obj(records[0])
    record["no_alternatives_reason"] = None
    with pytest.raises(ValidationError):
        RationaleDocument.model_validate(value)


def test_acd_skill_requires_skill_provenance() -> None:
    value = load_fixture("valid", "rationale.json")
    records = value["records"]
    assert isinstance(records, list)
    record = fixture_obj(records[0])
    provenance = fixture_obj(record["provenance"])
    provenance["source"] = "acd_skill"
    with pytest.raises(ValidationError):
        RationaleDocument.model_validate(value)


def test_rationale_requirement_reference_requires_path_and_identifier() -> None:
    value = load_fixture("valid", "rationale.json")
    records = value["records"]
    assert isinstance(records, list)
    record = fixture_obj(records[0])
    record["driving_requirement_refs"] = ["GD1-REQ-017"]
    with pytest.raises(ValidationError):
        RationaleDocument.model_validate(value)


def test_rationale_ids_must_be_unique() -> None:
    value = load_fixture("valid", "rationale.json")
    records = value["records"]
    assert isinstance(records, list)
    record = fixture_obj(records[0])
    value["records"] = [record, record.copy()]
    with pytest.raises(ValidationError):
        RationaleDocument.model_validate(value)
