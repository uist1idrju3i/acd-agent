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
    LABEL_ALLOWANCE,
    PWR_FLAG_LIB_ID,
    PlacedSymbol,
    _global_label,
    _label_collisions,
    _label_rotation,
    _LabelPlacement,
    _pin_point,
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
    short = _symbol_geometry(symbol, ["VCC"], reference="U1", value="T")[0]
    long = _symbol_geometry(
        symbol,
        ["LONG_NET_NAME_12345"],
        reference="U1",
        value="T",
    )[0]
    assert long.right - long.left > short.right - short.left


def test_pin_point_preserves_off_grid_library_offset() -> None:
    pin = SymbolPin("1", "P", "passive", 1.905, 0.0, 180.0, 2.54)
    x_mm, y_mm = _pin_point(40.64, 40.64, pin)
    label = _global_label("NET", x_mm, y_mm, 0, "U1.1")
    assert (x_mm, y_mm) == (42.545, 40.64)
    assert label[3][1:3] == ["42.545", "40.64"]


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


def test_vertical_pin_labels_move_properties_beside_body() -> None:
    symbol = ParsedSymbol(
        lib_id="test:T",
        pins=(
            SymbolPin("1", "P", "passive", 0.0, 3.81, 270.0, 2.54),
            SymbolPin("2", "P", "passive", 0.0, -3.81, 90.0, 2.54),
        ),
        embedded=[],
    )
    net_names = ["VBUS_5V", "GND"]
    placed = _collision_placement("C1", symbol, net_names)
    labels: list[_LabelPlacement] = []
    for pin, net in zip(symbol.pins, net_names, strict=True):
        px, py = _pin_point(placed.x_mm, placed.y_mm, pin)
        labels.append(
            _LabelPlacement(
                refdes="C1",
                pin=pin.number,
                net=net,
                x_mm=px,
                y_mm=py,
                rotation=_label_rotation(pin),
                allowance=len(net) * 1.27 * 0.9 + LABEL_ALLOWANCE,
            )
        )
    assert _label_collisions([placed], labels) == []
    assert placed.reference_box.left > placed.base_box.right
    for box in (placed.reference_box, placed.value_box):
        assert placed.extent.left <= box.left
        assert placed.extent.right >= box.right
        assert placed.extent.top <= box.top
        assert placed.extent.bottom >= box.bottom


def test_horizontal_pins_keep_properties_above_and_below() -> None:
    symbol = ParsedSymbol(
        lib_id="test:T",
        pins=(
            SymbolPin("1", "P", "passive", -2.54, 0.0, 0.0, 2.54),
            SymbolPin("2", "P", "passive", 2.54, 0.0, 180.0, 2.54),
        ),
        embedded=[],
    )
    placed = _collision_placement("U1", symbol, ["NET_A", "NET_B"])
    reference_center_x = (placed.reference_box.left + placed.reference_box.right) / 2
    value_center_x = (placed.value_box.left + placed.value_box.right) / 2
    assert reference_center_x == 0.0
    assert value_center_x == 0.0
    assert placed.reference_box.bottom <= placed.base_box.top
    assert placed.value_box.top >= placed.base_box.bottom


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
