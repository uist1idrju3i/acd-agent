"""Tests for deterministic quote contract reading."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from acd.core.quote import QuoteReadError, load_quote, read_quote
from acd.schema import QuoteAmount, QuoteRecord

ROOT = Path(__file__).parents[2]
QUOTE_PATH = ROOT / "fixtures/contracts/valid/quote.json"
EVALUATED_AT = datetime(2025, 1, 12, 9, 0, tzinfo=UTC)


def load_quote_value() -> dict[str, object]:
    return json.loads(QUOTE_PATH.read_text(encoding="utf-8"))


def test_quote_read_returns_primary_fee_set_and_stable_hash() -> None:
    first = load_quote(
        QUOTE_PATH,
        evaluated_at=EVALUATED_AT,
        target_revision="r12",
    )
    value = load_quote_value()
    items = value["items"]
    assert isinstance(items, list)
    items = cast(list[dict[str, object]], items)
    value["items"] = list(reversed(items))
    reordered = read_quote(
        QuoteRecord.model_validate(value),
        evaluated_at=EVALUATED_AT,
        target_revision="r12",
    )

    assert [item.item_id for item in first.fee_items] == [
        "assembly",
        "board",
        "components",
        "shipping",
        "tax",
    ]
    assert first.canonical_hash == reordered.canonical_hash
    assert all(item.basis == "primary" for item in first.fee_items)


@pytest.mark.parametrize(
    "name",
    [
        "quote-inference-amount.json",
    ],
)
def test_quote_inference_fixture_is_not_confirmed(name: str) -> None:
    with pytest.raises(QuoteReadError):
        load_quote(
            ROOT / "fixtures/contracts/invalid" / name,
            evaluated_at=EVALUATED_AT,
            target_revision="r12",
        )


def test_quote_expiry_is_evaluated_at_call_time() -> None:
    with pytest.raises(QuoteReadError, match="expired"):
        load_quote(
            QUOTE_PATH,
            evaluated_at=datetime(2025, 1, 17, 9, 0, 1, tzinfo=UTC),
            target_revision="r12",
        )


def test_quote_revision_mismatch_is_fail_closed() -> None:
    with pytest.raises(QuoteReadError, match="revision"):
        load_quote(
            QUOTE_PATH,
            evaluated_at=EVALUATED_AT,
            target_revision="r13",
        )


def test_inference_amount_is_not_a_confirmed_fee() -> None:
    value = load_quote_value()
    items = value["items"]
    assert isinstance(items, list)
    items = cast(list[dict[str, object]], items)
    first_item = items[0]
    first_item["basis"] = "inference"
    record = QuoteRecord.model_validate(value)

    with pytest.raises(QuoteReadError, match="primary"):
        read_quote(record, evaluated_at=EVALUATED_AT, target_revision="r12")


def test_missing_required_category_is_fail_closed() -> None:
    value = load_quote_value()
    items = value["items"]
    assert isinstance(items, list)
    items = cast(list[dict[str, object]], items)
    value["items"] = [
        item for item in items if item["category"] != "assembly"
    ]
    record = QuoteRecord.model_validate(value)

    with pytest.raises(QuoteReadError, match="categories"):
        read_quote(record, evaluated_at=EVALUATED_AT, target_revision="r12")


def test_quote_json_parse_failure_is_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "quote.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(QuoteReadError, match="invalid"):
        load_quote(path, evaluated_at=EVALUATED_AT, target_revision="r12")


def test_quote_amount_rejects_floating_minor_units() -> None:
    with pytest.raises(ValidationError):
        QuoteAmount.model_validate(
            {"amount_minor": 1.0, "currency": "USD", "minor_unit_digits": 2}
        )
