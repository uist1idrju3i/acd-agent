# pyright: reportUnusedImport=false,reportUnusedFunction=false

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from acd.adapters.kicad.fab import (
    BoardMeasurement,
    FootprintMeasurement,
    PadMeasurement,
    ViaMeasurement,
    derive_lcsc_rotation_offset,
    load_lcsc_pin_centers,
    run_dfm,
)
from acd.core.electrical import (
    BoardView,
    ComponentView,
    ElectricalLane,
    LibraryPin,
    extract_electrical_lane,
)
from acd.core.fab import FabProfile, ProcessAllowanceView, load_fab_profile
from acd.core.routing_width import NetWidthRequirement
from acd.schema import DesignGraph

ROOT = Path(__file__).parents[3]


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


def test_real_d1_evidence_derives_zero_degree_offset() -> None:
    footprint = FootprintMeasurement(
        "D1",
        0.0,
        0.0,
        0.0,
        "top",
        (
            PadMeasurement("D1", "smd", -0.7875, 0.0, 0.0, 1.0, 1.0, None, None, number="1"),
            PadMeasurement("D1", "smd", 0.7875, 0.0, 0.0, 1.0, 1.0, None, None, number="2"),
        ),
    )
    offset, _ = derive_lcsc_rotation_offset(
        footprint,
        load_lcsc_pin_centers(ROOT / "evidence/gd1-cpl-orientation/D1.json"),
        {"1": "K", "2": "A"},
        tolerance_mm=0.3,
    )
    assert offset == 0.0


def test_real_u2_evidence_derives_180_degree_offset() -> None:
    footprint = FootprintMeasurement(
        "U2",
        0.0,
        0.0,
        90.0,
        "top",
        (
            PadMeasurement("U2", "smd", -2.3, 3.15, 0.0, 1.0, 1.0, None, None, number="1"),
            PadMeasurement("U2", "smd", 0.0, 3.15, 0.0, 1.0, 1.0, None, None, number="2"),
            PadMeasurement("U2", "smd", 0.0, -3.15, 0.0, 1.0, 1.0, None, None, number="2"),
            PadMeasurement("U2", "smd", 2.3, 3.15, 0.0, 1.0, 1.0, None, None, number="3"),
        ),
    )
    offset, _ = derive_lcsc_rotation_offset(
        footprint,
        load_lcsc_pin_centers(ROOT / "evidence/gd1-cpl-orientation/U2.json"),
        {"1": "GND", "2": "VO", "3": "VI"},
        {"VO": "VOUT", "VI": "VIN"},
        tolerance_mm=0.3,
    )
    assert offset == 180.0


def test_small_via_requires_allowance() -> None:
    via = ViaMeasurement(1.0, 2.0, 0.4, 0.2, ("F.Cu", "B.Cu"))
    report = run_dfm(_measurement(via), PROFILE, "r1", (), edge_clearance_mm=0.3)
    assert report["status"] == "fail"
    assert any(
        item["rule_id"] == "via-hole-small-diameter-cost"
        for item in report["findings"]  # type: ignore[index]
    )
    allowance = ProcessAllowanceView(
        "allowance",
        "via-hole-small-diameter-cost",
        "BGA",
        "req",
        ("cost",),
    )
    report = run_dfm(_measurement(via), PROFILE, "r1", (allowance,), edge_clearance_mm=0.3)
    assert report["status"] == "pass"


def test_via_in_smd_pad_requires_allowance() -> None:
    pad = PadMeasurement("C1", "smd", 1.0, 2.0, 0.0, 0.5, 0.5, None, None)
    board = BoardMeasurement(
        (FootprintMeasurement("C1", 1.0, 2.0, 0.0, "F.Cu", (pad,)),),
        (ViaMeasurement(1.0, 2.0, 0.4, 0.2, ("F.Cu", "B.Cu")),),
        None,
        None,
        None,
        None,
        (),
        0,
    )
    report = run_dfm(board, PROFILE, "r1", (), edge_clearance_mm=0.3)
    assert report["status"] == "fail"
    assert any(item["rule_id"] == "via-in-pad-process" for item in report["findings"])  # type: ignore[index]


def test_capability_violation_cannot_be_allowed() -> None:
    via = ViaMeasurement(1.0, 2.0, 0.2, 0.1, ("F.Cu", "B.Cu"))
    report = run_dfm(_measurement(via), PROFILE, "r1", (), edge_clearance_mm=0.3)
    findings = cast(list[dict[str, object]], report["findings"])
    capability = next(item for item in findings if item["rule_id"] == "via-hole-capability")
    assert capability["status"] == "fail"
    assert capability["allowance"] is None


def test_oval_annular_ring_uses_each_axis() -> None:
    pad = PadMeasurement("J1", "through-hole", 0.0, 0.0, 0.0, 1.1, 2.2, 0.6, None, 0.6, 1.7)
    assert pad.annular_ring_mm == pytest.approx(0.25)
