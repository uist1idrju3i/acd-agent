"""Core deterministic wire-harness gate tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from acd.core.electrical.electrical import extract_electrical_lane
from acd.core.electrical.harness import evaluate_harness
from acd.schema import DesignGraph, GraphNode, HarnessContract

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
    assert [check.status for check in result.checks] == ["pass"] * 11
    assert result.dfa_findings == []


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


def test_unshielded_high_speed_wire_fails() -> None:
    _, original = _inputs()
    wire_types = [
        item.model_copy(update={"shield": "none"}) for item in original.wire_types
    ]
    wires = [
        item.model_copy(update={"twisted_pair_group": None})
        if item.wire_id == "w-usb-dp"
        else item
        for item in original.wires
    ]
    contract = original.model_copy(update={"wire_types": wire_types, "wires": wires})
    check = next(
        item
        for item in _evaluate(contract).checks
        if item.check_id == "shield_requirement"
    )
    assert check.status == "fail"


def test_missing_signal_class_is_unknown_for_pair_evaluation() -> None:
    graph, contract = _inputs()
    graph = graph.model_copy(
        update={
            "nodes": [
                node.model_copy(
                    update={
                        "attrs": {
                            key: value
                            for key, value in node.attrs.items()
                            if key != "signal_class"
                        }
                    }
                )
                if node.id == "net.usb_dp"
                else node
                for node in graph.nodes
            ]
        }
    )
    result = evaluate_harness(graph, extract_electrical_lane(graph), contract)
    check = next(
        item
        for item in result.checks
        if item.check_id == "signal_class_segregation"
    )
    assert check.status == "unknown"


def test_incompatible_bundle_signal_classes_fail() -> None:
    graph, contract = _inputs()
    graph = graph.model_copy(
        update={
            "nodes": [
                node.model_copy(
                    update={
                        "attrs": {**node.attrs, "signal_class": "mains"}
                    }
                )
                if node.id == "net.usb_dp"
                else node
                for node in graph.nodes
            ]
        }
    )
    result = evaluate_harness(graph, extract_electrical_lane(graph), contract)
    check = next(
        item
        for item in result.checks
        if item.check_id == "signal_class_segregation"
    )
    assert check.status == "fail"


def test_flex_cycles_exceeded_fail() -> None:
    _, original = _inputs()
    route = original.routes[0].model_copy(update={"expected_flex_cycles": 200000})
    result = _evaluate(original.model_copy(update={"routes": [route]}))
    check = next(item for item in result.checks if item.check_id == "flex_cycles")
    assert check.status == "fail"


def test_mating_cycles_exceeded_fail() -> None:
    _, original = _inputs()
    assert original.service_expectation is not None
    expectation = original.service_expectation.model_copy(
        update={"expected_mating_cycles": 30000}
    )
    result = _evaluate(original.model_copy(update={"service_expectation": expectation}))
    check = next(item for item in result.checks if item.check_id == "mating_cycles")
    assert check.status == "fail"


def test_retention_force_insufficient_fails() -> None:
    _, original = _inputs()
    connectors = [
        connector.model_copy(update={"retention_force_n": 1.0})
        for connector in original.connectors
    ]
    result = _evaluate(original.model_copy(update={"connectors": connectors}))
    check = next(item for item in result.checks if item.check_id == "mating_cycles")
    assert check.status == "fail"


def test_dynamic_bend_radius_insufficient_fails() -> None:
    _, original = _inputs()
    route = original.routes[0].model_copy(update={"bend_radius_dynamic_mm": 2.0})
    result = _evaluate(original.model_copy(update={"routes": [route]}))
    check = next(item for item in result.checks if item.check_id == "flex_cycles")
    assert check.status == "fail"


def test_same_housing_without_keying_guard_fails() -> None:
    _, original = _inputs()
    connectors = [
        connector.model_copy(
            update={"housing_mpn": "SHARED", "keying": "A", "polarity_guard": False}
        )
        for connector in original.connectors
    ]
    result = _evaluate(original.model_copy(update={"connectors": connectors}))
    check = next(item for item in result.checks if item.check_id == "keying_polarity")
    assert check.status == "fail"


def test_redundant_members_on_same_route_fail() -> None:
    graph, contract = _inputs()
    graph = graph.model_copy(
        update={
            "nodes": [
                *graph.nodes,
                GraphNode(
                    id="safety.harness-group",
                    kind="safety.redundant_group",
                    attrs={
                        "members": ["net.usb_dp", "net.usb_dn"],
                        "resources_shared_forbidden": ["harness"],
                    },
                ),
            ]
        }
    )
    result = evaluate_harness(graph, extract_electrical_lane(graph), contract)
    check = next(
        item
        for item in result.checks
        if item.check_id == "redundant_group_harness"
    )
    assert check.status == "fail"


def test_missing_second_stage_declarations_are_unknown() -> None:
    graph, original = _inputs()
    assert original.service_expectation is not None
    route = original.routes[0].model_copy(
        update={
            "moving_section": True,
            "expected_flex_cycles": None,
            "bend_radius_dynamic_mm": None,
        }
    )
    wire_types = [
        item.model_copy(update={"flex_rated_cycles": None})
        for item in original.wire_types
    ]
    connectors = [
        item.model_copy(
            update={"mating_cycles_rated": None, "retention_force_n": None}
        )
        for item in original.connectors
    ]
    contract = original.model_copy(
        update={
            "routes": [route],
            "wire_types": wire_types,
            "connectors": connectors,
            "service_expectation": original.service_expectation.model_copy(
                update={
                    "expected_mating_cycles": 100,
                    "min_retention_force_n": 1.0,
                }
            ),
        }
    )
    result = evaluate_harness(graph, extract_electrical_lane(graph), contract)
    assert (
        next(item for item in result.checks if item.check_id == "flex_cycles").status
        == "unknown"
    )
    assert (
        next(item for item in result.checks if item.check_id == "mating_cycles").status
        == "unknown"
    )


def test_legacy_contract_has_explicit_non_applicable_reasons() -> None:
    graph, original = _inputs()
    legacy_graph = graph.model_copy(
        update={
            "nodes": [
                node.model_copy(
                    update={
                        "attrs": {
                            key: value
                            for key, value in node.attrs.items()
                            if key != "signal_class"
                        }
                    }
                )
                for node in graph.nodes
            ]
        }
    )
    legacy_routes = [
        route.model_copy(
            update={
                "moving_section": False,
                "expected_flex_cycles": None,
                "bend_radius_dynamic_mm": None,
            }
        )
        for route in original.routes
    ]
    contract = original.model_copy(
        update={
            "routes": legacy_routes,
            "service_expectation": None,
            "segregation_policy": None,
        }
    )
    result = evaluate_harness(
        legacy_graph,
        extract_electrical_lane(legacy_graph),
        contract,
    )
    for check_id, expected_text in (
        ("shield_requirement", "no analog-sensitive"),
        ("flex_cycles", "no moving"),
        ("mating_cycles", "no mating-cycle"),
    ):
        check = next(item for item in result.checks if item.check_id == check_id)
        assert check.status == "pass"
        assert expected_text in check.reason


def test_dfa_findings_are_l2_observations() -> None:
    _, original = _inputs()
    connectors = [
        original.connectors[0].model_copy(update={"keying": None}),
        original.connectors[1],
    ]
    wires = [
        original.wires[0].model_copy(update={"slack_mm": 1.0}),
        *original.wires[1:],
    ]
    result = _evaluate(
        original.model_copy(update={"connectors": connectors, "wires": wires})
    )
    assert len(result.dfa_findings) == 2
    assert all(
        "L2 non-authoritative" in finding.basis
        for finding in result.dfa_findings
    )


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
