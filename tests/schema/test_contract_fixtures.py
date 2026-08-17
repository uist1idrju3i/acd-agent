"""Pydantic validation of retained contract fixtures."""

from __future__ import annotations

import pytest
from conftest import fixture_obj, load_fixture
from pydantic import ValidationError

from acd.schema import AcdModel, DesignGraph, Evidence, RationaleDocument, ToolEnvelope


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (DesignGraph, "design-graph.json"),
        (Evidence, "evidence.json"),
        (ToolEnvelope, "tool-envelope.json"),
        (RationaleDocument, "rationale.json"),
    ],
)
def test_valid_contract_fixtures(model: type[AcdModel], name: str) -> None:
    model.model_validate(load_fixture("valid", name))


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (DesignGraph, "design-graph-unknown-field.json"),
        (Evidence, "evidence-bad-status.json"),
        (ToolEnvelope, "tool-envelope-missing-input-hash.json"),
        (RationaleDocument, "rationale-bad-alternatives.json"),
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
