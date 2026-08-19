"""Canonical contract for the declared order scope."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, StrictInt, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    contains_unknown,
)
from acd.schema.quote import QuoteCategory, QuoteParty

ScopeFeeTreatment = Literal["itemized", "included", "exempt"]
MechanicalTreatment = Literal["included", "excluded"]


class OrderScope(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    scope_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    target_revision: Revision
    fab_profile_id: str = Field(pattern=r"^[a-z][a-z0-9.-]+$")
    counterparty_type: QuoteParty
    allowed_suppliers: list[NonEmptyStr] = Field(min_length=1)
    required_categories: list[QuoteCategory] = Field(min_length=1)
    shipping_treatment: ScopeFeeTreatment
    tax_treatment: ScopeFeeTreatment
    mechanical_treatment: MechanicalTreatment
    mechanical_item_ids: list[NonEmptyStr] | None = None
    mechanical_exclusion_reason: NonEmptyStr | None = None
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    minor_unit_digits: StrictInt = Field(ge=0, le=9)

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if contains_unknown(self.model_dump(mode="json")):
            raise ValueError("order scope values must not contain unknown")
        if len(set(self.allowed_suppliers)) != len(self.allowed_suppliers):
            raise ValueError("order scope allowed suppliers must be unique")
        categories = set(self.required_categories)
        if len(categories) != len(self.required_categories):
            raise ValueError("order scope required categories must be unique")
        required_base = {"board", "components", "assembly"}
        if not required_base <= categories:
            raise ValueError(
                "order scope required categories must include board, components, assembly"
            )
        for category, treatment in (
            ("shipping", self.shipping_treatment),
            ("tax", self.tax_treatment),
        ):
            if treatment != "itemized" and category in categories:
                raise ValueError(
                    f"order scope non-itemized {category} cannot be a required category"
                )
        if self.mechanical_treatment == "included":
            if not self.mechanical_item_ids:
                raise ValueError(
                    "order scope included mechanical treatment requires item IDs"
                )
            if self.mechanical_exclusion_reason is not None:
                raise ValueError(
                    "order scope included mechanical treatment cannot have an exclusion reason"
                )
            if len(set(self.mechanical_item_ids)) != len(self.mechanical_item_ids):
                raise ValueError("order scope mechanical item IDs must be unique")
        else:
            if self.mechanical_item_ids is not None:
                raise ValueError(
                    "order scope excluded mechanical treatment cannot have item IDs"
                )
            if self.mechanical_exclusion_reason is None:
                raise ValueError(
                    "order scope excluded mechanical treatment requires a reason"
                )
            if "mechanical" in categories:
                raise ValueError(
                    "order scope excluded mechanical treatment cannot be required"
                )
        return self
