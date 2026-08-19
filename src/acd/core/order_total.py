"""Deterministic aggregation of declared manufacturing order totals."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from acd.core.quote import read_quote
from acd.schema.common import Revision, Sha256, Timestamp, canonical_json_sha256
from acd.schema.fab_profile import FabProfileDocument
from acd.schema.order_scope import OrderScope
from acd.schema.quote import QuoteAmount, QuoteCategory, QuoteRecord


class OrderTotalError(ValueError):
    """Raised when an order total cannot be computed fail-closed."""


@dataclass(frozen=True)
class OrderSubtotal:
    category: QuoteCategory
    amount: QuoteAmount


@dataclass(frozen=True)
class QuoteCanonicalHash:
    quote_id: str
    canonical_hash: Sha256


@dataclass(frozen=True)
class OrderTotalResult:
    subtotals: tuple[OrderSubtotal, ...]
    total: QuoteAmount
    target_revision: Revision
    quote_hashes: tuple[QuoteCanonicalHash, ...]
    breakdown_hash: Sha256


def aggregate_order_total(
    records: Sequence[QuoteRecord],
    scope: OrderScope,
    *,
    fab_profile: FabProfileDocument,
    evaluated_at: Timestamp,
    target_revision: Revision,
) -> OrderTotalResult:
    """Aggregate revision-matched, confirmed quote fee items."""
    if fab_profile.profile_id != scope.fab_profile_id:
        raise OrderTotalError("fab profile does not match order scope")
    if scope.target_revision != target_revision:
        raise OrderTotalError("order scope target revision does not match")
    if not records:
        raise OrderTotalError("order total requires at least one quote record")

    quote_ids: set[str] = set()
    item_ids: set[str] = set()
    category_amounts: dict[QuoteCategory, int] = {}
    categories: set[QuoteCategory] = set()
    quote_hashes: list[QuoteCanonicalHash] = []
    declared_total_minor = 0
    mechanical_ids: set[str] = set()

    for record in records:
        if record.quote_id in quote_ids:
            raise OrderTotalError("quote identifiers must be unique")
        quote_ids.add(record.quote_id)
        if record.target_revision != scope.target_revision:
            raise OrderTotalError("quote target revision does not match order scope")
        if record.supplier_name not in scope.allowed_suppliers:
            raise OrderTotalError("quote supplier is not allowed by order scope")
        if record.counterparty_type != scope.counterparty_type:
            raise OrderTotalError("quote counterparty type does not match order scope")
        if (
            record.declared_total.currency != scope.currency
            or record.declared_total.minor_unit_digits != scope.minor_unit_digits
        ):
            raise OrderTotalError("quote declared total currency does not match scope")
        declared_total_minor += record.declared_total.amount_minor

        fee_set = read_quote(
            record,
            evaluated_at=evaluated_at,
            target_revision=target_revision,
        )
        quote_hashes.append(
            QuoteCanonicalHash(
                quote_id=record.quote_id,
                canonical_hash=fee_set.canonical_hash,
            )
        )
        for item in fee_set.fee_items:
            if item.item_id in item_ids:
                raise OrderTotalError("quote fee item identifiers must be unique")
            item_ids.add(item.item_id)
            if (
                item.amount.currency != scope.currency
                or item.amount.minor_unit_digits != scope.minor_unit_digits
            ):
                raise OrderTotalError("quote item currency does not match scope")
            if item.category == "mechanical":
                mechanical_ids.add(item.item_id)
            categories.add(item.category)
            category_amounts[item.category] = (
                category_amounts.get(item.category, 0) + item.amount.amount_minor
            )

    missing_categories = set(scope.required_categories) - categories
    if missing_categories:
        raise OrderTotalError(
            "order scope required categories are missing: "
            + ", ".join(sorted(missing_categories))
        )

    for category, treatment in (
        ("shipping", scope.shipping_treatment),
        ("tax", scope.tax_treatment),
    ):
        present = category in categories
        if treatment == "itemized" and not present:
            raise OrderTotalError(f"order scope requires itemized {category}")
        if treatment != "itemized" and present:
            raise OrderTotalError(
                f"order scope does not permit a {category} fee item"
            )

    if scope.mechanical_treatment == "included":
        expected_ids = set(scope.mechanical_item_ids or ())
        if mechanical_ids != expected_ids:
            raise OrderTotalError(
                "mechanical fee item identifiers do not match order scope"
            )
    elif mechanical_ids:
        raise OrderTotalError("mechanical fee items are outside order scope")

    subtotals = tuple(
        OrderSubtotal(
            category=category,
            amount=QuoteAmount(
                amount_minor=amount_minor,
                currency=scope.currency,
                minor_unit_digits=scope.minor_unit_digits,
            ),
        )
        for category, amount_minor in sorted(category_amounts.items())
    )
    subtotal_total = sum(item.amount.amount_minor for item in subtotals)
    if declared_total_minor != subtotal_total:
        raise OrderTotalError(
            "quote declared totals do not match order fee subtotals"
        )
    total = QuoteAmount(
        amount_minor=subtotal_total,
        currency=scope.currency,
        minor_unit_digits=scope.minor_unit_digits,
    )

    ordered_quote_hashes = tuple(sorted(quote_hashes, key=lambda item: item.quote_id))
    breakdown_hash = canonical_json_sha256(
        {
            "quote_hashes": [
                {
                    "canonical_hash": item.canonical_hash,
                    "quote_id": item.quote_id,
                }
                for item in ordered_quote_hashes
            ],
            "subtotals": [
                {
                    "amount": item.amount.model_dump(mode="json"),
                    "category": item.category,
                }
                for item in subtotals
            ],
            "target_revision": target_revision,
            "total": total.model_dump(mode="json"),
        }
    )
    return OrderTotalResult(
        subtotals=subtotals,
        total=total,
        target_revision=target_revision,
        quote_hashes=ordered_quote_hashes,
        breakdown_hash=breakdown_hash,
    )
