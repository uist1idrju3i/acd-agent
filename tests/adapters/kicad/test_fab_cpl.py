# pyright: reportUnusedImport=false,reportUnusedFunction=false

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from acd.adapters.kicad.fab import (
    BoardMeasurement,
    CplBasisError,
    FabOutputError,
    FootprintMeasurement,
    PadMeasurement,
    ViaMeasurement,
    apply_cpl_contract,
    cross_validate_cpl,
    derive_lcsc_rotation_offset,
    jlcpcb_cpl_csv,
    load_lcsc_pin_centers,
    load_lcsc_pin_geometries,
    rotate,
    verify_cpl_pin_function_declaration,
)
from acd.core.electrical import (
    BoardView,
    ComponentView,
    ElectricalLane,
    LibraryPin,
    extract_electrical_lane,
)
from acd.core.fab import FabProfile, load_fab_profile
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


def test_derive_lcsc_rotation_offset_matches_pin_functions() -> None:
    footprint = FootprintMeasurement(
        "U2",
        0.0,
        0.0,
        0.0,
        "top",
        (
            PadMeasurement("U2", "smd", -1.0, -1.0, 0.0, 1.0, 1.0, None, None, number="1"),
            PadMeasurement("U2", "smd", -1.0, 0.0, 0.0, 1.0, 1.0, None, None, number="2"),
            PadMeasurement("U2", "smd", -1.0, 1.0, 0.0, 1.0, 1.0, None, None, number="3"),
        ),
    )
    offset, note = derive_lcsc_rotation_offset(
        footprint,
        (("1", "G", -1.0, -1.0), ("2", "K", -1.0, 0.0), ("3", "A", -1.0, 1.0)),
        {"1": "G", "2": "K", "3": "A"},
        tolerance_mm=0.2,
        scale=1.0,
    )
    assert offset == 0.0
    assert "unique" in note


def test_derive_lcsc_rotation_offset_rejects_unmatched_pin_functions() -> None:
    footprint = FootprintMeasurement(
        "C1",
        0.0,
        0.0,
        0.0,
        "top",
        (
            PadMeasurement("C1", "smd", -1.0, 0.0, 0.0, 1.0, 1.0, None, None, number="1"),
            PadMeasurement("C1", "smd", 1.0, 0.0, 0.0, 1.0, 1.0, None, None, number="2"),
        ),
    )
    with pytest.raises(FabOutputError, match="pin-function mismatch"):
        derive_lcsc_rotation_offset(
            footprint,
            (("1", "A", 0.0, 1.0), ("2", "K", 0.0, 0.0)),
            {"1": "A", "2": "B"},
            scale=1.0,
        )


def test_derive_lcsc_rotation_offset_handles_ambiguous_nonpolarized_part() -> None:
    footprint = FootprintMeasurement(
        "C1",
        0.0,
        0.0,
        0.0,
        "top",
        (
            PadMeasurement("C1", "smd", 0.0, 0.0, 0.0, 1.0, 1.0, None, None, number="1"),
            PadMeasurement("C1", "smd", 0.0, 0.0, 0.0, 1.0, 1.0, None, None, number="2"),
        ),
    )
    offset, note = derive_lcsc_rotation_offset(
        footprint,
        (("1", "X", 0.0, 0.0), ("2", "X", 0.0, 0.0)),
        scale=1.0,
        polarized=False,
    )
    assert offset == 0.0
    assert "ambiguous but non-polarized" in note


def test_real_j1_evidence_derives_zero_degree_geometry_exception() -> None:
    geometries = load_lcsc_pin_geometries(ROOT / "evidence/gd1-cpl-orientation/J1.json")
    center_x = sum(item[2] for item in geometries) / len(geometries)
    center_y = sum(item[3] for item in geometries) / len(geometries)
    footprint = FootprintMeasurement(
        "J1",
        0.0,
        0.0,
        0.0,
        "top",
        tuple(
            PadMeasurement(
                "J1",
                "smd",
                x * 0.254 - center_x * 0.254,
                y * 0.254 - center_y * 0.254,
                0.0,
                width * 0.254,
                height * 0.254,
                None,
                None,
                number=str(index),
            )
            for index, (_, _, x, y, width, height) in enumerate(geometries)
        ),
    )
    offset, note = derive_lcsc_rotation_offset(
        footprint,
        load_lcsc_pin_centers(ROOT / "evidence/gd1-cpl-orientation/J1.json"),
        lcsc_pin_geometries=geometries,
        geometry_exception=True,
        tolerance_mm=0.01,
    )
    assert offset == 0.0
    assert "declared-geometry-exception" in note


def test_geometry_exception_requires_provenance_at_verification_boundary() -> None:
    footprint = FootprintMeasurement("J1", 0.0, 0.0, 0.0, "top", ())
    with pytest.raises(FabOutputError, match="KiCad pin functions are required"):
        derive_lcsc_rotation_offset(
            footprint,
            (),
            geometry_exception=False,
        )


def test_geometry_exception_rejects_symmetric_geometry() -> None:
    footprint = FootprintMeasurement(
        "J1",
        0.0,
        0.0,
        0.0,
        "top",
        (
            PadMeasurement("J1", "smd", -1.0, 0.0, 0.0, 1.0, 1.0, None, None, number="1"),
            PadMeasurement("J1", "smd", 1.0, 0.0, 0.0, 1.0, 1.0, None, None, number="2"),
        ),
    )
    with pytest.raises(FabOutputError, match="ambiguous geometry"):
        derive_lcsc_rotation_offset(
            footprint,
            (("1", "X", -1.0, 0.0), ("2", "X", 1.0, 0.0)),
            lcsc_pin_geometries=(
                ("1", "X", -1.0 / 0.254, 0.0, 1.0 / 0.254, 1.0 / 0.254),
                ("2", "X", 1.0 / 0.254, 0.0, 1.0 / 0.254, 1.0 / 0.254),
            ),
            geometry_exception=True,
            polarized=False,
            tolerance_mm=0.01,
            scale=0.254,
        )


@pytest.mark.parametrize("refdes", ["D1", "U2", "J1"])
def test_cpl_pin_functions_match_pinned_kicad_symbols(refdes: str, tmp_path: Path) -> None:
    note = verify_cpl_pin_function_declaration(
        _golden_component(refdes, tmp_path), ROOT / "fixtures/golden-design-1"
    )
    assert "symbol-verified" in note


@pytest.mark.parametrize("refdes", ["D1", "U2", "J1"])
def test_cpl_pin_functions_match_actual_pinned_kicad_symbols(refdes: str) -> None:
    note = verify_cpl_pin_function_declaration(
        _actual_golden_component(refdes), ROOT / "fixtures/golden-design-1"
    )
    assert "symbol-verified" in note


def test_cpl_pin_function_declaration_mismatch_fails_closed(tmp_path: Path) -> None:
    component = _golden_component("D1", tmp_path)
    with pytest.raises(FabOutputError, match="CPL pin function mismatch"):
        verify_cpl_pin_function_declaration(
            replace(
                component,
                cpl_rotation_pin_functions={"1": "A", "2": "K"},
            ),
            ROOT / "fixtures/golden-design-1",
        )


@pytest.mark.parametrize(
    ("angle", "expected"),
    [(0.0, (3.15, 2.3)), (90.0, (2.3, -3.15)), (180.0, (-3.15, -2.3)), (270.0, (-2.3, 3.15))],
)
def test_fab_rotation_matches_kicad(angle: float, expected: tuple[float, float]) -> None:
    assert rotate(3.15, 2.3, angle) == pytest.approx(expected)


def test_cpl_requires_exact_fitted_set() -> None:
    rows = ({"Ref": "C1", "PosX": "1", "PosY": "2", "Rot": "0", "Side": "top"},)
    try:
        jlcpcb_cpl_csv(rows, {"C1", "C2"})
    except FabOutputError:
        pass
    else:
        raise AssertionError("CPL mismatch must fail closed")


def test_cpl_basis_gate_accepts_coincident_centers() -> None:
    component = _bom_component("C1", "test")
    lane = _bom_lane(component)
    board = _cpl_board()
    coincident = FootprintMeasurement(
        "C1",
        0.0,
        0.0,
        0.0,
        "F.Cu",
        (
            PadMeasurement("C1", "smd", -1.0, 0.0, 0.0, 0.5, 0.5, None, None),
            PadMeasurement("C1", "smd", 1.0, 0.0, 0.0, 0.5, 0.5, None, None),
        ),
        body_bbox_mm=(-1.0, 0.0, 1.0, 0.0),
    )
    board = BoardMeasurement((coincident,), (), None, None, None, None, (), 0)
    rows, report = apply_cpl_contract(_cpl_rows(), board, lane, _cpl_profile(), {"C1"})
    assert rows[0]["PosX"] == "0.000000"
    assert report["status"] == "pass"


def test_cpl_basis_gate_rejects_divergent_centers_without_declaration() -> None:
    with pytest.raises(CplBasisError, match="position basis is unknown"):
        apply_cpl_contract(
            _cpl_rows(),
            _cpl_board(),
            _bom_lane(_bom_component("C1", "test")),
            _cpl_profile(),
            {"C1"},
        )


def test_cpl_basis_gate_rejects_declaration_without_provenance() -> None:
    component = replace(_bom_component("C1", "test"), cpl_position_basis="pad_bbox_center")
    with pytest.raises(CplBasisError, match="no source URL"):
        apply_cpl_contract(_cpl_rows(), _cpl_board(), _bom_lane(component), _cpl_profile(), {"C1"})


def test_cpl_basis_gate_emits_declared_provenanced_center() -> None:
    component = replace(
        _bom_component("C1", "test"),
        cpl_position_basis="pad_bbox_center",
        cpl_position_source_url="https://example.com/centroid",
        cpl_position_evidence_at="2026-08-13T00:00:00Z",
        cpl_position_evidence_basis="confirmed",
        cpl_position_evidence_method="test",
        cpl_position_evidence_revision="r1",
        cpl_position_evidence_note="test evidence",
    )
    rows, report = apply_cpl_contract(
        _cpl_rows(), _cpl_board(), _bom_lane(component), _cpl_profile(), {"C1"}
    )
    assert rows[0]["PosX"] == "0.000000"
    assert rows[0]["PosY"] == "-1.000000"
    assert report["status"] == "pass"


def test_cpl_estimated_position_remains_unknown_without_blocking_projection() -> None:
    component = replace(
        _bom_component("C1", "test"),
        cpl_position_basis="pad_bbox_center",
        cpl_position_source_url="https://example.com/centroid",
        cpl_position_evidence_at="2026-08-13T00:00:00Z",
        cpl_position_evidence_basis="estimated",
    )
    rows, report = apply_cpl_contract(
        _cpl_rows(), _cpl_board(), _bom_lane(component), _cpl_profile(), {"C1"}
    )
    assert rows[0]["PosY"] == "-1.000000"
    assert report["status"] == "fail"
    unknowns = cast(dict[str, object], report["unknowns"])
    assert unknowns["cpl_position_basis"] == ["C1"]


def test_cross_validate_cpl_rejects_rotation_offset_mismatch(tmp_path: Path) -> None:
    cpl_path = tmp_path / "cpl.csv"
    cpl_path.write_text(
        "Designator,Mid X,Mid Y,Rotation,Layer\nC1,0.000000,-1.000000,10.000000,Top\n",
        encoding="utf-8",
    )
    with pytest.raises(FabOutputError, match="CPL rotation differs"):
        cross_validate_cpl(
            cpl_path,
            (
                {
                    "Ref": "C1",
                    "PosX": "0.000000",
                    "PosY": "0.000000",
                    "Rot": "10.000000",
                    "Side": "top",
                },
            ),
            _cpl_board(),
            {"C1"},
            {"C1": "pad_bbox_center"},
            {"C1": 0.0},
        )
