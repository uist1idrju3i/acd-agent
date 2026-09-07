"""Firmware lane fail-closed coverage gate tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from acd.pipeline.firmware_lane import FirmwareLaneError, run_firmware_lane

REPO_ROOT = Path(__file__).resolve().parents[2]
GD1_GRAPH = REPO_ROOT / "fixtures" / "golden-design-1" / "graph.json"


def _fixture_dir(tmp_path: Path, graph_payload: dict[str, object]) -> Path:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "graph.json").write_text(
        json.dumps(graph_payload), encoding="utf-8"
    )
    return fixture


def _gd1_payload() -> dict[str, object]:
    return json.loads(GD1_GRAPH.read_text(encoding="utf-8"))


def test_failing_coverage_stops_before_the_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _gd1_payload()
    nodes = cast(list[dict[str, Any]], payload["nodes"])
    for node in nodes:
        if node["id"] == "fw.transition.report_measure":
            cast(dict[str, Any], node["attrs"])["trigger"] = "button_pressed"
    fixture = _fixture_dir(tmp_path, payload)
    output = tmp_path / "out"

    calls: list[list[str]] = []

    def forbidden_run(*_args: object, **_kwargs: object) -> None:
        calls.append(["called"])

    monkeypatch.setattr("acd.pipeline.firmware_lane.subprocess.run", forbidden_run)
    with pytest.raises(FirmwareLaneError, match="firmware coverage failed"):
        run_firmware_lane(REPO_ROOT, fixture, output, run_seconds=1)
    assert calls == []

    report = json.loads(
        (output / "firmware-coverage.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "fail"
    assert report["findings"] == [
        {
            "code": "trigger_unemitted",
            "node_id": "fw.transition.report_measure",
            "message": report["findings"][0]["message"],
        }
    ]
    assert "'button_pressed'" in report["findings"][0]["message"]


def test_passing_coverage_writes_report_and_invokes_the_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture_dir(tmp_path, _gd1_payload())
    output = tmp_path / "out"
    calls: list[str] = []

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(*_args: object, **_kwargs: object) -> _Completed:
        calls.append("run")
        output.mkdir(parents=True, exist_ok=True)
        (output / "summary.json").write_text(
            json.dumps(
                {
                    "schema_version": "0.1",
                    "run_seconds": 1,
                    "checks": [],
                    "log_path": "qemu-serial.log",
                }
            ),
            encoding="utf-8",
        )
        return _Completed()

    monkeypatch.setattr("acd.pipeline.firmware_lane.subprocess.run", fake_run)
    def stop_evidence(*_args: object, **_kwargs: object) -> None:
        raise ValueError("stop after coverage")

    monkeypatch.setattr(
        "acd.pipeline.firmware_lane.write_firmware_evidence",
        stop_evidence,
    )
    with pytest.raises(FirmwareLaneError, match="stop after coverage"):
        run_firmware_lane(REPO_ROOT, fixture, output, run_seconds=1)
    assert calls == ["run"]
    report = json.loads(
        (output / "firmware-coverage.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "pass"
    assert report["findings"] == []


def test_invalid_graph_fails_closed_without_the_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "graph.json").write_text("{not json", encoding="utf-8")
    calls: list[str] = []
    def forbidden_run(*_args: object, **_kwargs: object) -> None:
        calls.append("called")

    monkeypatch.setattr(
        "acd.pipeline.firmware_lane.subprocess.run", forbidden_run
    )
    with pytest.raises(
        FirmwareLaneError, match="firmware coverage could not be evaluated"
    ):
        run_firmware_lane(REPO_ROOT, fixture, tmp_path / "out", run_seconds=1)
    assert calls == []
