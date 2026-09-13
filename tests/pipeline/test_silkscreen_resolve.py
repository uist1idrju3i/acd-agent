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


def _routed_board(tmp_path: Path) -> Path:
    board = tmp_path / "board.kicad_pcb"
    board.write_text("(kicad_pcb)\n", encoding="utf-8")
    return board


def _patch_reresolve_measurement(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def measure(
        fixture_dir: Path,
        out_dir: Path,
        fab_profile_path: Path | None = None,
        fab_profile_id: str | None = None,
        routed_board: Path | None = None,
    ) -> dict[str, object]:
        calls.append(
            {
                "fixture_dir": fixture_dir,
                "fab_profile_path": fab_profile_path,
                "fab_profile_id": fab_profile_id,
                "routed_board": routed_board,
            }
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        return {"context": {"status": status, "failure_reason": "fake failure"}}

    monkeypatch.setattr(silkscreen_resolve, "measure_silkscreen", measure)
    return calls


def test_reresolve_routed_silkscreen_writes_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _unresolved_fixture(tmp_path)
    board = _routed_board(tmp_path)
    out_dir = tmp_path / "reresolve"
    measure_calls = _patch_reresolve_measurement(monkeypatch, "measured_fail")
    _patch_skill(monkeypatch, accept=True)

    record = silkscreen_resolve.reresolve_routed_silkscreen(
        fixture, out_dir, board
    )

    assert record["status"] == "candidates_written"
    assert record["round"] == 1
    assert record["max_rounds"] == silkscreen_resolve.ROUTED_SILKSCREEN_MAX_ROUNDS
    assert record["max_rounds"] == 1
    assert record["record_class"] == "L3"
    assert record["pass_evidence"] is False
    assert record["cache_hit"] is False
    assert measure_calls[0]["routed_board"] == board
    record_file = out_dir / "routed-silkscreen-reresolve.json"
    assert json.loads(record_file.read_text(encoding="utf-8"))["status"] == (
        "candidates_written"
    )
    graph = json.loads((fixture / "graph.json").read_text(encoding="utf-8"))
    for node in graph["nodes"]:
        if node["kind"] == "mechanical.silk_text":
            assert node["attrs"]["x_mm"] is not None
            assert node["attrs"]["y_mm"] is not None
            assert node["attrs"]["placement_source"] == "acd-silkscreen-placement"
    node = next(item for item in graph["nodes"] if item["id"] == UNRESOLVED_NODE)
    assert node["attrs"]["x_mm"] in {10.0 + index for index in range(6)}


def test_reresolve_routed_silkscreen_measured_pass_skips_skill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _unresolved_fixture(tmp_path)
    board = _routed_board(tmp_path)
    _patch_reresolve_measurement(monkeypatch, "measured_pass")
    skill_calls: list[Any] = []

    def record_run(*args: Any, **kwargs: Any) -> None:
        del kwargs
        skill_calls.append(args)

    monkeypatch.setattr(silkscreen_resolve.subprocess, "run", record_run)
    before = (fixture / "graph.json").read_text(encoding="utf-8")

    record = silkscreen_resolve.reresolve_routed_silkscreen(
        fixture, tmp_path / "reresolve", board
    )

    assert record["status"] == "measured_pass"
    assert skill_calls == []
    assert (fixture / "graph.json").read_text(encoding="utf-8") == before


def test_reresolve_routed_silkscreen_cache_hit_reapplies_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _unresolved_fixture(tmp_path)
    board = _routed_board(tmp_path)
    out_dir = tmp_path / "reresolve"
    _patch_reresolve_measurement(monkeypatch, "measured_fail")
    _patch_skill(monkeypatch, accept=True)

    first = silkscreen_resolve.reresolve_routed_silkscreen(fixture, out_dir, board)
    assert first["status"] == "candidates_written"
    first_graph = (fixture / "graph.json").read_text(encoding="utf-8")

    def fail_measure(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("measure_silkscreen must not run on cache hit")

    def fail_run(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Skill subprocess must not run on cache hit")

    monkeypatch.setattr(silkscreen_resolve, "measure_silkscreen", fail_measure)
    monkeypatch.setattr(silkscreen_resolve.subprocess, "run", fail_run)

    second = silkscreen_resolve.reresolve_routed_silkscreen(fixture, out_dir, board)

    assert second["status"] == "candidates_written"
    assert second["cache_hit"] is True
    assert (fixture / "graph.json").read_text(encoding="utf-8") == first_graph


def test_reresolve_routed_silkscreen_no_candidates_leaves_graph(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _unresolved_fixture(tmp_path)
    board = _routed_board(tmp_path)
    _patch_reresolve_measurement(monkeypatch, "measured_fail")
    _patch_skill(monkeypatch, accept=False)
    before = (fixture / "graph.json").read_text(encoding="utf-8")

    record = silkscreen_resolve.reresolve_routed_silkscreen(
        fixture, tmp_path / "reresolve", board
    )

    assert record["status"] == "failed_no_candidates"
    assert (fixture / "graph.json").read_text(encoding="utf-8") == before


def test_reresolve_routed_silkscreen_missing_board_fails_closed(
    tmp_path: Path,
) -> None:
    fixture = _unresolved_fixture(tmp_path)
    with pytest.raises(ValueError, match="routed board is missing"):
        silkscreen_resolve.reresolve_routed_silkscreen(
            fixture, tmp_path / "reresolve", tmp_path / "absent.kicad_pcb"
        )


def test_measure_silkscreen_routed_board_keeps_vias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _unresolved_fixture(tmp_path)
    board = _routed_board(tmp_path)
    out_dir = tmp_path / "measure"
    layers_seen: list[Path] = []
    measurements_seen: list[object] = []
    marker_vias = (object(),)

    class FakeKicad:
        def export_gerbers(
            self,
            board_path: Path,
            gerber_dir: Path,
            layers: list[str],
            revision: str,
        ) -> tuple[None, list[Path]]:
            del revision
            assert board_path == board
            gerber_dir.mkdir(parents=True, exist_ok=True)
            paths = [gerber_dir / f"{layer}.gbr" for layer in layers]
            layers_seen.extend(paths)
            return None, paths

    def fail_write_project(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("write_project must not run for routed board")

    monkeypatch.setattr(silkscreen_resolve, "KicadCli", FakeKicad)
    monkeypatch.setattr(silkscreen_resolve, "write_project", fail_write_project)
    def fake_parse_routed_board(path: Path) -> Any:
        del path
        return silkscreen_resolve.BoardMeasurement(
            (),
            cast(Any, marker_vias),
            0.2,
            1.0,
            0.15,
            (0.0, 0.0, 10.0, 10.0),
            (0.3,),
            4,
            "test",
            (),
        )

    monkeypatch.setattr(
        silkscreen_resolve, "parse_routed_board", fake_parse_routed_board
    )

    def fake_context(
        silk: dict[str, Path],
        mask: dict[str, Path],
        outline: Path,
        measurement: object,
        *args: Any,
    ) -> dict[str, object]:
        del silk, mask, outline, args
        measurements_seen.append(measurement)
        return {"status": "measured_pass"}

    monkeypatch.setattr(
        silkscreen_resolve, "build_silkscreen_context", fake_context
    )

    result = silkscreen_resolve.measure_silkscreen(
        fixture,
        out_dir,
        fab_profile_id="jlcpcb-fr4-2l-1oz",
        routed_board=board,
    )

    assert result["board"] == str(board)
    assert result["measurement_source"] == "routed"
    assert len(layers_seen) == 5
    measurement = cast(Any, measurements_seen[0])
    assert measurement.vias == marker_vias
    assert measurement.drill_tool_diameters_mm == ()
    assert measurement.drill_object_count == 0
