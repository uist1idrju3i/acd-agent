"""Contracts for the local deterministic parts catalog."""

from __future__ import annotations

from pydantic import Field

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


class PartCatalogEntry(AcdModel):
    part_number: NonEmptyStr
    kind: NonEmptyStr
    value: NonEmptyStr
    package: NonEmptyStr
    library_ref: PartLibraryRef


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
    "PartLibraryRef",
    "PartsCatalogDocument",
]
