"""CLI tests for the motion-sweep gate."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_motion_sweep import main

FIXTURE = Path(__file__).parents[2] / "fixtures/mechanism-library/graph.json"
GD1 = Path(__file__).parents[2] / "fixtures/golden-design-1/graph.json"


def test_motion_sweep_cli_passes_fixture(tmp_path: Path) -> None:
    out = tmp_path / "motion.json"
    assert main(["--graph", str(FIXTURE), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["gate_id"] == "motion_sweep"
    assert payload["status"] == "pass"
    assert {item["status"] for item in payload["findings"]} == {"pass"}


def test_motion_sweep_cli_is_not_applicable_without_features(tmp_path: Path) -> None:
    out = tmp_path / "motion.json"
    assert main(["--graph", str(GD1), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "not_applicable"
    assert payload["findings"] == []
