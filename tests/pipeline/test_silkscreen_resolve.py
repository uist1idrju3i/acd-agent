"""Silkscreen resolver fallback tests."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from acd.core.silkscreen import extract_silkscreen_lane
from acd.pipeline import silkscreen_resolve
from acd.pipeline.silkscreen_resolve import _assert_no_unresolved_texts

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "golden-design-1"
UNRESOLVED_NODE = "mechanical.silk_text.board_id"


def _unresolved_fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE, fixture)
    graph_path = fixture / "graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    for node in graph["nodes"]:
        if node["id"] == UNRESOLVED_NODE:
            node["attrs"].pop("x_mm", None)
            node["attrs"].pop("y_mm", None)
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    return fixture


def _patch_measurement(
    monkeypatch: pytest.MonkeyPatch,
    statuses: list[str],
) -> list[Path]:
    calls: list[Path] = []

    def measure(
        fixture_dir: Path,
        out_dir: Path,
        fab_profile_path: Path | None = None,
        fab_profile_id: str | None = None,
    ) -> dict[str, object]:
        del fab_profile_path, fab_profile_id
        calls.append(fixture_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        status = statuses.pop(0) if statuses else "measured_pass"
        return {"context": {"status": status}}

    monkeypatch.setattr(silkscreen_resolve, "measure_silkscreen", measure)
    return calls


def _patch_skill(monkeypatch: pytest.MonkeyPatch, *, accept: bool) -> None:
    def run(command: list[str], **kwargs: Any) -> None:
        input_path = Path(command[command.index("--input") + 1])
        output_path = Path(command[command.index("--output") + 1])
        input_data = json.loads(input_path.read_text(encoding="utf-8"))
        texts = cast(list[dict[str, Any]], input_data["lane"]["texts"])
        candidates: list[dict[str, object]] = []
        for index, text in enumerate(texts):
            candidates.append(
                {
                    "node_id": text["node_id"],
                    "accepted_position_mm": [10.0 + index, 10.0 + index] if accept else None,
                    "accepted_rotation_deg": 0.0 if accept else None,
                    "rejected_candidates": [],
                }
            )
        output_path.write_text(json.dumps({"candidates": candidates}), encoding="utf-8")

    monkeypatch.setattr(silkscreen_resolve.subprocess, "run", run)


def test_measured_pass_with_unresolved_text_forces_skill_search(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _unresolved_fixture(tmp_path)
    _patch_measurement(monkeypatch, ["measured_pass", "measured_pass"])
    _patch_skill(monkeypatch, accept=True)

    result = silkscreen_resolve.resolve_silkscreen(
        fixture,
        tmp_path / "output",
        max_iterations=2,
    )

    assert result["status"] == "resolved"
    iterations = result["iterations"]
    assert isinstance(iterations, list)
    assert iterations[0]["forced_search"] is True
    assert iterations[0]["unresolved_texts"] == [UNRESOLVED_NODE]
    graph = json.loads((fixture / "graph.json").read_text(encoding="utf-8"))
    node = next(item for item in graph["nodes"] if item["id"] == UNRESOLVED_NODE)
    assert node["attrs"]["x_mm"] is not None
    assert node["attrs"]["y_mm"] is not None


def test_measured_pass_with_unresolved_text_still_fails_without_skill_position(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _unresolved_fixture(tmp_path)
    _patch_measurement(monkeypatch, ["measured_pass"])
    _patch_skill(monkeypatch, accept=False)

    result = silkscreen_resolve.resolve_silkscreen(
        fixture,
        tmp_path / "output",
        max_iterations=2,
    )

    assert result["status"] != "resolved"
    iterations = result["iterations"]
    assert isinstance(iterations, list)
    assert iterations[0]["forced_search"] is True
    graph = json.loads((fixture / "graph.json").read_text(encoding="utf-8"))
    with pytest.raises(
        ValueError,
        match="silkscreen resolution accepted unresolved text coordinates: "
        + UNRESOLVED_NODE,
    ):
        _assert_no_unresolved_texts(extract_silkscreen_lane(
            silkscreen_resolve.DesignGraph.model_validate(graph)
        ))
