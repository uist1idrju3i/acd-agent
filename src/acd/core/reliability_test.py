"""Deterministic opt-in reliability-test stress coverage gate."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, cast

from acd.core.design_predicates import PREDICATE_CATALOG
from acd.core.electrical import ElectricalLane
from acd.schema.common import canonical_sha256
from acd.schema.design_graph import DesignGraph
from acd.schema.reliability_test import (
    ReliabilityCheckResult,
    ReliabilityEnvironmentRef,
    ReliabilityTestPlan,
    ReliabilityTestResult,
)
from acd.schema.use_environment import UseEnvironment

EMC_PREDICATES = frozenset(
    {
        "esd_protection_external_ports",
        "power_loop_area",
        "return_path_continuity",
        "environment_derating_inputs",
    }
)
DFT_CHECKS = frozenset(
    {"net_coverage", "probe_pitch", "pad_diameter", "probe_side", "component_keepout"}
)
HARNESS_CHECKS = frozenset(
    {
        "netlist_consistency",
        "ampacity",
        "voltage_drop",
        "insulation_rating",
        "bend_radius",
        "shield_requirement",
        "signal_class_segregation",
        "flex_cycles",
        "mating_cycles",
        "keying_polarity",
        "redundant_group_harness",
    }
)
KNOWN_TARGETS = frozenset(PREDICATE_CATALOG) | EMC_PREDICATES | DFT_CHECKS | HARNESS_CHECKS
BOLTZMANN_EV_PER_K = 8.617333262e-5


def _check(
    check_id: str,
    status: str,
    reason: str,
    subject_ids: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> ReliabilityCheckResult:
    return ReliabilityCheckResult(
        check_id=check_id,
        status=status,  # type: ignore[arg-type]
        reason=reason,
        subject_ids=sorted(set(subject_ids or [])),
        details=details or {},
    )


def _environment_value(environment: UseEnvironment, parameter: str) -> object | None:
    values: dict[str, object] = {
        "temperature": environment.temperature_c.model_dump(mode="json"),
        "temperature_c": environment.temperature_c.model_dump(mode="json"),
        "humidity": environment.humidity_rh_pct.model_dump(mode="json"),
        "humidity_rh_pct": environment.humidity_rh_pct.model_dump(mode="json"),
        "vibration": environment.vibration,
        "installation": environment.installation,
        "power_system": environment.power_system,
        "external_ports": [
            port.model_dump(mode="json") for port in environment.external_ports
        ],
    }
    return values.get(parameter)


def _environment_consistency(
    environment: UseEnvironment, plan: ReliabilityTestPlan
) -> ReliabilityCheckResult:
    failures: list[str] = []
    unknowns: list[str] = []
    details: dict[str, Any] = {}
    for stress in plan.stresses:
        condition = stress.real_use_condition
        if condition.source != "environment":
            continue
        expected = _environment_value(environment, condition.parameter)
        if expected is None:
            unknowns.append(stress.stress_id)
            continue
        details[stress.stress_id] = {
            "parameter": condition.parameter,
            "declared": condition.value,
            "environment": expected,
        }
        if condition.value != expected:
            failures.append(stress.stress_id)
    if failures:
        return _check(
            "environment_consistency",
            "fail",
            "environment-backed stress conditions do not match UseEnvironment",
            failures,
            details,
        )
    if unknowns:
        return _check(
            "environment_consistency",
            "unknown",
            "stress condition cannot be mapped to a UseEnvironment field",
            unknowns,
            details,
        )
    return _check(
        "environment_consistency",
        "pass",
        "environment-backed stress conditions match UseEnvironment",
        details=details,
    )


def _stress_coverage(plan: ReliabilityTestPlan) -> ReliabilityCheckResult:
    accepted = {gap.stress_id for gap in plan.accepted_gaps}
    items_by_stress: dict[str, list[str]] = {stress.stress_id: [] for stress in plan.stresses}
    relations: dict[str, str] = {}
    for item in plan.test_items:
        relations[item.test_item_id] = item.severity_relation
        for stress_id in item.simulates_stress_ids:
            items_by_stress.setdefault(stress_id, []).append(item.test_item_id)
    gaps: list[str] = []
    under: list[str] = []
    accepted_gaps: list[str] = []
    for stress in plan.stresses:
        item_ids = items_by_stress.get(stress.stress_id, [])
        if any(relations[item_id] in {"covers", "over"} for item_id in item_ids):
            continue
        if stress.stress_id in accepted:
            accepted_gaps.append(stress.stress_id)
        elif item_ids:
            under.append(stress.stress_id)
            gaps.append(stress.stress_id)
        else:
            gaps.append(stress.stress_id)
    over_tests = sorted(
        item.test_item_id
        for item in plan.test_items
        if item.severity_relation == "over"
    )
    details = {
        "gaps": sorted(gaps),
        "under_tests": sorted(under),
        "accepted_gaps": sorted(accepted_gaps),
        "over_tests": over_tests,
    }
    if gaps:
        return _check(
            "stress_coverage",
            "unknown",
            "one or more real-use stresses lack a covering test or accepted gap",
            gaps,
            details,
        )
    return _check(
        "stress_coverage",
        "pass",
        "all declared stresses are covered or explicitly accepted as gaps",
        details=details,
    )


def _test_item_provenance(plan: ReliabilityTestPlan) -> ReliabilityCheckResult:
    invalid = [
        item.test_item_id
        for item in plan.test_items
        if item.source_reference is None or item.background is None
    ]
    if invalid:
        return _check(
            "test_item_provenance",
            "fail",
            "every test item requires source identifier, edition, and background",
            invalid,
        )
    return _check(
        "test_item_provenance",
        "pass",
        "all test items carry source identifiers, editions, and background",
        details={
            "sources": {
                item.test_item_id: item.source_reference.model_dump(mode="json")
                for item in plan.test_items
                if item.source_reference is not None
            }
        },
    )


def _result_entries(result: object) -> dict[str, str]:
    if isinstance(result, Mapping):
        result_mapping = cast(Mapping[str, object], result)
        entries: dict[str, str] = {}
        for key in ("predicates", "checks"):
            values: object = result_mapping.get(key)
            if isinstance(values, list):
                values_list = cast(list[object], values)
                for value in values_list:
                    if isinstance(value, Mapping):
                        mapping = cast(Mapping[str, object], value)
                        identifier = mapping.get("predicate_id")
                        if identifier is None:
                            identifier = mapping.get("check_id")
                        if identifier is None:
                            identifier = mapping.get("name")
                        status = mapping.get("status")
                        if isinstance(identifier, str) and isinstance(status, str):
                            entries[identifier] = status
        return entries
    entries = {}
    for key in ("predicates", "checks"):
        values = getattr(result, key, ())
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            continue
        values_sequence = cast(Sequence[object], values)
        for value in values_sequence:
            identifier = getattr(value, "predicate_id", None) or getattr(
                value, "check_id", None
            ) or getattr(value, "name", None)
            status = getattr(value, "status", None)
            if isinstance(identifier, str) and isinstance(status, str):
                entries[identifier] = status
    return entries


def _design_requirement_linkage(
    plan: ReliabilityTestPlan,
    predicate_results: Sequence[object] | None,
) -> ReliabilityCheckResult:
    unknown_targets = [
        item.requirement_id
        for item in plan.design_requirements
        if item.target_predicate not in KNOWN_TARGETS
    ]
    if unknown_targets:
        return _check(
            "design_requirement_linkage",
            "fail",
            "design requirement targets an unknown predicate or check",
            unknown_targets,
        )
    if not plan.design_requirements:
        return _check(
            "design_requirement_linkage",
            "pass",
            "no design requirements are declared",
        )
    if predicate_results is None:
        return _check(
            "design_requirement_linkage",
            "unknown",
            "predicate results not provided",
            [item.requirement_id for item in plan.design_requirements],
        )
    available: dict[str, str] = {}
    for result in predicate_results:
        available.update(_result_entries(result))
    failures: list[str] = []
    unknowns: list[str] = []
    details: dict[str, Any] = {}
    for requirement in plan.design_requirements:
        status = available.get(requirement.target_predicate)
        details[requirement.requirement_id] = {
            "target_predicate": requirement.target_predicate,
            "status": status,
        }
        if status == "fail":
            failures.append(requirement.requirement_id)
        elif status != "pass":
            unknowns.append(requirement.requirement_id)
    if failures:
        return _check(
            "design_requirement_linkage",
            "fail",
            "linked predicate result is failing",
            failures,
            details,
        )
    if unknowns:
        return _check(
            "design_requirement_linkage",
            "unknown",
            "linked predicate result is unknown or unavailable",
            unknowns,
            details,
        )
    return _check(
        "design_requirement_linkage",
        "pass",
        "all design requirements link to passing predicate results",
        details=details,
    )


def _lifetime_estimate(plan: ReliabilityTestPlan) -> ReliabilityCheckResult:
    model = plan.lifetime_model
    if model is None:
        return _check(
            "lifetime_estimate",
            "pass",
            "no lifetime acceleration model is declared",
            details={"authority": "estimate", "model": None},
        )
    parameters = model.parameters
    try:
        if model.model == "arrhenius":
            ea = parameters["activation_energy_ev"]
            t_use = parameters["use_temperature_c"] + 273.15
            t_test = parameters["test_temperature_c"] + 273.15
            factor = math.exp(ea / BOLTZMANN_EV_PER_K * (1 / t_use - 1 / t_test))
        elif model.model == "coffin_manson":
            factor = (
                parameters["test_delta_t"] / parameters["use_delta_t"]
            ) ** parameters["exponent"]
        else:
            ea = parameters["activation_energy_ev"]
            rh_test = parameters["test_rh_pct"]
            rh_use = parameters["use_rh_pct"]
            t_use = parameters["use_temperature_c"] + 273.15
            t_test = parameters["test_temperature_c"] + 273.15
            factor = (rh_test / rh_use) ** parameters["exponent"] * math.exp(
                ea / BOLTZMANN_EV_PER_K * (1 / t_use - 1 / t_test)
            )
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError
    except (KeyError, ValueError, ZeroDivisionError, OverflowError):
        return _check(
            "lifetime_estimate",
            "unknown",
            "lifetime model parameters are incomplete or invalid",
            details={"authority": "estimate", "model": model.model},
        )
    return _check(
        "lifetime_estimate",
        "pass",
        "lifetime acceleration is recorded as a non-authoritative estimate",
        details={
            "authority": "estimate",
            "model": model.model,
            "acceleration_factor": factor,
        },
    )


def _measured_evidence(
    plan: ReliabilityTestPlan,
) -> ReliabilityCheckResult:
    rejected: list[str] = []
    observations: list[dict[str, Any]] = []
    for result in plan.measured_results:
        if (
            not result.conditions
            or result.equipment is None
            or result.date is None
            or result.specimen_revision is None
            or result.specimen_revision != plan.revision
        ):
            rejected.append(result.test_item_id)
            continue
        observations.append(result.model_dump(mode="json"))
    if rejected:
        return _check(
            "measured_evidence",
            "fail",
            "measured results require conditions, equipment, date, and matching specimen revision",
            rejected,
            {"observations": observations, "rejected": rejected},
        )
    return _check(
        "measured_evidence",
        "pass",
        "measured results are recorded as observations and do not provide pass authority",
        details={"observations": observations, "authority": "observation-only"},
    )


def evaluate_reliability_test_plan(
    graph: DesignGraph,
    lane: ElectricalLane,
    environment: UseEnvironment,
    plan: ReliabilityTestPlan,
    predicate_results: Sequence[object] | None = None,
) -> ReliabilityTestResult:
    """Evaluate a revision-matched reliability-test mapping."""
    del lane
    if graph.graph_id != plan.graph_id or graph.revision != plan.revision:
        raise ValueError("reliability plan graph_id/revision does not match graph")
    if environment.graph_id != graph.graph_id or environment.revision != graph.revision:
        raise ValueError("use environment graph_id/revision does not match graph")
    ref = plan.environment_ref
    inline_environment = (
        ref
        if isinstance(ref, UseEnvironment)
        else ref.environment
        if isinstance(ref, ReliabilityEnvironmentRef)
        else None
    )
    if inline_environment is not None and (
        inline_environment.graph_id != environment.graph_id
        or inline_environment.revision != environment.revision
    ):
        raise ValueError("inline reliability environment does not match environment")
    checks = [
        _environment_consistency(environment, plan),
        _stress_coverage(plan),
        _test_item_provenance(plan),
        _design_requirement_linkage(plan, predicate_results),
        _lifetime_estimate(plan),
        _measured_evidence(plan),
    ]
    statuses = {check.status for check in checks}
    status = "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"
    hashes: dict[str, str] = {
        "graph": canonical_sha256(graph),
        "environment": canonical_sha256(environment),
        "plan": canonical_sha256(plan),
    }
    return ReliabilityTestResult(
        plan_id=plan.plan_id,
        graph_id=graph.graph_id,
        revision=graph.revision,
        status=status,  # type: ignore[arg-type]
        checks=checks,
        input_hashes=hashes,  # type: ignore[arg-type]
    )
