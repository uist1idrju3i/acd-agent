"""Deterministic reading of time-bounded manufacturing quote records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from acd.schema.common import Revision, Sha256, Timestamp, canonical_json_sha256
from acd.schema.quote import QuoteLineItem, QuoteRecord


class QuoteReadError(ValueError):
    """Raised when a quote cannot produce a complete deterministic fee set."""


@dataclass(frozen=True)
class QuoteFeeSet:
    fee_items: tuple[QuoteLineItem, ...]
    canonical_hash: Sha256


def _contains_unknown(value: object) -> bool:
    if isinstance(value, str):
        return value == "unknown"
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return any(_contains_unknown(item) for item in mapping.values())
    if isinstance(value, list):
        items = cast(list[object], value)
        return any(_contains_unknown(item) for item in items)
    return False


def _validate_quote(record: QuoteRecord, target_revision: Revision) -> None:
    if record.target_revision != target_revision:
        raise QuoteReadError("quote target revision does not match")
    if not record.sources:
        raise QuoteReadError("quote sources are missing")
    if not record.items:
        raise QuoteReadError("quote fee items are missing")
    if _contains_unknown(record.model_dump(mode="json")):
        raise QuoteReadError("quote contains unknown values")
    required_categories = {"board", "components", "assembly"}
    categories = {item.category for item in record.items}
    if not required_categories <= categories:
        missing = sorted(required_categories - categories)
        raise QuoteReadError(
            "quote is missing required fee categories: " + ", ".join(missing)
        )
    currency_scales = {
        (item.amount.currency, item.amount.minor_unit_digits) for item in record.items
    }
    if len(currency_scales) != 1:
        raise QuoteReadError("quote amounts use inconsistent currency scales")
    item_ids = [item.item_id for item in record.items]
    if len(item_ids) != len(set(item_ids)):
        raise QuoteReadError("quote fee item identifiers are not unique")
    for item in record.items:
        if item.source_index >= len(record.sources):
            raise QuoteReadError("quote source_index is out of range")
        if item.basis != "primary":
            raise QuoteReadError(
                f"quote amount is not primary-confirmed: {item.item_id}"
            )


def read_quote(
    record: QuoteRecord,
    *,
    evaluated_at: Timestamp,
    target_revision: Revision,
) -> QuoteFeeSet:
    """Read a valid, unexpired quote into a deterministic fee set."""
    try:
        _validate_quote(record, target_revision)
        if evaluated_at > record.valid_until:
            raise QuoteReadError("quote has expired")
    except QuoteReadError:
        raise
    except (TypeError, ValueError) as exc:
        raise QuoteReadError("quote timestamps are invalid") from exc
    fee_items = tuple(sorted(record.items, key=lambda item: item.item_id))
    canonical_hash = canonical_json_sha256(
        {"items": [item.model_dump(mode="json") for item in fee_items]}
    )
    return QuoteFeeSet(fee_items=fee_items, canonical_hash=canonical_hash)


def load_quote(
    path: Path,
    *,
    evaluated_at: Timestamp,
    target_revision: Revision,
) -> QuoteFeeSet:
    """Load and deterministically read a quote record from JSON."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("quote JSON root must be an object")
        record = QuoteRecord.model_validate(cast(dict[str, object], value))
    except (OSError, json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
        raise QuoteReadError(f"quote record is invalid: {path}") from exc
    return read_quote(
        record,
        evaluated_at=evaluated_at,
        target_revision=target_revision,
    )
