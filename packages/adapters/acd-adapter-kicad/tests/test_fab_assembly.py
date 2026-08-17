# pyright: reportUnusedImport=false,reportUnusedFunction=false

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from acd_adapter_kicad.fab import (
    BoardMeasurement,
    FabOutputError,
    FootprintMeasurement,
    PadMeasurement,
    ViaMeasurement,
    cross_validate_bom,
    jlcpcb_bom_csv,
)
from acd_adapter_kicad.library import LibraryPinError
from acd_adapter_kicad.overlay import apply_overlay
from acd_core.electrical import (
    BoardView,
    ComponentView,
    ElectricalLane,
    LibraryPin,
    extract_electrical_lane,
)
from acd_core.fab import FabProfile, load_fab_profile
from acd_core.routing_width import NetWidthRequirement
from acd_core.sexpr import SExpr
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


def test_jlcpcb_bom_groups_by_fab_part_and_uses_mpn_for_mixed_values() -> None:
    lane = _bom_lane(
        _bom_component("SW1", "RESET"),
        _bom_component("SW2", "BOOT"),
        _bom_component("R1", "not fitted", assembly="not_fitted"),
    )
    rows = list(csv.DictReader(jlcpcb_bom_csv(lane).splitlines()))
    assert len(rows) == 1
    assert rows[0]["Designator"] == "SW1,SW2"
    assert rows[0]["Comment"] == "TS-1088-AR02016"
    assert rows[0]["LCSC Part #"] == "C720477"
    assert "R1" not in rows[0]["Designator"]


def test_bom_cross_validation_rejects_missing_designator(tmp_path: Path) -> None:
    lane = _bom_lane(_bom_component("SW1", "RESET"), _bom_component("SW2", "BOOT"))
    path = tmp_path / "bom.csv"
    _write_bom(path, "SW1")
    with pytest.raises(FabOutputError):
        cross_validate_bom(path, lane, {"SW1", "SW2"})


def test_bom_cross_validation_rejects_duplicate_designator(tmp_path: Path) -> None:
    lane = _bom_lane(_bom_component("SW1", "RESET"), _bom_component("SW2", "BOOT"))
    path = tmp_path / "bom.csv"
    path.write_text(
        "Comment,Designator,Footprint,LCSC Part #\n"
        "TS-1088-AR02016,SW1,Button_Switch_SMD:SW_SPST_TL3301,C720477\n"
        "TS-1088-AR02016,SW1,Button_Switch_SMD:SW_SPST_TL3301,C720477\n"
    )
    with pytest.raises(FabOutputError):
        cross_validate_bom(path, lane, {"SW1", "SW2"})


def test_bom_cross_validation_rejects_lcsc_mismatch(tmp_path: Path) -> None:
    lane = _bom_lane(_bom_component("SW1", "RESET"))
    path = tmp_path / "bom.csv"
    _write_bom(path, "SW1", lcsc="C999999")
    with pytest.raises(FabOutputError):
        cross_validate_bom(path, lane, {"SW1"})


def test_overlay_grows_oval_axes(tmp_path: Path) -> None:
    source = tmp_path / "source.kicad_mod"
    source.write_text(
        '(footprint "X" (pad "SH" thru_hole oval (at 0 0) (size 1 2) (drill oval 0.6 1.6)))\n'
    )
    source_hash = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    overlay = tmp_path / "overlay.json"
    overlay.write_text(
        json.dumps(
            {
                "source_footprint_file": str(source),
                "source_footprint_sha256": source_hash,
                "target": {"footprint": "X"},
                "overlay_id": "test-overlay",
                "reason": "test",
                "evidence": {
                    "fab_profile": "test",
                    "rule_id": "pth-annular-ring-prefer-025",
                    "url": "https://example.com",
                    "fetched_at": "2026-08-11T00:00:00Z",
                },
                "ops": [
                    {
                        "op": "grow_pad_annular_ring",
                        "pad_number": "SH",
                        "target_annular_ring_mm": 0.25,
                    }
                ],
            }
        )
    )
    overlay_hash = "sha256:" + hashlib.sha256(overlay.read_bytes()).hexdigest()
    raw: list[SExpr] = [
        "footprint",
        "X",
        [
            "pad",
            "SH",
            "thru_hole",
            "oval",
            ["at", "0", "0"],
            ["size", "1", "2"],
            ["drill", "oval", "0.6", "1.6"],
        ],
    ]
    updated, _ = apply_overlay(raw, source, overlay, overlay_hash, PROFILE)
    assert updated[2][5] == ["size", "1.1", "2.1"]


def test_overlay_rejects_unknown_op(tmp_path: Path) -> None:
    source = tmp_path / "source.kicad_mod"
    source.write_text(
        '(footprint "X" (pad "SH" thru_hole circle (at 0 0) (size 1 1) (drill 0.6))\n'
    )
    source_hash = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    overlay = tmp_path / "overlay.json"
    overlay.write_text(
        json.dumps(
            {
                "source_footprint_file": str(source),
                "source_footprint_sha256": source_hash,
                "target": {"footprint": "X"},
                "overlay_id": "test-overlay",
                "reason": "test",
                "evidence": {
                    "fab_profile": "test",
                    "rule_id": "pth-annular-ring-prefer-025",
                    "url": "https://example.com",
                    "fetched_at": "2026-08-11T00:00:00Z",
                },
                "ops": [
                    {
                        "op": "unknown",
                        "pad_number": "SH",
                        "target_annular_ring_mm": 0.25,
                    }
                ],
            }
        )
    )
    overlay_hash = "sha256:" + hashlib.sha256(overlay.read_bytes()).hexdigest()
    raw: list[SExpr] = [
        "footprint",
        "X",
        [
            "pad",
            "SH",
            "thru_hole",
            "circle",
            ["at", "0", "0"],
            ["size", "1", "1"],
            ["drill", "0.6"],
        ],
    ]
    with pytest.raises(LibraryPinError):
        apply_overlay(raw, source, overlay, overlay_hash, PROFILE)
