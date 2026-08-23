"""Canonical Pydantic model for declarative fab profiles."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AnyUrl, Field, RootModel, model_validator

from acd.schema.common import AcdModel, NonEmptyStr, SchemaVersion, Timestamp

Basis = Literal["primary", "inference"]
Impact = Literal["cost", "lead_time", "quality"]
AssemblySide = Literal["top", "bottom", "both"]


class FabSource(AcdModel):
    url: AnyUrl
    fetched_at: Timestamp
    title: NonEmptyStr


class Measurement(AcdModel):
    value: Any
    unit: NonEmptyStr
    source_index: int = Field(ge=0)
    basis: Basis
    note: str


class Threshold(AcdModel):
    value: float | list[float]
    unit: NonEmptyStr
    comparison: Literal["eq", "lt", "lte", "gt", "gte"]


class Preference(AcdModel):
    rule_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    description: NonEmptyStr
    impact: Impact | list[Impact]
    source_index: int = Field(ge=0)
    basis: Basis
    note: str
    threshold: Threshold | None = None

    @model_validator(mode="after")
    def _unique_impacts(self) -> Preference:
        if isinstance(self.impact, list) and len(set(self.impact)) != len(self.impact):
            raise ValueError("preference impact entries must be unique")
        return self


class Range1(AcdModel):
    min: float
    max: float | None = None


class Range2(RootModel[tuple[float, float]]):
    root: tuple[float, float] = Field(min_length=2, max_length=2)


class SizeRange(AcdModel):
    min: Range2
    max: Range2


class AssemblyClass(AcdModel):
    assembly_sides: list[AssemblySide] = Field(min_length=1)
    layers: list[int] = Field(min_length=1, validate_default=True)
    thickness_mm: list[float] = Field(min_length=1)
    thickness_policy: Literal["listed_options", "unrestricted"] | None = None
    thickness_note: str | None = None
    board_size_mm: SizeRange
    panel_size_mm: SizeRange
    quantity_pcs: Range1
    min_package: NonEmptyStr
    min_ic_pitch_mm: float = Field(gt=0)
    min_bga_pitch_mm: float = Field(gt=0)
    edge_rails_required: bool
    fiducials_required: bool
    build_time_days: Range1
    combinations: list[dict[str, Any]]

    @model_validator(mode="after")
    def _positive_measurements(self) -> AssemblyClass:
        if len(set(self.assembly_sides)) != len(self.assembly_sides):
            raise ValueError("assembly_sides entries must be unique")
        if any(layer < 1 for layer in self.layers):
            raise ValueError("layers must be positive")
        if any(value <= 0 for value in self.thickness_mm):
            raise ValueError("thickness_mm values must be positive")
        return self


class CplContract(AcdModel):
    position_basis: Literal["footprint_origin", "body_bbox_center", "pad_bbox_center"]
    position_source_index: int = Field(ge=0)
    position_evidence_status: Literal["estimated", "confirmed"]
    position_note: NonEmptyStr
    rotation_basis: Literal["kicad_footprint", "component_part_number"]
    rotation_source_index: int = Field(ge=0)
    rotation_evidence_status: Literal["estimated", "confirmed"]
    rotation_note: NonEmptyStr


class AssemblyClasses(AcdModel):
    economic: AssemblyClass
    standard: AssemblyClass


class FabProfileDocument(AcdModel):
    schema_version: SchemaVersion
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9.-]+$")
    fab: NonEmptyStr
    process: NonEmptyStr
    sources: list[FabSource] = Field(min_length=1)
    capabilities: dict[str, Measurement] = Field(min_length=1)
    preferences: list[Preference]
    unsupported: list[NonEmptyStr]
    assembly_classes: AssemblyClasses
    cpl_contract: CplContract

    @model_validator(mode="after")
    def _unique_values(self) -> FabProfileDocument:
        if len(set(self.unsupported)) != len(self.unsupported):
            raise ValueError("unsupported entries must be unique")
        if len(set(self.preferences_rule_ids)) != len(self.preferences_rule_ids):
            raise ValueError("preference rule_id values must be unique")
        return self

    @property
    def preferences_rule_ids(self) -> tuple[str, ...]:
        return tuple(item.rule_id for item in self.preferences)


class FabProfileRegistryEntry(AcdModel):
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9.-]+$")
    path: NonEmptyStr
    fab: NonEmptyStr
    process: NonEmptyStr


class FabProfileRegistryDocument(AcdModel):
    schema_version: SchemaVersion
    registry_id: NonEmptyStr
    profiles: list[FabProfileRegistryEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_profile_ids(self) -> FabProfileRegistryDocument:
        ids = [profile.profile_id for profile in self.profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("fab profile registry profile_id values must be unique")
        return self
