"""Synthetic firmware-analysis parser and simulation tests."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from acd.schema.design_graph import DesignGraph
from fw_graph import (
    extract_firmware_lane,
    extract_firmware_settings,
    resolve_firmware_capability_plan,
)
from fw_project import write_firmware_project
from fw_qemu import (
    VirtualRunCheckError,
    assert_sensor_log_matches_scenario,
    encode_sht40_sample,
    sht40_crc,
)
from fw_stack_usage import evaluate_stack_usage, parse_size_json, parse_su
from fw_static_analysis import evaluate_findings, parse_diagnostics, run_clang_tidy

FIXTURES = Path(__file__).parent / "fixtures"
GRAPH = Path(__file__).resolve().parents[5] / "fixtures/golden-design-1/graph.json"


def test_clang_tidy_synthetic_warning_fails(tmp_path: Path) -> None:
    findings = parse_diagnostics(
        (FIXTURES / "synthetic-clang-tidy.txt").read_text(encoding="utf-8"),
        tmp_path,
    )
    result = evaluate_findings(findings, [])
    assert result["status"] == "fail"
    assert result["counts"] == {"warning": 1, "error": 1}


def test_clang_tidy_malformed_output_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="malformed"):
        parse_diagnostics("main.c:1:2: warning: missing check", tmp_path)


def test_clang_tidy_exemption_is_not_a_failure(tmp_path: Path) -> None:
    findings = parse_diagnostics(
        "main.c:1:2: warning: excluded [cert-err58-cpp]\n", tmp_path
    )
    assert evaluate_findings(findings, ["cert-err58-cpp"])["status"] == "pass"


def test_clang_tidy_missing_tool_is_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    build_dir = tmp_path / "project"
    (build_dir / "build").mkdir(parents=True)
    (build_dir / "build/compile_commands.json").write_text("[]\n", encoding="utf-8")
    monkeypatch.delenv("IDF_TOOLS_PATH", raising=False)
    result = run_clang_tidy(
        build_dir,
        Path(__file__).parents[1] / "rules/clang_tidy_checks.json",
    )
    assert result["status"] == "unknown"
    assert "gcc_toolchain_missing" in cast(list[str], result["findings_detail"])


def test_stack_usage_dynamic_is_unknown_and_budget_is_deterministic() -> None:
    functions = parse_su(
        (FIXTURES / "synthetic-stack.su").read_text(encoding="utf-8"),
        Path("/workspace"),
    )
    result = evaluate_stack_usage(
        functions,
        task_budgets={"main": (512, 10.0)},
        size=parse_size_json(
            (FIXTURES / "synthetic-size.json").read_text(encoding="utf-8")
        ),
    )
    assert result["status"] == "unknown"
    assert "unbounded_dynamic_stack:dynamic_worker" in cast(
        list[str], result["findings"]
    )


def test_stack_usage_budget_exceedance_fails() -> None:
    functions = parse_su(
        (FIXTURES / "synthetic-stack.su").read_text(encoding="utf-8"),
        Path("/workspace"),
    )
    result = evaluate_stack_usage(
        functions,
        task_budgets={"main": (64, 0.0)},
        size=parse_size_json(
            (FIXTURES / "synthetic-size.json").read_text(encoding="utf-8")
        ),
    )
    assert result["status"] == "fail"


def test_sht40_reference_crc_and_log_match() -> None:
    assert sht40_crc(bytes.fromhex("beef")) == 0x92
    frame = encode_sht40_sample(25.0, 40.0)
    assert frame[2] == sht40_crc(frame[:2])
    assert frame[5] == sht40_crc(frame[3:5])
    assert_sensor_log_matches_scenario(
        "I SHT40 temp_c=25.00 rh=40.00\n",
        [{"t_c": 25.0, "rh_pct": 40.0}],
    )


def test_sht40_missing_or_mismatched_log_fails_closed() -> None:
    scenario = [{"t_c": 25.0, "rh_pct": 40.0}]
    with pytest.raises(VirtualRunCheckError, match="requires"):
        assert_sensor_log_matches_scenario("", scenario)
    with pytest.raises(VirtualRunCheckError, match="mismatch"):
        assert_sensor_log_matches_scenario("SHT40 temp_c=20.00 rh=40.00\n", scenario)


def test_simulated_project_is_deterministic_and_opt_in(tmp_path: Path) -> None:
    graph = DesignGraph.model_validate(
        __import__("json").loads(GRAPH.read_text(encoding="utf-8"))
    )
    lane = extract_firmware_lane(graph)
    plan = resolve_firmware_capability_plan(graph, lane)
    settings = extract_firmware_settings(graph)
    scenario = [{"t_c": 25.0, "rh_pct": 40.0}]
    first = write_firmware_project(
        lane,
        graph.revision,
        tmp_path / "first",
        graph.graph_id,
        settings,
        plan=plan,
        stack_usage=True,
        sim_peripherals=True,
        sim_scenario=scenario,
    )
    second = write_firmware_project(
        lane,
        graph.revision,
        tmp_path / "second",
        graph.graph_id,
        settings,
        plan=plan,
        stack_usage=True,
        sim_peripherals=True,
        sim_scenario=scenario,
    )
    assert first.main_source.read_bytes() == second.main_source.read_bytes()
    assert (first.root / "main/acd_sim_sht40.c").read_bytes() == (
        second.root / "main/acd_sim_sht40.c"
    ).read_bytes()
    assert "-fstack-usage" in (first.root / "main/CMakeLists.txt").read_text(
        encoding="utf-8"
    )
