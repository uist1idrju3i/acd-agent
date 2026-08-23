"""Pydantic contracts for declared physical design freedom."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import AcdModel, NonEmptyStr, SchemaVersion

DesignFreedomDimensionId = Literal[
    "component_placement_xy",
    "component_rotation_deg",
    "gpio_assignment",
    "track_width_mm",
    "copper_layer_count",
    "clearance_mm",
    "via_rule",
    "router_max_passes",
    "mechanical_datum",
]
DesignFreedomLane = Literal["electrical", "mechanical", "firmware"]
DesignFreedomKind = Literal["continuous", "integer_range", "discrete_set", "categorical"]

DESIGN_FREEDOM_DIMENSION_IDS = frozenset(
    {
        "component_placement_xy",
        "component_rotation_deg",
        "gpio_assignment",
        "track_width_mm",
        "copper_layer_count",
        "clearance_mm",
        "via_rule",
        "router_max_passes",
        "mechanical_datum",
    }
)


class DesignFreedomDimension(AcdModel):
    dimension_id: DesignFreedomDimensionId
    title: NonEmptyStr
    description: NonEmptyStr
    lane: DesignFreedomLane
    kind: DesignFreedomKind
    unit: NonEmptyStr | None = None
    value_source: NonEmptyStr
    bound_basis: NonEmptyStr
    minimum: float | int | None = None
    maximum: float | int | None = None
    allowed_values: list[NonEmptyStr] = Field(default_factory=list)
    gate_authority: list[NonEmptyStr] = Field(min_length=1)
    search_enabled: bool
    search_disabled_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _validate_declaration(self) -> DesignFreedomDimension:
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        if self.kind in {"discrete_set", "categorical"}:
            if not self.allowed_values:
                raise ValueError("discrete_set and categorical dimensions require allowed_values")
        elif self.allowed_values:
            raise ValueError("continuous and integer_range dimensions forbid allowed_values")
        if self.kind == "categorical" and self.unit is not None:
            raise ValueError("categorical dimensions must not declare a unit")
        if self.search_enabled and self.search_disabled_reason is not None:
            raise ValueError("search_disabled_reason is forbidden for searchable dimensions")
        if not self.search_enabled and self.search_disabled_reason is None:
            raise ValueError("search_disabled_reason is required for disabled dimensions")
        if len(self.gate_authority) != len(set(self.gate_authority)):
            raise ValueError("gate_authority entries must be unique")
        return self


class DesignFreedomDeclarationDocument(AcdModel):
    schema_version: SchemaVersion
    declaration_id: NonEmptyStr
    dimensions: list[DesignFreedomDimension] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_canonical_dimension_set(self) -> DesignFreedomDeclarationDocument:
        ids = [dimension.dimension_id for dimension in self.dimensions]
        if len(ids) != len(set(ids)):
            raise ValueError("design freedom dimension_id values must be unique")
        declared = set(ids)
        if declared != set(DESIGN_FREEDOM_DIMENSION_IDS):
            missing = sorted(DESIGN_FREEDOM_DIMENSION_IDS - declared)
            unknown = sorted(declared - DESIGN_FREEDOM_DIMENSION_IDS)
            details: list[str] = []
            if missing:
                details.append("missing: " + ", ".join(missing))
            if unknown:
                details.append("unknown: " + ", ".join(unknown))
            raise ValueError("design freedom dimension set is invalid (" + "; ".join(details) + ")")
        return self


__all__ = [
    "DESIGN_FREEDOM_DIMENSION_IDS",
    "DesignFreedomDeclarationDocument",
    "DesignFreedomDimension",
    "DesignFreedomDimensionId",
]
