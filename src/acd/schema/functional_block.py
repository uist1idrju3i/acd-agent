"""Pydantic contracts for functional-block predicate applicability."""

from __future__ import annotations

from pydantic import Field, model_validator

from acd.schema.common import AcdModel, NonEmptyStr, SchemaVersion

KNOWN_CHANGE_DIMENSIONS = frozenset({"component_placement_xy"})


class FunctionalBlockContract(AcdModel):
    block_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    title: NonEmptyStr
    description: NonEmptyStr
    mandatory: bool = False
    required_predicates: list[NonEmptyStr] = Field(min_length=1)
    allowed_change_dimensions: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_required_predicates(self) -> FunctionalBlockContract:
        if len(self.required_predicates) != len(set(self.required_predicates)):
            raise ValueError("required_predicates entries must be unique")
        if len(self.allowed_change_dimensions) != len(set(self.allowed_change_dimensions)):
            raise ValueError("allowed_change_dimensions entries must be unique")
        unknown = sorted(set(self.allowed_change_dimensions) - KNOWN_CHANGE_DIMENSIONS)
        if unknown:
            raise ValueError(
                "allowed_change_dimensions contains unknown values: " + ", ".join(unknown)
            )
        return self


class FunctionalBlockRegistryDocument(AcdModel):
    schema_version: SchemaVersion
    registry_id: NonEmptyStr
    contracts: list[FunctionalBlockContract] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_block_ids(self) -> FunctionalBlockRegistryDocument:
        ids = [contract.block_id for contract in self.contracts]
        if len(ids) != len(set(ids)):
            raise ValueError("functional block block_id values must be unique")
        return self
