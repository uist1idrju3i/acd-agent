"""Tests for fail-closed KiCad STEP export."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acd.adapters.kicad import step_export


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb (version 20240108))\n", encoding="utf-8")
    models = tmp_path / "models"
    models.mkdir()
    (models / "part.step").write_bytes(b"model")
    return pcb, models, tmp_path / "board.step"


def test_missing_kicad_cli_is_unknown(tmp_path: Path) -> None:
    pcb, models, output = _inputs(tmp_path)
    result = step_export.export_board_step(
        pcb,
        output,
        kicad_cli="missing-kicad-cli",
        models_dir=models,
    )
    assert result.status == "unknown"
    assert "unavailable" in (result.error or "")


def test_version_mismatch_is_unknown(
    tmp_path: Path, monkeypatch: Any
) -> None:
    pcb, models, output = _inputs(tmp_path)

    def fake_version(_executable: str) -> str:
        return "9.0.0"

    monkeypatch.setattr(
        step_export, "_version", fake_version
    )
    monkeypatch.setattr(step_export, "_expected_version", lambda: "10.0.6")
    result = step_export.export_board_step(
        pcb,
        output,
        kicad_cli="kicad-cli",
        models_dir=models,
    )
    assert result.status == "unknown"
    assert "version mismatch" in (result.error or "")
