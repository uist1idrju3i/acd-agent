"""Tests for the enclosure pipeline pass verdict reporting (fail-closed wording)."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from acd.pipeline import enclosure


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summary: dict[str, Any],
) -> None:
    def _fake_run_pipeline(
        fixture: Path,
        out: Path,
        *,
        pipeline_workers: int,
    ) -> dict[str, Any]:
        assert pipeline_workers > 0
        return summary

    monkeypatch.setattr(enclosure, "run_pipeline", _fake_run_pipeline)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_enclosure_pipeline.py",
            "--fixture",
            "fixtures/golden-design-1",
            "--out",
            str(tmp_path),
        ],
    )
    assert enclosure.main() == 0


def test_missing_authoritative_provenance_is_reported_as_provisional(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_main(
        monkeypatch,
        tmp_path,
        {"provisional": False, "authoritative": False},
    )
    assert "provisional host execution" in capsys.readouterr().out
    written = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert written["authoritative"] is False


def test_authoritative_provenance_is_reported_as_authoritative(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_main(
        monkeypatch,
        tmp_path,
        {"provisional": False, "authoritative": True},
    )
    assert "authoritative container execution" in capsys.readouterr().out


def test_enclosure_pipeline_records_mesh_artifacts(
    tmp_path: Path,
) -> None:
    summary = enclosure.run_pipeline(
        Path("fixtures/golden-design-1"),
        tmp_path,
        pipeline_workers=1,
    )
    assert str(summary["mesh_stl_path"]).endswith("enclosure.stl")
    assert summary["stl_triangle_count"] == 6156
    assert summary["model_part_count"] == 2
    manifest = json.loads(
        (tmp_path / "enclosure-artifacts.json").read_text(encoding="utf-8")
    )
    stl = next(
        item for item in manifest["artifacts"] if item["role"] == "enclosure_mesh_stl"
    )
    evidence = json.loads(
        (tmp_path / "evidence-mechanical.json").read_text(encoding="utf-8")
    )
    assert any(
        claim["property"] == "enclosure_mesh_stl_normalized_sha256"
        and claim["value"] == stl["normalized_sha256"]
        for claim in evidence["claims"]
    )
    assert summary["stl_measured_volume_mm3"] == pytest.approx(6695.063990, abs=1e-3)
