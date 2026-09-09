"""Content-fitted KiCad paper selection tests."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from pathlib import Path

import pytest

from acd.adapters.kicad.board import generate_board
from acd.adapters.kicad.library import FootprintLibrary, SymbolLibrary
from acd.adapters.kicad.paper import select_paper
from acd.adapters.kicad.schematic import PWR_FLAG_LIB_ID, generate_schematic
from acd.core.electrical import (
    ComponentView,
    ElectricalLane,
    LibraryPin,
    NetView,
    PinView,
    extract_electrical_lane,
)
from acd.pipeline.gd1_board import placements_from_graph
from tests.pipeline.gd1_negative_fixtures import (
    FIXTURE_DIR,
    load_fixture_fab_profile,
    load_gd1_graph,
)

_SYMBOL_LIB = """(kicad_symbol_lib (version 20211014) (generator kicad_symbol_editor)
  (symbol "T" (pin_names hide) (pin_numbers hide) (in_bom yes) (on_board yes)
    (property "Reference" "U" (at 0 0 0)
      (effects (font (size 1.27 1.27))))
    (symbol "T_0_1"
      (rectangle (start -2.54 -1.27) (end 2.54 1.27)
        (stroke (width 0) (type default)) (fill (type background))))
    (symbol "T_1_1"
      (pin passive line (at 5.08 0 180) (length 2.54)
        (name "P" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))))
  (symbol "FLAG" (pin_names hide) (pin_numbers hide) (in_bom yes) (on_board yes)
    (property "Reference" "#PWR" (at 0 0 0)
      (effects (font (size 1.27 1.27))))
    (symbol "FLAG_1_1"
      (pin power_in line (at 0 0 0) (length 0)
        (name "pwr" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))))
  (symbol "PWRIN" (pin_names hide) (pin_numbers hide) (in_bom yes) (on_board yes)
    (property "Reference" "U" (at 0 0 0)
      (effects (font (size 1.27 1.27))))
    (symbol "PWRIN_0_1"
      (rectangle (start -2.54 -1.27) (end 2.54 1.27)
        (stroke (width 0) (type default)) (fill (type background))))
    (symbol "PWRIN_1_1"
      (pin power_in line (at 5.08 0 180) (length 2.54)
        (name "V" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))))
)
"""


@pytest.mark.parametrize(
    ("width_mm", "height_mm", "expected"),
    [
        (297.0, 210.0, "A4"),
        (297.1, 210.0, "A3"),
        (297.0, 210.1, "A3"),
        (420.0, 297.0, "A3"),
        (594.0, 420.0, "A2"),
        (841.0, 594.0, "A1"),
        (1189.0, 841.0, "A0"),
        (1.0, 1.0, "A4"),
    ],
)
def test_select_paper_boundaries(width_mm: float, height_mm: float, expected: str) -> None:
    assert select_paper(width_mm, height_mm) == expected


def test_select_paper_rejects_a0_overflow() -> None:
    with pytest.raises(ValueError, match="exceeds A0"):
        select_paper(1189.1, 841.0)
    with pytest.raises(ValueError, match="exceeds A0"):
        select_paper(1189.0, 841.1)


def test_select_paper_rejects_non_positive_dimensions() -> None:
    with pytest.raises(ValueError, match="positive"):
        select_paper(0.0, 100.0)
    with pytest.raises(ValueError, match="positive"):
        select_paper(100.0, -1.0)


def _paper_of(content: str) -> str:
    match = re.search(r'\(paper "([A-Z][0-9]+)"\)', content)
    assert match is not None
    return match.group(1)


def _schematic_for_count(tmp_path: Path, count: int, flag_nets: int = 0) -> str:
    fixture_dir = tmp_path / "fixture"
    lib_dir = fixture_dir / "libraries"
    lib_dir.mkdir(parents=True)
    symbol_path = lib_dir / "test.kicad_sym"
    symbol_path.write_text(_SYMBOL_LIB, encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(symbol_path.read_bytes()).hexdigest()

    lane = extract_electrical_lane(load_gd1_graph())
    library_pin = LibraryPin(
        symbol="test:PWRIN",
        symbol_file="libraries/test.kicad_sym",
        symbol_source="fixture",
        symbol_source_ref="test",
        symbol_sha256=digest,
        footprint="",
        footprint_file="",
        footprint_source="",
        footprint_source_ref="",
        footprint_sha256="",
    )
    components = tuple(
        ComponentView(
            node_id=f"electrical.component.t{index:02d}",
            refdes=f"T{index:02d}",
            value="T",
            mpn="",
            lcsc="",
            jlcpcb_class="none",
            assembly="not_fitted",
            library=library_pin,
        )
        for index in range(1, count + 1)
    )
    nets = tuple(
        NetView(
            node_id=f"net.pwr{index:02d}",
            name=f"VCC_{index:02d}",
            voltage_nominal_v=3.3,
            width_basis="power_rail",
            current_max_a=0.1,
            width_basis_source=None,
            manufacturing_minimum_mm=None,
            manufacturing_margin_mm=None,
        )
        for index in range(1, flag_nets + 1)
    )
    pins = tuple(
        PinView(
            node_id=f"electrical.pin.t{index:02d}.1",
            component_id=component.node_id,
            pad="1",
            net_id=f"net.pwr{index:02d}" if index <= flag_nets else None,
            no_connect=index > flag_nets,
        )
        for index, component in enumerate(components, start=1)
    )
    test_lane = ElectricalLane(
        components=components,
        nets=nets,
        pins=pins,
        board=lane.board,
    )

    symbol_library = SymbolLibrary()
    pwr_flag = symbol_library.load("test:FLAG", symbol_path, digest)
    return generate_schematic(
        test_lane,
        symbol_library,
        fixture_dir,
        pwr_flag,
        project_name="test",
    )


@pytest.mark.parametrize(
    ("count", "expected_paper"),
    [
        (1, "A4"),
        (4, "A4"),
        (10, "A3"),
        (36, "A1"),
    ],
)
def test_schematic_paper_fits_content(tmp_path: Path, count: int, expected_paper: str) -> None:
    content = _schematic_for_count(tmp_path, count)
    assert _paper_of(content) == expected_paper


def test_schematic_columns_shrink_for_small_sheets(tmp_path: Path) -> None:
    content = _schematic_for_count(tmp_path, 4)
    # n=4 uses 2 columns: the third component starts row two at the left edge.
    assert content.count("(symbol ") >= 4
    assert "(at 40.64 110.49 0)" in content


def test_pwr_flags_fill_spare_cells_then_new_row(tmp_path: Path) -> None:
    # n=10 → cols=4, rows=3; the last row holds 2 comps so 2 spare cells take
    # the first two flags and the rest continue from the next grid row.
    content = _schematic_for_count(tmp_path, 10, flag_nets=10)
    assert "(at 200.66 180.34 0)" in content  # PWR01: last row, col 2
    assert "(at 280.67 180.34 0)" in content  # PWR02: last row, col 3
    assert "(at 40.64 250.19 0)" in content  # PWR03: new row, col 0
    assert "(at 280.67 320.04 0)" in content  # PWR10: row 4, col 3
    assert _paper_of(content) == "A2"


_KICAD_SYMBOLS = Path("/usr/share/kicad/symbols")


def test_gd1_schematic_places_flags_on_the_row_after_a_full_grid() -> None:
    power_library = _KICAD_SYMBOLS / "power.kicad_sym"
    if not _KICAD_SYMBOLS.is_dir() or not (
        FIXTURE_DIR.parent.parent / "libraries/Espressif.kicad_sym"
    ).is_file():
        pytest.skip("host KiCad symbol libraries are unavailable")
    graph = load_gd1_graph()
    lane = extract_electrical_lane(graph)
    library = SymbolLibrary()
    digest = "sha256:" + hashlib.sha256(power_library.read_bytes()).hexdigest()
    pwr_flag = library.load(PWR_FLAG_LIB_ID, power_library, digest)
    content = generate_schematic(
        lane, library, FIXTURE_DIR, pwr_flag, project_name="gd1"
    )
    flag_count = content.count('lib_id "power:PWR_FLAG"') - 1
    assert flag_count >= 1
    # n=30 → cols=6 fills five rows exactly, so flags start on row 5.
    assert "(at 40.64 391.16 0)" in content


_KICAD_FOOTPRINTS = Path("/usr/share/kicad/footprints")


def _gd1_board_paper(board_width: float | None = None, board_height: float | None = None) -> str:
    if not _KICAD_FOOTPRINTS.is_dir():
        pytest.skip("host KiCad footprint library is unavailable")
    graph = load_gd1_graph()
    lane = extract_electrical_lane(graph)
    if board_width is not None and board_height is not None:
        lane = replace(
            lane,
            board=replace(lane.board, width_mm=board_width, height_mm=board_height),
        )
    projection = generate_board(
        lane,
        FootprintLibrary(),
        FIXTURE_DIR,
        load_fixture_fab_profile(),
        placements_from_graph(graph, lane),
    )
    return _paper_of(projection.content)


def test_board_paper_a4_for_gd1() -> None:
    assert _gd1_board_paper() == "A4"


def test_board_paper_a3_for_300x200_board() -> None:
    assert _gd1_board_paper(300.0, 200.0) == "A3"
