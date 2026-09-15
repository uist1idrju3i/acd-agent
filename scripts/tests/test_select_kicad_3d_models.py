"""Tests for deterministic KiCad 3D model selection."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.select_kicad_3d_models import select_models


def test_checked_in_allowlist_matches_gd1_derivation() -> None:
    root = Path(__file__).resolve().parents[2]
    pcb = root / "examples/golden-design-1-vps-20260901/board/golden-design-1.kicad_pcb"
    checked_in = json.loads(
        (root / "docker/kicad-3d-models.json").read_text(encoding="utf-8")
    )
    assert checked_in == select_models(
        pcb, missing_upstream=checked_in["missing_upstream"]
    )


def test_declared_missing_model_is_not_an_entry(tmp_path: Path) -> None:
    pcb = tmp_path / "select-kicad-models-test.kicad_pcb"
    pcb.write_text(
        '(model "${KICAD10_3DMODEL_DIR}/Connector_USB.3dshapes/'
        'USB_C_Receptacle_HRO_TYPE-C-31-M-12.step")\n'
        '(model "${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes/'
        'R_0603_1608Metric.step")\n',
        encoding="utf-8",
    )
    missing_upstream = [
        {
            "footprint_lib": "Connector_USB",
            "model_rel_path": "USB_C_Receptacle_HRO_TYPE-C-31-M-12.step",
            "note": "Not shipped by kicad-packages3D; the footprint references it.",
        }
    ]
    selected = select_models(pcb, missing_upstream=missing_upstream)
    assert selected["entries"] == [
        {
            "footprint_lib": "Resistor_SMD",
            "model_rel_path": "R_0603_1608Metric.step",
        }
    ]
    assert selected["missing_upstream"] == missing_upstream


def test_unreferenced_declared_missing_model_is_dropped(tmp_path: Path) -> None:
    pcb = tmp_path / "select-kicad-models-test.kicad_pcb"
    pcb.write_text(
        '(model "${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes/'
        'R_0603_1608Metric.step")\n',
        encoding="utf-8",
    )
    selected = select_models(
        pcb,
        missing_upstream=[
            {
                "footprint_lib": "Connector_USB",
                "model_rel_path": "USB_C_Receptacle_HRO_TYPE-C-31-M-12.step",
                "note": "Not shipped by kicad-packages3D; the footprint references it.",
            }
        ],
    )
    assert selected["missing_upstream"] == []


def test_external_model_references_are_not_selected(tmp_path: Path) -> None:
    pcb = tmp_path / "select-kicad-models-test.kicad_pcb"
    pcb.write_text(
        '(model "${KICAD8_3RD_PARTY}/3dmodels/vendor.3dshapes/part.step")\n',
        encoding="utf-8",
    )
    selected = select_models(pcb)
    assert selected["entries"] == []
    assert selected["missing_upstream"] == []
