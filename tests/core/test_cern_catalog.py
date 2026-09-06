"""Tests for dynamic CERN catalog selection."""

from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from acd.adapters.kicad.library import LibraryPinError, SymbolLibrary
from acd.core.cern_catalog import (
    CERN_SUBMODULE,
    CernCatalogError,
    pinned_cern_commit,
    resolve_cern_part,
)
from acd.core.library_assets import LibraryAsset, verify_library_asset
from acd.core.part_selection import PartSelectionError, select_cern_part, select_part
from acd.pipeline.repository import repository_root
from acd.schema import ComponentPartRequest

ROOT = repository_root()
SUBMODULE = ROOT / CERN_SUBMODULE


def _request() -> ComponentPartRequest:
    return ComponentPartRequest(
        kind="ic",
        value="CP2102N-A02-GQFN28",
        package="QFN-28",
        preferred_part_number="CP2102N-A02-GQFN28",
        catalog="cern",
    )


def test_cern_part_selection_resolves_and_verifies_assets() -> None:
    result = select_cern_part(_request())
    ref = result.entry.library_ref
    assert result.entry.part_number == "CP2102N-A02-GQFN28"
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
    assert result.entry.part_number == "CP2102N-A02-GQFN28"
    assert result.catalog_id == "cern-kicad-libs"


@pytest.mark.parametrize(
    ("part_number", "message"),
    (
        ("does-not-exist", "has no part"),
        ("SC18IM700IPW", "ambiguous across tables"),
        ("LM358BID", "conflicting library mappings"),
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


def _fake_cern_root(
    root: Path,
    rows: list[tuple[str, str, str]],
) -> Path:
    libraries = root / "libraries"
    checkout = libraries / "cern-kicad-libs"
    (checkout / "SchLib").mkdir(parents=True)
    (checkout / "PcbLib").mkdir()
    shutil.copy2(ROOT / "libraries" / "README.md", libraries / "README.md")
    connection = sqlite3.connect(checkout / "CERN.sqlite")
    try:
        connection.execute(
            'CREATE TABLE "Fake Table" '
            '("Part Number" TEXT, "LibSymbol" TEXT, "LibFootprint" TEXT)'
        )
        connection.executemany(
            'INSERT INTO "Fake Table" '
            '("Part Number", "LibSymbol", "LibFootprint") VALUES (?, ?, ?)',
            rows,
        )
        connection.commit()
    finally:
        connection.close()
    return checkout


def test_cern_catalog_rejects_conflicting_same_table_mappings(
    tmp_path: Path,
) -> None:
    _fake_cern_root(
        tmp_path,
        [
            (
                "DUPLICATE",
                "Operational Amplifiers:Operational Amplifier x2 Type1",
                "ICs And Semiconductors SMD:SOIC127P600X175-8N",
            ),
            (
                "DUPLICATE",
                "Operational Amplifiers:Operational Amplifier x2 Type1 [alt]",
                "ICs And Semiconductors SMD:SOIC127P600X175-8N",
            ),
        ],
    )
    with pytest.raises(
        CernCatalogError,
        match="CERN catalog part 'DUPLICATE' has conflicting library mappings",
    ):
        resolve_cern_part(tmp_path, "DUPLICATE")


def test_cern_catalog_accepts_identical_same_table_mappings(
    tmp_path: Path,
) -> None:
    checkout = _fake_cern_root(
        tmp_path,
        [
            (
                "DUPLICATE",
                "Operational Amplifiers:Operational Amplifier x2 Type1",
                "ICs And Semiconductors SMD:SOIC127P600X175-8N",
            ),
            (
                "DUPLICATE",
                "Operational Amplifiers:Operational Amplifier x2 Type1",
                "ICs And Semiconductors SMD:SOIC127P600X175-8N",
            ),
        ],
    )
    real_checkout = ROOT / CERN_SUBMODULE
    symbol = "Operational Amplifiers.kicad_sym"
    footprint = "SOIC127P600X175-8N.kicad_mod"
    real_symbol = real_checkout / "SchLib" / symbol
    real_footprint = (
        real_checkout
        / "PcbLib"
        / "ICs And Semiconductors SMD.pretty"
        / footprint
    )
    shutil.copy2(real_symbol, checkout / "SchLib" / symbol)
    footprint_dir = (
        checkout / "PcbLib" / "ICs And Semiconductors SMD.pretty"
    )
    footprint_dir.mkdir()
    shutil.copy2(real_footprint, footprint_dir / footprint)

    resolved = resolve_cern_part(tmp_path, "DUPLICATE")
    assert resolved.symbol == "Operational Amplifiers:Operational Amplifier x2 Type1"
    assert resolved.footprint == (
        "ICs And Semiconductors SMD:SOIC127P600X175-8N"
    )
