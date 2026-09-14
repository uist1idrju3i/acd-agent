"""Core deterministic wire-harness gate tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from acd.core.electrical import extract_electrical_lane
from acd.core.harness import evaluate_harness
from acd.schema import DesignGraph, HarnessContract

ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "fixtures/harness/gd1-external-sensor"


def _inputs() -> tuple[DesignGraph, HarnessContract]:
    graph = DesignGraph.model_validate(
        json.loads((FIXTURE / "graph.json").read_text(encoding="utf-8"))
    )
    contract = HarnessContract.model_validate(
        json.loads((FIXTURE / "harness.json").read_text(encoding="utf-8"))
    )
    return graph, contract


def _evaluate(contract: HarnessContract):
    graph, _ = _inputs()
    return evaluate_harness(graph, extract_electrical_lane(graph), contract)


def test_harness_fixture_passes() -> None:
    graph, contract = _inputs()
    result = evaluate_harness(graph, extract_electrical_lane(graph), contract)
    assert result.status == "pass"
    assert [check.status for check in result.checks] == ["pass"] * 5


def test_wrong_net_fails_netlist() -> None:
    _, original = _inputs()
    wires = list(original.wires)
    wires[0] = wires[0].model_copy(update={"net_id": "net.gnd"})
    result = _evaluate(original.model_copy(update={"wires": wires}))
    check = result.checks[0]
    assert result.status == "fail"
    assert check.check_id == "netlist_consistency"
    assert check.status == "fail"


def test_derated_ampacity_fails() -> None:
    graph, contract = _inputs()
    net = next(node for node in graph.nodes if node.id == "net.vbus_5v")
    net.attrs["current_max_a"] = 2.0  # type: ignore[index]
    result = evaluate_harness(graph, extract_electrical_lane(graph), contract)
    check = next(item for item in result.checks if item.check_id == "ampacity")
    assert check.status == "fail"


def test_long_wire_fails_voltage_drop() -> None:
    _, original = _inputs()
    wires = list(original.wires)
    wires[0] = wires[0].model_copy(update={"length_mm": 50000.0})
    result = _evaluate(original.model_copy(update={"wires": wires}))
    check = next(item for item in result.checks if item.check_id == "voltage_drop")
    assert check.status == "fail"


def test_insulation_voltage_fails() -> None:
    _, original = _inputs()
    types = list(original.wire_types)
    types[0] = types[0].model_copy(update={"insulation_rating_v": 3.0})
    result = _evaluate(original.model_copy(update={"wire_types": types}))
    check = next(item for item in result.checks if item.check_id == "insulation_rating")
    assert check.status == "fail"


def test_missing_current_is_unknown() -> None:
    graph, contract = _inputs()
    net = next(node for node in graph.nodes if node.id == "net.vbus_5v")
    del net.attrs["current_max_a"]  # type: ignore[attr-defined]
    result = evaluate_harness(graph, extract_electrical_lane(graph), contract)
    check = next(item for item in result.checks if item.check_id == "ampacity")
    assert check.status == "unknown"


def test_cli_revision_mismatch_exits_two_without_output(tmp_path: Path) -> None:
    payload = json.loads((FIXTURE / "harness.json").read_text(encoding="utf-8"))
    payload["revision"] = "r999"
    harness = tmp_path / "harness.json"
    harness.write_text(json.dumps(payload), encoding="utf-8")
    out = tmp_path / "out"
    completed = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/check_harness.py",
            "--graph",
            str(FIXTURE / "graph.json"),
            "--harness",
            str(harness),
            "--out",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert not out.exists()


def test_cli_absent_harness_exits_two_with_clear_message(tmp_path: Path) -> None:
    out = tmp_path / "out"
    completed = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/check_harness.py",
            "--graph",
            str(FIXTURE / "graph.json"),
            "--harness",
            str(tmp_path / "missing-harness.json"),
            "--out",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "Harness input error" in completed.stderr
    assert not out.exists()


def test_gate_is_deterministic() -> None:
    graph, contract = _inputs()
    lane = extract_electrical_lane(graph)
    first = evaluate_harness(graph, lane, contract).model_dump_json()
    second = evaluate_harness(graph, lane, contract).model_dump_json()
    assert first == second
