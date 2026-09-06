"""Integrity checks for the pinned CERN KiCad submodule."""

from __future__ import annotations

import json
import re
import subprocess

from acd.adapters.kicad.library import SymbolLibrary
from acd.core.library_assets import LibraryAsset, verify_library_asset
from acd.pipeline.repository import repository_root
from acd.schema import PartsCatalogDocument

ROOT = repository_root()
SUBMODULE = ROOT / "libraries" / "cern-kicad-libs"
SPEC_PATH = ROOT / "libraries" / "cern-catalog-parts.json"
README_PATH = ROOT / "libraries" / "README.md"
CERN_URL = "https://gitlab.com/ohwr/cern-kicad-libs"


def _spec_commit() -> str:
    payload = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    return str(payload["source_commit"])


def _readme_commit() -> str:
    text = README_PATH.read_text(encoding="utf-8")
    match = re.search(
        rf"- 取得元URL:\s*`{re.escape(CERN_URL)}`\s*"
        r"\n- 取得commit:\s*`([0-9a-f]{40})`",
        text,
    )
    assert match is not None, "CERN URL/commit pair is missing from libraries/README.md"
    return match.group(1)


def _gitlink_commit() -> str:
    result = subprocess.run(
        ["git", "ls-tree", "HEAD", "libraries/cern-kicad-libs"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    fields = result.stdout.strip().split()
    assert len(fields) == 4, "CERN submodule gitlink is missing from HEAD"
    assert fields[0] == "160000", "CERN entry is not a gitlink"
    return fields[2]


def test_cern_submodule_commit_matches_spec_and_readme() -> None:
    assert _gitlink_commit() == _spec_commit() == _readme_commit()


def test_cern_catalog_assets_exist_hash_and_parse() -> None:
    catalog = PartsCatalogDocument.model_validate_json(
        (ROOT / "contracts" / "parts-catalog.json").read_text(encoding="utf-8")
    )
    library = SymbolLibrary()
    found = 0
    for entry in catalog.entries:
        if entry.library_ref.symbol_source != CERN_URL:
            continue
        found += 1
        symbol_path = verify_library_asset(
            LibraryAsset(
                declared_path=entry.library_ref.symbol_file,
                sha256=entry.library_ref.symbol_sha256,
            )
        )
        verify_library_asset(
            LibraryAsset(
                declared_path=entry.library_ref.footprint_file,
                sha256=entry.library_ref.footprint_sha256,
            )
        )
        parsed = library.load(
            entry.library_ref.symbol,
            symbol_path,
            entry.library_ref.symbol_sha256,
        )
        assert parsed.pins
    assert found == 13


def test_cern_submodule_is_shallow() -> None:
    config = (ROOT / ".gitmodules").read_text(encoding="utf-8")
    section = re.search(
        r'\[submodule "libraries/cern-kicad-libs"\](.*?)(?=\n\[|\Z)',
        config,
        re.DOTALL,
    )
    assert section is not None
    body = section.group(1)
    assert re.search(r"^\s*path = libraries/cern-kicad-libs\s*$", body, re.MULTILINE)
    assert re.search(
        r"^\s*url = https://gitlab\.com/ohwr/cern-kicad-libs\.git\s*$",
        body,
        re.MULTILINE,
    )
    assert re.search(r"^\s*shallow = true\s*$", body, re.MULTILINE)
