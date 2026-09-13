"""Deterministic KiCad schematic projection tests."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from acd.adapters.kicad.library import ParsedSymbol, SymbolLibrary, SymbolPin
from acd.adapters.kicad.schematic import (
    CONNECTION_CONVENTION_NOTE,
    PWR_FLAG_LIB_ID,
    PlacedSymbol,
    _label_collisions,
    _LabelPlacement,
    _symbol_extent,
    _symbol_geometry,
    generate_schematic,
)
from acd.core.electrical import ComponentView, LibraryPin, extract_electrical_lane
from acd.schema import DesignGraph

ROOT = Path(__file__).parents[3]
FIXTURE_DIR = ROOT / "fixtures/golden-design-1"
POWER_LIBRARY = Path("/usr/share/kicad/symbols/power.kicad_sym")


def _schematic() -> str:
    if not POWER_LIBRARY.is_file():
        pytest.skip("host KiCad power symbol library is unavailable")
    graph = DesignGraph.model_validate(
        json.loads((FIXTURE_DIR / "graph.json").read_text(encoding="utf-8"))
    )
    library = SymbolLibrary()
    digest = "sha256:" + hashlib.sha256(POWER_LIBRARY.read_bytes()).hexdigest()
    pwr_flag = library.load(PWR_FLAG_LIB_ID, POWER_LIBRARY, digest)
    return generate_schematic(
        extract_electrical_lane(graph),
        library,
        FIXTURE_DIR,
        pwr_flag,
        project_name="gd1",
    )


def test_schematic_states_the_label_connection_convention() -> None:
    content = _schematic()
    assert f'(text "{CONNECTION_CONVENTION_NOTE}"' in content
    assert "global net labels" in CONNECTION_CONVENTION_NOTE


def test_schematic_generation_is_deterministic() -> None:
    assert _schematic() == _schematic()


def test_long_net_names_widen_symbol_extent() -> None:
    symbol = ParsedSymbol(
        lib_id="test:T",
        pins=(
            SymbolPin(
                number="1",
                name="P",
                electrical_type="passive",
                x_mm=5.08,
                y_mm=0.0,
                rotation_deg=180.0,
                length_mm=2.54,
            ),
        ),
        embedded=[],
    )
    short = _symbol_extent(symbol, ["VCC"], reference="U1", value="T")
    long = _symbol_extent(symbol, ["LONG_NET_NAME_12345"], reference="U1", value="T")
    assert long.right - long.left > short.right - short.left


def _collision_component(refdes: str, value: str) -> ComponentView:
    return ComponentView(
        node_id=f"electrical.component.{refdes.lower()}",
        refdes=refdes,
        value=value,
        mpn="",
        lcsc="",
        jlcpcb_class="none",
        assembly="not_fitted",
        library=LibraryPin(
            symbol="test:T",
            symbol_file="",
            symbol_source="",
            symbol_source_ref="",
            symbol_sha256="",
            footprint="",
            footprint_file="",
            footprint_source="",
            footprint_source_ref="",
            footprint_sha256="",
        ),
    )


def _collision_placement(
    refdes: str,
    symbol: ParsedSymbol,
    labels: list[str],
) -> PlacedSymbol:
    component = _collision_component(refdes, "VALUE")
    extent, base, reference_box, value_box = _symbol_geometry(
        symbol, labels, reference=refdes, value=component.value
    )
    return PlacedSymbol(
        component=component,
        symbol=symbol,
        x_mm=40.64,
        y_mm=40.64,
        extent=extent,
        base_box=base,
        reference_box=reference_box,
        value_box=value_box,
    )


def test_label_property_collision_resolves_once() -> None:
    symbol = ParsedSymbol(
        lib_id="test:T",
        pins=(
            SymbolPin("1", "P", "passive", 0.0, -1.27, 270.0, 2.54),
        ),
        embedded=[],
    )
    placed = _collision_placement("U1", symbol, ["A_VERY_LONG_NET_NAME"])
    label = _LabelPlacement(
        refdes="U1",
        pin="1",
        net="A_VERY_LONG_NET_NAME",
        x_mm=40.64,
        y_mm=41.91,
        rotation=270,
        allowance=2.54,
    )
    assert _label_collisions([placed], [label]) == []
    assert placed.value_adjusted is True


def test_overlapping_labels_fail_closed() -> None:
    symbol = ParsedSymbol(
        lib_id="test:T",
        pins=(
            SymbolPin("1", "P", "passive", 0.0, 0.0, 180.0, 2.54),
            SymbolPin("2", "P", "passive", 1.27, 0.0, 180.0, 2.54),
        ),
        embedded=[],
    )
    first = _collision_placement("U1", symbol, ["LONG_NET_A", "LONG_NET_B"])
    labels = [
        _LabelPlacement("U1", "1", "LONG_NET_A", 40.64, 40.64, 0, 20.0),
        _LabelPlacement("U1", "2", "LONG_NET_B", 41.91, 40.64, 0, 20.0),
    ]
    collisions = _label_collisions([first], labels)
    assert any("fail-closed" in collision for collision in collisions)
