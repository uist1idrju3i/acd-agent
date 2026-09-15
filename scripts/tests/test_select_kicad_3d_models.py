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
    assert checked_in == select_models(pcb)


def test_external_model_references_are_not_selected(tmp_path: Path) -> None:
    pcb = tmp_path / "select-kicad-models-test.kicad_pcb"
    pcb.write_text(
        '(model "${KICAD8_3RD_PARTY}/3dmodels/vendor.3dshapes/part.step")\n',
        encoding="utf-8",
    )
    assert select_models(pcb)["entries"] == []
