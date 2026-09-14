from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from acd.core.spice import (
    SpiceRawResult,
    evaluate_spice,
    extract_power_netlist,
    run_ngspice,
)
from acd.schema import DesignGraph, SpiceAnalysisRequest

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
REQUEST_PATH = ROOT / "fixtures/spice/gd1-power.json"
OUTPUT_PATH = ROOT / "fixtures/spice/gd1-power.ngspice-out.txt"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(
        json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    )


def _request() -> SpiceAnalysisRequest:
    return SpiceAnalysisRequest.model_validate(
        json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    )


def test_netlist_bytes_are_deterministic() -> None:
    first = extract_power_netlist(_graph(), _request())
    second = extract_power_netlist(_graph(), _request())
    assert first.text == second.text
    assert first.sha256 == second.sha256
    assert ".control" not in first.text
    assert "B_U2" in first.text


def test_recorded_output_evaluates() -> None:
    netlist = extract_power_netlist(_graph(), _request())
    output = OUTPUT_PATH.read_text(encoding="utf-8")
    from acd.core import spice

    parse_output = cast(
        Callable[
            [str],
            tuple[
                dict[str, float],
                dict[str, tuple[tuple[float, float], ...]],
                tuple[str, ...],
            ],
        ],
        spice._parse_output,  # pyright: ignore[reportPrivateUsage]
    )
    measures, traces, findings = parse_output(output)
    raw = SpiceRawResult(
        status="unknown" if findings else "pass",
        ngspice_version="45.2",
        output_text=output,
        raw_output_sha256="sha256:" + "b" * 64,
        measures=measures,
        traces=traces,
        findings=findings,
        netlist_sha256=netlist.sha256,
    )
    result = evaluate_spice(_graph(), _request(), raw)
    assert result.status == "pass"
    assert result.authority == "estimate"


def test_malformed_output_is_unknown() -> None:
    netlist = extract_power_netlist(_graph(), _request())
    raw = SpiceRawResult(
        status="unknown",
        ngspice_version="45.2",
        output_text="not ngspice output",
        raw_output_sha256="sha256:" + "b" * 64,
        measures={},
        traces={},
        findings=("ngspice output parse failed",),
        netlist_sha256=netlist.sha256,
    )
    result = evaluate_spice(_graph(), _request(), raw)
    assert result.status == "unknown"
    assert "ngspice output parse failed" in result.findings


def test_revision_mismatch_fails_closed() -> None:
    payload = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    payload["revision"] = "r2"
    with pytest.raises(ValueError, match="mismatch"):
        extract_power_netlist(
            _graph(), SpiceAnalysisRequest.model_validate(payload)
        )


def test_missing_value_is_unknown() -> None:
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    resistor = next(
        node
        for node in graph["nodes"]
        if node["kind"] == "electrical.component"
        and node["attrs"]["refdes"] == "R6"
    )
    resistor["attrs"]["value"] = ""
    result = extract_power_netlist(
        DesignGraph.model_validate(graph), _request()
    )
    assert result.status == "unknown"
    assert any("R6" in finding for finding in result.findings)


def test_tightened_limit_fails() -> None:
    request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    request["limits"][0]["max"] = 3.0
    request["limits"][0].pop("min")
    netlist = extract_power_netlist(_graph(), SpiceAnalysisRequest.model_validate(request))
    raw = SpiceRawResult(
        status="pass",
        ngspice_version="45.2",
        output_text="v(n3v3) = 3.3",
        raw_output_sha256="sha256:" + "b" * 64,
        measures={"v(n3v3)": 3.3},
        traces={},
        netlist_sha256=netlist.sha256,
    )
    assert (
        evaluate_spice(_graph(), SpiceAnalysisRequest.model_validate(request), raw).status
        == "fail"
    )


def test_version_mismatch_is_unknown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    netlist = extract_power_netlist(_graph(), _request())

    def fake_run_tool(**_: object) -> SimpleNamespace:
        return SimpleNamespace(stdout="ngspice-44.0\n", stderr="")

    monkeypatch.setattr("acd.core.spice.run_tool", fake_run_tool)
    result = run_ngspice(netlist, tmp_path)
    assert result.status == "unknown"
    assert "tool_version_mismatch" in result.findings


def test_tool_missing_is_unknown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    netlist = extract_power_netlist(_graph(), _request())

    def missing_tool(**_: object) -> SimpleNamespace:
        raise OSError("ngspice not found")

    monkeypatch.setattr("acd.core.spice.run_tool", missing_tool)
    result = run_ngspice(netlist, tmp_path)
    assert result.status == "unknown"
    assert "tool_missing" in result.findings


def test_non_convergence_is_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    netlist = extract_power_netlist(_graph(), _request())

    def fake_run_tool(**kwargs: object) -> SimpleNamespace:
        command = cast(list[str], kwargs["command"])
        if command[-1] == "-v":
            return SimpleNamespace(stdout="ngspice-45.2\n", stderr="")
        output_paths = cast(list[Path], kwargs["output_paths"])
        output_paths[0].write_text(
            "timestep too small\n",
            encoding="utf-8",
        )
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr("acd.core.spice.run_tool", fake_run_tool)
    result = run_ngspice(netlist, tmp_path)
    assert result.status == "unknown"
    assert "ngspice did not converge" in result.findings


def test_mocked_subprocess_parses_recorded_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    netlist = extract_power_netlist(_graph(), _request())
    output = OUTPUT_PATH.read_text(encoding="utf-8")

    def fake_run_tool(**kwargs: object) -> SimpleNamespace:
        command = cast(list[str], kwargs["command"])
        if command[-1] == "-v":
            return SimpleNamespace(stdout="ngspice-45.2\n", stderr="")
        output_paths = cast(list[Path], kwargs["output_paths"])
        output_paths[0].write_text(output, encoding="utf-8")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr("acd.core.spice.run_tool", fake_run_tool)
    result = run_ngspice(netlist, tmp_path)
    assert result.status == "pass"
    assert result.ngspice_version == "45.2"


@pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice is not installed")
def test_host_ngspice_optional() -> None:
    assert shutil.which("ngspice") is not None
