"""Canonical Pydantic models for time-bounded manufacturing quotes."""

from __future__ import annotations

from typing import Literal, Self, cast

from pydantic import Field, StrictInt, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Timestamp,
)
from acd.schema.fab_profile import Basis, FabSource

QuoteParty = Literal["fab", "distributor"]
QuoteCategory = Literal["board", "components", "assembly", "shipping", "tax"]


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


class QuoteModel(AcdModel):
    @model_validator(mode="after")
    def reject_unknown_values(self) -> Self:
        if _contains_unknown(self.model_dump(mode="json")):
            raise ValueError("quote values must not contain unknown")
        return self


class QuoteAmount(QuoteModel):
    amount_minor: StrictInt = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    minor_unit_digits: StrictInt = Field(ge=0, le=9)


class QuoteLineItem(QuoteModel):
    item_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    category: QuoteCategory
    amount: QuoteAmount
    quantity: int | None = Field(default=None, ge=1)
    stock_quantity: int | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0)
    assembly_capable: bool | None = None
    source_index: int = Field(ge=0)
    basis: Basis
    note: NonEmptyStr

    @model_validator(mode="after")
    def validate_category_fields(self) -> QuoteLineItem:
        required: dict[QuoteCategory, tuple[str, ...]] = {
            "board": ("quantity", "stock_quantity", "lead_time_days"),
            "components": ("quantity", "stock_quantity", "lead_time_days"),
            "assembly": ("quantity", "lead_time_days", "assembly_capable"),
            "shipping": (),
            "tax": (),
        }
        missing = [
            name
            for name in required[self.category]
            if getattr(self, name) is None
        ]
        if missing:
            raise ValueError(
                f"{self.category} quote item is missing required fields: "
                + ", ".join(missing)
            )
        return self


class QuoteRecord(QuoteModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    quote_id: NonEmptyStr
    counterparty_type: QuoteParty
    supplier_name: NonEmptyStr
    target_revision: Revision
    sources: list[FabSource] = Field(min_length=1)
    items: list[QuoteLineItem] = Field(min_length=1)
    fetched_at: Timestamp
    valid_until: Timestamp
    recorded_at: Timestamp

    @model_validator(mode="after")
    def validate_record(self) -> QuoteRecord:
        if not self.fetched_at <= self.recorded_at:
            raise ValueError("quote timestamps must satisfy fetched_at <= recorded_at")
        if not self.valid_until > self.fetched_at:
            raise ValueError("quote valid_until must be later than fetched_at")
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("quote item_id values must be unique")
        currencies = {
            (item.amount.currency, item.amount.minor_unit_digits) for item in self.items
        }
        if len(currencies) != 1:
            raise ValueError("quote amounts must use one currency and minor unit scale")
        for item in self.items:
            if item.source_index >= len(self.sources):
                raise ValueError("quote item source_index is out of range")
        return self
