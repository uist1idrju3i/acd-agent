from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from acd.core.electrical.electrical import extract_electrical_lane
from acd.core.electrical.emc_esd import evaluate_emc_esd
from acd.core.manufacturing.reliability_test import evaluate_reliability_test_plan
from acd.schema import DesignGraph, ReliabilityTestPlan, UseEnvironment

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
ENVIRONMENT_PATH = ROOT / "fixtures/use-environment/gd1-indoor-usb.json"
PLAN_PATH = ROOT / "fixtures/reliability-test/gd1-indoor-usb.json"


def _payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _inputs() -> tuple[DesignGraph, UseEnvironment, ReliabilityTestPlan]:
    graph = DesignGraph.model_validate(_payload(GRAPH_PATH))
    environment = UseEnvironment.model_validate(_payload(ENVIRONMENT_PATH))
    plan = ReliabilityTestPlan.model_validate(_payload(PLAN_PATH))
    return graph, environment, plan


def _result(plan: ReliabilityTestPlan, predicate_results: list[object] | None = None):
    graph, environment, _ = _inputs()
    return evaluate_reliability_test_plan(
        graph,
        extract_electrical_lane(graph),
        environment,
        plan,
        predicate_results,
    )


def test_fixture_passes_all_non_linkage_checks_without_predicates() -> None:
    result = _result(_inputs()[2])
    assert result.status == "unknown"
    statuses = {check.check_id: check.status for check in result.checks}
    assert statuses == {
        "environment_consistency": "pass",
        "stress_coverage": "pass",
        "test_item_provenance": "pass",
        "design_requirement_linkage": "unknown",
        "lifetime_estimate": "pass",
        "measured_evidence": "pass",
    }
    linkage = next(
        check for check in result.checks if check.check_id == "design_requirement_linkage"
    )
    assert linkage.reason == "predicate results not provided"


def test_emc_result_propagates_linked_failure() -> None:
    graph, environment, plan = _inputs()
    emc = evaluate_emc_esd(graph, extract_electrical_lane(graph), environment)
    result = evaluate_reliability_test_plan(
        graph,
        extract_electrical_lane(graph),
        environment,
        plan,
        [emc],
    )
    linkage = next(
        check for check in result.checks if check.check_id == "design_requirement_linkage"
    )
    assert result.status == "fail"
    assert linkage.status == "fail"
    assert "req-esd-port" in linkage.subject_ids


def test_uncovered_stress_is_unknown() -> None:
    payload = _payload(PLAN_PATH)
    payload["accepted_gaps"] = []
    payload["test_items"] = [
        item for item in payload["test_items"] if "drop-user" not in item["simulates_stress_ids"]
    ]
    result = _result(ReliabilityTestPlan.model_validate(payload))
    coverage = next(check for check in result.checks if check.check_id == "stress_coverage")
    assert coverage.status == "unknown"
    assert coverage.details["gaps"] == ["drop-user"]


def test_provenance_and_unknown_target_fail_closed() -> None:
    payload = _payload(PLAN_PATH)
    payload["test_items"][0].pop("source_reference")
    payload["design_requirements"][0]["target_predicate"] = "not_a_known_check"
    result = _result(ReliabilityTestPlan.model_validate(payload))
    assert next(
        check for check in result.checks if check.check_id == "test_item_provenance"
    ).status == "fail"
    assert next(
        check for check in result.checks if check.check_id == "design_requirement_linkage"
    ).status == "fail"


def test_measured_result_requires_complete_matching_metadata() -> None:
    payload = _payload(PLAN_PATH)
    payload["measured_results"] = [
        {
            "conditions": {"temperature_c": 25.0},
            "equipment": None,
            "date": "2025-01-01",
            "specimen_revision": "r1",
            "test_item_id": "test-esd",
            "verdict": "observed",
        }
    ]
    result = _result(ReliabilityTestPlan.model_validate(payload))
    measured = next(check for check in result.checks if check.check_id == "measured_evidence")
    assert measured.status == "fail"


def test_environment_mismatch_fails() -> None:
    payload = _payload(PLAN_PATH)
    payload["stresses"][1]["real_use_condition"]["value"]["max"] = 41.0
    result = _result(ReliabilityTestPlan.model_validate(payload))
    environment = next(
        check for check in result.checks if check.check_id == "environment_consistency"
    )
    assert environment.status == "fail"


def test_lifetime_estimate_is_non_authoritative() -> None:
    payload = _payload(PLAN_PATH)
    payload["lifetime_model"] = {
        "model": "arrhenius",
        "note": "estimate",
        "parameters": {
            "activation_energy_ev": 0.7,
            "test_temperature_c": 85.0,
            "use_temperature_c": 40.0,
        },
    }
    result = _result(ReliabilityTestPlan.model_validate(payload))
    lifetime = next(check for check in result.checks if check.check_id == "lifetime_estimate")
    assert lifetime.status == "pass"
    assert lifetime.details["authority"] == "estimate"
    assert lifetime.details["acceleration_factor"] > 1.0


def test_evaluation_is_deterministic() -> None:
    first = _result(_inputs()[2]).model_dump_json()
    second = _result(_inputs()[2]).model_dump_json()
    assert first == second


def test_cli_revision_mismatch_exits_two_without_output(tmp_path: Path) -> None:
    environment = _payload(ENVIRONMENT_PATH)
    environment["revision"] = "r2"
    environment_path = tmp_path / "environment.json"
    environment_path.write_text(json.dumps(environment), encoding="utf-8")
    output = tmp_path / "out"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check_reliability_test_plan.py"),
            "--graph",
            str(GRAPH_PATH),
            "--environment",
            str(environment_path),
            "--plan",
            str(PLAN_PATH),
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
