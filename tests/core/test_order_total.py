"""Tests for deterministic order total aggregation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from acd.core.order_total import OrderTotalError, aggregate_order_total
from acd.core.quote import QuoteReadError
from acd.schema import FabProfileDocument, OrderScope, QuoteAmount, QuoteRecord

ROOT = Path(__file__).parents[2]
SCOPE_PATH = ROOT / "fixtures/contracts/valid/order-scope.json"
QUOTE_PATH = ROOT / "fixtures/contracts/valid/quote-order.json"
PROFILE_PATH = ROOT / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json"
EVALUATED_AT = datetime(2025, 1, 12, 9, 0, tzinfo=UTC)


def load_json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def load_scope() -> OrderScope:
    return OrderScope.model_validate(load_json(SCOPE_PATH))


def load_quote() -> QuoteRecord:
    return QuoteRecord.model_validate(load_json(QUOTE_PATH))


def load_profile() -> FabProfileDocument:
    return FabProfileDocument.model_validate(load_json(PROFILE_PATH))


def test_aggregate_order_total_returns_subtotals_and_hashes() -> None:
    result = aggregate_order_total(
        [load_quote()],
        load_scope(),
        fab_profile=load_profile(),
        evaluated_at=EVALUATED_AT,
        target_revision="r12",
    )

    assert [(item.category, item.amount.amount_minor) for item in result.subtotals] == [
        ("assembly", 1800),
        ("board", 2500),
        ("components", 4200),
        ("mechanical", 800),
    ]
    assert result.total.amount_minor == 9300
    assert result.total.currency == "USD"
    assert result.target_revision == "r12"
    assert result.quote_hashes[0].quote_id == "quote-gd1-order-001"
    assert result.breakdown_hash.startswith("sha256:")


def test_order_total_requires_matching_fab_profile() -> None:
    scope_value = load_json(SCOPE_PATH)
    scope_value["fab_profile_id"] = "other-fab-profile"
    mismatched_scope = OrderScope.model_validate(scope_value)

    with pytest.raises(OrderTotalError, match="fab profile"):
        aggregate_order_total(
            [load_quote()],
            mismatched_scope,
            fab_profile=load_profile(),
            evaluated_at=EVALUATED_AT,
            target_revision="r12",
        )


def test_order_total_reconciles_supplier_declared_totals() -> None:
    broken_quote = load_quote().model_copy(
        update={
            "declared_total": QuoteAmount(
                amount_minor=9301,
                currency="USD",
                minor_unit_digits=2,
            )
        }
    )

    with pytest.raises(OrderTotalError, match="declared totals"):
        aggregate_order_total(
            [broken_quote],
            load_scope(),
            fab_profile=load_profile(),
            evaluated_at=EVALUATED_AT,
            target_revision="r12",
        )


def test_aggregate_order_total_is_reproducible_when_quote_order_changes() -> None:
    first_value = load_json(QUOTE_PATH)
    second_value = json.loads(json.dumps(first_value))
    assert isinstance(second_value, dict)
    second_value = cast(dict[str, object], second_value)
    second_value["quote_id"] = "quote-gd1-order-002"
    second_items = cast(list[dict[str, object]], second_value["items"])
    for item in second_items:
        item["item_id"] = f"{item['item_id']}-second"
    second_value["declared_total"] = {
        "amount_minor": 9300,
        "currency": "USD",
        "minor_unit_digits": 2,
    }
    first = QuoteRecord.model_validate(first_value)
    second = QuoteRecord.model_validate(second_value)
    scope_value = load_json(SCOPE_PATH)
    scope_value["mechanical_item_ids"] = [
        "mechanical-enclosure",
        "mechanical-enclosure-second",
    ]
    scope = OrderScope.model_validate(scope_value)

    forward = aggregate_order_total(
        [first, second],
        scope,
        fab_profile=load_profile(),
        evaluated_at=EVALUATED_AT,
        target_revision="r12",
    )
    reverse = aggregate_order_total(
        [second, first],
        scope,
        fab_profile=load_profile(),
        evaluated_at=EVALUATED_AT,
        target_revision="r12",
    )

    assert forward == reverse
    assert forward.total.amount_minor == 18600


def test_order_total_rejects_scope_revision_mismatch() -> None:
    with pytest.raises(OrderTotalError, match="scope target revision"):
        aggregate_order_total(
            [load_quote()],
            load_scope(),
            fab_profile=load_profile(),
            evaluated_at=EVALUATED_AT,
            target_revision="r13",
        )


def test_order_total_rejects_record_revision_and_scope_currency_mismatch() -> None:
    value = load_json(QUOTE_PATH)
    value["target_revision"] = "r13"
    with pytest.raises(OrderTotalError, match="target revision"):
        aggregate_order_total(
            [QuoteRecord.model_validate(value)],
            load_scope(),
            fab_profile=load_profile(),
            evaluated_at=EVALUATED_AT,
            target_revision="r12",
        )

    scope_value = load_json(SCOPE_PATH)
    scope_value["currency"] = "EUR"
    with pytest.raises(OrderTotalError, match="currency"):
        aggregate_order_total(
            [load_quote()],
            OrderScope.model_validate(scope_value),
            fab_profile=load_profile(),
            evaluated_at=EVALUATED_AT,
            target_revision="r12",
        )


def test_order_total_rejects_supplier_and_counterparty_mismatch() -> None:
    value = load_json(QUOTE_PATH)
    value["supplier_name"] = "Other Fab"
    with pytest.raises(OrderTotalError, match="supplier"):
        aggregate_order_total(
            [QuoteRecord.model_validate(value)],
            load_scope(),
            fab_profile=load_profile(),
            evaluated_at=EVALUATED_AT,
            target_revision="r12",
        )

    value["supplier_name"] = "Example Fab"
    value["counterparty_type"] = "distributor"
    with pytest.raises(OrderTotalError, match="counterparty"):
        aggregate_order_total(
            [QuoteRecord.model_validate(value)],
            load_scope(),
            fab_profile=load_profile(),
            evaluated_at=EVALUATED_AT,
            target_revision="r12",
        )


def test_order_total_rejects_duplicate_quote_and_item_ids() -> None:
    value = load_json(QUOTE_PATH)
    with pytest.raises(OrderTotalError, match="quote identifiers"):
        aggregate_order_total(
            [load_quote(), QuoteRecord.model_validate(value)],
            load_scope(),
            fab_profile=load_profile(),
            evaluated_at=EVALUATED_AT,
            target_revision="r12",
        )

    value["quote_id"] = "quote-gd1-order-002"
    with pytest.raises(OrderTotalError, match="quote fee item identifiers"):
        aggregate_order_total(
            [load_quote(), QuoteRecord.model_validate(value)],
            load_scope(),
            fab_profile=load_profile(),
            evaluated_at=EVALUATED_AT,
            target_revision="r12",
        )


def test_order_total_rejects_missing_and_out_of_scope_categories() -> None:
    value = load_json(QUOTE_PATH)
    items = cast(list[dict[str, object]], value["items"])
    value["items"] = [
        item for item in items if item["category"] != "mechanical"
    ]
    value["declared_total"] = {
        "amount_minor": 8500,
        "currency": "USD",
        "minor_unit_digits": 2,
    }
    with pytest.raises(OrderTotalError, match="required categories"):
        aggregate_order_total(
            [QuoteRecord.model_validate(value)],
            load_scope(),
            fab_profile=load_profile(),
            evaluated_at=EVALUATED_AT,
            target_revision="r12",
        )

    scope_value = load_json(SCOPE_PATH)
    scope_value["mechanical_treatment"] = "excluded"
    scope_value["mechanical_item_ids"] = None
    scope_value["mechanical_exclusion_reason"] = "Outside order scope"
    scope_value["required_categories"] = [
        "board",
        "components",
        "assembly",
    ]
    excluded_scope = OrderScope.model_validate(scope_value)
    with pytest.raises(OrderTotalError, match="mechanical"):
        aggregate_order_total(
            [load_quote()],
            excluded_scope,
            fab_profile=load_profile(),
            evaluated_at=EVALUATED_AT,
            target_revision="r12",
        )


def test_order_total_rejects_shipping_and_tax_outside_scope() -> None:
    scope_value = load_json(SCOPE_PATH)
    scope_value["mechanical_treatment"] = "excluded"
    scope_value["mechanical_item_ids"] = None
    scope_value["mechanical_exclusion_reason"] = "Outside order scope"
    scope_value["required_categories"] = [
        "board",
        "components",
        "assembly",
    ]
    scope = OrderScope.model_validate(scope_value)
    with pytest.raises(OrderTotalError, match="shipping"):
        aggregate_order_total(
            [QuoteRecord.model_validate(load_json(ROOT / "fixtures/contracts/valid/quote.json"))],
            scope,
            fab_profile=load_profile(),
            evaluated_at=EVALUATED_AT,
            target_revision="r12",
        )


def test_order_total_propagates_quote_read_failures() -> None:
    with pytest.raises(QuoteReadError, match="expired"):
        aggregate_order_total(
            [load_quote()],
            load_scope(),
            fab_profile=load_profile(),
            evaluated_at=datetime(2025, 1, 18, 9, 0, tzinfo=UTC),
            target_revision="r12",
        )
