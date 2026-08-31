"""Library asset materialization tests for the fixture builder."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from acd.core import library_assets
from acd.core.library_assets import (
    LibraryAsset,
    LibraryAssetError,
    graph_library_assets,
    verify_materialized_library_assets,
)
from acd.pipeline.fixture_builder import FixtureBuilderError, build_design_fixture
from acd.schema import (
    DesignFixtureSpec,
    FixtureComponentSpec,
    FixtureCplOrientationEvidence,
    RequirementRecord,
)
from acd.schema.parts_catalog import ComponentPartRequest

SYMBOL_DECLARATION = "libraries/Espressif.kicad_sym"
FOOTPRINT_DECLARATION = "libraries/Espressif.pretty/ESP32-C3-MINI-1.kicad_mod"


def _spec() -> DesignFixtureSpec:
    return DesignFixtureSpec(
        design_name="library-asset-demo",
        components=[
            FixtureComponentSpec(
                refdes="U1",
                part_request=ComponentPartRequest(
                    kind="ic",
                    value="ESP32-C3-MINI-1-N4",
                    package="ESP32-C3-MINI-1",
                ),
                cpl_orientation_evidence=FixtureCplOrientationEvidence(
                    evidence_at=datetime(2026, 8, 11, tzinfo=UTC),
                    evidence_method="fixture placement cross-check",
                    evidence_basis="confirmed",
                    evidence_note="Declared rotation matches this design placement.",
                ),
            )
        ],
        requirements=[
            RequirementRecord(
                requirement_id="mcu",
                statement="Use the selected MCU module.",
                constrains_node_ids=["comp.u1"],
            )
        ],
    )


def test_generated_fixture_carries_declared_library_assets(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixture"
    graph = build_design_fixture(_spec(), fixture_dir)

    declarations = {asset.declared_path for asset in graph_library_assets(graph)}
    assert SYMBOL_DECLARATION in declarations
    assert FOOTPRINT_DECLARATION in declarations
    for declaration in (SYMBOL_DECLARATION, FOOTPRINT_DECLARATION):
        materialized = fixture_dir / declaration
        assert materialized.is_file()
        source = Path(declaration)
        assert materialized.read_bytes() == source.read_bytes()
    verify_materialized_library_assets(graph, fixture_dir)


def test_generation_fails_closed_when_a_declared_asset_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(library_assets, "repository_root", lambda: tmp_path)

    with pytest.raises(FixtureBuilderError, match="library assets could not be"):
        build_design_fixture(_spec(), tmp_path / "fixture")


def test_materialized_asset_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixture"
    graph = build_design_fixture(_spec(), fixture_dir)
    (fixture_dir / SYMBOL_DECLARATION).write_text("tampered", encoding="utf-8")

    with pytest.raises(LibraryAssetError, match="does not match declaration"):
        verify_materialized_library_assets(graph, fixture_dir)


def test_relative_declaration_cannot_escape_the_asset_store() -> None:
    digest = hashlib.sha256(b"").hexdigest()
    asset = LibraryAsset(
        declared_path="libraries/../pyproject.toml", sha256=f"sha256:{digest}"
    )

    with pytest.raises(LibraryAssetError, match="canonical store"):
        library_assets.verify_library_asset(asset)
