"""Integrity checks for the committed CERN library extraction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from acd.adapters.kicad.library import SymbolLibrary
from acd.core.library_assets import (
    LibraryAsset,
    LibraryAssetError,
    verify_library_asset,
)
from acd.pipeline.repository import repository_root
from acd.schema import PartsCatalogDocument

ROOT = repository_root()
LIBRARIES = ROOT / "libraries"
MANIFEST_PATH = LIBRARIES / "CERN.manifest.json"


def _footprint_name(part: dict[str, object]) -> str:
    return str(part["footprint"]).removeprefix("CERN:")


def _manifest() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8")),
    )


def test_cern_manifest_hashes_match_committed_store() -> None:
    manifest = _manifest()
    symbol_path = LIBRARIES / "CERN.kicad_sym"
    assert manifest["symbol_file_sha256"] == (
        "sha256:" + hashlib.sha256(symbol_path.read_bytes()).hexdigest()
    )
    for part in manifest["parts"]:
        part = cast(dict[str, Any], part)
        path = LIBRARIES / "CERN.pretty" / (_footprint_name(part) + ".kicad_mod")
        assert part["footprint_sha256"] == (
            "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        )


def test_cern_manifest_references_every_footprint() -> None:
    manifest = _manifest()
    referenced = {_footprint_name(part) + ".kicad_mod" for part in manifest["parts"]}
    actual = {path.name for path in (LIBRARIES / "CERN.pretty").glob("*.kicad_mod")}
    assert actual == referenced


def test_cern_symbols_load_through_kicad_parser() -> None:
    manifest = _manifest()
    path = LIBRARIES / "CERN.kicad_sym"
    library = SymbolLibrary()
    for part in manifest["parts"]:
        part = cast(dict[str, Any], part)
        parsed = library.load(part["symbol"], path, manifest["symbol_file_sha256"])
        assert parsed.lib_id == part["symbol"]


def test_cern_catalog_entries_match_manifest_parts() -> None:
    manifest = _manifest()
    manifest_by_footprint = {
        part["footprint"]: part
        for part in (cast(dict[str, Any], item) for item in manifest["parts"])
    }
    catalog = PartsCatalogDocument.model_validate_json(
        (ROOT / "contracts" / "parts-catalog.json").read_text(encoding="utf-8")
    )
    for entry in catalog.entries:
        if entry.library_ref.symbol_file != "libraries/CERN.kicad_sym":
            continue
        assert entry.library_ref.footprint in manifest_by_footprint


def test_cern_footprint_tampering_fails_closed(tmp_path: Path) -> None:
    manifest = _manifest()
    part = cast(dict[str, Any], manifest["parts"][0])
    source = LIBRARIES / "CERN.pretty" / (_footprint_name(part) + ".kicad_mod")
    target = tmp_path / source.name
    target.write_bytes(source.read_bytes()[:-1] + bytes([source.read_bytes()[-1] ^ 1]))
    with pytest.raises(LibraryAssetError, match="does not match declaration"):
        verify_library_asset(
            LibraryAsset(
                declared_path=str(target),
                sha256=part["footprint_sha256"],
            )
        )
