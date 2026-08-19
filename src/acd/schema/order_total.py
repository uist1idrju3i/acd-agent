"""Canonical persisted contract for deterministic order totals."""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
)
from acd.schema.quote import QuoteAmount, QuoteCategory


class OrderSubtotalDocument(AcdModel):
    category: QuoteCategory
    amount: QuoteAmount


class QuoteCanonicalHashDocument(AcdModel):
    quote_id: NonEmptyStr
    canonical_hash: Sha256


class OrderTotalDocument(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    subtotals: list[OrderSubtotalDocument] = Field(min_length=1)
    total: QuoteAmount
    target_revision: Revision
    quote_hashes: list[QuoteCanonicalHashDocument] = Field(min_length=1)
    breakdown_hash: Sha256

    @model_validator(mode="after")
    def validate_document(self) -> Self:
        categories = [item.category for item in self.subtotals]
        if len(categories) != len(set(categories)):
            raise ValueError("order total subtotal categories must be unique")
        if categories != sorted(categories):
            raise ValueError("order total subtotal categories must be sorted")
        if any(
            item.amount.currency != self.total.currency
            or item.amount.minor_unit_digits != self.total.minor_unit_digits
            for item in self.subtotals
        ):
            raise ValueError("order subtotal currency does not match total")
        if sum(item.amount.amount_minor for item in self.subtotals) != (
            self.total.amount_minor
        ):
            raise ValueError("order subtotal does not match total")
        quote_ids = [item.quote_id for item in self.quote_hashes]
        if len(quote_ids) != len(set(quote_ids)):
            raise ValueError("order total quote identifiers must be unique")
        if quote_ids != sorted(quote_ids):
            raise ValueError("order total quote identifiers must be sorted")
        return self
