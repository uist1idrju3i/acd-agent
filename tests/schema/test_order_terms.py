"""OrderTermsDeclaration rejects undeclared and unknown values."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from acd.schema import OrderTermsDeclaration

TERMS_PATH = Path("fixtures/golden-design-1/order-terms.json")


def test_valid_gd1_terms() -> None:
    terms = OrderTermsDeclaration.model_validate_json(
        TERMS_PATH.read_text(encoding="utf-8")
    )
    assert terms.currency == "USD"
    assert terms.minor_unit_digits == 2
    assert terms.allowed_suppliers == ["Example Fab"]


def test_unknown_value_is_rejected() -> None:
    terms = json.loads(TERMS_PATH.read_text(encoding="utf-8"))
    terms["mechanical_exclusion_reason"] = "unknown"
    with pytest.raises(ValidationError):
        OrderTermsDeclaration.model_validate(terms)


def test_extra_field_is_rejected() -> None:
    terms = json.loads(TERMS_PATH.read_text(encoding="utf-8"))
    terms["vendor_notes"] = "call before ordering"
    with pytest.raises(ValidationError):
        OrderTermsDeclaration.model_validate(terms)


def test_bad_currency_is_rejected() -> None:
    terms = json.loads(TERMS_PATH.read_text(encoding="utf-8"))
    terms["currency"] = "usd"
    with pytest.raises(ValidationError):
        OrderTermsDeclaration.model_validate(terms)
