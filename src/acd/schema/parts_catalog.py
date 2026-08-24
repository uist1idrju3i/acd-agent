"""Contracts for the local deterministic parts catalog."""

from __future__ import annotations

from typing import Literal

from pydantic import AnyUrl, Field, FiniteFloat, model_validator

from acd.schema.common import AcdModel, NonEmptyStr, SchemaVersion, Sha256


class PartLibraryRef(AcdModel):
    symbol: NonEmptyStr
    symbol_file: NonEmptyStr
    symbol_source: NonEmptyStr
    symbol_source_ref: NonEmptyStr
    symbol_sha256: Sha256
    footprint: NonEmptyStr
    footprint_file: NonEmptyStr
    footprint_source: NonEmptyStr
    footprint_source_ref: NonEmptyStr
    footprint_sha256: Sha256


class PartCplOrientation(AcdModel):
    basis: Literal["component_part_number"]
    source_url: AnyUrl
    offset_deg: FiniteFloat
    polarized: bool
    pin_functions: list[NonEmptyStr] = Field(default_factory=list)
    pin_aliases: list[NonEmptyStr] = Field(default_factory=list)
    unverified_pads: list[NonEmptyStr] = Field(default_factory=list)
    unverified_pad_reason: NonEmptyStr | None = None
    unverified_pad_source: NonEmptyStr | None = None
    geometry_exception: bool = False
    geometry_exception_reason: NonEmptyStr | None = None
    geometry_exception_source: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _validate_conditional_provenance(self) -> PartCplOrientation:
        if bool(self.unverified_pads) and (
            self.unverified_pad_reason is None or self.unverified_pad_source is None
        ):
            raise ValueError(
                "unverified pads require a reason and source"
            )
        if self.geometry_exception and (
            self.geometry_exception_reason is None
            or self.geometry_exception_source is None
        ):
            raise ValueError(
                "geometry exception requires a reason and source"
            )
        if self.geometry_exception and (
            "{artifact_prefix}" not in (self.geometry_exception_source or "")
            or "{refdes}" not in (self.geometry_exception_source or "")
        ):
            raise ValueError(
                "geometry exception source must derive artifact_prefix and refdes"
            )
        return self


class PartCatalogEntry(AcdModel):
    part_number: NonEmptyStr
    kind: NonEmptyStr
    value: NonEmptyStr
    package: NonEmptyStr
    library_ref: PartLibraryRef
    cpl_orientation: PartCplOrientation | None = None


class PartsCatalogDocument(AcdModel):
    schema_version: SchemaVersion
    catalog_id: NonEmptyStr
    entries: list[PartCatalogEntry] = Field(min_length=1)

    @property
    def entries_by_part_number(self) -> dict[str, PartCatalogEntry]:
        return {entry.part_number: entry for entry in self.entries}


class ComponentPartRequest(AcdModel):
    kind: NonEmptyStr
    value: NonEmptyStr
    package: NonEmptyStr
    preferred_part_number: NonEmptyStr | None = None


__all__ = [
    "ComponentPartRequest",
    "PartCatalogEntry",
    "PartCplOrientation",
    "PartLibraryRef",
    "PartsCatalogDocument",
]
