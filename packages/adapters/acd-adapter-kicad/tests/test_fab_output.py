import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from acd_adapter_kicad.fab import (
    BoardMeasurement,
    CplBasisError,
    FabOutputError,
    FootprintMeasurement,
    PadMeasurement,
    ViaMeasurement,
    apply_cpl_contract,
    cross_validate_bom,
    deterministic_zip,
    jlcpcb_bom_csv,
    jlcpcb_cpl_csv,
    rotate,
    run_dfm,
)
from acd_adapter_kicad.library import LibraryPinError
from acd_adapter_kicad.overlay import apply_overlay
from acd_core.electrical import BoardView, ComponentView, ElectricalLane, LibraryPin
from acd_core.fab import FabProfile, ProcessAllowanceView, load_fab_profile
from acd_core.sexpr import SExpr

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


@pytest.mark.parametrize(
    ("angle", "expected"),
    [(0.0, (3.15, 2.3)), (90.0, (2.3, -3.15)), (180.0, (-3.15, -2.3)), (270.0, (-2.3, 3.15))],
)
def test_fab_rotation_matches_kicad(angle: float, expected: tuple[float, float]) -> None:
    assert rotate(3.15, 2.3, angle) == pytest.approx(expected)


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


def test_via_copper_edge_touch_without_drill_overlap_is_not_via_in_pad() -> None:
    pad = PadMeasurement("TP1", "smd", 27.55, 12.55, 0.0, 1.5, 1.5, None, "+3V3")
    via = ViaMeasurement(26.5219, 11.791, 0.6, 0.3, ("F.Cu", "B.Cu"))
    board = BoardMeasurement(
        (FootprintMeasurement("TP1", 27.55, 12.55, 0.0, "F.Cu", (pad,)),),
        (via,),
        None,
        None,
        None,
        None,
        (),
        0,
    )
    report = run_dfm(board, PROFILE, "r1", (), edge_clearance_mm=0.3)
    assert not any(item["rule_id"] == "via-in-pad-process" for item in report["findings"])  # type: ignore[index]


def test_capability_violation_cannot_be_allowed() -> None:
    via = ViaMeasurement(1.0, 2.0, 0.2, 0.1, ("F.Cu", "B.Cu"))
    report = run_dfm(_measurement(via), PROFILE, "r1", (), edge_clearance_mm=0.3)
    findings = cast(list[dict[str, object]], report["findings"])
    capability = next(item for item in findings if item["rule_id"] == "via-hole-capability")
    assert capability["status"] == "fail"
    assert capability["allowance"] is None


def test_oval_annular_ring_uses_each_axis() -> None:
    pad = PadMeasurement(
        "J1", "through-hole", 0.0, 0.0, 0.0, 1.1, 2.2, 0.6, None, 0.6, 1.7
    )
    assert pad.annular_ring_mm == pytest.approx(0.25)


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
    rows, report = apply_cpl_contract(
        _cpl_rows(), board, lane, _cpl_profile(), {"C1"}
    )
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
        apply_cpl_contract(
            _cpl_rows(), _cpl_board(), _bom_lane(component), _cpl_profile(), {"C1"}
        )


def test_cpl_basis_gate_emits_declared_provenanced_center() -> None:
    component = replace(
        _bom_component("C1", "test"),
        cpl_position_basis="pad_bbox_center",
        cpl_position_source_url="https://example.com/centroid",
        cpl_position_confirmed_at="2026-08-13T00:00:00Z",
        cpl_position_evidence_basis="confirmed",
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
        cpl_position_confirmed_at="2026-08-13T00:00:00Z",
        cpl_position_evidence_basis="estimated",
    )
    rows, report = apply_cpl_contract(
        _cpl_rows(), _cpl_board(), _bom_lane(component), _cpl_profile(), {"C1"}
    )
    assert rows[0]["PosY"] == "-1.000000"
    assert report["status"] == "fail"
    unknowns = cast(dict[str, object], report["unknowns"])
    assert unknowns["cpl_position_basis_fab_preview"] == ["C1"]


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


def _write_bom(path: Path, designator: str, lcsc: str = "C720477") -> None:
    path.write_text(
        "Comment,Designator,Footprint,LCSC Part #\n"
        f"TS-1088-AR02016,{designator},Button_Switch_SMD:SW_SPST_TL3301,{lcsc}\n"
    )


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
