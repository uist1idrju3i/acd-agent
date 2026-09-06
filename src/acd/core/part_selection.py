"""Deterministic selection from the declared local parts catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from acd.adapters.kicad.library import LibraryPinError, SymbolLibrary
from acd.core.cern_catalog import (
    CERN_CATALOG_ID,
    CERN_SOURCE_URL,
    CernCatalogError,
    cern_catalog_hash,
    cern_checkout_commit,
    pinned_cern_commit,
    resolve_cern_part,
)
from acd.pipeline.repository import repository_root
from acd.schema import (
    ComponentPartRequest,
    PartCatalogEntry,
    PartLibraryRef,
    PartsCatalogDocument,
)
from acd.schema.common import canonical_json_sha256


class PartSelectionError(ValueError):
    """Raised when a component request cannot be resolved unambiguously."""


@dataclass(frozen=True)
class PartSelectionResult:
    entry: PartCatalogEntry
    catalog_id: str
    catalog_hash: str
    pass_evidence: bool = False


def default_parts_catalog_path() -> Path:
    return repository_root() / "contracts" / "parts-catalog.json"


def load_parts_catalog(path: Path | None = None) -> tuple[PartsCatalogDocument, str]:
    catalog_path = path or default_parts_catalog_path()
    try:
        document = PartsCatalogDocument.model_validate_json(
            catalog_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise PartSelectionError(
            f"parts catalog is invalid or unreadable: {catalog_path}: {exc}"
        ) from exc
    return document, canonical_json_sha256(document.model_dump(mode="json"))


def select_part(
    request: ComponentPartRequest,
    path: Path | None = None,
) -> PartSelectionResult:
    if request.catalog == "cern":
        return select_cern_part(request)
    document, catalog_hash = load_parts_catalog(path)
    entries = [
        entry
        for entry in document.entries
        if entry.kind == request.kind
        and entry.value == request.value
        and entry.package == request.package
    ]
    if request.preferred_part_number is not None:
        entries = [
            entry
            for entry in entries
            if entry.part_number == request.preferred_part_number
        ]
    if not entries:
        raise PartSelectionError(
            "parts catalog has no matching part"
            + (
                f" for preferred part {request.preferred_part_number!r}"
                if request.preferred_part_number
                else ""
            )
        )
    if len(entries) > 1:
        raise PartSelectionError(
            "parts catalog match is ambiguous: "
            + ", ".join(sorted(entry.part_number for entry in entries))
        )
    return PartSelectionResult(
        entry=entries[0],
        catalog_id=document.catalog_id,
        catalog_hash=catalog_hash,
    )


def select_cern_part(
    request: ComponentPartRequest,
    root: Path | None = None,
) -> PartSelectionResult:
    repository = root or repository_root()
    try:
        expected_commit = pinned_cern_commit(repository)
        actual_commit = cern_checkout_commit(repository)
        if actual_commit != expected_commit:
            raise CernCatalogError(
                f"CERN submodule commit drift: expected {expected_commit}, "
                f"got {actual_commit}"
            )
        resolved = resolve_cern_part(
            repository,
            request.preferred_part_number or "",
        )
        symbol_sha256 = resolved.symbol_sha256
        SymbolLibrary().load(
            resolved.symbol,
            resolved.symbol_path,
            symbol_sha256,
        )
        entry = PartCatalogEntry(
            part_number=resolved.part_number,
            kind=request.kind,
            value=request.value,
            package=request.package,
            library_ref=PartLibraryRef(
                symbol=resolved.symbol,
                symbol_file=resolved.symbol_file,
                symbol_source=CERN_SOURCE_URL,
                symbol_source_ref=actual_commit,
                symbol_sha256=resolved.symbol_sha256,
                footprint=resolved.footprint,
                footprint_file=resolved.footprint_file,
                footprint_source=CERN_SOURCE_URL,
                footprint_source_ref=actual_commit,
                footprint_sha256=resolved.footprint_sha256,
            ),
            cpl_orientation=None,
        )
        return PartSelectionResult(
            entry=entry,
            catalog_id=CERN_CATALOG_ID,
            catalog_hash=cern_catalog_hash(repository),
        )
    except (CernCatalogError, LibraryPinError) as exc:
        raise PartSelectionError(str(exc)) from exc


__all__ = [
    "PartSelectionError",
    "PartSelectionResult",
    "default_parts_catalog_path",
    "load_parts_catalog",
    "select_cern_part",
    "select_part",
]
