"""Kind-specific typed views over ``GraphNode.attrs``.

``GraphNode.attrs`` stays a free-form mapping so that the graph format remains
open for new kinds and lane-local attributes. For the kinds whose attributes
carry gate semantics, this module defines a strict Pydantic model. The design
graph validator runs the matching model when a node is constructed so that a
malformed declaration fails closed at load time, and consumers can call
``GraphNode.typed_attrs(Model)`` to read the same declaration without repeating
``isinstance`` checks.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, ClassVar, Final, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyAttr = Annotated[str, StringConstraints(min_length=1, strict=True)]

SignalClass = Literal[
    "safety_extra_low_voltage",
    "mains",
    "analog_sensitive",
    "high_speed",
    "power",
    "digital",
]
SIGNAL_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "safety_extra_low_voltage",
        "mains",
        "analog_sensitive",
        "high_speed",
        "power",
        "digital",
    }
)

ProtectionRole = Literal["fuse", "efuse", "polyfuse", "tvs", "current_limit"]
PROTECTION_ROLES: Final[frozenset[str]] = frozenset(
    {"fuse", "efuse", "polyfuse", "tvs", "current_limit"}
)

ForbiddenResource = Literal[
    "connector",
    "harness",
    "power_bus",
    "ic",
    "via",
    "thermal_path",
    "protection_device",
]
FORBIDDEN_RESOURCES: Final[frozenset[str]] = frozenset(
    {"connector", "harness", "power_bus", "ic", "via", "thermal_path", "protection_device"}
)


class ClosedAttrs(BaseModel):
    """Attribute set where every key is declared; unknown keys fail closed."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)


class OpenAttrs(BaseModel):
    """Attribute set that types known keys and passes lane-local keys through."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow", frozen=True, strict=True)


class FunctionalBlockAttrs(ClosedAttrs):
    """``design.functional_block``: registry block id and optional parent."""

    block_id: NonEmptyAttr | None = None
    parent_block_id: NonEmptyAttr | None = None


class PlacementGroupAttrs(ClosedAttrs):
    """``electrical.placement_group``: coupled placement constraint."""

    primary_refdes: NonEmptyAttr
    coupled_refdes: list[NonEmptyAttr] = Field(min_length=1)
    max_distance_mm: float | int
    move_together: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _require_explicit_distance(cls, data: object) -> object:
        if not isinstance(data, Mapping):
            return data
        mapping = cast(Mapping[str, object], data)
        if mapping.get("max_distance_mm") is None:
            raise ValueError("electrical.placement_group requires explicit max_distance_mm")
        return mapping

    @model_validator(mode="after")
    def _positive_distance(self) -> PlacementGroupAttrs:
        if isinstance(self.max_distance_mm, bool) or self.max_distance_mm <= 0:
            raise ValueError("electrical.placement_group max_distance_mm must be positive")
        return self


class NetAttrs(OpenAttrs):
    """``electrical.net``: safety-relevant classification of a net."""

    signal_class: SignalClass | None = None
    critical: bool | None = None
    off_board: bool | None = None
    intended_coupling: list[NonEmptyAttr] | None = None


class ComponentAttrs(OpenAttrs):
    """``electrical.component``: protection role used by structural safety."""

    protection_role: ProtectionRole | None = None


class RedundantGroupAttrs(ClosedAttrs):
    """``safety.redundant_group``: members that must not share a resource."""

    members: list[NonEmptyAttr]
    resources_shared_forbidden: list[ForbiddenResource]


AttrsModel = TypeVar("AttrsModel", bound=BaseModel)

KIND_ATTRS_MODELS: Final[dict[str, type[BaseModel]]] = {
    "design.functional_block": FunctionalBlockAttrs,
    "electrical.placement_group": PlacementGroupAttrs,
    "electrical.net": NetAttrs,
    "electrical.component": ComponentAttrs,
    "safety.redundant_group": RedundantGroupAttrs,
}
"""Node kinds whose attrs are validated against a typed model at graph load."""

__all__ = [
    "FORBIDDEN_RESOURCES",
    "KIND_ATTRS_MODELS",
    "PROTECTION_ROLES",
    "SIGNAL_CLASSES",
    "AttrsModel",
    "ComponentAttrs",
    "ForbiddenResource",
    "FunctionalBlockAttrs",
    "NetAttrs",
    "PlacementGroupAttrs",
    "ProtectionRole",
    "RedundantGroupAttrs",
    "SignalClass",
]
