import hashlib
import json
from pathlib import Path

import pytest

from acd_adapter_kicad.fab import (
    BoardMeasurement,
    FabOutputError,
    FootprintMeasurement,
    PadMeasurement,
    ViaMeasurement,
    deterministic_zip,
    jlcpcb_cpl_csv,
    run_dfm,
)
from acd_adapter_kicad.library import LibraryPinError
from acd_adapter_kicad.overlay import apply_overlay
from acd_core.fab import ProcessAllowanceView, load_fab_profile
from acd_core.sexpr import SExpr

ROOT = Path(__file__).parents[4]
PROFILE = load_fab_profile(ROOT / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json")


def _measurement(via: ViaMeasurement) -> BoardMeasurement:
    return BoardMeasurement((), (via,), None, None, None, None, (), 0)


def test_small_via_requires_allowance() -> None:
    via = ViaMeasurement(1.0, 2.0, 0.4, 0.2, ("F.Cu", "B.Cu"))
    report = run_dfm(_measurement(via), PROFILE, "r1", ())
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
    report = run_dfm(_measurement(via), PROFILE, "r1", (allowance,))
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
    report = run_dfm(board, PROFILE, "r1", ())
    assert report["status"] == "fail"
    assert any(item["rule_id"] == "via-in-pad-process" for item in report["findings"])  # type: ignore[index]


def test_cpl_requires_exact_fitted_set() -> None:
    rows = ({"Ref": "C1", "PosX": "1", "PosY": "2", "Rot": "0", "Side": "top"},)
    try:
        jlcpcb_cpl_csv(rows, {"C1", "C2"})
    except FabOutputError:
        pass
    else:
        raise AssertionError("CPL mismatch must fail closed")


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
    updated, _ = apply_overlay(raw, source, overlay, overlay_hash)
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
        apply_overlay(raw, source, overlay, overlay_hash)
