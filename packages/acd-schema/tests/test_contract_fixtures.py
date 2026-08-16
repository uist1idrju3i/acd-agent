"""Pydantic validation of retained contract fixtures."""

from __future__ import annotations

import pytest
from conftest import load_fixture
from pydantic import ValidationError

from acd_schema import AcdModel, DesignGraph, Evidence, FwPackage, ToolEnvelope


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (DesignGraph, "design-graph.json"),
        (Evidence, "evidence.json"),
        (FwPackage, "fw-package.json"),
        (ToolEnvelope, "tool-envelope.json"),
    ],
)
def test_valid_contract_fixtures(model: type[AcdModel], name: str) -> None:
    model.model_validate(load_fixture("valid", name))


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (DesignGraph, "design-graph-unknown-field.json"),
        (Evidence, "evidence-bad-status.json"),
        (FwPackage, "fw-package-unknown-field.json"),
        (ToolEnvelope, "tool-envelope-missing-input-hash.json"),
    ],
)
def test_invalid_contract_fixtures(model: type[AcdModel], name: str) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(load_fixture("invalid", name))
