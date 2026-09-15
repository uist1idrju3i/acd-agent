from datetime import date
from typing import Any, cast

import pytest
from pydantic import ValidationError

from acd.schema import PartPriceBook


def _payload() -> dict[str, Any]:
    return {
        "price_book_id": "test-price-book",
        "graph_id": "golden-design-1",
        "revision": "r1",
        "as_of": "2026-09-01",
        "currency": "USD",
        "minor_unit_digits": 2,
        "build_quantity": 10,
        "entries": [
            {
                "mpn": "TEST-MPN",
                "supplier": "fixture",
                "source": {
                    "kind": "manual_declaration",
                    "reference": "internal:test",
                    "fetched_at": "2026-08-15T00:00:00Z",
                    "valid_until": "2026-12-31T00:00:00Z",
                },
                "price_breaks": [
                    {"min_qty": 1, "unit_price_minor": 25},
                    {"min_qty": 100, "unit_price_minor": 20},
                ],
                "basis": "primary",
            }
        ],
        "policy": {"require_primary_basis": True},
    }


def test_part_price_book_validates_contract() -> None:
    book = PartPriceBook.model_validate(_payload())
    assert book.artifact_kind == "part_price_book"
    assert book.as_of == date(2026, 9, 1)


@pytest.mark.parametrize(
    "change",
    [
        {
            "entries": [
                {
                    **cast(dict[str, Any], _payload()["entries"][0]),
                    "price_breaks": [
                        {"min_qty": 100, "unit_price_minor": 20},
                        {"min_qty": 1, "unit_price_minor": 25},
                    ],
                }
            ]
        },
        {"currency": "usd"},
        {"build_quantity": 0},
    ],
)
def test_part_price_book_rejects_malformed_contract(
    change: dict[str, object],
) -> None:
    payload = _payload()
    payload.update(change)
    with pytest.raises(ValidationError):
        PartPriceBook.model_validate(payload)


def test_duplicate_price_book_mpn_is_rejected() -> None:
    payload = _payload()
    entries = cast(list[dict[str, Any]], payload["entries"])
    payload["entries"] = [entries[0], entries[0]]
    with pytest.raises(ValidationError):
        PartPriceBook.model_validate(payload)
