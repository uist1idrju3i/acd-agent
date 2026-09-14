"""Declared order terms input for deterministic order-scope derivation."""

from __future__ import annotations

from typing import Self

from pydantic import Field, StrictInt, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    SchemaVersion,
    contains_unknown,
)
from acd.schema.order_scope import ScopeFeeTreatment


class OrderTermsDeclaration(AcdModel):
    """Order terms that design inputs do not carry and must be declared."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    minor_unit_digits: StrictInt = Field(ge=0, le=9)
    shipping_treatment: ScopeFeeTreatment
    tax_treatment: ScopeFeeTreatment
    mechanical_exclusion_reason: NonEmptyStr | None = None
    allowed_suppliers: list[NonEmptyStr] | None = None

    @model_validator(mode="after")
    def validate_terms(self) -> Self:
        if contains_unknown(self.model_dump(mode="json")):
            raise ValueError("order terms values must not contain unknown")
        suppliers = self.allowed_suppliers
        if suppliers is not None and len(set(suppliers)) != len(suppliers):
            raise ValueError("order terms allowed suppliers must be unique")
        return self
