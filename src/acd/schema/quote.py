"""Canonical Pydantic models for time-bounded manufacturing quotes."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, StrictInt, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Timestamp,
    contains_unknown,
)
from acd.schema.fab_profile import Basis, FabSource

QuoteParty = Literal["fab", "distributor"]
QuoteCategory = Literal[
    "board",
    "components",
    "assembly",
    "mechanical",
    "shipping",
    "tax",
]


class QuoteModel(AcdModel):
    @model_validator(mode="after")
    def reject_unknown_values(self) -> Self:
        if contains_unknown(self.model_dump(mode="json")):
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
        if self.category in ("board", "components"):
            required_values = (
                ("quantity", self.quantity),
                ("stock_quantity", self.stock_quantity),
                ("lead_time_days", self.lead_time_days),
            )
        elif self.category == "assembly":
            required_values = (
                ("quantity", self.quantity),
                ("lead_time_days", self.lead_time_days),
                ("assembly_capable", self.assembly_capable),
            )
        else:
            required_values = ()
        missing = [name for name, value in required_values if value is None]
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
    declared_total: QuoteAmount
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
        amounts = [item.amount for item in self.items]
        amounts.append(self.declared_total)
        currencies = {
            (amount.currency, amount.minor_unit_digits) for amount in amounts
        }
        if len(currencies) != 1:
            raise ValueError("quote amounts must use one currency and minor unit scale")
        item_total = sum(item.amount.amount_minor for item in self.items)
        if item_total != self.declared_total.amount_minor:
            raise ValueError("quote declared_total does not match item total")
        for item in self.items:
            if item.source_index >= len(self.sources):
                raise ValueError("quote item source_index is out of range")
        return self
