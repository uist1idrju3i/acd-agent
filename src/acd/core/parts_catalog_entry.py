"""Deterministic entrypoint for parts-catalog declarations."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from acd.core.part_selection import default_parts_catalog_path, load_parts_catalog
from acd.schema import PartCatalogEntry, PartsCatalogDocument
from acd.schema.common import canonical_json_sha256


class PartsCatalogEntryError(ValueError):
    """Raised when a parts-catalog entry cannot be safely registered."""


@dataclass(frozen=True)
class PartsCatalogEntryResult:
    """Validated catalog entry result and its provenance."""

    catalog_id: str
    prior_catalog_hash: str
    new_catalog_hash: str
    entry_source: str
    entry: PartCatalogEntry
    written: bool
    pass_evidence: bool = False

    def model_dump(self) -> dict[str, Any]:
        value = asdict(self)
        value["entry"] = self.entry.model_dump(mode="json")
        return value


def _read_entry_input(
    value: PartCatalogEntry | Mapping[str, Any] | str | Path,
) -> tuple[PartCatalogEntry, str]:
    if isinstance(value, PartCatalogEntry):
        return value, "model"
    if isinstance(value, Mapping):
        return PartCatalogEntry.model_validate(value), "mapping"
    if isinstance(value, Path):
        source = str(value)
        try:
            payload = json.loads(value.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise PartsCatalogEntryError(
                f"parts catalog entry is invalid: {source}: {exc}"
            ) from exc
        return PartCatalogEntry.model_validate(payload), source
    stripped = value.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise PartsCatalogEntryError(
                f"parts catalog entry JSON is invalid: {exc}"
            ) from exc
        return PartCatalogEntry.model_validate(payload), "inline"
    path = Path(value)
    try:
        if path.is_file():
            return _read_entry_input(path)
    except OSError as exc:
        raise PartsCatalogEntryError(
            f"parts catalog entry path cannot be read: {value}: {exc}"
        ) from exc
    raise PartsCatalogEntryError(
        "parts catalog entry is neither a JSON object nor a readable file: "
        + str(value)
    )


def _verify_library_file(path_value: str, expected: str, label: str) -> None:
    path = Path(path_value).expanduser()
    try:
        actual = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    except OSError as exc:
        raise PartsCatalogEntryError(
            f"{label} library file is unavailable: {path}: {exc}"
        ) from exc
    if actual != expected:
        raise PartsCatalogEntryError(
            f"{label} library file sha256 does not match declaration: {path}"
        )


def _validate_library_provenance(entry: PartCatalogEntry) -> None:
    library = entry.library_ref
    _verify_library_file(library.symbol_file, library.symbol_sha256, "symbol")
    _verify_library_file(library.footprint_file, library.footprint_sha256, "footprint")


def _validate_new_entry(entry: PartCatalogEntry, document: PartsCatalogDocument) -> None:
    _validate_library_provenance(entry)
    existing_part_numbers = {item.part_number for item in document.entries}
    if entry.part_number in existing_part_numbers:
        raise PartsCatalogEntryError(
            f"parts catalog part_number is already registered: {entry.part_number!r}"
        )
    selection_key = (entry.kind, entry.value, entry.package)
    conflicting = [
        item.part_number
        for item in document.entries
        if (item.kind, item.value, item.package) == selection_key
    ]
    if conflicting:
        raise PartsCatalogEntryError(
            "parts catalog entry would make selection ambiguous for "
            f"{entry.kind!r}, {entry.value!r}, {entry.package!r}: "
            + ", ".join(sorted([*conflicting, entry.part_number]))
        )


def _catalog_entry_payload(entry: PartCatalogEntry) -> dict[str, Any]:
    library_values = entry.library_ref.model_dump(mode="json")
    library_ref = {
        key: library_values[key]
        for key in (
            "footprint",
            "footprint_file",
            "footprint_sha256",
            "footprint_source",
            "footprint_source_ref",
            "symbol",
            "symbol_file",
            "symbol_sha256",
            "symbol_source",
            "symbol_source_ref",
        )
    }
    payload: dict[str, Any] = {
        "kind": entry.kind,
        "library_ref": library_ref,
        "package": entry.package,
        "part_number": entry.part_number,
        "value": entry.value,
    }
    if entry.cpl_orientation is not None:
        orientation_values = entry.cpl_orientation.model_dump(
            mode="json",
            exclude_defaults=True,
            exclude_none=True,
        )
        orientation = {
            key: orientation_values[key]
            for key in (
                "basis",
                "source_url",
                "offset_deg",
                "polarized",
                "pin_functions",
                "pin_aliases",
                "unverified_pads",
                "unverified_pad_reason",
                "unverified_pad_source",
                "geometry_exception",
                "geometry_exception_reason",
                "geometry_exception_source",
            )
            if key in orientation_values
        }
        payload["cpl_orientation"] = orientation
    return payload


def _catalog_json(existing: str, entry: PartCatalogEntry) -> str:
    entries_key = existing.find('"entries"')
    opening = existing.find("[", entries_key)
    if entries_key < 0 or opening < 0:
        raise PartsCatalogEntryError(
            "parts catalog has no recognized entries array representation"
        )
    depth = 0
    in_string = False
    escaped = False
    closing = -1
    for index in range(opening, len(existing)):
        character = existing[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                closing = index
                break
    if closing < 0:
        raise PartsCatalogEntryError(
            "parts catalog has no recognized entries array representation"
        )
    serialized = json.dumps(
        _catalog_entry_payload(entry),
        ensure_ascii=False,
        indent=2,
    )
    indented = "\n".join("    " + line for line in serialized.splitlines())
    prefix = existing[:closing]
    content = prefix.rstrip()
    whitespace = prefix[len(content) :]
    return content + ",\n" + indented + whitespace + existing[closing:]


def _write_catalog(path: Path, existing: str, entry: PartCatalogEntry) -> None:
    payload = _catalog_json(existing, entry)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    except OSError as exc:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
        raise PartsCatalogEntryError(
            f"parts catalog cannot be written: {path}: {exc}"
        ) from exc


def register_parts_catalog_entry(
    entry: PartCatalogEntry | Mapping[str, Any] | str | Path,
    catalog_path: Path | None = None,
    *,
    dry_run: bool = False,
) -> PartsCatalogEntryResult:
    """Validate and optionally append one unambiguous catalog declaration."""
    proposed, detected_source = _read_entry_input(entry)
    path = catalog_path or default_parts_catalog_path()
    try:
        existing_catalog = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PartsCatalogEntryError(
            f"parts catalog is invalid or unreadable: {path}: {exc}"
        ) from exc
    try:
        document, prior_hash = load_parts_catalog(path)
    except ValueError as exc:
        raise PartsCatalogEntryError(str(exc)) from exc
    _validate_new_entry(proposed, document)
    updated_document = document.model_copy(update={"entries": [*document.entries, proposed]})
    new_hash = canonical_json_sha256(updated_document.model_dump(mode="json"))
    if not dry_run:
        _write_catalog(path, existing_catalog, proposed)
    return PartsCatalogEntryResult(
        catalog_id=document.catalog_id,
        prior_catalog_hash=prior_hash,
        new_catalog_hash=new_hash,
        entry_source=detected_source,
        entry=proposed,
        written=not dry_run,
    )


__all__ = [
    "PartsCatalogEntryError",
    "PartsCatalogEntryResult",
    "register_parts_catalog_entry",
]
