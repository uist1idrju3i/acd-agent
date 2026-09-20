from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from acd.core.electrical.dft_coverage import evaluate_dft_coverage
from acd.core.electrical.electrical import extract_electrical_lane
from acd.core.knowledge.design_predicates import PREDICATE_CATALOG
from acd.schema import DesignGraph, DftPolicy

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
POLICY_PATH = ROOT / "fixtures/dft/gd1-ict-basic.json"


def _graph_payload() -> dict[str, object]:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def _policy(**updates: object) -> DftPolicy:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    payload.update(updates)
    return DftPolicy.model_validate(payload)


def _result(
    graph_payload: dict[str, object] | None = None,
    policy: DftPolicy | None = None,
):
    graph = DesignGraph.model_validate(graph_payload or _graph_payload())
    return evaluate_dft_coverage(
        graph,
        extract_electrical_lane(graph),
        policy or _policy(),
    )


def test_gd1_coverage_lists_actual_test_point_nets_and_uncovered_power() -> None:
    result = _result()
    assert result.status == "fail"
    assert result.coverage.covered_nets == [
        "net.gnd",
        "net.i2c_scl",
        "net.i2c_sda",
        "net.led",
        "net.p3v3",
        "net.uart_rx",
        "net.uart_tx",
    ]
    assert "net.vbus_5v" in result.coverage.uncovered_nets
    assert (
        next(check for check in result.checks if check.check_id == "net_coverage").status
        == "fail"
    )


def test_explicit_covered_net_policy_passes_coverage() -> None:
    result = _result(
        policy=_policy(
            required_net_classes=[],
            required_net_ids=[
                "net.gnd",
                "net.i2c_scl",
                "net.i2c_sda",
                "net.led",
                "net.p3v3",
                "net.uart_rx",
                "net.uart_tx",
            ],
        )
    )
    assert result.coverage.uncovered_nets == []
    assert (
        next(check for check in result.checks if check.check_id == "net_coverage").status
        == "pass"
    )


def test_probe_pitch_and_pad_diameter_fail_below_policy_limits() -> None:
    pitch = _result(policy=_policy(min_probe_pitch_mm=50.0))
    pitch_check = next(check for check in pitch.checks if check.check_id == "probe_pitch")
    assert pitch_check.status == "fail"
    assert pitch_check.details["pairs"]

    diameter = _result(policy=_policy(min_pad_diameter_mm=2.0))
    diameter_check = next(check for check in diameter.checks if check.check_id == "pad_diameter")
    assert diameter_check.status == "fail"


def test_missing_test_points_fails_with_zero_ratio() -> None:
    payload = _graph_payload()
    nodes = cast(list[dict[str, Any]], payload["nodes"])
    nodes[:] = [
        node
        for node in nodes
        if not (
            node["kind"] in {"electrical.component", "electrical.pin"}
            and str(node["id"]).startswith(("comp.tp", "pin.tp"))
        )
    ]
    for node in nodes:
        node["depends_on"] = [
            dependency
            for dependency in node.get("depends_on", [])
            if not str(dependency).startswith("comp.tp")
        ]
    result = _result(payload)
    assert result.coverage.ratio == 0.0
    assert result.coverage.covered_nets == []
    assert result.coverage.uncovered_nets


def test_evaluation_is_deterministic_and_gate_is_opt_in() -> None:
    first = _result().model_dump_json()
    second = _result().model_dump_json()
    assert first == second
    assert not any("dft" in name for name in PREDICATE_CATALOG)


def test_cli_revision_mismatch_exits_two_without_output(tmp_path: Path) -> None:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    policy["revision"] = "r2"
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    output = tmp_path / "out"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check_dft_coverage.py"),
            "--graph",
            str(GRAPH_PATH),
            "--policy",
            str(policy_path),
            "--out",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert not output.exists()
