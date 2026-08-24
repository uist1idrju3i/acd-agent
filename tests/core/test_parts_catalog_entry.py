"""Tests for parts-catalog declaration registration."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from acd.core.part_selection import select_part
from acd.core.parts_catalog_entry import (
    PartsCatalogEntryError,
    register_parts_catalog_entry,
)
from acd.schema import ComponentPartRequest


def _library_files(tmp_path: Path) -> tuple[Path, Path]:
    symbol = tmp_path / "Device.kicad_sym"
    footprint = tmp_path / "R.kicad_mod"
    symbol.write_text("symbol", encoding="utf-8")
    footprint.write_text("footprint", encoding="utf-8")
    return symbol, footprint


def _entry(tmp_path: Path, **overrides: object) -> dict[str, object]:
    symbol, footprint = _library_files(tmp_path)
    value: dict[str, object] = {
        "part_number": "CUSTOM-22K",
        "kind": "resistor",
        "value": "22k",
        "package": "R_0603_1608Metric",
        "library_ref": {
            "symbol": "Device:R",
            "symbol_file": str(symbol),
            "symbol_source": "test-library",
            "symbol_source_ref": "test-1",
            "symbol_sha256": "sha256:" + hashlib.sha256(symbol.read_bytes()).hexdigest(),
            "footprint": "Resistor_SMD:R_0603_1608Metric",
            "footprint_file": str(footprint),
            "footprint_source": "test-library",
            "footprint_source_ref": "test-1",
            "footprint_sha256": "sha256:" + hashlib.sha256(footprint.read_bytes()).hexdigest(),
        },
    }
    value.update(overrides)
    return value


def _catalog_copy(tmp_path: Path) -> Path:
    path = tmp_path / "parts-catalog.json"
    source = Path(__file__).parents[2] / "contracts" / "parts-catalog.json"
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_registers_entry_atomically_and_selects_it(tmp_path: Path) -> None:
    catalog = _catalog_copy(tmp_path)
    entry = _entry(tmp_path)

    dry_run = register_parts_catalog_entry(entry, catalog, dry_run=True)
    assert dry_run.written is False
    assert dry_run.pass_evidence is False
    assert dry_run.prior_catalog_hash != dry_run.new_catalog_hash
    assert "CUSTOM-22K" not in catalog.read_text(encoding="utf-8")

    result = register_parts_catalog_entry(entry, catalog)
    assert result.written is True
    assert result.new_catalog_hash == dry_run.new_catalog_hash
    selected = select_part(
        ComponentPartRequest(kind="resistor", value="22k", package="R_0603_1608Metric"),
        catalog,
    )
    assert selected.entry.part_number == "CUSTOM-22K"
    assert selected.pass_evidence is False


@pytest.mark.parametrize("field", ["symbol_sha256", "footprint_sha256"])
def test_provenance_hash_mismatch_fails_closed(tmp_path: Path, field: str) -> None:
    catalog = _catalog_copy(tmp_path)
    entry = _entry(tmp_path)
    library = entry["library_ref"]
    assert isinstance(library, dict)
    library[field] = "sha256:" + "0" * 64

    with pytest.raises(PartsCatalogEntryError, match="sha256"):
        register_parts_catalog_entry(entry, catalog)
    assert "CUSTOM-22K" not in catalog.read_text(encoding="utf-8")


def test_existing_selection_key_is_rejected_to_preserve_unambiguous_selection(
    tmp_path: Path,
) -> None:
    catalog = _catalog_copy(tmp_path)
    entry = _entry(tmp_path, value="1k", part_number="CUSTOM-1K")

    with pytest.raises(PartsCatalogEntryError, match="ambiguous"):
        register_parts_catalog_entry(entry, catalog)


def test_missing_library_file_fails_closed(tmp_path: Path) -> None:
    catalog = _catalog_copy(tmp_path)
    entry = _entry(tmp_path)
    library = entry["library_ref"]
    assert isinstance(library, dict)
    library["symbol_file"] = str(tmp_path / "missing.kicad_sym")

    with pytest.raises(PartsCatalogEntryError, match="unavailable"):
        register_parts_catalog_entry(entry, catalog)
