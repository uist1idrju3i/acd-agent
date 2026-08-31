"""Declared library asset resolution tests for committed and generated fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.adapters.kicad.library import FootprintLibrary
from acd.core.electrical import extract_electrical_lane
from acd.core.library_assets import (
    LibraryAssetError,
    graph_library_assets,
    library_asset_store,
    resolve_fixture_library_path,
    verify_fixture_library_asset,
)
from acd.pipeline.repository import repository_root
from acd.schema.design_graph import DesignGraph

GD1_FIXTURE = repository_root() / "fixtures" / "golden-design-1"


def _gd1_graph() -> DesignGraph:
    return DesignGraph.model_validate(
        json.loads((GD1_FIXTURE / "graph.json").read_text(encoding="utf-8"))
    )


def test_committed_fixture_resolves_declarations_in_the_canonical_store() -> None:
    graph = _gd1_graph()
    relative = [asset for asset in graph_library_assets(graph) if asset.relative]
    assert relative
    for asset in relative:
        resolved = resolve_fixture_library_path(asset.declared_path, GD1_FIXTURE)
        assert resolved == library_asset_store() / Path(asset.declared_path).relative_to(
            "libraries"
        )
        assert resolved.is_file()
        assert verify_fixture_library_asset(asset, GD1_FIXTURE) == resolved


def test_footprint_library_loads_a_committed_fixture_declaration() -> None:
    graph = _gd1_graph()
    lane = extract_electrical_lane(graph)
    component = next(
        comp
        for comp in lane.components
        if not Path(comp.library.footprint_file).is_absolute()
    )
    shape = FootprintLibrary().load(
        component.library.footprint,
        resolve_fixture_library_path(component.library.footprint_file, GD1_FIXTURE),
        component.library.footprint_sha256,
    )
    assert shape.pads


def test_fixture_local_copy_is_preferred_over_the_canonical_store(tmp_path: Path) -> None:
    declared = "libraries/Espressif.kicad_sym"
    local = tmp_path / declared
    local.parent.mkdir(parents=True)
    local.write_bytes(b"(kicad_symbol_lib)\n")
    assert resolve_fixture_library_path(declared, tmp_path) == local


def test_declaration_outside_the_canonical_store_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(LibraryAssetError):
        resolve_fixture_library_path("libraries/../pyproject.toml", tmp_path)
