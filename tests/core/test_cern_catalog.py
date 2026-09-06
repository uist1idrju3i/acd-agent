"""Tests for dynamic CERN catalog selection."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from acd.adapters.kicad.library import LibraryPinError, SymbolLibrary
from acd.core.cern_catalog import CERN_SUBMODULE, pinned_cern_commit
from acd.core.library_assets import LibraryAsset, verify_library_asset
from acd.core.part_selection import PartSelectionError, select_cern_part, select_part
from acd.pipeline.repository import repository_root
from acd.schema import ComponentPartRequest

ROOT = repository_root()
SUBMODULE = ROOT / CERN_SUBMODULE


def _request() -> ComponentPartRequest:
    return ComponentPartRequest(
        kind="ic",
        value="LM358",
        package="SOIC-8",
        preferred_part_number="LM358BID",
        catalog="cern",
    )


def test_cern_part_selection_resolves_and_verifies_assets() -> None:
    result = select_cern_part(_request())
    ref = result.entry.library_ref
    assert result.entry.part_number == "LM358BID"
    assert ref.symbol_file.startswith("libraries/cern-kicad-libs/SchLib/")
    assert Path(ref.footprint_file).is_file()
    assert result.catalog_id == "cern-kicad-libs"
    assert result.catalog_hash.startswith("sha256:")
    assert ref.symbol_source_ref == pinned_cern_commit(ROOT)
    verify_library_asset(
        LibraryAsset(declared_path=ref.symbol_file, sha256=ref.symbol_sha256)
    )
    verify_library_asset(
        LibraryAsset(declared_path=ref.footprint_file, sha256=ref.footprint_sha256)
    )


def test_select_part_dispatches_to_cern() -> None:
    result = select_part(_request())
    assert result.entry.part_number == "LM358BID"
    assert result.catalog_id == "cern-kicad-libs"


@pytest.mark.parametrize(
    ("part_number", "message"),
    (
        ("does-not-exist", "has no part"),
        ("SC18IM700IPW", "ambiguous across tables"),
        ("CERN_OHL_BIS", "footprint file is missing"),
        ("CD4050BPW", "LibFootprint is empty"),
    ),
)
def test_cern_selection_rejects_invalid_parts(
    part_number: str,
    message: str,
) -> None:
    request = _request().model_copy(update={"preferred_part_number": part_number})
    with pytest.raises(PartSelectionError, match=re.escape(message)):
        select_cern_part(request)


def _pinless_part_number() -> str:
    connection = sqlite3.connect(f"file:{SUBMODULE / 'CERN.sqlite'}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            'SELECT "Part Number", "LibSymbol" FROM "Fasteners & Fixings"'
        ).fetchall()
    finally:
        connection.close()
    for part_number, lib_id in rows:
        if not isinstance(lib_id, str) or ":" not in lib_id:
            continue
        library, _ = lib_id.split(":", 1)
        symbol_path = SUBMODULE / "SchLib" / f"{library}.kicad_sym"
        if not symbol_path.is_file():
            continue
        digest = "sha256:" + hashlib.sha256(symbol_path.read_bytes()).hexdigest()
        try:
            SymbolLibrary().load(lib_id, symbol_path, digest)
        except LibraryPinError as exc:
            if "has no pins" in str(exc):
                return str(part_number)
    raise AssertionError("Fasteners & Fixings has no pinless symbol row")


def test_cern_selection_rejects_pinless_part() -> None:
    request = _request().model_copy(
        update={"preferred_part_number": _pinless_part_number()}
    )
    with pytest.raises(PartSelectionError, match="has no pins"):
        select_cern_part(request)


def test_cern_selection_rejects_pin_drift(tmp_path: Path) -> None:
    libraries = tmp_path / "libraries"
    libraries.mkdir()
    readme = (ROOT / "libraries" / "README.md").read_text(encoding="utf-8")
    readme = readme.replace(
        pinned_cern_commit(ROOT),
        "0" * 40,
        1,
    )
    (libraries / "README.md").write_text(readme, encoding="utf-8")
    (libraries / "cern-kicad-libs").symlink_to(SUBMODULE, target_is_directory=True)
    with pytest.raises(PartSelectionError, match="commit drift"):
        select_cern_part(_request(), root=tmp_path)


def test_cern_catalog_requires_preferred_part_number() -> None:
    with pytest.raises(ValidationError, match="preferred_part_number"):
        ComponentPartRequest(
            kind="ic",
            value="LM358",
            package="SOIC-8",
            catalog="cern",
        )
