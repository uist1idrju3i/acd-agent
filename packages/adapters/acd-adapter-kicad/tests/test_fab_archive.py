# pyright: reportUnusedImport=false,reportUnusedFunction=false

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from acd_adapter_kicad.fab import (
    BoardMeasurement,
    FootprintMeasurement,
    PadMeasurement,
    ViaMeasurement,
    deterministic_zip,
)
from acd_core.electrical import (
    BoardView,
    ComponentView,
    ElectricalLane,
    LibraryPin,
    extract_electrical_lane,
)
from acd_core.fab import FabProfile, load_fab_profile
from acd_core.routing_width import NetWidthRequirement
from acd_schema import DesignGraph

ROOT = Path(__file__).parents[4]


PROFILE = load_fab_profile(ROOT / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json")


def _bom_lane(*components: ComponentView) -> ElectricalLane:
    library = BoardView(
        "board",
        30.0,
        25.0,
        2,
        1.6,
        "mm",
        "lower-left",
        "up",
        0.15,
        0.15,
        0.2,
        0.4,
        0.2,
        False,
    )
    return ElectricalLane(tuple(components), (), (), library)


def _golden_component(refdes: str, symbol_dir: Path) -> ComponentView:
    graph = DesignGraph.model_validate(
        json.loads((ROOT / "fixtures/golden-design-1/graph.json").read_text(encoding="utf-8"))
    )
    lane = extract_electrical_lane(graph)
    component = next(component for component in lane.components if component.refdes == refdes)
    symbol_name = component.library.symbol.split(":", 1)[1]
    pins = [
        f'      (pin passive line (at 0 0 0) (length 2.54) (name "{function}") (number "{number}"))'
        for number, function in component.cpl_rotation_pin_functions.items()
        if number not in component.cpl_rotation_unverified_pads
    ]
    symbol_path = symbol_dir / f"{refdes}.kicad_sym"
    symbol_path.write_text(
        "(kicad_symbol_lib (version 20231120) (generator kicad_symbol_editor) "
        f'(symbol "{symbol_name}" (symbol "{symbol_name}_0_1" ' + " ".join(pins) + ")))\n",
        encoding="utf-8",
    )
    symbol_hash = "sha256:" + hashlib.sha256(symbol_path.read_bytes()).hexdigest()
    return replace(
        component,
        library=replace(
            component.library,
            symbol_file=str(symbol_path),
            symbol_sha256=symbol_hash,
        ),
    )


def _actual_golden_component(refdes: str) -> ComponentView:
    graph = DesignGraph.model_validate(
        json.loads((ROOT / "fixtures/golden-design-1/graph.json").read_text(encoding="utf-8"))
    )
    lane = extract_electrical_lane(graph)
    component = next(component for component in lane.components if component.refdes == refdes)
    path = Path(component.library.symbol_file)
    if not path.is_absolute():
        path = ROOT / "fixtures/golden-design-1" / path
    if not path.is_file():
        pytest.skip(f"pinned KiCad library not present in this environment: {path}")
    return component


def _bom_component(
    refdes: str,
    value: str,
    *,
    assembly: str = "fitted",
    lcsc: str = "C720477",
    mpn: str = "TS-1088-AR02016",
) -> ComponentView:
    footprint = "Button_Switch_SMD:SW_SPST_TL3301"
    return ComponentView(
        refdes,
        refdes,
        value,
        mpn,
        lcsc,
        "basic",
        assembly,
        LibraryPin(
            "Switch:SW_Push",
            "symbol.kicad_sym",
            "fixture",
            "r1",
            "sha256:symbol",
            footprint,
            "footprint.kicad_mod",
            "fixture",
            "r1",
            "sha256:footprint",
        ),
    )


def _measurement(via: ViaMeasurement) -> BoardMeasurement:
    return BoardMeasurement((), (via,), None, None, None, None, (), 0)


def _width_requirement() -> NetWidthRequirement:
    return NetWidthRequirement(
        "PWR",
        "manufacturing_minimum",
        None,
        "logic signal manufacturing basis",
        0.1,
        0.15,
        0.1,
        0.15,
        True,
    )


def _cpl_profile(*, position_basis: str = "footprint_origin") -> FabProfile:
    data = dict(PROFILE.data)
    data["cpl_contract"] = {
        "position_basis": position_basis,
        "position_source_index": 0,
        "position_evidence_status": "confirmed",
        "position_note": "test",
        "rotation_basis": "kicad_footprint",
        "rotation_source_index": 0,
        "rotation_evidence_status": "confirmed",
        "rotation_note": "test",
    }
    return FabProfile(data)


def _cpl_board() -> BoardMeasurement:
    pads = (
        PadMeasurement("C1", "smd", -1.0, 1.0, 0.0, 0.5, 0.5, None, None),
        PadMeasurement("C1", "smd", 1.0, 1.0, 0.0, 0.5, 0.5, None, None),
    )
    fp = FootprintMeasurement(
        "C1",
        0.0,
        0.0,
        0.0,
        "F.Cu",
        pads,
        body_bbox_mm=(-1.0, -1.0, 1.0, 1.0),
    )
    return BoardMeasurement((fp,), (), None, None, None, None, (), 0)


def _cpl_rows() -> tuple[dict[str, str], ...]:
    return (
        {
            "Ref": "C1",
            "PosX": "0.000000",
            "PosY": "0.000000",
            "Rot": "0.000000",
            "Side": "top",
        },
    )


def _write_bom(path: Path, designator: str, lcsc: str = "C720477") -> None:
    path.write_text(
        "Comment,Designator,Footprint,LCSC Part #\n"
        f"TS-1088-AR02016,{designator},Button_Switch_SMD:SW_SPST_TL3301,{lcsc}\n"
    )


def test_zip_is_byte_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    member = source / "a.gtl"
    member.write_bytes(b"gerber")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    deterministic_zip(first, (member,), source)
    deterministic_zip(second, (member,), source)
    assert first.read_bytes() == second.read_bytes()
