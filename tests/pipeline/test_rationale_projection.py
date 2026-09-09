"""AA-17: rationale coverage failure points back at spec regeneration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.pipeline.rationale import validate_and_project_rationale
from acd.schema import DesignGraph


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(
        {
            "graph_id": "test",
            "revision": "r1",
            "nodes": [
                {
                    "id": "comp.u1",
                    "kind": "electrical.component",
                    "attrs": {
                        "mpn": "U1",
                        "lcsc": "C1",
                        "placement_x_mm": 1.0,
                        "placement_y_mm": 2.0,
                        "placement_rotation_deg": 0.0,
                    },
                },
                {"id": "req.1", "kind": "requirement", "attrs": {"text": "required"}},
            ],
        }
    )


def test_coverage_failure_directs_to_spec_regeneration(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    (fixture_dir / "rationale.json").write_text(
        json.dumps({"graph_id": "test", "revision": "r1", "records": []}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as excinfo:
        validate_and_project_rationale(
            _graph(), fixture_dir, tmp_path / "out"
        )
    message = str(excinfo.value)
    assert "rationale coverage failed" in message
    assert "regenerate the fixture from its DesignFixtureSpec" in message
    assert "--fixture-spec <spec.json> --fixture-overwrite" in message
    assert "coverage rules are unchanged" in message
    assert (tmp_path / "out" / "rationale-coverage.json").is_file()
