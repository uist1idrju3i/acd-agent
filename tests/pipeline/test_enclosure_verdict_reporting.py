"""Tests for the enclosure pipeline pass verdict reporting (fail-closed wording)."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from acd.pipeline import gd1_enclosure


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

    monkeypatch.setattr(gd1_enclosure, "run_pipeline", _fake_run_pipeline)
    monkeypatch.setattr(
        "sys.argv",
        ["run_gd1_enclosure_pipeline.py", "--out", str(tmp_path)],
    )
    assert gd1_enclosure.main() == 0


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
