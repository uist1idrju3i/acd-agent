"""Core tests for deterministic thermal and FEM estimates."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from acd.core.fem import FemRawResult, evaluate_fem, generate_ccx_input, run_ccx
from acd.core.thermal import estimate_thermal
from acd.schema import DesignGraph, FemLimits, FemRequest, ThermalRequest, UseEnvironment

ROOT = Path(__file__).parents[2]


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(
        json.loads((ROOT / "fixtures/golden-design-1/graph.json").read_text(encoding="utf-8"))
    )


def _thermal_request() -> ThermalRequest:
    return ThermalRequest.model_validate(
        json.loads((ROOT / "fixtures/thermal/gd1-ldo.json").read_text(encoding="utf-8"))
    )


def _environment() -> UseEnvironment:
    return UseEnvironment.model_validate(
        json.loads(
            (ROOT / "fixtures/use-environment/gd1-indoor-usb.json").read_text(
                encoding="utf-8"
            )
        )
    )


def test_gd1_thermal_estimate_passes_and_is_deterministic() -> None:
    graph = _graph()
    request = _thermal_request()
    environment = _environment()
    first = estimate_thermal(graph, request, environment)
    second = estimate_thermal(graph, request, environment)
    assert first == second
    assert first.status == "pass"
    assert first.sources[0].tj_c == pytest.approx(45.0)


def test_missing_theta_is_unknown() -> None:
    request = _thermal_request().model_copy(
        update={
            "sources": [
                _thermal_request().sources[0].model_copy(
                    update={"package_theta_ja_c_per_w": None}
                )
            ]
        }
    )
    result = estimate_thermal(_graph(), request, _environment())
    assert result.status == "unknown"


def test_overtemperature_is_fail() -> None:
    source = _thermal_request().sources[0].model_copy(update={"tj_max_c": 41.0})
    request = _thermal_request().model_copy(update={"sources": [source]})
    result = estimate_thermal(_graph(), request, _environment())
    assert result.status == "fail"


def test_fem_input_is_deterministic() -> None:
    request = FemRequest.model_validate(
        json.loads((ROOT / "fixtures/fem/gd1-drop.json").read_text(encoding="utf-8"))
    )
    first = generate_ccx_input(request, (36.0, 31.0, 6.0, 2.0))
    second = generate_ccx_input(request, (36.0, 31.0, 6.0, 2.0))
    assert first == second
    assert hashlib.sha256(first.encode("utf-8")).hexdigest() == (
        "8b2dd0d720628ab32590c6f22700a8279b5894883ccd2c41477130cf35498d63"
    )
    assert "*ELEMENT, TYPE=C3D8R, ELSET=BOX" in first
    assert "equivalent_drop_acceleration_m_s2" in first


def test_fem_parser_evaluates_synthetic_dat() -> None:
    graph = _graph()
    request = FemRequest.model_validate(
        json.loads((ROOT / "fixtures/fem/gd1-drop.json").read_text(encoding="utf-8"))
    )
    raw = FemRawResult(
        "pass",
        "2.21",
        (ROOT / "fixtures/fem/gd1-drop.dat").read_text(encoding="utf-8"),
    )
    result = evaluate_fem(graph, request, raw)
    assert result.status == "pass"
    assert result.max_deflection_mm == pytest.approx(0.1)
    assert result.max_von_mises_pa is not None


def test_fem_parser_accepts_sectioned_dat_output() -> None:
    graph = _graph()
    request = FemRequest.model_validate(
        json.loads((ROOT / "fixtures/fem/gd1-drop.json").read_text(encoding="utf-8"))
    )
    raw = FemRawResult(
        "pass",
        "2.21",
        "displacements (vx,vy,vz)\n"
        "1 0.10 0.00 0.00\n"
        "stresses (sxx,syy,szz,sxy,sxz,syz)\n"
        "1 1000000 500000 250000 10000 20000 30000\n",
    )
    result = evaluate_fem(graph, request, raw)
    assert result.status == "pass"
    assert result.max_deflection_mm == pytest.approx(0.1)


def test_fem_malformed_dat_is_unknown() -> None:
    graph = _graph()
    request = FemRequest.model_validate(
        json.loads((ROOT / "fixtures/fem/gd1-drop.json").read_text(encoding="utf-8"))
    )
    result = evaluate_fem(graph, request, FemRawResult("pass", "2.21", "not a dat file"))
    assert result.status == "unknown"


def test_fem_limit_exceeded_is_fail() -> None:
    graph = _graph()
    request = FemRequest.model_validate(
        json.loads((ROOT / "fixtures/fem/gd1-drop.json").read_text(encoding="utf-8"))
    ).model_copy(update={"limits": FemLimits(max_von_mises_pa=1.0)})
    raw = FemRawResult(
        "pass",
        "2.21",
        (ROOT / "fixtures/fem/gd1-drop.dat").read_text(encoding="utf-8"),
    )
    assert evaluate_fem(graph, request, raw).status == "fail"


def test_fem_version_mismatch_is_unknown() -> None:
    graph = _graph()
    request = FemRequest.model_validate(
        json.loads((ROOT / "fixtures/fem/gd1-drop.json").read_text(encoding="utf-8"))
    )
    raw = FemRawResult("unknown", "2.20", "", ("tool_version_mismatch",))
    result = evaluate_fem(graph, request, raw)
    assert result.status == "unknown"
    assert "tool_version_mismatch" in result.findings


def test_fem_missing_tool_is_unknown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from acd.core import fem

    def missing(**_kwargs: object) -> object:
        raise fem.ExternalToolError("ccx not found")

    monkeypatch.setattr(fem, "run_tool", missing)
    inp = tmp_path / "model.inp"
    inp.write_text("*HEADING\n", encoding="utf-8")
    result = run_ccx(inp, tmp_path)
    assert result.status == "unknown"


def test_ccx_version_probe_accepts_real_banner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from acd.core import fem

    calls: list[dict[str, object]] = []

    def fake_run_tool(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        if kwargs["command"] == ["ccx", "-v"]:
            return SimpleNamespace(stdout="\nThis is Version 2.21\n", stderr="")
        (tmp_path / "model.dat").write_text(
            (ROOT / "fixtures/fem/gd1-drop.dat").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(fem, "run_tool", fake_run_tool)
    inp = tmp_path / "model.inp"
    inp.write_text("*HEADING\n", encoding="utf-8")
    raw = run_ccx(inp, tmp_path)
    assert raw.status == "pass"
    assert raw.ccx_version == "2.21"
    assert calls[0]["allowed_exit_codes"] == frozenset({0, 201})


@pytest.mark.skipif(shutil.which("ccx") is None, reason="CalculiX is unavailable")
def test_real_ccx_path_is_available_when_installed(tmp_path: Path) -> None:
    request = FemRequest.model_validate(
        json.loads((ROOT / "fixtures/fem/gd1-drop.json").read_text(encoding="utf-8"))
    )
    inp = tmp_path / "model.inp"
    inp.write_text(generate_ccx_input(request, (36.0, 31.0, 6.0, 2.0)), encoding="utf-8")
    raw = run_ccx(inp, tmp_path, version_pin=request.ccx.version_pin)
    assert raw.status in {"pass", "unknown"}
